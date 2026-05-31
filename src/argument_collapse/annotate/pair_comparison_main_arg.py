#!/usr/bin/env python3
"""4-label pairwise judge over essay ``main_argument`` statements within each
cohort.

Compares the two essays' single-sentence ``main_argument`` strings and emits
one of the four labels described in the system prompt:

  - ``equivalent``     same central position
  - ``strong_overlap`` shared core proposal + extra elaborations
  - ``weak_overlap``   shared stance + different central proposals
  - ``different``      no shared stance / disjoint commitments

Output: ``<data_root>/<venue>/<cohort>/analysis/main_argument_pairs.jsonl``
with one row per judged ``(essay_i, essay_j)`` pair:

  {cohort, essay_i, essay_j, kind_i, kind_j, model_i, model_j,
   relation, rationale,
   judged_at_utc, judge_provider, judge_model, judge_effort,
   tagger_prompt_version}

Run with ``python -m argument_collapse.annotate.pair_comparison_main_arg``.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional
    load_dotenv = None
if load_dotenv is not None:
    load_dotenv()

from argument_collapse.data import (
    cohort_analysis_path,
    get_data_root,
    iter_cohort_jsonl,
    parse_frontmatter_and_body,
    set_data_root,
)
from argument_collapse.inference import (
    InferenceError,
    InferenceRequest,
    get_provider,
    provider_choices,
)
# Per-cohort output filenames, both under
# ``<data_root>/<venue>/<cohort>/analysis/``.
OUT_FILENAME = "main_argument_pairs.jsonl"
# Source of main-argument text. ``annotate.toulmin`` writes this.
TOULMIN_FILENAME = "toulmin.jsonl"

VALID_RELATIONS = {"equivalent", "strong_overlap", "weak_overlap", "different"}
# Prompt-version tag stamped on each output row. The base name identifies
# the task; ``judge_pair`` appends ``_lead`` when the shared cohort
# context is a lead essay instead of a debate question, so the two
# variants stay distinguishable in the released JSONL.
TAGGER_PROMPT_VERSION = "pair_comparison_main_arg"

_PROGRESS_LOCK = threading.Lock()
# One file per cohort; per-cohort locks let cohorts run concurrently.
_COHORT_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()


def _cohort_lock(cohort: str) -> threading.Lock:
    with _LOCKS_LOCK:
        lock = _COHORT_LOCKS.get(cohort)
        if lock is None:
            lock = threading.Lock()
            _COHORT_LOCKS[cohort] = lock
        return lock


def progress(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    with _PROGRESS_LOCK:
        print(f"[{stamp}] {message}", flush=True)


# ---------- prompt ----------

SYSTEM_PROMPT = """\
You compare two op-ed essays' main_argument statements (one sentence each)
about the SAME debate question, and decide the logical relation between them.

Return exactly one `relation` from a 4-way scale:

- "equivalent"     — both main_arguments commit to the SAME central position
                     on the question. Paraphrase or different wording is fine;
                     what matters is that a careful reader would say they
                     take the same stance and make the same essential claim.
                     Mutual entailment in the context of the question.

- "strong_overlap" — both main_arguments SHARE THE CORE PROPOSAL or claim,
                     but one (or both) adds elaborations, secondary
                     commitments, or extensions the other doesn't. The
                     central thing they propose / argue is the same; the
                     difference is in what each adds around it.

- "weak_overlap"   — both main_arguments share the same STANCE or
                     ORIENTATION toward the question (e.g., both favor
                     intervention, both reject a framing, both endorse a
                     general goal), but propose different central
                     mechanisms, reasons, or commitments. They agree at
                     the directional level but propose different
                     specifics.

- "different"      — no shared stance or substantive commitment beyond
                     responding to the same debate question. Covers
                     opposing positions on the same axis, disjoint
                     choices on open-ended questions, and pairs where
                     neither side's stance or central commitment aligns
                     with the other.

Critical rules:
- All pairs in a cohort share the debate question by construction, so
  "shared topic" alone is NEVER enough for any kind of overlap label.
  `weak_overlap` requires shared STANCE or ORIENTATION, not just
  shared question framing.
- OPPOSING positions are always `different`. Pro and con of the same
  proposition never count as `equivalent`, `strong_overlap`, or
  `weak_overlap`.
- The split between `strong_overlap` and `weak_overlap` is structural,
  not magnitudinal:
    * `strong_overlap`: shared CORE proposal/claim + extra elaborations.
    * `weak_overlap`:   shared STANCE + different central proposals.
- Different framings of the SAME position ARE equivalent.
- If in doubt between `equivalent` and `strong_overlap`: would a careful
  reader say these are "the same argument said differently" (equivalent)
  or "two related arguments sharing a core proposal" (strong_overlap)?
- If in doubt between `strong_overlap` and `weak_overlap`: do they share
  the CENTRAL PROPOSAL, or only the stance / orientation? If only the
  stance, it's weak.
- If in doubt between `weak_overlap` and `different`: do they share any
  stance or orientation beyond merely responding to the same question?
  If yes, it's `weak_overlap`; if no, it's `different`.
- OPEN-ENDED QUESTIONS that name a goal in the question itself (e.g.,
  "how should we improve X?", "what changes to X would make it better?",
  "what should we do to fix X?") require a STRICTER test for shared
  stance. The question already names the goal. Two main_arguments that
  both endorse that named goal have NOT shared a stance — they have
  just answered the question.
  CRITICAL: this includes "X over Y" framings where Y is what the
  question implicitly wants to move away from. If the question asks how
  to make debates "more substantive," then both essays saying "prioritize
  substance over spectacle" / "favor policy depth over theatricality" /
  "emphasize substantive discourse over performance" do NOT have a
  shared substantive orientation — they are both just restating the
  question's own framing in oppositional form. The same logic applies
  to "engagement over passivity," "quality over quantity," "equity over
  efficiency" when the named thing on the left is exactly what the
  question asked for.
  To qualify as `weak_overlap` on these questions, the shared
  orientation must go BEYOND the question's stated goal — e.g., both
  prefer market mechanisms over regulation, both prioritize the
  underserved over typical users, both reject institutional reform in
  favor of grassroots change, both blame a common root cause.
  If two main_arguments propose disjoint specific mechanisms but their
  only commonality is "we should achieve the goal the question asks
  about" (in any phrasing, including "X over Y"-style framings drawn
  from the question), the relation is `different`.

Return strict JSON:
{
  "relation": "equivalent" | "strong_overlap" | "weak_overlap" | "different",
  "rationale": "1-2 sentences explaining the relation, grounded in the actual main_argument text"
}

## Calibration examples

The example questions below are deliberately invented small-town policy
debates and do not correspond to any real cohort in the dataset. Each
example targets a specific boundary between adjacent labels.

Question: Should Brookline adopt a four-day workweek for municipal staff?
I: "Brookline should adopt the four-day workweek because the pilot data showed productivity held steady while sick leave dropped."
J: "The municipal four-day schedule should be made permanent; the pilot showed comparable output with fewer health absences."
→ {"relation": "equivalent", "rationale": "Both endorse adopting the four-day workweek and both ground that endorsement in the same pilot evidence (productivity + reduced absences). Paraphrase, same position."}

Question: Should the city of Brookline require electric scooters to be parked in marked corrals?
I: "Brookline should mandate corral parking and impose escalating fines on repeat violators."
J: "Brookline should mandate corral parking and require operators to provide real-time corral-availability maps in their apps."
→ {"relation": "strong_overlap", "rationale": "Both endorse mandating corral parking (the shared core proposal). I adds an enforcement mechanism (fines), J adds an operator-side usability mechanism (maps) — different secondary commitments around the same center."}

Question: How should Brookline reduce car traffic on Main Street?
I: "Brookline should redesign Main Street as a transit-and-bike priority corridor with reduced car lanes."
J: "Brookline should raise downtown parking prices and use the revenue to fund a free shuttle loop."
→ {"relation": "weak_overlap", "rationale": "Both share the stance that car traffic should be reduced, but propose completely different central mechanisms: I focuses on physical street redesign, J on pricing plus transit subsidy. Shared orientation, no shared central proposal."}

Question: Should Brookline adopt a four-day workweek for municipal staff?
I: "Brookline should adopt the four-day workweek to give public-sector workers the recovery time the private sector won't offer."
J: "Brookline should adopt the four-day workweek to make municipal jobs competitive with neighboring towns that already offer flexible scheduling."
→ {"relation": "weak_overlap", "rationale": "Both share the yes-stance on adopting the workweek, but ground it in different primary reasons (worker welfare vs hiring competitiveness). Shared yes-stance, different central WHY."}

Question: Should the Riverton library extend weekend hours?
I: "The library should extend weekend hours because current hours leave working residents unable to use the building."
J: "Weekend hours should stay as they are; further extension diverts limited staff from the children's programming the library is known for."
→ {"relation": "different", "rationale": "Directly opposing positions on the question."}

Question: How could the Brookline garden club make its monthly programs more substantive?
I: "The club should invite guest horticulturalists once per quarter to prioritize substantive instruction over informal show-and-tell."
J: "The club should organize hands-on workshops at members' gardens to prioritize substantive practice over slideshow lectures."
→ {"relation": "different", "rationale": "Open-ended question asking what changes would make the programs 'more substantive.' Both arguments use 'substantive X over Y' framing, but the 'substantive' half is just the question's named goal and the Y half (show-and-tell / slideshow lectures) describes the current shortcoming the question implicitly asks them to fix — i.e., the entire 'substantive X over Y' framing is a restatement of the question's own setup. The specific commitments (guest horticulturalists vs hands-on workshops) are disjoint mechanisms with no substantive shared orientation. Per the open-ended-question rule, this is `different`, not `weak_overlap`."}
"""


SYSTEM_PROMPT_LEAD = """\
You compare two op-ed essays' main_argument statements (one sentence each),
both written in response to the SAME lead essay (an opinion piece they are
reacting to), and decide the logical relation between them.

Return exactly one `relation` from a 4-way scale:

- "equivalent"     — both main_arguments commit to the SAME central position
                     in response to the lead essay. Paraphrase or different
                     wording is fine; what matters is that a careful reader
                     would say they take the same stance and make the same
                     essential claim. Mutual entailment in the context of the
                     lead essay.

- "strong_overlap" — both main_arguments SHARE THE CORE PROPOSAL or claim,
                     but one (or both) adds elaborations, secondary
                     commitments, or extensions the other doesn't. The
                     central thing they propose / argue is the same; the
                     difference is in what each adds around it.

- "weak_overlap"   — both main_arguments share the same STANCE or
                     ORIENTATION in response to the lead essay (e.g., both
                     endorse the lead's thesis, both reject it, both
                     redirect it toward a common alternative), but propose
                     different central mechanisms, reasons, or commitments.
                     They agree at the directional level but propose
                     different specifics.

- "different"      — no shared stance or substantive commitment beyond
                     responding to the same lead essay. Covers opposing
                     positions on the same axis, disjoint angles on the
                     lead's topic, and pairs where neither side's stance or
                     central commitment aligns with the other.

Critical rules:
- All pairs in a cohort react to the same lead essay by construction, so
  "both engage the lead's topic" alone is NEVER enough for any kind of
  overlap label. `weak_overlap` requires shared STANCE or ORIENTATION, not
  just shared subject matter.
- OPPOSING positions are always `different`. Endorsing the lead's thesis vs
  rejecting it never counts as `equivalent`, `strong_overlap`, or
  `weak_overlap`.
- The split between `strong_overlap` and `weak_overlap` is structural,
  not magnitudinal:
    * `strong_overlap`: shared CORE proposal/claim + extra elaborations.
    * `weak_overlap`:   shared STANCE + different central proposals.
- Different framings of the SAME position ARE equivalent.
- If in doubt between `equivalent` and `strong_overlap`: would a careful
  reader say these are "the same argument said differently" (equivalent)
  or "two related arguments sharing a core proposal" (strong_overlap)?
- If in doubt between `strong_overlap` and `weak_overlap`: do they share
  the CENTRAL PROPOSAL, or only the stance / orientation? If only the
  stance, it's weak.
- If in doubt between `weak_overlap` and `different`: do they share any
  stance or orientation beyond merely reacting to the same lead essay?
  If yes, it's `weak_overlap`; if no, it's `different`.
- The lead essay itself advances a thesis. Agreeing with the lead's overall
  thesis, or rejecting it, IS a genuine shared stance and counts toward
  overlap. BUT when the lead essay frames the debate around achieving a
  named goal (e.g., a lead arguing "we must end poverty" or "democracy must
  be defended"), two main_arguments whose ONLY commonality is endorsing
  that named goal have NOT shared a distinctive stance — they have just
  accepted the lead's framing. To qualify as `weak_overlap` in that case,
  the shared orientation must go BEYOND the lead's stated goal — e.g., both
  locate the same root cause, both prefer market mechanisms over
  regulation, both prioritize the same overlooked constituency, both reject
  institutional reform in favor of grassroots change. If two main_arguments
  propose disjoint specific mechanisms and their only commonality is "we
  should achieve the goal the lead essay argues for," the relation is
  `different`.

Return strict JSON:
{
  "relation": "equivalent" | "strong_overlap" | "weak_overlap" | "different",
  "rationale": "1-2 sentences explaining the relation, grounded in the actual main_argument text"
}

## Calibration examples

The examples below illustrate the label BOUNDARIES using simple invented
debate questions as the shared context. The same boundary logic applies
when the shared context is a lead essay: substitute "the position the lead
essay argues" for "the question's named goal." The examples do not
correspond to any real cohort in the dataset.

Question: Should Brookline adopt a four-day workweek for municipal staff?
I: "Brookline should adopt the four-day workweek because the pilot data showed productivity held steady while sick leave dropped."
J: "The municipal four-day schedule should be made permanent; the pilot showed comparable output with fewer health absences."
→ {"relation": "equivalent", "rationale": "Both endorse adopting the four-day workweek and both ground that endorsement in the same pilot evidence (productivity + reduced absences). Paraphrase, same position."}

Question: Should the city of Brookline require electric scooters to be parked in marked corrals?
I: "Brookline should mandate corral parking and impose escalating fines on repeat violators."
J: "Brookline should mandate corral parking and require operators to provide real-time corral-availability maps in their apps."
→ {"relation": "strong_overlap", "rationale": "Both endorse mandating corral parking (the shared core proposal). I adds an enforcement mechanism (fines), J adds an operator-side usability mechanism (maps) — different secondary commitments around the same center."}

Question: How should Brookline reduce car traffic on Main Street?
I: "Brookline should redesign Main Street as a transit-and-bike priority corridor with reduced car lanes."
J: "Brookline should raise downtown parking prices and use the revenue to fund a free shuttle loop."
→ {"relation": "weak_overlap", "rationale": "Both share the stance that car traffic should be reduced, but propose completely different central mechanisms: I focuses on physical street redesign, J on pricing plus transit subsidy. Shared orientation, no shared central proposal."}

Question: Should the Riverton library extend weekend hours?
I: "The library should extend weekend hours because current hours leave working residents unable to use the building."
J: "Weekend hours should stay as they are; further extension diverts limited staff from the children's programming the library is known for."
→ {"relation": "different", "rationale": "Directly opposing positions."}

Question: How could the Brookline garden club make its monthly programs more substantive?
I: "The club should invite guest horticulturalists once per quarter to prioritize substantive instruction over informal show-and-tell."
J: "The club should organize hands-on workshops at members' gardens to prioritize substantive practice over slideshow lectures."
→ {"relation": "different", "rationale": "The shared 'substantive X over Y' framing just restates the named goal; the specific commitments (guest horticulturalists vs hands-on workshops) are disjoint mechanisms with no substantive shared orientation beyond the goal itself. Per the named-goal rule, this is `different`, not `weak_overlap`."}
"""


def user_prompt(question: str, main_i: str, main_j: str,
                context_label: str = "Debate question") -> str:
    return (
        f"{context_label}:\n{question.strip()}\n\n"
        f"Main argument I:\n{main_i.strip()}\n\n"
        f"Main argument J:\n{main_j.strip()}"
    )


# ---------- json parsing ----------

def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    if start < 0:
        raise json.JSONDecodeError("no opening brace", cleaned, 0)
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start : i + 1])
    raise json.JSONDecodeError("unbalanced braces", cleaned, start)


def normalize(payload: dict[str, Any]) -> dict[str, Any]:
    rel = str(payload.get("relation", "")).strip().lower()
    if rel not in VALID_RELATIONS:
        raise ValueError(f"invalid relation {rel!r}; expected one of {sorted(VALID_RELATIONS)}")
    rationale = ""
    for key in ("rationale", "reason", "explanation"):
        v = str(payload.get(key, "")).strip()
        if v:
            rationale = v
            break
    return {"relation": rel, "rationale": rationale}


# ---------- data loading ----------

def load_essays_with_main_arg(
    venue: str,
    data_root: Path | str | None = None,
) -> dict[tuple, dict]:
    """Load toulmin rows for every essay with a non-empty ``main_argument``.

    Returns a ``(cohort, stem) -> {cohort, stem, kind, model, main_argument}``
    map.
    """
    out: dict[tuple, dict] = {}
    for cohort, rows in iter_cohort_jsonl(venue, TOULMIN_FILENAME, data_root=data_root):
        for r in rows:
            main = (r.get("main_argument") or "").strip()
            if not main:
                continue
            row_cohort = r.get("cohort", cohort)
            out[(row_cohort, r["stem"])] = {
                "cohort": row_cohort,
                "stem": r["stem"],
                "kind": r.get("kind", ""),
                "model": r.get("model"),
                "main_argument": main,
            }
    return out


# ``--context-kind`` -> (filename inside ``<cohort>/human/``, "missing"
# error label). ``question`` is the debate-question convention; ``lead`` is
# the lead-essay convention.
CONTEXT_FILES = {
    "question": ("00_question.md", "question prompt"),
    "lead": ("00_lead.md", "lead essay"),
}
CONTEXT_LABELS = {"question": "Debate question", "lead": "Lead essay"}


def context_path(venue: str, cohort: str, context_kind: str,
                 data_root: Path | str | None = None) -> Path:
    filename, _ = CONTEXT_FILES[context_kind]
    root = Path(data_root) if data_root is not None else get_data_root()
    return root / venue / cohort / "human" / filename


def load_question(venue: str, cohort: str, context_kind: str = "question",
                  data_root: Path | str | None = None) -> str:
    path = context_path(venue, cohort, context_kind, data_root=data_root)
    if not path.exists():
        _, label = CONTEXT_FILES[context_kind]
        raise FileNotFoundError(f"missing {label}: {path}")
    _fm, body = parse_frontmatter_and_body(path)
    return body


def load_question_type(venue: str, cohort: str,
                       data_root: Path | str | None = None) -> str | None:
    """Read ``question_type.json`` for the cohort, if present.

    The file's ``question_type`` key is one of ``stance`` / ``open_ended``;
    used by ``--question-type`` to filter the cohort set.
    """
    root = Path(data_root) if data_root is not None else get_data_root()
    path = root / venue / cohort / "question_type.json"
    if not path.exists():
        return None
    return json.loads(path.read_text()).get("question_type")


# ---------- output state ----------

def load_existing_pairs(
    venue: str,
    data_root: Path | str | None = None,
) -> set[tuple[str, str, str]]:
    """Return ``(cohort, essay_i, essay_j)`` triples already on disk."""
    seen: set[tuple[str, str, str]] = set()
    for cohort, rows in iter_cohort_jsonl(venue, OUT_FILENAME, data_root=data_root):
        for r in rows:
            seen.add((r.get("cohort", cohort), r["essay_i"], r["essay_j"]))
    return seen


def append_row(venue: str, row: dict,
               data_root: Path | str | None = None) -> None:
    """Append ``row`` to its cohort's ``analysis/main_argument_pairs.jsonl``.

    Per-cohort lock keeps concurrent writers safe across cohorts.
    """
    cohort = row["cohort"]
    path = cohort_analysis_path(venue, cohort, OUT_FILENAME, data_root=data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False)
    with _cohort_lock(cohort):
        with path.open("a") as fh:
            fh.write(line + "\n")


# ---------- judge call ----------

def request_params(args: argparse.Namespace) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if args.temperature is not None and args.provider != "vertex-claude":
        params["temperature"] = args.temperature
    if args.max_output_tokens is not None:
        if args.provider in {"openai", "vertex"}:
            params["max_output_tokens"] = args.max_output_tokens
        else:
            params["max_tokens"] = args.max_output_tokens
    return params


def main_only_prompt(main_i: str, main_j: str) -> str:
    """User prompt with ONLY the two main arguments — used when the system
    prompt + shared context have been supplied via Vertex's explicit cache,
    so they must not be repeated in the live request."""
    return (f"Main argument I:\n{main_i.strip()}\n\n"
            f"Main argument J:\n{main_j.strip()}")


def call_judge(args: argparse.Namespace, question: str,
               main_i: str, main_j: str,
               cache_name: str | None = None) -> tuple[dict, int | None]:
    """Run one judge call. Returns ``(normalized_annotation,
    cached_content_token_count)``.

    When ``cache_name`` is set, the system prompt + shared context come
    from the cache, so the live request carries only the two main
    arguments.
    """
    context_kind = getattr(args, "context_kind", "question")
    if cache_name:
        sys_p = ""  # provider omits system_instruction when cached_content set
        usr_p = main_only_prompt(main_i, main_j)
    else:
        sys_p = SYSTEM_PROMPT_LEAD if context_kind == "lead" else SYSTEM_PROMPT
        usr_p = user_prompt(question, main_i, main_j,
                            context_label=CONTEXT_LABELS[context_kind])
    request = InferenceRequest(
        provider=args.provider,
        model=args.model,
        system_prompt=sys_p,
        user_prompt=usr_p,
        combined_prompt=(sys_p + "\n\n" + usr_p) if sys_p else usr_p,
        condition="main_argument_judge_4label",
        effort=args.effort or "",
        request_params=request_params(args),
        cached_content=cache_name,
    )
    result = get_provider(args.provider).generate(request)
    payload = extract_json(result.text)
    usage = result.metadata.get("usage") or {}
    cached_tok = usage.get("cached_content_token_count") if isinstance(usage, dict) else None
    return normalize(payload), cached_tok


def judge_pair(args: argparse.Namespace, cohort: str,
               question: str, essay_i: dict, essay_j: dict,
               cache_name: str | None = None,
               data_root: Path | str | None = None) -> tuple[bool, str]:
    try:
        ann, cached_tok = call_judge(
            args, question, essay_i["main_argument"], essay_j["main_argument"],
            cache_name=cache_name)
    except (InferenceError, ValueError, json.JSONDecodeError) as exc:
        return False, f"{cohort} {essay_i['stem']}<>{essay_j['stem']}: {exc}"
    context_kind = getattr(args, "context_kind", "question")
    prompt_version = (
        TAGGER_PROMPT_VERSION + "_lead" if context_kind == "lead"
        else TAGGER_PROMPT_VERSION
    )
    row = {
        "cohort": cohort,
        "essay_i": essay_i["stem"],
        "essay_j": essay_j["stem"],
        "kind_i": essay_i["kind"],
        "kind_j": essay_j["kind"],
        "model_i": essay_i["model"],
        "model_j": essay_j["model"],
        **ann,
        "judged_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "judge_provider": args.provider,
        "judge_model": args.model,
        "judge_effort": args.effort or "",
        "tagger_prompt_version": prompt_version,
    }
    append_row(args.venue, row, data_root=data_root)
    cache_note = f" [cached={cached_tok}]" if cached_tok else ""
    return True, f"{cohort} {essay_i['stem'][:24]}..<>{essay_j['stem'][:24]}.. -> {ann['relation']}{cache_note}"


# ---------- planning ----------

def plan_pairs(
    essays_by_cohort: dict[str, list[dict]],
    venue: str,
    cohort_filter: set[str] | None,
    question_type_filter: str,
    essay_effort_filter: set[str] | None,
    same_model_generated_pairs: bool,
    context_kind: str,
    already_done: set[tuple[str, str, str]],
    human_vs_generated_only: bool = False,
    data_root: Path | str | None = None,
) -> tuple[list[tuple[str, str, dict, dict]], dict[str, int]]:
    plan: list[tuple[str, str, dict, dict]] = []
    stats = {"cohorts_considered": 0, "cohorts_filtered_by_qt": 0,
             "cohorts_planned": 0, "pairs_total": 0, "pairs_skipped_existing": 0,
             "pairs_skipped_cross_model_generated": 0,
             "pairs_skipped_generated_generated": 0, "pairs_to_run": 0}
    for cohort, essays in essays_by_cohort.items():
        stats["cohorts_considered"] += 1
        if cohort_filter and cohort not in cohort_filter:
            continue
        if question_type_filter != "all":
            qt = load_question_type(venue, cohort, data_root=data_root)
            if qt != question_type_filter:
                stats["cohorts_filtered_by_qt"] += 1
                continue
        # Cohort must have the shared-context file.
        if not context_path(venue, cohort, context_kind, data_root=data_root).exists():
            continue
        if essay_effort_filter:
            essays = [
                e for e in essays
                if e["kind"] == "human"
                or stem_effort(e["stem"]) in essay_effort_filter
            ]
        if len(essays) < 2:
            continue
        stats["cohorts_planned"] += 1
        for a, b in itertools.combinations(sorted(essays, key=lambda e: e["stem"]), 2):
            stats["pairs_total"] += 1
            if (
                human_vs_generated_only
                and a["kind"] != "human"
                and b["kind"] != "human"
            ):
                stats["pairs_skipped_generated_generated"] += 1
                continue
            if (
                same_model_generated_pairs
                and a["kind"] != "human"
                and b["kind"] != "human"
                and a.get("model") != b.get("model")
            ):
                stats["pairs_skipped_cross_model_generated"] += 1
                continue
            key = (cohort, a["stem"], b["stem"])
            if key in already_done:
                stats["pairs_skipped_existing"] += 1
                continue
            plan.append((cohort, "", a, b))
            stats["pairs_to_run"] += 1
    return plan, stats


def group_by_cohort(essays: Iterable[dict], kinds: set[str]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for e in essays:
        if e["kind"] not in kinds:
            continue
        by.setdefault(e["cohort"], []).append(e)
    return by


def stem_effort(stem: str) -> str:
    """Return the ``effort`` token of a generated stem
    (``api__family__effort__kind...``), or ``""`` for non-conforming stems."""
    parts = str(stem or "").split("__")
    return parts[2] if len(parts) >= 3 else ""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-root", default=None,
                   help="Dataset root directory; defaults to "
                        "$ARGUMENT_COLLAPSE_DATA_ROOT if set, otherwise "
                        "./data/dataset.")
    p.add_argument("--venue", required=True,
                   help="Venue subdirectory inside the data root.")
    p.add_argument("--cohort", action="append",
                   help="Restrict to this cohort; pass repeatedly to add more.")
    p.add_argument("--kinds", default="human,vanilla",
                   help="Comma-separated essay kinds (default: human,vanilla). "
                        "'vanilla' is the default LLM condition (no persona).")
    p.add_argument("--question-type", default="all",
                   choices=["stance", "open_ended", "all"])
    p.add_argument("--context-kind", default="question",
                   choices=["question", "lead"],
                   help="Shared cohort context fed to the judge: 'question' "
                        "loads 00_question.md, 'lead' loads 00_lead.md "
                        "(with a lead-aware judge prompt).")
    p.add_argument("--provider", choices=provider_choices(), default="vertex")
    p.add_argument("--model", default="gemini-3-flash-preview")
    p.add_argument("--effort", default="minimal")
    p.add_argument("--essay-effort",
                   help="Comma-separated generated-essay efforts to include "
                        "(humans are always retained). Filters essays, "
                        "unlike --effort which controls the judge.")
    p.add_argument("--same-model-generated-pairs", action="store_true",
                   help="When both essays are generated, only compare pairs "
                        "from the same model. Human-generated and human-"
                        "human pairs are unaffected.")
    p.add_argument("--human-vs-generated-only", action="store_true",
                   help="Only annotate human-vs-generated pairs (skip all "
                        "generated-generated pairs).")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--max-output-tokens", type=int, default=2000,
                   help="Max output tokens (Gemini-3 counts thinking against "
                        "this; raise if you see MAX_TOKENS finish_reason).")
    p.add_argument("--num-workers", type=int, default=20)
    p.add_argument("--limit-pairs", type=int)
    p.add_argument("--use-cache", action="store_true",
                   help="Vertex explicit context caching: cache (system "
                        "prompt + shared context) once per cohort and "
                        "reference it on every pair. Requires --context-"
                        "kind lead and --provider vertex; cohorts whose "
                        "cached content is below the model's min-token "
                        "threshold fall back to inline.")
    p.add_argument("--cache-ttl", type=int, default=1800,
                   help="TTL (seconds) for each per-cohort cache; deleted "
                        "explicitly after the cohort regardless.")
    p.add_argument("--force", action="store_true",
                   help="Re-judge even when a pair is already on disk.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    if args.data_root:
        set_data_root(args.data_root)

    kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
    cohort_filter = set(args.cohort) if args.cohort else None
    essay_effort_filter = (
        {e.strip() for e in args.essay_effort.split(",") if e.strip()}
        if args.essay_effort else None
    )

    progress(f"data_root={get_data_root()}")
    progress(f"loading essays from per-cohort {TOULMIN_FILENAME} ...")
    essays_idx = load_essays_with_main_arg(args.venue, data_root=args.data_root)
    essays_by_cohort = group_by_cohort(essays_idx.values(), kinds)
    progress(f"  {len(essays_idx)} essays across {len(essays_by_cohort)} cohorts "
             f"(kinds={sorted(kinds)})")

    already_done: set[tuple[str, str, str]] = (
        set() if args.force
        else load_existing_pairs(args.venue, data_root=args.data_root)
    )
    progress(f"existing pairs across per-cohort {OUT_FILENAME}: {len(already_done)}"
             f"{' (ignored, --force)' if args.force else ''}")

    plan, stats = plan_pairs(essays_by_cohort, args.venue,
                             cohort_filter, args.question_type,
                             essay_effort_filter,
                             args.same_model_generated_pairs,
                             args.context_kind, already_done,
                             args.human_vs_generated_only,
                             data_root=args.data_root)
    progress(f"plan: {stats}")

    if args.limit_pairs:
        plan = plan[: args.limit_pairs]
        progress(f"capped plan to {len(plan)} pairs (--limit-pairs)")

    if args.dry_run or not plan:
        progress("done (no judge calls made)")
        return 0

    q_cache: dict[str, str] = {}
    def get_question(cohort: str) -> str:
        if cohort not in q_cache:
            q_cache[cohort] = load_question(args.venue, cohort, args.context_kind,
                                            data_root=args.data_root)
        return q_cache[cohort]

    use_cache = bool(getattr(args, "use_cache", False))
    if use_cache and (args.context_kind != "lead" or args.provider != "vertex"):
        progress("--use-cache requires --context-kind lead and --provider vertex; "
                 "ignoring (running inline).")
        use_cache = False

    total = len(plan)
    done = 0
    failures = 0

    def run_pool(items: list, judge_fn) -> tuple[int, int]:
        nonlocal done
        local_fail = 0
        if args.num_workers == 1:
            for item in items:
                ok, msg = judge_fn(item)
                done += 1
                if not ok:
                    local_fail += 1
                if done % 50 == 0 or not ok:
                    progress(f"[{done}/{total}] {'OK' if ok else 'FAIL'} {msg}")
            return len(items), local_fail
        with ThreadPoolExecutor(max_workers=args.num_workers) as ex:
            futs = [ex.submit(judge_fn, it) for it in items]
            for fut in as_completed(futs):
                try:
                    ok, msg = fut.result()
                except Exception as exc:
                    local_fail += 1
                    done += 1
                    progress(f"[{done}/{total}] unexpected failure: {exc}")
                    continue
                done += 1
                if not ok:
                    local_fail += 1
                if done % 50 == 0 or not ok:
                    progress(f"[{done}/{total}] {'OK' if ok else 'FAIL'} {msg}")
        return len(items), local_fail

    if not use_cache:
        progress(f"calling judge ({args.provider}/{args.model}/{args.effort or 'default'}) "
                 f"on {len(plan)} pairs with {args.num_workers} workers")
        def task(item):
            cohort, _q, a, b = item
            return judge_pair(args, cohort, get_question(cohort), a, b,
                              data_root=args.data_root)
        _, failures = run_pool(plan, task)
        progress(f"complete: {done - failures}/{total} ok, {failures} failures")
        return 1 if failures else 0

    # Cached path: one explicit Vertex cache per cohort holding the
    # lead-aware system prompt + lead essay. Each per-pair request then
    # only carries the two main arguments.
    by_cohort: "OrderedDict[str, list]" = OrderedDict()
    for item in plan:
        by_cohort.setdefault(item[0], []).append(item)

    provider = get_provider(args.provider)
    # Rough token estimate for the cache-eligibility check (Gemini 3
    # explicit caches require >= ~4096 tokens).
    sys_tok = int(len(SYSTEM_PROMPT_LEAD.split()) * 1.3)
    MIN_CACHE_TOK = 4096
    progress(f"calling judge ({args.provider}/{args.model}/{args.effort or 'default'}) "
             f"on {len(plan)} pairs across {len(by_cohort)} cohorts, {args.num_workers} "
             f"workers, EXPLICIT CACHE per cohort (ttl={args.cache_ttl}s)")

    cached_cohorts = inline_cohorts = 0
    for cohort, items in by_cohort.items():
        lead = get_question(cohort)
        cached_text = f"{CONTEXT_LABELS['lead']}:\n{lead}"
        est_tok = sys_tok + int(len(lead.split()) * 1.3)
        cache_name = None
        if est_tok >= MIN_CACHE_TOK:
            try:
                cache_name = provider.create_cache(
                    model=args.model, system_instruction=SYSTEM_PROMPT_LEAD,
                    cached_text=cached_text, ttl_seconds=args.cache_ttl)
            except InferenceError as exc:
                progress(f"  {cohort}: cache create failed ({exc}); inline fallback")
                cache_name = None
        if cache_name:
            cached_cohorts += 1
            progress(f"  {cohort}: cache={cache_name.split('/')[-1]} "
                     f"(~{est_tok} tok) over {len(items)} pairs")
        else:
            inline_cohorts += 1
            progress(f"  {cohort}: inline (~{est_tok} tok < {MIN_CACHE_TOK}) "
                     f"over {len(items)} pairs")
        def task(item, _q=lead, _cn=cache_name):
            cohort_i, _, a, b = item
            return judge_pair(args, cohort_i, _q, a, b, cache_name=_cn,
                              data_root=args.data_root)
        try:
            _, fails = run_pool(items, task)
            failures += fails
        finally:
            if cache_name:
                provider.delete_cache(cache_name)

    progress(f"complete: {done - failures}/{total} ok, {failures} failures "
             f"(cached cohorts={cached_cohorts}, inline={inline_cohorts})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

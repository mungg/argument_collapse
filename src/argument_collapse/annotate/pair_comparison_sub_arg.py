#!/usr/bin/env python3
"""4-label pairwise judge over extracted ``sub_arguments`` within each cohort.

The sub-argument analogue of ``annotate.pair_comparison_main_arg``. Reads the
``sub_arguments`` already produced by ``annotate.toulmin``, compares the
sub-argument units across essays in the same cohort, and appends judgments
to that cohort's analysis directory.

Output: ``<data_root>/<venue>/<cohort>/analysis/sub_argument_pairs.jsonl``
with one row per judged sub-argument pair:

  {cohort, sub_i, sub_j, essay_i, essay_j, sub_index_i, sub_index_j,
   kind_i, kind_j, model_i, model_j,
   main_argument_i, main_argument_j, sub_argument_i, sub_argument_j,
   relation, rationale,
   judged_at_utc, judge_provider, judge_model, judge_effort,
   tagger_prompt_version}

By default the script compares sub-arguments across different essays only;
within-essay pairs measure how distinct the extractor made one essay's own
supporting claims, which is usually not the quantity of interest.

Run with ``python -m argument_collapse.annotate.pair_comparison_sub_arg``.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import re
import threading
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

OUT_FILENAME = "sub_argument_pairs.jsonl"
TOULMIN_FILENAME = "toulmin.jsonl"

VALID_RELATIONS = {"equivalent", "strong_overlap", "weak_overlap", "different"}
# Prompt-version tag stamped on each output row. ``judge_pair`` appends
# ``_lead`` or ``_none`` depending on the cohort's shared-context
# convention, so the three variants stay distinguishable.
TAGGER_PROMPT_VERSION = "pair_comparison_sub_arg"

_PROGRESS_LOCK = threading.Lock()
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
You compare two supporting sub-argument statements from op-ed essays that
respond to the SAME debate question. A sub-argument is a supporting reason,
mechanism, evidence claim, or consideration used to develop an essay's main
argument.

Decide the logical relation between the two sub-arguments. Return exactly one
`relation` from this 4-way scale:

- "equivalent": both sub-arguments make the SAME supporting point. They may
  use different wording, but a careful reader would treat them as the same
  reason, mechanism, evidence claim, or consideration.

- "strong_overlap": both sub-arguments share the same core supporting idea,
  but one adds details, scope, examples, or secondary implications that the
  other does not.

- "weak_overlap": both sub-arguments fall under the same broad concern or
  type of support, but the specific reason, mechanism, or evidence claim is
  different.

- "different": the sub-arguments do not share a substantive supporting point
  beyond answering the same debate question or belonging to the same broad
  topic.

Critical rules:
- All pairs share the debate question by construction, so shared topic alone
  is never enough for an overlap label.
- Focus on the supporting point itself, not whether the two essays have the
  same main conclusion. Two sub-arguments can overlap even if they support
  different final positions.
- The surrounding main arguments are provided only as context. Do not label
  two sub-arguments as overlapping merely because the main arguments are
  similar.
- If both statements use the same generic value word, such as fairness,
  safety, accountability, innovation, or democracy, that is not enough for
  overlap unless they also share the same concrete supporting idea.
- Use `equivalent` only when the two statements would collapse into one
  support point without losing substantive information.
- Use `strong_overlap` when they share the core support point but one is more
  specific or adds a related extension.
- Use `weak_overlap` when they share the broad kind of support but make
  different concrete points.

Return strict JSON:
{
  "relation": "equivalent" | "strong_overlap" | "weak_overlap" | "different",
  "rationale": "1-2 sentences explaining the relation, grounded in the actual sub-argument text"
}

## Calibration examples

Question: Should Brookline adopt a four-day workweek for municipal staff?
Essay I main argument: "Brookline should adopt the four-day workweek because the pilot improved work quality without reducing services."
Sub-argument I: "The pilot showed productivity held steady while sick leave declined."
Essay J main argument: "The four-day schedule should become permanent because the pilot improved staff well-being without hurting service delivery."
Sub-argument J: "Trial data showed comparable output and fewer health-related absences."
=> {"relation": "equivalent", "rationale": "Both sub-arguments make the same supporting point: the pilot maintained productivity while reducing absences. The wording differs, but the support claim is the same."}

Question: Should the city require electric scooters to be parked in marked corrals?
Essay I main argument: "The city should require corral parking and fine repeat violators."
Sub-argument I: "Unregulated sidewalk parking blocks curb cuts and makes travel harder for wheelchair users."
Essay J main argument: "The city should require corral parking and make operators map available spaces."
Sub-argument J: "Scooters left outside marked areas obstruct curb ramps, creating access problems for people with disabilities and parents with strollers."
=> {"relation": "strong_overlap", "rationale": "Both identify sidewalk obstruction and curb-ramp access as the core support point. J adds another affected group, but the central reason is shared."}

Question: How should Brookline reduce car traffic on Main Street?
Essay I main argument: "Brookline should redesign Main Street around transit and bikes."
Sub-argument I: "Reducing car lanes would make buses faster and more reliable."
Essay J main argument: "Brookline should raise downtown parking prices and fund a shuttle."
Sub-argument J: "Charging more for parking would discourage unnecessary car trips into the town center."
=> {"relation": "weak_overlap", "rationale": "Both sub-arguments support reducing car use, but they make different concrete mechanism claims: street redesign for bus reliability versus parking prices to discourage driving."}

Question: Should the Riverton library extend weekend hours?
Essay I main argument: "The library should extend weekend hours for working residents."
Sub-argument I: "Current hours leave residents with weekday jobs unable to use the building."
Essay J main argument: "Weekend hours should stay the same to protect children's programming."
Sub-argument J: "Extending hours would divert limited staff from the children's programs the library is known for."
=> {"relation": "different", "rationale": "The first sub-argument is about access for working residents, while the second is about staffing tradeoffs for children's programming. They do not share a substantive support point."}
"""


SYSTEM_PROMPT_LEAD = """\
You compare two supporting sub-argument statements from op-ed essays that
respond to the SAME lead essay (an opinion piece they are reacting to). A
sub-argument is a supporting reason, mechanism, evidence claim, or
consideration used to develop an essay's main argument.

Decide the logical relation between the two sub-arguments. Return exactly one
`relation` from this 4-way scale:

- "equivalent": both sub-arguments make the SAME supporting point. They may
  use different wording, but a careful reader would treat them as the same
  reason, mechanism, evidence claim, or consideration.

- "strong_overlap": both sub-arguments share the same core supporting idea,
  but one adds details, scope, examples, or secondary implications that the
  other does not.

- "weak_overlap": both sub-arguments fall under the same broad concern or
  type of support, but the specific reason, mechanism, or evidence claim is
  different.

- "different": the sub-arguments do not share a substantive supporting point
  beyond reacting to the same lead essay or belonging to the same broad
  topic.

Critical rules:
- All pairs in a cohort react to the same lead essay by construction, so
  shared topic alone is never enough for an overlap label.
- Focus on the supporting point itself, not whether the two essays have the
  same main conclusion. Two sub-arguments can overlap even if they support
  different final positions.
- The surrounding main arguments are provided only as context. Do not label
  two sub-arguments as overlapping merely because the main arguments are
  similar.
- If both statements use the same generic value word, such as fairness,
  safety, accountability, innovation, or democracy, that is not enough for
  overlap unless they also share the same concrete supporting idea.
- Use `equivalent` only when the two statements would collapse into one
  support point without losing substantive information.
- Use `strong_overlap` when they share the core support point but one is more
  specific or adds a related extension.
- Use `weak_overlap` when they share the broad kind of support but make
  different concrete points.

Return strict JSON:
{
  "relation": "equivalent" | "strong_overlap" | "weak_overlap" | "different",
  "rationale": "1-2 sentences explaining the relation, grounded in the actual sub-argument text"
}

## Calibration examples

(The examples below use simple invented debate questions as the shared
context to illustrate the label boundaries; the same logic applies when the
shared context is a lead essay.)

Question: Should Brookline adopt a four-day workweek for municipal staff?
Essay I main argument: "Brookline should adopt the four-day workweek because the pilot improved work quality without reducing services."
Sub-argument I: "The pilot showed productivity held steady while sick leave declined."
Essay J main argument: "The four-day schedule should become permanent because the pilot improved staff well-being without hurting service delivery."
Sub-argument J: "Trial data showed comparable output and fewer health-related absences."
=> {"relation": "equivalent", "rationale": "Both sub-arguments make the same supporting point: the pilot maintained productivity while reducing absences. The wording differs, but the support claim is the same."}

Question: Should the city require electric scooters to be parked in marked corrals?
Essay I main argument: "The city should require corral parking and fine repeat violators."
Sub-argument I: "Unregulated sidewalk parking blocks curb cuts and makes travel harder for wheelchair users."
Essay J main argument: "The city should require corral parking and make operators map available spaces."
Sub-argument J: "Scooters left outside marked areas obstruct curb ramps, creating access problems for people with disabilities and parents with strollers."
=> {"relation": "strong_overlap", "rationale": "Both identify sidewalk obstruction and curb-ramp access as the core support point. J adds another affected group, but the central reason is shared."}

Question: How should Brookline reduce car traffic on Main Street?
Essay I main argument: "Brookline should redesign Main Street around transit and bikes."
Sub-argument I: "Reducing car lanes would make buses faster and more reliable."
Essay J main argument: "Brookline should raise downtown parking prices and fund a shuttle."
Sub-argument J: "Charging more for parking would discourage unnecessary car trips into the town center."
=> {"relation": "weak_overlap", "rationale": "Both sub-arguments support reducing car use, but they make different concrete mechanism claims: street redesign for bus reliability versus parking prices to discourage driving."}

Question: Should the Riverton library extend weekend hours?
Essay I main argument: "The library should extend weekend hours for working residents."
Sub-argument I: "Current hours leave residents with weekday jobs unable to use the building."
Essay J main argument: "Weekend hours should stay the same to protect children's programming."
Sub-argument J: "Extending hours would divert limited staff from the children's programs the library is known for."
=> {"relation": "different", "rationale": "The first sub-argument is about access for working residents, while the second is about staffing tradeoffs for children's programming. They do not share a substantive support point."}
"""


SYSTEM_PROMPT_NONE = """\
You compare two supporting sub-argument statements from op-ed essays in the
same cohort. A sub-argument is a supporting reason, mechanism, evidence
claim, or consideration used to develop an essay's main argument. The
essays do not share a debate question or lead essay; only the cohort and
broad topic are shared.

Decide the logical relation between the two sub-arguments. Return exactly one
`relation` from this 4-way scale:

- "equivalent": both sub-arguments make the SAME supporting point. They may
  use different wording, but a careful reader would treat them as the same
  reason, mechanism, evidence claim, or consideration.

- "strong_overlap": both sub-arguments share the same core supporting idea,
  but one adds details, scope, examples, or secondary implications that the
  other does not.

- "weak_overlap": both sub-arguments fall under the same broad concern or
  type of support, but the specific reason, mechanism, or evidence claim is
  different.

- "different": the sub-arguments do not share a substantive supporting point
  beyond belonging to the same broad topic.

Critical rules:
- Cohort-internal pairs may share a topic by construction, so shared topic
  alone is never enough for an overlap label.
- Focus on the supporting point itself, not whether the two essays have the
  same main conclusion. Two sub-arguments can overlap even if they support
  different final positions.
- The surrounding main arguments are provided only as context. Do not label
  two sub-arguments as overlapping merely because the main arguments are
  similar.
- If both statements use the same generic value word, such as fairness,
  safety, accountability, innovation, or democracy, that is not enough for
  overlap unless they also share the same concrete supporting idea.
- Use `equivalent` only when the two statements would collapse into one
  support point without losing substantive information.
- Use `strong_overlap` when they share the core support point but one is more
  specific or adds a related extension.
- Use `weak_overlap` when they share the broad kind of support but make
  different concrete points.

Return strict JSON:
{
  "relation": "equivalent" | "strong_overlap" | "weak_overlap" | "different",
  "rationale": "1-2 sentences explaining the relation, grounded in the actual sub-argument text"
}

## Calibration examples

(The examples below use simple invented debate questions as the shared
context to illustrate the label boundaries; in the no-context setting the
same logic applies without any shared anchor.)

Question: Should Brookline adopt a four-day workweek for municipal staff?
Essay I main argument: "Brookline should adopt the four-day workweek because the pilot improved work quality without reducing services."
Sub-argument I: "The pilot showed productivity held steady while sick leave declined."
Essay J main argument: "The four-day schedule should become permanent because the pilot improved staff well-being without hurting service delivery."
Sub-argument J: "Trial data showed comparable output and fewer health-related absences."
=> {"relation": "equivalent", "rationale": "Both sub-arguments make the same supporting point: the pilot maintained productivity while reducing absences. The wording differs, but the support claim is the same."}

Question: Should the city require electric scooters to be parked in marked corrals?
Essay I main argument: "The city should require corral parking and fine repeat violators."
Sub-argument I: "Unregulated sidewalk parking blocks curb cuts and makes travel harder for wheelchair users."
Essay J main argument: "The city should require corral parking and make operators map available spaces."
Sub-argument J: "Scooters left outside marked areas obstruct curb ramps, creating access problems for people with disabilities and parents with strollers."
=> {"relation": "strong_overlap", "rationale": "Both identify sidewalk obstruction and curb-ramp access as the core support point. J adds another affected group, but the central reason is shared."}

Question: How should Brookline reduce car traffic on Main Street?
Essay I main argument: "Brookline should redesign Main Street around transit and bikes."
Sub-argument I: "Reducing car lanes would make buses faster and more reliable."
Essay J main argument: "Brookline should raise downtown parking prices and fund a shuttle."
Sub-argument J: "Charging more for parking would discourage unnecessary car trips into the town center."
=> {"relation": "weak_overlap", "rationale": "Both sub-arguments support reducing car use, but they make different concrete mechanism claims: street redesign for bus reliability versus parking prices to discourage driving."}

Question: Should the Riverton library extend weekend hours?
Essay I main argument: "The library should extend weekend hours for working residents."
Sub-argument I: "Current hours leave residents with weekday jobs unable to use the building."
Essay J main argument: "Weekend hours should stay the same to protect children's programming."
Sub-argument J: "Extending hours would divert limited staff from the children's programs the library is known for."
=> {"relation": "different", "rationale": "The first sub-argument is about access for working residents, while the second is about staffing tradeoffs for children's programming. They do not share a substantive support point."}
"""


def user_prompt(
    question: str,
    main_i: str,
    sub_i: str,
    main_j: str,
    sub_j: str,
    context_label: str = "Debate question",
) -> str:
    parts: list[str] = []
    q = (question or "").strip()
    if q:
        parts.append(f"{context_label}:\n{q}")
    parts.extend([
        f"Essay I main argument:\n{main_i.strip()}",
        f"Sub-argument I:\n{sub_i.strip()}",
        f"Essay J main argument:\n{main_j.strip()}",
        f"Sub-argument J:\n{sub_j.strip()}",
    ])
    return "\n\n".join(parts)


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

def load_sub_arguments(
    venue: str,
    data_root: Path | str | None = None,
) -> dict[tuple[str, str], dict]:
    """Load one row per extracted sub-argument from per-cohort toulmin files.

    Each output row carries the parent essay's stem + kind/model so the
    planner can join cohorts and apply same-essay / cross-family filters.
    """
    out: dict[tuple[str, str], dict] = {}
    for cohort, rows in iter_cohort_jsonl(venue, TOULMIN_FILENAME, data_root=data_root):
        for r in rows:
            main = str(r.get("main_argument") or "").strip()
            subs = r.get("sub_arguments") or []
            if not isinstance(subs, list):
                continue
            essay_stem = r["stem"]
            row_cohort = r.get("cohort", cohort)
            for idx, sub in enumerate(subs):
                sub_text = str(sub).strip()
                if not sub_text:
                    continue
                sub_id = f"{essay_stem}::sub{idx:02d}"
                out[(row_cohort, sub_id)] = {
                    "cohort": row_cohort,
                    "sub_id": sub_id,
                    "essay_stem": essay_stem,
                    "sub_index": idx,
                    "kind": r.get("kind", ""),
                    "model": r.get("model"),
                    "main_argument": main,
                    "sub_argument": sub_text,
                }
    return out


# ``--context-kind`` -> (filename, "missing" error label). ``question`` is
# the debate-question convention; ``lead`` is the lead-essay convention;
# ``none`` skips context loading and uses ``SYSTEM_PROMPT_NONE``.
CONTEXT_FILES = {
    "question": ("00_question.md", "question prompt"),
    "lead": ("00_lead.md", "lead essay"),
}
CONTEXT_LABELS = {
    "question": "Debate question",
    "lead": "Lead essay",
    "none": "",
}


def load_context(venue: str, cohort: str, context_kind: str = "question",
                 data_root: Path | str | None = None) -> str:
    if context_kind == "none":
        return ""
    filename, label = CONTEXT_FILES[context_kind]
    root = Path(data_root) if data_root is not None else get_data_root()
    path = root / venue / cohort / "human" / filename
    if not path.exists():
        raise FileNotFoundError(f"missing {label}: {path}")
    _fm, body = parse_frontmatter_and_body(path)
    return body


def load_question_type(venue: str, cohort: str,
                       data_root: Path | str | None = None) -> str | None:
    root = Path(data_root) if data_root is not None else get_data_root()
    path = root / venue / cohort / "question_type.json"
    if not path.exists():
        return None
    return json.loads(path.read_text()).get("question_type")


# ---------- output state ----------

def canonical_pair_key(cohort: str, sub_i: str, sub_j: str) -> tuple[str, str, str]:
    a, b = sorted((sub_i, sub_j))
    return (cohort, a, b)


def load_existing_pairs(
    venue: str,
    data_root: Path | str | None = None,
) -> set[tuple[str, str, str]]:
    seen: set[tuple[str, str, str]] = set()
    for cohort, rows in iter_cohort_jsonl(venue, OUT_FILENAME, data_root=data_root):
        for r in rows:
            seen.add(canonical_pair_key(r.get("cohort", cohort), r["sub_i"], r["sub_j"]))
    return seen


def append_row(venue: str, row: dict,
               data_root: Path | str | None = None) -> None:
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


def call_judge(args: argparse.Namespace, question: str,
               item_i: dict, item_j: dict) -> dict:
    ck = getattr(args, "context_kind", "question")
    sys_p = (SYSTEM_PROMPT_LEAD if ck == "lead"
             else SYSTEM_PROMPT_NONE if ck == "none"
             else SYSTEM_PROMPT)
    usr_p = user_prompt(
        question,
        item_i["main_argument"],
        item_i["sub_argument"],
        item_j["main_argument"],
        item_j["sub_argument"],
        context_label=CONTEXT_LABELS.get(ck, "Debate question"),
    )
    request = InferenceRequest(
        provider=args.provider,
        model=args.model,
        system_prompt=sys_p,
        user_prompt=usr_p,
        combined_prompt=sys_p + "\n\n" + usr_p,
        condition="sub_argument_judge_4label",
        effort=args.effort or "",
        request_params=request_params(args),
    )
    result = get_provider(args.provider).generate(request)
    payload = extract_json(result.text)
    return normalize(payload)


def judge_pair(
    args: argparse.Namespace,
    cohort: str,
    question: str,
    item_i: dict,
    item_j: dict,
    data_root: Path | str | None = None,
) -> tuple[bool, str]:
    try:
        ann = call_judge(args, question, item_i, item_j)
    except (InferenceError, ValueError, json.JSONDecodeError) as exc:
        return False, f"{cohort} {item_i['sub_id']}<>{item_j['sub_id']}: {exc}"
    ck = getattr(args, "context_kind", "question")
    prompt_version = TAGGER_PROMPT_VERSION + (
        "_lead" if ck == "lead"
        else "_none" if ck == "none"
        else ""
    )
    row = {
        "cohort": cohort,
        "sub_i": item_i["sub_id"],
        "sub_j": item_j["sub_id"],
        "essay_i": item_i["essay_stem"],
        "essay_j": item_j["essay_stem"],
        "sub_index_i": item_i["sub_index"],
        "sub_index_j": item_j["sub_index"],
        "kind_i": item_i["kind"],
        "kind_j": item_j["kind"],
        "model_i": item_i["model"],
        "model_j": item_j["model"],
        "main_argument_i": item_i["main_argument"],
        "main_argument_j": item_j["main_argument"],
        "sub_argument_i": item_i["sub_argument"],
        "sub_argument_j": item_j["sub_argument"],
        **ann,
        "judged_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "judge_provider": args.provider,
        "judge_model": args.model,
        "judge_effort": args.effort or "",
        "tagger_prompt_version": prompt_version,
    }
    append_row(args.venue, row, data_root=data_root)
    return True, f"{cohort} {item_i['sub_id'][:24]}...<>{item_j['sub_id'][:24]}... -> {ann['relation']}"


# ---------- planning ----------

# Maps a generated-essay stem prefix to its short model-family name. The
# entries below cover the paper's 5 LLM families; users running the
# pipeline on different generations should override ``FAM_PREFIX`` (or set
# ``--family-prefixes`` to a JSON file) before calling
# :func:`plan_pairs` with ``cross_family_only=True``.
FAM_PREFIX: dict[str, str] = {
    "openai-api__gpt-5.5":                        "gpt",
    "openrouter-api__anthropic-claude-opus-4.7":  "claude",
    "openrouter-api__deepseek-deepseek-v4-pro":   "deepseek",
    "vertex-api__gemini-3.1-pro-preview":         "gemini",
    "openrouter-api__minimax-minimax-m2.7":       "minimax",
}


def llm_family(stem: str, fam_prefix: dict[str, str] | None = None) -> str | None:
    table = fam_prefix if fam_prefix is not None else FAM_PREFIX
    for pre, fam in table.items():
        if stem.startswith(pre):
            return fam
    return None


def plan_pairs(
    subs_by_cohort: dict[str, list[dict]],
    venue: str,
    cohort_filter: set[str] | None,
    question_type_filter: str,
    already_done: set[tuple[str, str, str]],
    include_same_essay_pairs: bool,
    pair_groups: set[str],
    max_pairs_per_cohort: int | None,
    shuffle_seed: int,
    context_kind: str = "question",
    cross_family_only: bool = False,
    data_root: Path | str | None = None,
    fam_prefix: dict[str, str] | None = None,
) -> tuple[list[tuple[str, dict, dict]], dict[str, int]]:
    plan: list[tuple[str, dict, dict]] = []
    rng = random.Random(shuffle_seed)
    stats = {
        "cohorts_considered": 0,
        "cohorts_filtered_by_qt": 0,
        "cohorts_planned": 0,
        "pairs_total": 0,
        "pairs_skipped_pair_group": 0,
        "pairs_skipped_same_essay": 0,
        "pairs_skipped_same_family": 0,
        "pairs_skipped_existing": 0,
        "pairs_sampled_out": 0,
        "pairs_to_run": 0,
    }
    root = Path(data_root) if data_root is not None else get_data_root()
    for cohort, items in subs_by_cohort.items():
        stats["cohorts_considered"] += 1
        if cohort_filter and cohort not in cohort_filter:
            continue
        if question_type_filter != "all":
            qt = load_question_type(venue, cohort, data_root=data_root)
            if qt != question_type_filter:
                stats["cohorts_filtered_by_qt"] += 1
                continue
        if len(items) < 2:
            continue
        if context_kind != "none":
            ctx_filename, _ = CONTEXT_FILES[context_kind]
            if not (root / venue / cohort / "human" / ctx_filename).exists():
                continue
        stats["cohorts_planned"] += 1
        cohort_plan: list[tuple[str, dict, dict]] = []
        for a, b in itertools.combinations(sorted(items, key=lambda s: s["sub_id"]), 2):
            stats["pairs_total"] += 1
            if not include_same_essay_pairs and a["essay_stem"] == b["essay_stem"]:
                stats["pairs_skipped_same_essay"] += 1
                continue
            group = source_pair_group(a, b)
            if "all" not in pair_groups and group not in pair_groups:
                stats["pairs_skipped_pair_group"] += 1
                continue
            if cross_family_only and a["kind"] != "human" and b["kind"] != "human":
                fa = llm_family(a["essay_stem"], fam_prefix)
                fb = llm_family(b["essay_stem"], fam_prefix)
                if fa is not None and fb is not None and fa == fb:
                    stats["pairs_skipped_same_family"] += 1
                    continue
            key = canonical_pair_key(cohort, a["sub_id"], b["sub_id"])
            if key in already_done:
                stats["pairs_skipped_existing"] += 1
                continue
            cohort_plan.append((cohort, a, b))
            stats["pairs_to_run"] += 1
        if max_pairs_per_cohort is not None and len(cohort_plan) > max_pairs_per_cohort:
            rng.shuffle(cohort_plan)
            sampled_out = len(cohort_plan) - max_pairs_per_cohort
            stats["pairs_sampled_out"] += sampled_out
            stats["pairs_to_run"] -= sampled_out
            cohort_plan = cohort_plan[:max_pairs_per_cohort]
        plan.extend(cohort_plan)
    return plan, stats


def source_pair_group(item_i: dict, item_j: dict) -> str:
    is_human_i = item_i["kind"] == "human"
    is_human_j = item_j["kind"] == "human"
    if is_human_i and is_human_j:
        return "human-human"
    if is_human_i != is_human_j:
        return "human-llm"
    return "llm-llm"


def group_by_cohort(items: Iterable[dict], kinds: set[str]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for item in items:
        if item["kind"] not in kinds:
            continue
        by.setdefault(item["cohort"], []).append(item)
    return by


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
    p.add_argument("--context-kind", default="question",
                   choices=["question", "lead", "none"],
                   help="Shared cohort context fed to the judge: 'question' "
                        "loads 00_question.md (default), 'lead' loads "
                        "00_lead.md, 'none' skips context loading.")
    p.add_argument("--kinds", default="human,vanilla,diversified,position",
                   help="Comma-separated essay kinds to include "
                        "(default: human,vanilla,diversified,position).")
    p.add_argument("--question-type", default="all",
                   choices=["stance", "open_ended", "all"])
    p.add_argument("--include-same-essay-pairs", action="store_true",
                   help="Also judge pairs of sub-arguments from the same essay.")
    p.add_argument("--pair-groups", default="all",
                   help="Comma-separated pair groups to judge: all, human-"
                        "human, human-llm, llm-llm (default: all).")
    p.add_argument("--cross-family-only", action="store_true",
                   help="Skip LLM-LLM pairs where both essays come from the "
                        "same model family (e.g., gpt-gpt). Useful for the "
                        "diversified U_m which only needs cross-family pairs.")
    p.add_argument("--family-prefixes",
                   help="Optional JSON file mapping stem-prefix -> short "
                        "family name; overrides the built-in FAM_PREFIX "
                        "table used by --cross-family-only.")
    p.add_argument("--max-pairs-per-cohort", type=int,
                   help="Reproducibly sample at most this many unjudged "
                        "pairs per cohort.")
    p.add_argument("--shuffle-seed", type=int, default=17,
                   help="Seed used with --max-pairs-per-cohort.")
    p.add_argument("--include-personas-file",
                   help="JSON file mapping cohort -> list of persona slugs "
                        "to keep; only LLM essays whose persona (stem field "
                        "[4]) is in this list are included.")
    p.add_argument("--include-essays-file",
                   help="JSON file mapping cohort -> list of essay stems to "
                        "keep; only essays with stems in this list are "
                        "included (humans without stems in list are dropped).")
    p.add_argument("--provider", choices=provider_choices(), default="vertex")
    p.add_argument("--model", default="gemini-3-flash-preview")
    p.add_argument("--effort", default="minimal")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--max-output-tokens", type=int, default=1800)
    p.add_argument("--num-workers", type=int, default=20)
    p.add_argument("--limit-pairs", type=int)
    p.add_argument("--force", action="store_true",
                   help="Re-judge even when a pair is already on disk.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    if args.data_root:
        set_data_root(args.data_root)

    kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
    pair_groups = {g.strip() for g in args.pair_groups.split(",") if g.strip()}
    valid_pair_groups = {"all", "human-human", "human-llm", "llm-llm"}
    invalid_pair_groups = pair_groups - valid_pair_groups
    if invalid_pair_groups:
        p.error(f"invalid --pair-groups values: {sorted(invalid_pair_groups)}")
    cohort_filter = set(args.cohort) if args.cohort else None

    fam_prefix: dict[str, str] | None = None
    if args.family_prefixes:
        with open(args.family_prefixes) as f:
            fam_prefix = json.load(f)

    progress(f"data_root={get_data_root()}")
    progress(f"loading sub-arguments from per-cohort {TOULMIN_FILENAME} ...")
    sub_idx = load_sub_arguments(args.venue, data_root=args.data_root)
    subs_by_cohort = group_by_cohort(sub_idx.values(), kinds)
    if args.include_personas_file:
        with open(args.include_personas_file) as f:
            include_personas = {c: set(ps) for c, ps in json.load(f).items()}

        def _persona_of(stem: str) -> str | None:
            parts = stem.split("__")
            return parts[4] if len(parts) > 4 else None

        before = sum(len(v) for v in subs_by_cohort.values())
        for cohort, items in list(subs_by_cohort.items()):
            allowed = include_personas.get(cohort, set())
            subs_by_cohort[cohort] = [
                it for it in items
                if it["kind"] == "human"  # humans always kept
                or _persona_of(it["essay_stem"]) in allowed
            ]
        after = sum(len(v) for v in subs_by_cohort.values())
        progress(f"  persona filter: {before} -> {after} sub-args kept (cluster personas only)")

    if args.include_essays_file:
        with open(args.include_essays_file) as f:
            include_essays = {c: set(stems) for c, stems in json.load(f).items()}
        before = sum(len(v) for v in subs_by_cohort.values())
        for cohort, items in list(subs_by_cohort.items()):
            allowed = include_essays.get(cohort, set())
            subs_by_cohort[cohort] = [it for it in items if it["essay_stem"] in allowed]
        after = sum(len(v) for v in subs_by_cohort.values())
        progress(f"  essay filter: {before} -> {after} sub-args kept")
    progress(
        f"  {len(sub_idx)} sub-arguments across {len(subs_by_cohort)} cohorts "
        f"(kinds={sorted(kinds)})"
    )

    already_done: set[tuple[str, str, str]] = (
        set() if args.force else load_existing_pairs(args.venue, data_root=args.data_root)
    )
    progress(
        f"existing pairs across per-cohort {OUT_FILENAME}: {len(already_done)}"
        f"{' (ignored, --force)' if args.force else ''}"
    )

    plan, stats = plan_pairs(
        subs_by_cohort,
        args.venue,
        cohort_filter,
        args.question_type,
        already_done,
        args.include_same_essay_pairs,
        pair_groups,
        args.max_pairs_per_cohort,
        args.shuffle_seed,
        context_kind=args.context_kind,
        cross_family_only=args.cross_family_only,
        data_root=args.data_root,
        fam_prefix=fam_prefix,
    )
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
            q_cache[cohort] = load_context(args.venue, cohort, args.context_kind,
                                            data_root=args.data_root)
        return q_cache[cohort]

    progress(
        f"calling judge ({args.provider}/{args.model}/{args.effort or 'default'}) "
        f"on {len(plan)} sub-argument pairs with {args.num_workers} workers "
        f"(prompt={TAGGER_PROMPT_VERSION})"
    )

    total = len(plan)
    done = 0
    failures = 0

    def task(item: tuple[str, dict, dict]) -> tuple[bool, str]:
        cohort, a, b = item
        q = get_question(cohort)
        return judge_pair(args, cohort, q, a, b, data_root=args.data_root)

    if args.num_workers == 1:
        for item in plan:
            ok, msg = task(item)
            done += 1
            if not ok:
                failures += 1
            progress(f"[{done}/{total}] {'OK' if ok else 'FAIL'} {msg}")
        return 1 if failures else 0

    with ThreadPoolExecutor(max_workers=args.num_workers) as ex:
        futs = [ex.submit(task, item) for item in plan]
        for fut in as_completed(futs):
            try:
                ok, msg = fut.result()
            except Exception as exc:
                failures += 1
                done += 1
                progress(f"[{done}/{total}] unexpected failure: {exc}")
                continue
            done += 1
            if not ok:
                failures += 1
            if done % 50 == 0 or not ok:
                progress(f"[{done}/{total}] {'OK' if ok else 'FAIL'} {msg}")

    progress(f"complete: {done - failures}/{total} ok, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

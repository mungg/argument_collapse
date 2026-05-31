#!/usr/bin/env python3
"""Toulmin-style annotation: extract ``main_argument`` + ``sub_arguments`` per
essay.

For each essay in the venue × cohort × kind selection, call an LLM with the
toulmin extraction prompt and append a row to that cohort's
``<data_root>/<venue>/<cohort>/analysis/toulmin.jsonl``.

Schema (one row per essay):

  {cohort, stem, kind, model,
   main_argument, sub_arguments,
   annotated_at_utc, annotator_provider, annotator_model, annotator_effort,
   tagger_prompt_version}

Resume-safe: rows with the same ``(cohort, stem)`` are skipped unless
``--force``.

Run with ``python -m argument_collapse.annotate.toulmin``.
"""
from __future__ import annotations

import argparse
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional
    load_dotenv = None
if load_dotenv is not None:
    load_dotenv()

from argument_collapse.data import (
    cohort_analysis_path,
    find_human_responses,
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

# Per-cohort output filename:
# ``<data_root>/<venue>/<cohort>/analysis/toulmin.jsonl``
OUT_FILENAME = "toulmin.jsonl"

# Prompt-version tag stamped on each output row. The base name identifies
# the extraction task; ``annotate_one`` appends a ``_lead`` suffix when the
# cohort uses a lead-essay context instead of a debate question, so the two
# variants are distinguishable in the released JSONL.
TAGGER_PROMPT_VERSION = "toulmin_annotation"

_PROGRESS_LOCK = threading.Lock()
# One file per cohort; per-cohort locks let cohorts run concurrently while
# guaranteeing each output file has serialized writers.
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
Given an op-ed essay and the debate question it responds to, extract the
essay's argumentative structure.

Field definitions:
- main_argument: The single central claim the essay makes in response to
  the debate question (1 sentence).
- sub_arguments: Distinct supporting claims that develop or back the
  main_argument. Each one sentence. Avoid restating the main_argument or another sub_argument.

Return strict JSON:
{
  "annotation": {
    "main_argument": "...",
    "sub_arguments": ["...", "..."]
  }
}
"""

# Lead-aware variant for venues where responders react to a shared lead
# essay rather than answering a debate question.
SYSTEM_PROMPT_LEAD = """\
Given an op-ed essay and the lead essay it responds to, extract the
responding essay's argumentative structure.

Field definitions:
- main_argument: The single central claim the responding essay makes in
  response to the lead essay (1 sentence).
- sub_arguments: Distinct supporting claims that develop or back the
  main_argument. Each one sentence. Avoid restating the main_argument or another sub_argument.

Extract the structure of the RESPONDING essay only; the lead essay is
context for what the response is reacting to, not material to summarize.

Return strict JSON:
{
  "annotation": {
    "main_argument": "...",
    "sub_arguments": ["...", "..."]
  }
}
"""

# ``--context-kind`` -> (filename inside ``<cohort>/human/``, user-prompt
# label). ``question`` is the debate-question convention; ``lead`` is the
# lead-essay convention.
CONTEXT_FILES = {"question": "00_question.md", "lead": "00_lead.md"}
CONTEXT_LABELS = {"question": "Debate question", "lead": "Lead essay"}


def user_prompt(context: str, body: str, context_label: str = "Debate question") -> str:
    c = (context or "").strip()
    context_block = f"{context_label}:\n{c}\n\n" if c else ""
    return f"{context_block}Essay:\n{body.strip()}"


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
    ann = payload.get("annotation") if isinstance(payload.get("annotation"), dict) else payload
    main = str(ann.get("main_argument", "")).strip()
    subs_raw = ann.get("sub_arguments") or []
    if not isinstance(subs_raw, list):
        raise ValueError(f"sub_arguments must be a list, got {type(subs_raw).__name__}")
    subs = [str(s).strip() for s in subs_raw if str(s).strip()]
    if not main:
        raise ValueError("main_argument missing or empty")
    return {"main_argument": main, "sub_arguments": subs}


# ---------- data loading ----------

# Map a generated-essay model-family token to its short name. The released
# dataset uses long family tokens like ``anthropic-claude-opus-4.7``; this
# table compresses those down to the short model name used in row metadata.
_MODEL_FROM_FAMILY = (
    ("gpt", "gpt"),
    ("gemini", "gemini"),
    ("claude", "claude"),
    ("minimax", "minimax"),
    ("deepseek", "deepseek"),
    ("kimi", "kimi"),
)


def _model_from_family(family: str) -> str | None:
    family = family.lower()
    for token, name in _MODEL_FROM_FAMILY:
        if token in family:
            return name
    return None


def parse_generated_stem(stem: str) -> dict | None:
    """Parse a generated-essay filename stem.

    The convention is ``{api}__{model_family}__{effort}__{kind}[__{persona}]__{timestamp}``.
    Returns ``{kind, model, persona}`` or ``None`` if the stem doesn't match.
    """
    parts = stem.split("__")
    if len(parts) < 5:
        return None
    _api, family, _effort, kind = parts[:4]
    persona = parts[4] if len(parts) >= 6 else None
    return {"kind": kind, "model": _model_from_family(family), "persona": persona}


def discover_essays(venue: str, kinds: set[str],
                    data_root: Path | str | None = None) -> list[dict]:
    """Walk ``<data_root>/<venue>/*/`` for human and generated essays.

    Returns rows shaped like the essays index used elsewhere in the
    pipeline:

      {cohort, stem, kind, model, persona, path}
    """
    root = Path(data_root) if data_root is not None else get_data_root()
    venue_root = root / venue
    if not venue_root.is_dir():
        return []
    out: list[dict] = []
    for cohort_dir in sorted(venue_root.iterdir()):
        if not cohort_dir.is_dir():
            continue
        cohort = cohort_dir.name
        human_dir = cohort_dir / "human"
        if "human" in kinds and human_dir.is_dir():
            # Skip the lead, the derived question, and any role-tagged
            # non-response files. Only human responder essays count.
            for path in find_human_responses(cohort_dir):
                out.append({
                    "cohort": cohort, "stem": path.stem,
                    "kind": "human", "model": None, "persona": None,
                    "path": str(path),
                })
        gen_dir = cohort_dir / "generated"
        if gen_dir.is_dir():
            for path in sorted(gen_dir.glob("*.md")):
                parsed = parse_generated_stem(path.stem)
                if parsed is None:
                    continue
                if parsed["kind"] not in kinds:
                    continue
                out.append({
                    "cohort": cohort, "stem": path.stem,
                    "kind": parsed["kind"], "model": parsed["model"],
                    "persona": parsed["persona"], "path": str(path),
                })
    return out


def load_existing(venue: str,
                  data_root: Path | str | None = None) -> set[tuple[str, str]]:
    """Return the ``(cohort, stem)`` set already present across every per-
    cohort ``analysis/toulmin.jsonl`` under the given venue.
    """
    seen: set[tuple[str, str]] = set()
    for cohort, rows in iter_cohort_jsonl(venue, OUT_FILENAME, data_root=data_root):
        for r in rows:
            seen.add((r.get("cohort", cohort), r["stem"]))
    return seen


def append_row(venue: str, row: dict,
               data_root: Path | str | None = None) -> None:
    """Append ``row`` to its cohort's ``analysis/toulmin.jsonl``.

    Uses a per-cohort lock so concurrent writes against different cohorts
    don't block each other.
    """
    cohort = row["cohort"]
    path = cohort_analysis_path(venue, cohort, OUT_FILENAME, data_root=data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False)
    with _cohort_lock(cohort):
        with path.open("a") as fh:
            fh.write(line + "\n")


# ---------- LLM call ----------

def request_params(args: argparse.Namespace) -> dict[str, Any]:
    """Translate top-level CLI flags into provider-specific request kwargs.

    Most providers want ``temperature`` and a ``max_*_tokens`` field, but the
    field name and applicability vary per provider, so this helper hides
    those details from ``call_annotator``.
    """
    params: dict[str, Any] = {}
    # vertex-claude does not honor a temperature kwarg through this path.
    if args.temperature is not None and args.provider != "vertex-claude":
        params["temperature"] = args.temperature
    if args.max_output_tokens is not None:
        if args.provider in {"openai", "vertex"}:
            params["max_output_tokens"] = args.max_output_tokens
        else:
            params["max_tokens"] = args.max_output_tokens
    return params


def call_annotator(args: argparse.Namespace, question: str, body: str) -> dict:
    context_kind = getattr(args, "context_kind", "question")
    sys_p = SYSTEM_PROMPT_LEAD if context_kind == "lead" else SYSTEM_PROMPT
    usr_p = user_prompt(question, body, context_label=CONTEXT_LABELS[context_kind])
    request = InferenceRequest(
        provider=args.provider,
        model=args.model,
        system_prompt=sys_p,
        user_prompt=usr_p,
        combined_prompt=sys_p + "\n\n" + usr_p,
        condition="toulmin_annotation",
        effort=args.effort or "",
        request_params=request_params(args),
    )
    result = get_provider(args.provider).generate(request)
    payload = extract_json(result.text)
    return normalize(payload)


def annotate_one(args: argparse.Namespace, essay: dict,
                 question: str, body: str,
                 data_root: Path | str | None = None) -> tuple[bool, str]:
    try:
        ann = call_annotator(args, question, body)
    except (InferenceError, ValueError, json.JSONDecodeError) as exc:
        return False, f"{essay['cohort']} {essay['stem'][:32]}: {exc}"
    context_kind = getattr(args, "context_kind", "question")
    prompt_version = (
        TAGGER_PROMPT_VERSION + "_lead" if context_kind == "lead"
        else TAGGER_PROMPT_VERSION
    )
    row = {
        "cohort": essay["cohort"],
        "stem": essay["stem"],
        "kind": essay.get("kind", ""),
        "model": essay.get("model"),
        **ann,
        "annotated_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "annotator_provider": args.provider,
        "annotator_model": args.model,
        "annotator_effort": args.effort or "",
        "tagger_prompt_version": prompt_version,
    }
    append_row(args.venue, row, data_root=data_root)
    return True, f"{essay['cohort']} {essay['stem'][:32]} -> {len(ann['sub_arguments'])} subs"


def load_question_cached(venue: str, cohort: str, cache: dict[str, str],
                         context_kind: str = "question",
                         data_root: Path | str | None = None) -> str:
    if cohort in cache:
        return cache[cohort]
    root = Path(data_root) if data_root is not None else get_data_root()
    path = root / venue / cohort / "human" / CONTEXT_FILES[context_kind]
    if not path.exists():
        cache[cohort] = ""
        return ""
    try:
        _fm, body = parse_frontmatter_and_body(path)
        cache[cohort] = body
    except Exception:
        cache[cohort] = ""
    return cache[cohort]


# ---------- planning ----------

def plan_essays(
    essays: list[dict],
    cohort_filter: set[str] | None,
    already_done: set[tuple[str, str]],
) -> tuple[list[tuple[dict, str]], dict[str, int]]:
    """Apply cohort filter and skip-existing to a discovered essay list.

    Each plan entry is ``(essay_row, resolved_md_path)``.
    """
    plan: list[tuple[dict, str]] = []
    stats = {"essays_considered": 0, "filtered_by_cohort": 0,
             "skipped_existing": 0, "to_run": 0}
    for e in essays:
        stats["essays_considered"] += 1
        if cohort_filter and e["cohort"] not in cohort_filter:
            stats["filtered_by_cohort"] += 1
            continue
        key = (e["cohort"], e["stem"])
        if key in already_done:
            stats["skipped_existing"] += 1
            continue
        plan.append((e, e["path"]))
        stats["to_run"] += 1
    return plan, stats


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
    p.add_argument("--kinds", default="human,vanilla,diversified,position",
                   help="Comma-separated essay kinds to include "
                        "(default: human,vanilla,diversified,position). "
                        "'vanilla' = default LLM (no persona); "
                        "'diversified' = 1-per-family diverse sampling; "
                        "'position' = position-grounded.")
    p.add_argument("--context-kind", default="question",
                   choices=["question", "lead"],
                   help="Shared cohort context fed to the tagger: 'question' "
                        "loads 00_question.md, 'lead' loads 00_lead.md (with "
                        "a lead-aware extraction prompt).")
    p.add_argument("--provider", choices=provider_choices(), default="vertex")
    p.add_argument("--model", default="gemini-3-flash-preview")
    p.add_argument("--effort", default="minimal")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--max-output-tokens", type=int, default=1200)
    p.add_argument("--num-workers", type=int, default=20)
    p.add_argument("--limit-essays", type=int)
    p.add_argument("--force", action="store_true",
                   help="Re-annotate even when (cohort, stem) is already on disk.")
    p.add_argument("--dry-run", action="store_true",
                   help="Plan the run and print stats without calling the annotator.")
    args = p.parse_args(argv)

    if args.data_root:
        set_data_root(args.data_root)

    kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
    cohort_filter = set(args.cohort) if args.cohort else None

    progress(f"data_root={get_data_root()}")
    progress(f"discovering essays in {args.venue}/ (kinds={sorted(kinds)}) ...")
    essays = discover_essays(args.venue, kinds, data_root=args.data_root)
    progress(f"  {len(essays)} essays on disk matching selected kinds")

    already_done = (set() if args.force
                    else load_existing(args.venue, data_root=args.data_root))
    progress(f"existing rows across per-cohort {OUT_FILENAME}: {len(already_done)}"
             f"{' (ignored, --force)' if args.force else ''}")

    plan, stats = plan_essays(essays, cohort_filter, already_done)
    progress(f"plan: {stats}")

    if args.limit_essays:
        plan = plan[: args.limit_essays]
        progress(f"capped plan to {len(plan)} essays (--limit-essays)")

    if args.dry_run or not plan:
        progress("done (no annotator calls made)")
        return 0

    eff_version = TAGGER_PROMPT_VERSION + ("_lead" if args.context_kind == "lead" else "")
    progress(f"calling annotator ({args.provider}/{args.model}/{args.effort or 'default'}) "
             f"on {len(plan)} essays with {args.num_workers} workers "
             f"(prompt={eff_version}, context_kind={args.context_kind})")

    total = len(plan)
    done = 0
    failures = 0
    question_cache: dict[str, str] = {}

    def task(item):
        essay, path = item
        try:
            _fm, body = parse_frontmatter_and_body(Path(path))
        except Exception as exc:
            return False, f"{essay['cohort']} {essay['stem'][:32]}: parse failure: {exc}"
        if not body.strip():
            return False, f"{essay['cohort']} {essay['stem'][:32]}: empty body"
        question = load_question_cached(args.venue, essay["cohort"], question_cache,
                                         args.context_kind,
                                         data_root=args.data_root)
        return annotate_one(args, essay, question, body, data_root=args.data_root)

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

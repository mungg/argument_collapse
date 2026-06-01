#!/usr/bin/env python3
"""Two-stage stance labelling for the binary cohorts used in the paper.

The pipeline is split into two stages because side definitions are shared
across all essays in a cohort:

* **Stage 1** — for each cohort, extract a one-sentence ``support_side`` and
  ``oppose_side`` from the cohort's debate question. Cached per cohort.
* **Stage 2** — for every essay in those cohorts, label its final position on
  the extracted sides as ``strong_oppose`` / ``weak_oppose`` / ``neutral`` /
  ``weak_support`` / ``strong_support``. Cached per
  ``(cohort, stem, prompt_version, sides_hash)`` tuple.

Run with ``python -m argument_collapse.annotate.stance stage1|stage2 ...``.

Both stages call an LLM via :mod:`argument_collapse.inference`; the default
provider/model is configurable via flags so the same script works against
Vertex (Gemini), OpenAI, OpenRouter, etc.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional
    load_dotenv = None
if load_dotenv is not None:
    load_dotenv()

from argument_collapse.data import (
    get_data_root,
    parse_frontmatter_and_body,
    set_data_root,
)
from argument_collapse.inference import (
    InferenceError,
    InferenceRequest,
    get_provider,
    provider_choices,
)

# Prompt-version tags used to key the per-stage filesystem cache. Internal
# iteration numbers from development have been collapsed to descriptive
# names for the public release.
STAGE1_PROMPT_VERSION = "stance_stage1"
STAGE2_PROMPT_VERSION = "stance_stage2"

_PROGRESS_LOCK = threading.Lock()


def progress(message: str) -> None:
    with _PROGRESS_LOCK:
        print(message, flush=True)


# ---------- prompts ----------

STAGE1_SYSTEM_PROMPT = """\
You will receive a debate title and a debate question body.

Your task is to extract the two sides of the debate as very concise statements:
- "support_side": the side treated as the supported position under the annotation convention
- "oppose_side": the opposing side

Goal
Identify the single binary debate axis that defines the debate, then express its two sides concisely.

Rules for choosing the debate axis
1. If the title states a clear binary debate question, use the title axis.
2. Otherwise, use the first explicit binary question in the body.
3. If the body restates the same axis more explicitly, you may use the body wording, but do not change the axis.
4. If the body introduces a different axis from a clear binary title, keep the title axis.
5. Ignore wh-questions (what / how / why / when / where) when identifying the axis.
6. Never merge two different binary questions into one combined side definition.
7. If no usable binary axis can be identified in either the title or the body, return "none" for both sides.

How to map the chosen axis
- For yes/no, should/should-not, is/is-not, can/cannot questions:
  - support = yes / should / is / can
  - oppose = no / should-not / is-not / cannot
- For genuine binary choice questions ("A or B"):
  - support = the first option
  - oppose = the second option

Writing constraints
- Write each side as a short, content-preserving statement, not just "yes" or "no".
- The two sides must be true opposites on the same axis.
- Do not add content from another question or another axis.
- If the title and body use different wording for the same axis, prefer the clearer wording.
- Preserve important scope qualifiers when present, such as time, place, population, or institution (for example: "contemporary," "in the U.S.," "for local drug cases"), unless removing them would clearly not change the debate axis.

Return strict JSON only:
{
  "support_side": "string or none",
  "oppose_side": "string or none",
  "source": "title_binary" | "body_first_binary" | "body_restatement_of_title" | "none",
  "rationale": "One sentence explaining which axis was chosen and why."
}
"""

STAGE2_SYSTEM_PROMPT = """\
You will receive:
- a support-side statement
- an oppose-side statement
- an op-ed essay

Your task is to label the essay's final position relative to the provided side definitions.

The support_side and oppose_side define the debate axis.
Use them exactly as given.
Do not redefine the issue, substitute a different question, or infer a different debate axis from the essay.

Label set
- "strong_support": The essay clearly and firmly endorses the support side. Its final position is decisive and minimally qualified.
- "weak_support": The essay ultimately leans toward the support side, but its final position is meaningfully qualified, limited in scope, or noticeably hedged.
- "neutral": The essay does not ultimately commit to either side. This includes balanced discussion, unresolved ambiguity, mixed or split positions without a clear final choice, rejecting the premise, or reframing the issue instead of choosing between the provided sides.
- "weak_oppose": The essay ultimately leans toward the oppose side, but its final position is meaningfully qualified, limited in scope, or noticeably hedged.
- "strong_oppose": The essay clearly and firmly endorses the oppose side. Its final position is decisive and minimally qualified.

Important rules
- If the essay ultimately lands on one side, even with qualifications, do not label it "neutral".
- Use "neutral" only when the essay does not finally choose either side.
- If the essay leans more toward one side than the other, use "weak_support" or "weak_oppose" rather than "neutral".
- Judge "weak" vs "strong" based on strength of commitment to the final position, not on tone alone.
- Conditionality suggests "weak" only when it meaningfully limits the final position.
- Strong language alone does not make a label "strong" if the conclusion is substantially qualified.
- Calm or analytical wording can still be "strong" if the final commitment is clear and firm.

Return strict JSON only:
{
  "label": "strong_support" | "weak_support" | "neutral" | "weak_oppose" | "strong_oppose",
  "rationale": "One sentence explaining which side the essay ultimately supports, or why it remains neutral."
}
"""

STAGE2_LABELS = {
    "strong_support", "weak_support", "neutral", "weak_oppose", "strong_oppose"
}


# ---------- helpers ----------

def stable_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def extract_json(text: str) -> dict[str, Any]:
    """Same brace-matching JSON parser used by the other annotation
    scripts. Tolerates leading ```json fences."""
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


def split_question(venue: str, cohort: str,
                   data_root: Path | str | None = None) -> tuple[str, str]:
    """Return ``(title, body)`` for the cohort's debate question.

    Front-matter (if any) is stripped; the first ``#``/``##``-prefixed line
    of the body becomes the title.
    """
    root = Path(data_root) if data_root is not None else get_data_root()
    path = root / venue / cohort / "human" / "00_question.md"
    _fm, body = parse_frontmatter_and_body(path)
    lines = body.strip().split("\n", 1)
    title = lines[0].lstrip("#").strip()
    rest = lines[1].strip() if len(lines) > 1 else ""
    return title, rest


def load_body(venue: str, cohort: str, stem: str,
              data_root: Path | str | None = None) -> str:
    """Read one essay's markdown body (no front-matter, no leading title)."""
    root = Path(data_root) if data_root is not None else get_data_root()
    for sub in ("human", "generated"):
        path = root / venue / cohort / sub / f"{stem}.md"
        if path.exists():
            _fm, body = parse_frontmatter_and_body(path)
            return body.strip()
    return ""


def kind_of(stem: str) -> str:
    """Coarse ``kind-model`` label used by downstream Stage 2 aggregation
    (``vanilla-gpt``, ``diversified-claude``, ``human``, ...).

    Recognises the three LLM conditions shipped in the public release
    (``vanilla``, ``diversified``, ``position``); anything else is
    treated as a human essay.
    """
    if "diversified" in stem:
        v = "diversified"
    elif "position" in stem:
        v = "position"
    elif "vanilla" in stem:
        v = "vanilla"
    else:
        return "human"
    if "gpt-5" in stem:
        m = "gpt"
    elif "gemini" in stem:
        m = "gemini"
    elif "claude-opus" in stem:
        m = "opus"
    elif "minimax" in stem:
        m = "minimax"
    elif "deepseek" in stem:
        m = "deepseek"
    else:
        m = "other"
    return f"{v}-{m}"


def request_params(args: argparse.Namespace, max_output_tokens: int) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if args.temperature is not None and args.provider != "vertex-claude":
        params["temperature"] = args.temperature
    if args.provider in {"openai", "vertex"}:
        params["max_output_tokens"] = max_output_tokens
    else:
        params["max_tokens"] = max_output_tokens
    return params


def call_llm(args: argparse.Namespace, system_prompt: str, user_prompt: str,
             condition: str, max_output_tokens: int) -> dict[str, Any]:
    """Submit one prompt and return the parsed JSON payload."""
    request = InferenceRequest(
        provider=args.provider,
        model=args.model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        combined_prompt=system_prompt + "\n\n" + user_prompt,
        condition=condition,
        effort=args.effort or "",
        request_params=request_params(args, max_output_tokens),
    )
    result = get_provider(args.provider).generate(request)
    return extract_json(result.text)


# ---------- Stage 1: side extraction ----------

def extract_sides(args: argparse.Namespace, cohort: str,
                  cache_dir: Path | None,
                  data_root: Path | str | None = None) -> dict:
    """Extract ``support_side`` / ``oppose_side`` for one cohort.

    The result is cached at ``cache_dir/<key>.json`` (key derived from
    cohort + prompt version) so repeated runs do not re-bill the API.
    Pass ``cache_dir=None`` to disable caching entirely.
    """
    key = stable_hash(cohort, STAGE1_PROMPT_VERSION)
    cache_file = (cache_dir / f"{key}.json") if cache_dir is not None else None
    if cache_file is not None and cache_file.exists():
        rec = json.loads(cache_file.read_text())
        rec["_cached"] = True
        return rec

    title, body = split_question(args.venue, cohort, data_root=data_root)
    user = f"Debate title:\n{title}\n\nDebate question body:\n{body}\n"
    try:
        payload = call_llm(args, STAGE1_SYSTEM_PROMPT, user,
                           condition="stance_stage1_sides",
                           max_output_tokens=400)
    except (InferenceError, json.JSONDecodeError) as exc:
        return {"cohort": cohort, "error": str(exc), "_cached": False}

    rec = {
        "cohort": cohort,
        "support_side": payload.get("support_side"),
        "oppose_side": payload.get("oppose_side"),
        "source": payload.get("source"),
        "rationale": payload.get("rationale"),
        "_cached": False,
    }
    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def run_stage1(args: argparse.Namespace) -> int:
    if not args.cohort:
        progress("error: stage1 requires at least one --cohort")
        return 2

    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)

    sides: dict[str, dict] = {}
    errors = 0
    with ThreadPoolExecutor(max_workers=args.num_workers) as ex:
        futs = {ex.submit(extract_sides, args, c, cache_dir,
                           data_root=args.data_root): c
                for c in args.cohort}
        for fut in as_completed(futs):
            rec = fut.result()
            if "error" in rec:
                errors += 1
                progress(f"  {rec['cohort']}: ERROR {rec['error']}")
            sides[rec["cohort"]] = rec

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(sides, ensure_ascii=False, indent=2))
    progress(f"saved {len(sides)} cohorts -> {out_path}"
             f"{f' ({errors} errors)' if errors else ''}")
    return 1 if errors else 0


# ---------- Stage 2: essay labelling ----------

def label_essay(args: argparse.Namespace, cohort: str, stem: str,
                sides: dict, cache_dir: Path | None,
                data_root: Path | str | None = None) -> dict:
    """Label one essay against pre-extracted ``support_side`` /
    ``oppose_side``.

    Cached by ``(cohort, stem, prompt_version, sides_hash)`` so a change to
    the side definitions invalidates the relevant entries.
    """
    sides_hash = stable_hash(sides.get("support_side", "") or "",
                              sides.get("oppose_side", "") or "")
    key = stable_hash(cohort, stem, STAGE2_PROMPT_VERSION, sides_hash)
    cache_file = (cache_dir / f"{key}.json") if cache_dir is not None else None
    if cache_file is not None and cache_file.exists():
        rec = json.loads(cache_file.read_text())
        rec["_cached"] = True
        return rec

    body = load_body(args.venue, cohort, stem, data_root=data_root)
    if not body:
        return {"cohort": cohort, "stem": stem,
                "error": "essay markdown not found",
                "_cached": False}
    truncated = body[: args.max_body_chars]
    user = (
        f"support_side: {sides.get('support_side')}\n"
        f"oppose_side: {sides.get('oppose_side')}\n\n"
        f"Essay:\n{truncated}\n"
    )
    try:
        payload = call_llm(args, STAGE2_SYSTEM_PROMPT, user,
                           condition="stance_stage2_label",
                           max_output_tokens=300)
    except (InferenceError, json.JSONDecodeError) as exc:
        return {"cohort": cohort, "stem": stem, "error": str(exc),
                "_cached": False}

    label = payload.get("label")
    if label not in STAGE2_LABELS:
        return {"cohort": cohort, "stem": stem,
                "error": f"invalid label {label!r}",
                "_cached": False}

    rec = {
        "cohort": cohort,
        "stem": stem,
        "support_side": sides.get("support_side"),
        "oppose_side": sides.get("oppose_side"),
        "label": label,
        "rationale": payload.get("rationale", ""),
        "_cached": False,
    }
    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(rec, ensure_ascii=False, indent=2))
    return rec


def discover_stage2_essays(venue: str, cohort: str,
                           data_root: Path | str | None = None) -> list[str]:
    """List essay stems in ``<cohort>/{human,generated}/*.md`` (excluding
    the debate-question file itself)."""
    root = Path(data_root) if data_root is not None else get_data_root()
    out: list[str] = []
    for sub in ("human", "generated"):
        d = root / venue / cohort / sub
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            if f.stem == "00_question":
                continue
            out.append(f.stem)
    return out


def run_stage2(args: argparse.Namespace) -> int:
    sides_path = Path(args.sides)
    if not sides_path.exists():
        progress(f"error: --sides file not found: {sides_path}")
        return 2
    sides_by_cohort = json.loads(sides_path.read_text())

    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)

    cohorts = args.cohort if args.cohort else sorted(sides_by_cohort.keys())

    tasks: list[tuple[str, str]] = []
    for cohort in cohorts:
        if cohort not in sides_by_cohort:
            progress(f"  {cohort}: no sides in {sides_path.name}, skipping")
            continue
        for stem in discover_stage2_essays(args.venue, cohort,
                                            data_root=args.data_root):
            tasks.append((cohort, stem))
    progress(f"total essays to label: {len(tasks)}")

    if args.dry_run:
        return 0

    results: list[dict] = []
    errors = 0
    done = 0
    with ThreadPoolExecutor(max_workers=args.num_workers) as ex:
        futs = [
            ex.submit(label_essay, args, c, s, sides_by_cohort[c], cache_dir,
                       data_root=args.data_root)
            for (c, s) in tasks
        ]
        for fut in as_completed(futs):
            rec = fut.result()
            done += 1
            if "error" in rec:
                errors += 1
                progress(f"[{done}/{len(tasks)}] ERROR {rec['cohort']} "
                         f"{rec.get('stem','')}: {rec['error']}")
                continue
            rec["kind"] = kind_of(rec["stem"])
            results.append(rec)
            if done % 100 == 0:
                progress(f"[{done}/{len(tasks)}] labelled")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    progress(f"saved {len(results)} labels -> {out_path}"
             f"{f' ({errors} errors)' if errors else ''}")
    return 1 if errors else 0


# ---------- CLI ----------

def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--data-root", default=None,
                   help="Dataset root directory; defaults to "
                        "$ARGUMENT_COLLAPSE_DATA_ROOT if set, otherwise "
                        "./data.")
    p.add_argument("--venue", required=True,
                   help="Venue subdirectory inside the data root.")
    p.add_argument("--cache-dir", default=None,
                   help="Per-stage cache directory; omit to disable caching.")
    p.add_argument("--provider", choices=provider_choices(), default="vertex")
    p.add_argument("--model", default="gemini-3-flash-preview")
    p.add_argument("--effort", default="minimal")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--num-workers", type=int, default=8)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="stage", required=True)

    s1 = sub.add_parser("stage1",
                        help="Extract support/oppose side definitions per cohort.")
    _add_common_args(s1)
    s1.add_argument("--cohort", action="append", required=True,
                    help="Cohort slug to process; pass repeatedly.")
    s1.add_argument("--output", required=True,
                    help="JSON file to write {cohort: sides_record}.")

    s2 = sub.add_parser("stage2",
                        help="Label each essay against pre-extracted sides.")
    _add_common_args(s2)
    s2.add_argument("--sides", required=True,
                    help="Path to the stage1 output JSON.")
    s2.add_argument("--cohort", action="append",
                    help="Restrict to these cohorts (default: all from --sides).")
    s2.add_argument("--output", required=True,
                    help="JSON file to write [label_record, ...].")
    s2.add_argument("--max-body-chars", type=int, default=6000,
                    help="Truncate each essay to at most this many characters "
                         "before prompting (default 6000).")
    s2.add_argument("--dry-run", action="store_true",
                    help="List essays to label and exit without calling LLM.")

    args = p.parse_args(argv)
    if args.data_root:
        set_data_root(args.data_root)
    progress(f"data_root={get_data_root()}")

    if args.stage == "stage1":
        return run_stage1(args)
    if args.stage == "stage2":
        return run_stage2(args)
    progress(f"unknown stage: {args.stage}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

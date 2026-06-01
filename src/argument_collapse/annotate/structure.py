#!/usr/bin/env python3
"""Paragraph-level structure annotation for argumentative essays.

For each selected essay, call an LLM with one of the released structure
prompts and write a per-essay JSON file under the cohort's analysis directory:

  <data_root>/<venue>/<cohort>/analysis/argument/<stem>.json
  <data_root>/<venue>/<cohort>/analysis/discourse_mode/<stem>.json

The public data release aggregates those files into
``structure_argument.jsonl.gz`` and ``structure_discourse_mode.jsonl.gz``.
This script keeps the working-layout outputs resume-safe: an essay/layer is
skipped when its JSON file already exists unless ``--force`` is passed.

Run with ``python -m argument_collapse.annotate.structure``.
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
    parse_frontmatter_and_body,
    set_data_root,
)
from argument_collapse.inference import (
    InferenceError,
    InferenceRequest,
    get_provider,
    provider_choices,
)

LAYER_ARGUMENT = "argument"
LAYER_DISCOURSE = "discourse_mode"
PROMPT_VERSION = {
    LAYER_ARGUMENT: "structure_argument",
    LAYER_DISCOURSE: "structure_discourse_mode",
}
PROMPT_FILE = {
    LAYER_ARGUMENT: Path("prompts/structure/argument.md"),
    LAYER_DISCOURSE: Path("prompts/structure/discourse_mode.md"),
}

KIND_ALIASES = {
    "vanilla": "v1a",
    "default": "v1a",
    "diversified": "v15a",
    "position-guided": "v4a",
    "position": "v4a",
}
SRC_TO_PUBLIC_KIND = {
    "v1a": "vanilla",
    "v15a": "diversified",
    "v4a": "position-guided",
}

_MODEL_FROM_FAMILY = (
    ("gpt", "gpt"),
    ("gemini", "gemini"),
    ("claude", "claude"),
    ("minimax", "minimax"),
    ("deepseek", "deepseek"),
    ("kimi", "kimi"),
)

_PROGRESS_LOCK = threading.Lock()


def progress(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    with _PROGRESS_LOCK:
        print(f"[{stamp}] {message}", flush=True)


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


def normalize_annotation(payload: dict[str, Any], layer: str, n_paragraphs: int) -> list[dict[str, Any]]:
    anns = payload.get("annotations")
    if not isinstance(anns, list):
        raise ValueError("annotations must be a list")
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in anns:
        if not isinstance(item, dict):
            raise ValueError("each annotation must be an object")
        idx = int(item.get("paragraph_index"))
        if idx < 0 or idx >= n_paragraphs:
            raise ValueError(f"paragraph_index {idx} out of range 0..{n_paragraphs - 1}")
        if idx in seen:
            raise ValueError(f"duplicate paragraph_index {idx}")
        seen.add(idx)
        rationale = str(item.get("rationale", "")).strip()
        if layer == LAYER_ARGUMENT:
            labels = item.get("labels")
            if isinstance(labels, str):
                labels = [labels]
            if not isinstance(labels, list) or not labels:
                raise ValueError(f"missing labels for paragraph {idx}")
            labels = [str(x).strip() for x in labels if str(x).strip()]
            out.append({"paragraph_index": idx, "labels": labels, "rationale": rationale})
        else:
            label = str(item.get("label", "")).strip()
            if not label:
                raise ValueError(f"missing label for paragraph {idx}")
            out.append({"paragraph_index": idx, "label": label, "rationale": rationale})
    if len(out) != n_paragraphs:
        missing = sorted(set(range(n_paragraphs)) - seen)
        raise ValueError(f"missing paragraph annotations: {missing[:10]}")
    return sorted(out, key=lambda x: x["paragraph_index"])


def split_paragraphs(body: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n+", body.strip()) if p.strip()]


def paragraph_user_prompt(paragraphs: list[str]) -> str:
    blocks = [f"[{i}]\n{p}" for i, p in enumerate(paragraphs)]
    return "Essay paragraphs:\n\n" + "\n\n".join(blocks)


def _model_from_family(family: str) -> str | None:
    family = family.lower()
    for token, name in _MODEL_FROM_FAMILY:
        if token in family:
            return name
    return None


def parse_generated_stem(stem: str) -> dict[str, str | None] | None:
    parts = stem.split("__")
    if len(parts) < 5:
        return None
    _api, family, _effort, src_kind = parts[:4]
    position_source_id = parts[4] if len(parts) >= 6 else None
    return {
        "src_kind": src_kind,
        "kind": SRC_TO_PUBLIC_KIND.get(src_kind, src_kind),
        "model": _model_from_family(family),
        "position_source_id": position_source_id,
    }


def normalize_kind_set(kinds: set[str]) -> set[str]:
    out: set[str] = set()
    for kind in kinds:
        out.add(kind)
        if kind in KIND_ALIASES:
            out.add(KIND_ALIASES[kind])
    return out


def discover_essays(venue: str, kinds: set[str], data_root: Path | str | None = None) -> list[dict]:
    root = Path(data_root) if data_root is not None else get_data_root()
    venue_root = root / venue
    wanted = normalize_kind_set(kinds)
    if not venue_root.is_dir():
        return []
    out: list[dict] = []
    for cohort_dir in sorted(venue_root.iterdir()):
        if not cohort_dir.is_dir():
            continue
        cohort = cohort_dir.name
        if "human" in wanted:
            for path in find_human_responses(cohort_dir):
                out.append({
                    "cohort": cohort,
                    "stem": path.stem,
                    "kind": "human",
                    "src_kind": "human",
                    "model": None,
                    "position_source_id": None,
                    "path": str(path),
                })
        gen_dir = cohort_dir / "generated"
        if not gen_dir.is_dir():
            continue
        for path in sorted(gen_dir.glob("*.md")):
            parsed = parse_generated_stem(path.stem)
            if parsed is None:
                continue
            if parsed["kind"] not in wanted and parsed["src_kind"] not in wanted:
                continue
            out.append({
                "cohort": cohort,
                "stem": path.stem,
                "kind": parsed["kind"],
                "src_kind": parsed["src_kind"],
                "model": parsed["model"],
                "position_source_id": parsed["position_source_id"],
                "path": str(path),
            })
    return out


def output_path(venue: str, cohort: str, stem: str, layer: str,
                data_root: Path | str | None = None) -> Path:
    # Ask data.py for the cohort analysis root, then place structure outputs
    # in the existing per-layer subdirectory convention.
    marker = cohort_analysis_path(venue, cohort, ".structure_marker", data_root=data_root)
    return marker.parent / layer / f"{stem}.json"


def load_system_prompt(layer: str, prompt_path: Path | None = None) -> str:
    if prompt_path is not None:
        return prompt_path.read_text()
    path = PROMPT_FILE[layer]
    if not path.exists():
        repo_root = Path(__file__).resolve().parents[3]
        path = repo_root / PROMPT_FILE[layer]
    if not path.exists():
        raise FileNotFoundError(f"missing structure prompt file for {layer}: {PROMPT_FILE[layer]}")
    return path.read_text()


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


def call_annotator(args: argparse.Namespace, layer: str, paragraphs: list[str], system_prompt: str) -> list[dict[str, Any]]:
    usr_p = paragraph_user_prompt(paragraphs)
    request = InferenceRequest(
        provider=args.provider,
        model=args.model,
        system_prompt=system_prompt,
        user_prompt=usr_p,
        combined_prompt=system_prompt + "\n\n" + usr_p,
        condition=PROMPT_VERSION[layer],
        effort=args.effort or "",
        request_params=request_params(args),
    )
    result = get_provider(args.provider).generate(request)
    payload = extract_json(result.text)
    return normalize_annotation(payload, layer, len(paragraphs))


def annotate_one(args: argparse.Namespace, essay: dict, layer: str, system_prompt: str,
                 data_root: Path | str | None = None) -> tuple[bool, str]:
    path = Path(essay["path"])
    try:
        _fm, body = parse_frontmatter_and_body(path)
    except Exception as exc:
        return False, f"{essay['cohort']} {essay['stem'][:32]} {layer}: parse failure: {exc}"
    paragraphs = split_paragraphs(body)
    if not paragraphs:
        return False, f"{essay['cohort']} {essay['stem'][:32]} {layer}: no paragraphs"
    try:
        anns = call_annotator(args, layer, paragraphs, system_prompt)
    except (InferenceError, ValueError, json.JSONDecodeError) as exc:
        return False, f"{essay['cohort']} {essay['stem'][:32]} {layer}: {exc}"
    row = {
        "cohort": essay["cohort"],
        "stem": essay["stem"],
        "kind": essay.get("kind"),
        "model": essay.get("model"),
        "layer": layer,
        "annotations": anns,
        "annotated_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "judge_provider": args.provider,
        "judge_model": args.model,
        "judge_effort": args.effort or "",
        "prompt_version": PROMPT_VERSION[layer],
    }
    out = output_path(args.venue, essay["cohort"], essay["stem"], layer, data_root=data_root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n")
    return True, f"{essay['cohort']} {essay['stem'][:32]} {layer} -> {len(anns)} paragraphs"


def plan_items(essays: list[dict], layers: list[str], cohort_filter: set[str] | None,
               force: bool, venue: str, data_root: Path | str | None = None) -> tuple[list[tuple[dict, str]], dict[str, int]]:
    plan: list[tuple[dict, str]] = []
    stats = {"essays_considered": 0, "filtered_by_cohort": 0, "skipped_existing": 0, "to_run": 0}
    for essay in essays:
        stats["essays_considered"] += 1
        if cohort_filter and essay["cohort"] not in cohort_filter:
            stats["filtered_by_cohort"] += 1
            continue
        for layer in layers:
            if not force and output_path(venue, essay["cohort"], essay["stem"], layer, data_root=data_root).exists():
                stats["skipped_existing"] += 1
                continue
            plan.append((essay, layer))
            stats["to_run"] += 1
    return plan, stats


def parse_layers(value: str) -> list[str]:
    v = value.strip().lower().replace("-", "_")
    if v == "both":
        return [LAYER_ARGUMENT, LAYER_DISCOURSE]
    if v in {LAYER_ARGUMENT, "argumentative_role", "role"}:
        return [LAYER_ARGUMENT]
    if v in {LAYER_DISCOURSE, "discourse", "discourse_mode"}:
        return [LAYER_DISCOURSE]
    raise argparse.ArgumentTypeError("layer must be argument, discourse-mode, or both")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-root", default=None,
                   help="Dataset root directory; defaults to $ARGUMENT_COLLAPSE_DATA_ROOT if set, otherwise ./data.")
    p.add_argument("--venue", required=True,
                   help="Venue subdirectory inside the data root.")
    p.add_argument("--cohort", action="append",
                   help="Restrict to this cohort; pass repeatedly to add more.")
    p.add_argument("--kinds", default="human,vanilla,diversified,position-guided",
                   help="Comma-separated essay kinds to include (default: human,vanilla,diversified,position-guided).")
    p.add_argument("--layer", type=parse_layers, default=[LAYER_ARGUMENT, LAYER_DISCOURSE],
                   help="Structure layer to annotate: argument, discourse-mode, or both (default: both).")
    p.add_argument("--argument-prompt", type=Path,
                   help="Override prompt file for the argumentative-role layer.")
    p.add_argument("--discourse-prompt", type=Path,
                   help="Override prompt file for the discourse-mode layer.")
    p.add_argument("--provider", choices=provider_choices(), default="vertex")
    p.add_argument("--model", default="gemini-3-flash-preview")
    p.add_argument("--effort", default="minimal")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--max-output-tokens", type=int, default=2000)
    p.add_argument("--num-workers", type=int, default=20)
    p.add_argument("--limit-essays", type=int)
    p.add_argument("--force", action="store_true",
                   help="Re-annotate even when the per-essay structure JSON already exists.")
    p.add_argument("--dry-run", action="store_true",
                   help="Plan the run and print stats without calling the annotator.")
    args = p.parse_args(argv)

    if args.data_root:
        set_data_root(args.data_root)

    kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
    layers: list[str] = args.layer
    cohort_filter = set(args.cohort) if args.cohort else None

    progress(f"data_root={get_data_root()}")
    progress(f"discovering essays in {args.venue}/ (kinds={sorted(kinds)}, layers={layers}) ...")
    essays = discover_essays(args.venue, kinds, data_root=args.data_root)
    progress(f"  {len(essays)} essays on disk matching selected kinds")

    plan, stats = plan_items(essays, layers, cohort_filter, args.force, args.venue, data_root=args.data_root)
    progress(f"plan: {stats}")
    if args.limit_essays:
        plan = plan[: args.limit_essays]
        progress(f"capped plan to {len(plan)} essay/layer tasks (--limit-essays)")
    if args.dry_run or not plan:
        progress("done (no annotator calls made)")
        return 0

    system_prompts = {
        LAYER_ARGUMENT: load_system_prompt(LAYER_ARGUMENT, args.argument_prompt),
        LAYER_DISCOURSE: load_system_prompt(LAYER_DISCOURSE, args.discourse_prompt),
    }
    progress(f"calling structure annotator ({args.provider}/{args.model}/{args.effort or 'default'}) "
             f"on {len(plan)} essay/layer tasks with {args.num_workers} workers")

    total = len(plan)
    done = 0
    failures = 0

    def task(item: tuple[dict, str]) -> tuple[bool, str]:
        essay, layer = item
        return annotate_one(args, essay, layer, system_prompts[layer], data_root=args.data_root)

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
                ok, msg = False, f"unexpected failure: {exc}"
            done += 1
            if not ok:
                failures += 1
            if done % 50 == 0 or not ok:
                progress(f"[{done}/{total}] {'OK' if ok else 'FAIL'} {msg}")

    progress(f"complete: {done - failures}/{total} ok, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

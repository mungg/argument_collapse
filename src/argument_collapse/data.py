"""Cohort and essay loaders.

Two on-disk layouts are supported and auto-detected.

**Public-release layout (split)**::

    {DATA_ROOT}/
        cohorts.jsonl                              # cohort index (one row each)
        essays/{venue}/{cohort}/
            00_question.md   or   00_lead.md       # shared context (one or the other)
            humans/{author}.md                     # per-human response essays
            generated/{llm-essay}.md               # LLM-generated response essays
        annotations/
            toulmin.jsonl                          # flat across venues + cohorts
            main_argument_pairs.jsonl
            sub_argument_pairs.jsonl
            stance.jsonl                           # binary cohorts only

**Working / legacy layout (cohort_grouped)**::

    {DATA_ROOT}/{venue}/{cohort_id}/
        human/00_question.md   or   human/00_lead.md
        human/{author}.md
        generated/{llm-essay}.md
        analysis/toulmin.jsonl
        analysis/main_argument_pairs.jsonl
        analysis/sub_argument_pairs.jsonl
        personas.json                              # persona definitions, optional
        question_type.json                         # binary/open, optional

The two layouts carry the same content; the split layout is the form
shipped in the public dataset release (Hugging-Face-friendly flat
annotations, browsable per-cohort essays, dedicated cohort index), and
the cohort_grouped layout is the working state produced by the
annotation pipeline. Existing tooling that wrote per-cohort
``analysis/<file>.jsonl`` continues to work; new tooling pointed at the
split release reads through the same public API and sees identical rows.

``DATA_ROOT`` defaults to ``$ARGUMENT_COLLAPSE_DATA_ROOT`` if that
environment variable is set, otherwise ``./data/dataset``. Override
programmatically with :func:`set_data_root` or per call by passing
``data_root`` to the loader.

The Markdown convention is two ``---`` lines wrapping a YAML-ish header
followed by an empty line and the body. Front-matter is parsed as plain
``key: value`` pairs (no nested types). The ``role`` field is used to filter
human response essays from prompts and meta files.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator


# ---------------------------------------------------------------------------
# Schema constants. These name the on-disk layout used throughout the project
# and are exported as module-level constants rather than inlined string
# literals so callers can refer to them when extending the pipeline.
# ---------------------------------------------------------------------------

DEFAULT_DATA_ROOT = Path(
    os.environ.get(
        "ARGUMENT_COLLAPSE_DATA_ROOT",
        str(Path.cwd() / "data" / "dataset"),
    )
)

# Subdirectory names. The first three apply to the cohort_grouped layout;
# ESSAYS_DIRNAME, ANNOTATIONS_DIRNAME, and HUMANS_DIRNAME apply to the split
# layout. HUMAN_DIRNAME is kept as the legacy singular form ("human") so
# pre-existing pipelines do not have to rename anything.
HUMAN_DIRNAME = "human"
HUMANS_DIRNAME = "humans"
GENERATED_DIRNAME = "generated"
ANALYSIS_DIRNAME = "analysis"
ESSAYS_DIRNAME = "essays"
ANNOTATIONS_DIRNAME = "annotations"

# Per-cohort markdown filenames.
QUESTION_FILENAME = "00_question.md"
LEAD_FILENAME = "00_lead.md"

# Per-cohort metadata files (cohort_grouped layout) and dataset-level index
# (split layout).
PERSONAS_FILENAME = "personas.json"
QUESTION_TYPE_FILENAME = "question_type.json"
GENERATION_LOG_FILENAME = "generation_log.jsonl"
COHORTS_INDEX_FILENAME = "cohorts.jsonl"

# Front-matter ``role`` values that mark non-response files. Anything else
# in ``human/`` (or ``humans/``) is treated as a human response.
NON_RESPONSE_ROLES = frozenset(
    {"lead", "question", "authors_final_response", "llm_response"}
)


# Mutable module-level state so set_data_root() can override without callers
# having to thread data_root through every helper.
_DATA_ROOT = DEFAULT_DATA_ROOT


def set_data_root(path: Path | str) -> None:
    """Override the default data root used by helpers that do not take an
    explicit ``data_root`` argument. The override persists for the lifetime
    of the Python process.
    """
    global _DATA_ROOT
    _DATA_ROOT = Path(path)


def get_data_root() -> Path:
    """Return the data root currently in effect."""
    return _DATA_ROOT


def _resolve_root(data_root: Path | str | None) -> Path:
    return Path(data_root) if data_root is not None else _DATA_ROOT


# ---------------------------------------------------------------------------
# Layout detection
# ---------------------------------------------------------------------------

LAYOUT_SPLIT = "split"
LAYOUT_COHORT_GROUPED = "cohort_grouped"


def detect_layout(data_root: Path | str | None = None) -> str:
    """Return ``"split"`` if the data root looks like the public release
    layout (``essays/`` + ``annotations/`` subdirs), otherwise
    ``"cohort_grouped"``.

    The split layout is preferred when both ``essays/`` and ``annotations/``
    exist; partial layouts (only one of the two) fall through to
    ``cohort_grouped`` so that an in-progress migration does not silently
    point the reader at empty inputs.
    """
    root = _resolve_root(data_root)
    if (root / ESSAYS_DIRNAME).is_dir() and (root / ANNOTATIONS_DIRNAME).is_dir():
        return LAYOUT_SPLIT
    return LAYOUT_COHORT_GROUPED


# ---------------------------------------------------------------------------
# Markdown front-matter
# ---------------------------------------------------------------------------

def parse_frontmatter_and_body(path: Path) -> tuple[dict[str, str], str]:
    """Read a Markdown file with optional ``---`` YAML front-matter.

    Returns ``({}, full_text)`` when the file has no front-matter, otherwise
    a flat dict of ``key -> value`` strings (no nested types) and the body
    portion (everything after the closing ``---``).
    """
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip()

    frontmatter: dict[str, str] = {}
    end_idx = 0
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = idx
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip()
    if not end_idx:
        return {}, text.strip()
    return frontmatter, "\n".join(lines[end_idx + 1:]).strip()


def parse_frontmatter(path: Path) -> dict[str, str]:
    """Convenience wrapper around :func:`parse_frontmatter_and_body` that
    discards the body. Returns ``{}`` if the file does not exist."""
    if not path.exists():
        return {}
    return parse_frontmatter_and_body(path)[0]


def write_markdown_with_frontmatter(
    path: Path,
    frontmatter: dict[str, Any],
    body: str,
) -> None:
    """Write a Markdown file with a flat YAML-ish front-matter block."""
    lines = ["---"]
    for key, value in frontmatter.items():
        if value is None:
            continue
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = str(value)
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    lines.extend(["---", "", body.strip(), ""])
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Cohort objects and discovery
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Cohort:
    """Lightweight handle to a single cohort on disk.

    ``prompt_kind`` is one of ``"question"`` (NYT-style debate question) or
    ``"lead"`` (BR-style lead essay) and selects which Markdown file in the
    cohort's humans directory the LLM judges should consume as shared
    context. ``humans_dir`` resolves to whichever of ``human/`` (cohort-
    grouped) or ``humans/`` (split) the cohort uses; the legacy
    :attr:`human_dir` alias is preserved for back-compat.
    """

    venue: str
    cohort_id: str
    cohort_dir: Path
    prompt_path: Path
    prompt_kind: str
    layout: str = LAYOUT_COHORT_GROUPED

    @property
    def humans_dir(self) -> Path:
        if self.layout == LAYOUT_SPLIT:
            return self.cohort_dir / HUMANS_DIRNAME
        return self.cohort_dir / HUMAN_DIRNAME

    # Alias retained so callers written against the cohort_grouped layout
    # keep working.
    @property
    def human_dir(self) -> Path:
        return self.humans_dir

    @property
    def generated_dir(self) -> Path:
        return self.cohort_dir / GENERATED_DIRNAME

    @property
    def analysis_dir(self) -> Path:
        """Per-cohort analysis directory.

        Only meaningful under the cohort_grouped layout — annotation rows
        in the split layout live in flat files under
        ``<data_root>/annotations/``. The property still returns a path so
        existing code that builds analysis sub-paths does not crash; check
        :attr:`layout` before relying on the contents.
        """
        return self.cohort_dir / ANALYSIS_DIRNAME

    @property
    def generation_log_path(self) -> Path:
        return self.cohort_dir / GENERATION_LOG_FILENAME

    @property
    def prompt_file_relative(self) -> str:
        return str(self.prompt_path.relative_to(self.cohort_dir))


def essays_root(data_root: Path | str | None = None) -> Path:
    """Resolve the directory under which per-venue essay trees live.

    Split layout: ``<data_root>/essays/``.
    Cohort_grouped layout: ``<data_root>/`` itself.
    """
    root = _resolve_root(data_root)
    if detect_layout(root) == LAYOUT_SPLIT:
        return root / ESSAYS_DIRNAME
    return root


def annotations_root(data_root: Path | str | None = None) -> Path:
    """Directory holding flat ``<file>.jsonl`` files in the split layout.

    Under cohort_grouped the concept does not apply; the function returns
    ``<data_root>/<ANNOTATIONS_DIRNAME>`` anyway so callers that want to
    write a release artefact have a canonical target, but readers should
    branch on :func:`detect_layout` first.
    """
    return _resolve_root(data_root) / ANNOTATIONS_DIRNAME


def venue_dir(venue: str, data_root: Path | str | None = None) -> Path:
    """Path of a single venue's essay tree.

    Split layout: ``<data_root>/essays/<venue>``.
    Cohort_grouped layout: ``<data_root>/<venue>``.
    """
    return essays_root(data_root) / venue


# ---------------------------------------------------------------------------
# Cohort index (split layout)
# ---------------------------------------------------------------------------

def cohorts_index_path(data_root: Path | str | None = None) -> Path:
    """``<data_root>/cohorts.jsonl`` (whether or not it exists)."""
    return _resolve_root(data_root) / COHORTS_INDEX_FILENAME


def load_cohorts_index(
    data_root: Path | str | None = None,
) -> dict[str, dict[str, Any]]:
    """Load ``cohorts.jsonl`` into a ``{cohort_id: row}`` map.

    Expected row schema (extra fields are preserved verbatim)::

        {"cohort": str, "venue": str, "context_kind": "question" | "lead",
         "title": str, "question_type": str | null,
         "n_humans": int, "n_personas": int,
         "in_paper_subset": bool}

    Returns ``{}`` when the index file is absent (cohort_grouped layouts
    derive the same information from per-cohort ``question_type.json`` and
    ``personas.json`` instead).
    """
    path = cohorts_index_path(data_root)
    if not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        cohort_id = row.get("cohort") or row.get("cohort_id")
        if cohort_id:
            out[cohort_id] = row
    return out


# ---------------------------------------------------------------------------
# Annotation file path resolution (used by both readers and writers)
# ---------------------------------------------------------------------------

def annotations_path(
    filename: str,
    data_root: Path | str | None = None,
) -> Path:
    """``<data_root>/annotations/<filename>`` — the flat annotation file
    used in the split layout. Independent of venue / cohort."""
    return annotations_root(data_root) / filename


def cohort_analysis_path(
    venue: str,
    cohort: str,
    filename: str,
    data_root: Path | str | None = None,
) -> Path:
    """Canonical write target for a per-cohort annotation row.

    Split layout: ``<data_root>/annotations/<filename>`` (shared file;
    rows from every cohort interleave). The append-side helper in
    annotation scripts holds a process-global lock when writing here.

    Cohort_grouped layout: ``<data_root>/<venue>/<cohort>/analysis/<filename>``
    (the legacy per-cohort file). This is preserved bit-for-bit so the
    existing annotation pipeline continues to resume from old state.
    """
    if detect_layout(data_root) == LAYOUT_SPLIT:
        return annotations_path(filename, data_root)
    return venue_dir(venue, data_root) / cohort / ANALYSIS_DIRNAME / filename


# Process-global lock used when annotation scripts append to a flat
# annotations file under the split layout. Each annotation script already
# holds a per-cohort lock; this extra lock serialises the actual filesystem
# write so two cohorts' rows never interleave mid-line.
_FLAT_APPEND_LOCK = threading.Lock()


def flat_append_lock() -> threading.Lock:
    """Module-level lock that annotation scripts should acquire when
    appending to ``<data_root>/annotations/<filename>`` in the split
    layout. A no-op under cohort_grouped writes (the per-cohort file
    pattern needs only the per-cohort lock that the scripts already
    hold)."""
    return _FLAT_APPEND_LOCK


# ---------------------------------------------------------------------------
# JSONL readers
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def iter_cohort_jsonl(
    venue: str,
    filename: str,
    data_root: Path | str | None = None,
) -> Iterator[tuple[str, list[dict]]]:
    """Yield ``(cohort_id, rows)`` for every cohort that has data for
    ``filename`` under the requested venue.

    Split layout: read the flat ``<data_root>/annotations/<filename>``,
    keep only rows whose ``venue`` field matches (or rows that omit a
    venue field, for back-compat), then group by ``cohort``. Cohorts are
    yielded in lexicographic order; within each group the rows preserve
    their relative order in the source file.

    Cohort_grouped layout: walk ``<data_root>/<venue>/*/analysis/<filename>``
    in lexicographic order and yield one ``(cohort, rows)`` per file.
    """
    if detect_layout(data_root) == LAYOUT_SPLIT:
        path = annotations_path(filename, data_root)
        if not path.exists():
            return
        grouped: dict[str, list[dict]] = {}
        for row in _read_jsonl(path):
            row_venue = row.get("venue")
            if row_venue is not None and row_venue != venue:
                continue
            cohort = row.get("cohort")
            if not cohort:
                continue
            grouped.setdefault(cohort, []).append(row)
        for cohort in sorted(grouped):
            yield cohort, grouped[cohort]
        return

    root = venue_dir(venue, data_root)
    for analysis_dir in sorted(root.glob(f"*/{ANALYSIS_DIRNAME}")):
        path = analysis_dir / filename
        if not path.exists():
            continue
        yield analysis_dir.parent.name, _read_jsonl(path)


def read_cohort_jsonl(
    venue: str,
    filename: str,
    data_root: Path | str | None = None,
) -> list[dict]:
    """Concatenate every cohort's rows for ``filename`` (across both
    layouts) into a single flat list. Convenience wrapper around
    :func:`iter_cohort_jsonl`."""
    out: list[dict] = []
    for _, rows in iter_cohort_jsonl(venue, filename, data_root=data_root):
        out.extend(rows)
    return out


# ---------------------------------------------------------------------------
# Internal helpers used by cohort discovery
# ---------------------------------------------------------------------------

def _cohort_id(
    venue: str, cohort_dir: Path, data_root: Path | str | None = None,
) -> str:
    return cohort_dir.relative_to(venue_dir(venue, data_root)).as_posix()


def _humans_dirs(
    venue: str, data_root: Path | str | None = None,
) -> list[Path]:
    """Return every cohort's humans-essay directory under a venue.

    Looks for the split-layout ``humans/`` first, then falls back to the
    cohort_grouped ``human/`` directory.
    """
    root = venue_dir(venue, data_root)
    if not root.exists():
        return []
    by_parent: dict[Path, Path] = {}
    for dirname in (HUMANS_DIRNAME, HUMAN_DIRNAME):
        for path in root.glob(f"**/{dirname}"):
            if not path.is_dir():
                continue
            by_parent.setdefault(path.parent, path)
    return sorted(by_parent.values())


def _prompt_from_humans_dir(
    humans_dir: Path,
    prompt_kind: str,
    prompt_file: str | None = None,
) -> Path | None:
    """Locate the prompt file inside ``humans_dir`` for a given ``prompt_kind``.

    - ``"question"`` looks for :data:`QUESTION_FILENAME` (``00_question.md``).
    - ``"lead"`` looks first for :data:`LEAD_FILENAME` (``00_lead.md``), then
      for any ``00_lead_*.md`` (alphabetical), then any ``*.md`` whose
      front-matter has ``role: lead``.
    - An explicit ``prompt_file`` overrides the convention.

    The prompt file may live one directory up in the split layout (where
    ``00_question.md`` sits next to ``humans/`` rather than inside it).

    Returns ``None`` if nothing matches so the caller can skip the cohort.
    """
    search_dirs = [humans_dir, humans_dir.parent]

    if prompt_file:
        for d in search_dirs:
            candidate = d / prompt_file
            if candidate.exists():
                return candidate
        return None
    if prompt_kind == "question":
        for d in search_dirs:
            candidate = d / QUESTION_FILENAME
            if candidate.exists():
                return candidate
        return None
    if prompt_kind != "lead":
        raise ValueError(f"unknown prompt_kind: {prompt_kind!r}")

    for d in search_dirs:
        exact = d / LEAD_FILENAME
        if exact.exists():
            return exact
    for d in search_dirs:
        lead_named = sorted(d.glob("00_lead_*.md"))
        if lead_named:
            return lead_named[0]
    for d in search_dirs:
        for path in sorted(d.glob("*.md")):
            if parse_frontmatter(path).get("role", "").strip().lower() == "lead":
                return path
    return None


# Back-compat alias.
def _prompt_from_human_dir(
    human_dir: Path,
    prompt_kind: str,
    prompt_file: str | None = None,
) -> Path | None:
    return _prompt_from_humans_dir(human_dir, prompt_kind, prompt_file)


# ---------------------------------------------------------------------------
# Public discovery API
# ---------------------------------------------------------------------------

def discover_cohorts(
    venue: str,
    prompt_kind: str,
    *,
    prompt_file: str | None = None,
    cohort_ids: Iterable[str] | None = None,
    data_root: Path | str | None = None,
) -> list[Cohort]:
    """Scan ``venue_dir(venue)`` for every cohort that has the requested
    prompt file. ``cohort_ids`` filters the result to a specific set; pass
    ``None`` (default) to return every cohort that qualifies. Works under
    both layouts."""
    wanted = set(cohort_ids or [])
    layout = detect_layout(data_root)
    cohorts: list[Cohort] = []
    for humans_dir in _humans_dirs(venue, data_root):
        cohort_dir = humans_dir.parent
        cohort_id = _cohort_id(venue, cohort_dir, data_root)
        if wanted and cohort_id not in wanted:
            continue
        prompt_path = _prompt_from_humans_dir(humans_dir, prompt_kind, prompt_file)
        if prompt_path is None:
            continue
        cohorts.append(
            Cohort(
                venue=venue,
                cohort_id=cohort_id,
                cohort_dir=cohort_dir,
                prompt_path=prompt_path,
                prompt_kind=prompt_kind,
                layout=layout,
            )
        )
    return cohorts


def find_prompt_source(
    venue: str,
    cohort_id: str,
    prompt_kind: str,
    *,
    prompt_file: str | None = None,
    data_root: Path | str | None = None,
) -> Path:
    """Return the resolved prompt path for ``cohort_id`` or raise
    ``FileNotFoundError`` if it cannot be found. Works under both layouts."""
    cohort_dir = venue_dir(venue, data_root) / cohort_id
    humans_dir = (cohort_dir / HUMANS_DIRNAME if (cohort_dir / HUMANS_DIRNAME).is_dir()
                  else cohort_dir / HUMAN_DIRNAME)
    prompt_path = _prompt_from_humans_dir(humans_dir, prompt_kind, prompt_file)
    if prompt_path is None:
        label = prompt_file or (
            QUESTION_FILENAME if prompt_kind == "question" else "lead markdown"
        )
        raise FileNotFoundError(f"missing {label} for {venue}/{cohort_id}")
    return prompt_path


def find_human_responses(cohort: Cohort | Path) -> list[Path]:
    """List the per-human response markdown files inside the cohort's
    humans directory.

    Files are excluded when their front-matter ``role`` is in
    :data:`NON_RESPONSE_ROLES` or when the filename matches a reserved
    prompt pattern (``00_lead*.md``, ``00_question.md``). Works for both
    layout conventions: when ``cohort`` is a :class:`Path` it is treated
    as the cohort directory and we look for ``humans/`` then ``human/``."""
    if isinstance(cohort, Cohort):
        humans_dir = cohort.humans_dir
    else:
        cohort_dir = cohort
        humans_dir = cohort_dir / HUMANS_DIRNAME
        if not humans_dir.is_dir():
            humans_dir = cohort_dir / HUMAN_DIRNAME
    responses: list[Path] = []
    for path in sorted(humans_dir.glob("*.md")):
        meta = parse_frontmatter(path)
        role = meta.get("role", "").strip().lower()
        if role in NON_RESPONSE_ROLES:
            continue
        if path.name.startswith("00_lead") or path.name == QUESTION_FILENAME:
            continue
        responses.append(path)
    return responses


def find_personas(cohort: Cohort | Path) -> dict[str, Any]:
    """Load the ``personas.json`` for a cohort. Returns ``{}`` if the file
    does not exist. Looks for it next to the humans directory and inside
    it (cohort_grouped versus split conventions). The expected shape is
    ``{"personas": {<name>: <spec>}}``; only the ``personas`` mapping is
    returned."""
    if isinstance(cohort, Cohort):
        cohort_dir = cohort.cohort_dir
        humans_dir = cohort.humans_dir
    else:
        cohort_dir = cohort
        humans_dir = (cohort_dir / HUMANS_DIRNAME if (cohort_dir / HUMANS_DIRNAME).is_dir()
                      else cohort_dir / HUMAN_DIRNAME)
    for candidate in (cohort_dir / PERSONAS_FILENAME,
                      humans_dir / PERSONAS_FILENAME):
        if candidate.exists():
            blob = json.loads(candidate.read_text())
            return blob.get("personas", blob)
    return {}


def cohort_from_id(
    venue: str,
    cohort_id: str,
    prompt_kind: str,
    *,
    prompt_file: str | None = None,
    data_root: Path | str | None = None,
) -> Cohort:
    """Construct a :class:`Cohort` for a single ``cohort_id`` without
    scanning the venue directory. Raises ``FileNotFoundError`` if the
    required prompt file is absent."""
    prompt_path = find_prompt_source(
        venue, cohort_id, prompt_kind,
        prompt_file=prompt_file, data_root=data_root,
    )
    cohort_dir = venue_dir(venue, data_root) / cohort_id
    return Cohort(
        venue=venue,
        cohort_id=cohort_id,
        cohort_dir=cohort_dir,
        prompt_path=prompt_path,
        prompt_kind=prompt_kind,
        layout=detect_layout(data_root),
    )

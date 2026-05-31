#!/usr/bin/env python3
"""Reconstruct the human responder corpus from the published metadata.

Human responder essays are not redistributed in this release. This script
walks `data/human_essays.jsonl`, attempts to locate each essay's original
URL, fetches the page, extracts the body text, and writes one Markdown
file per essay to `human_essays_corpus/<venue>/<debate_id>/<essay_id>.md`.

URL availability
================
The release's `human_essays.jsonl` carries `source_url: null` for both
venues — the original scraper did not preserve URLs. This script applies a
best-effort venue URL template (see `URL_TEMPLATES` below) when no URL is
present, but reconstruction is not guaranteed.

If you have a verified URL list (CSV, JSONL, etc.), pass it via
`--url-overrides PATH`. The override file should contain rows of:
    {"venue": "...", "debate_id": "...", "essay_id": "...", "source_url": "..."}
Rows present here take precedence over template-based reconstruction.

Usage
=====
    python refetch_human_essays.py --data ../data --out ../human_essays_corpus
    python refetch_human_essays.py --venue nyt --limit 5      # try a small batch first
    python refetch_human_essays.py --dry-run                  # show planned URLs, no fetches

Reasonable politeness: 1 request / second per venue, configurable.

Compliance
==========
Re-fetching from a publisher's site is subject to that publisher's Terms
of Service. NYT's Terms reserve content for personal use only; downloading
in bulk for a derivative dataset is not endorsed by this script. Use is
the user's responsibility.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

try:
    import requests
except ImportError:
    requests = None

USER_AGENT = (
    "argument_collapse_refetcher/1.0 "
    "(academic research; respects publisher ToS; contact: maintainers via repo issues)"
)
REQUEST_TIMEOUT_S = 30


# Per-venue URL templates. Substitute the available fields; return None if
# we don't have enough information to construct a candidate URL.
URL_TEMPLATES = {
    # NYT Room for Debate URL pattern (legacy archive):
    # https://www.nytimes.com/roomfordebate/<YYYY/MM/DD>/<debate-slug>/<essay-slug>
    "nyt": (
        "https://www.nytimes.com/roomfordebate/"
        "{date_path}/{debate_id}/{essay_id}"
    ),
    # Boston Review forum response URL pattern (best guess):
    # https://www.bostonreview.net/forum_response/<essay-slug>/
    "br": "https://www.bostonreview.net/forum_response/{essay_id}/",
}


def date_path(iso_date: str | None) -> str | None:
    if not iso_date:
        return None
    parts = iso_date.split("-")
    if len(parts) < 3:
        return None
    return "/".join(parts[:3])


def construct_url(row: dict[str, Any]) -> str | None:
    if row.get("source_url"):
        return row["source_url"]
    tmpl = URL_TEMPLATES.get(row["venue"])
    if not tmpl:
        return None
    try:
        if row["venue"] == "nyt":
            dp = date_path(row.get("date"))
            if not dp:
                return None
            return tmpl.format(
                date_path=dp,
                debate_id=urllib.parse.quote(row["debate_id"], safe=""),
                essay_id=urllib.parse.quote(row["essay_id"], safe=""),
            )
        return tmpl.format(essay_id=urllib.parse.quote(row["essay_id"], safe=""))
    except KeyError:
        return None


def extract_body(html: str, venue: str) -> str | None:
    """Crude body extractor — replace with publisher-specific selectors as needed.

    For a real run, install `readability-lxml` or `trafilatura` and use that
    instead of regex; this is a placeholder so the script is self-contained.
    """
    import re
    # strip scripts, styles
    text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    # drop tags
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def load_jsonl(path: Path) -> Iterable[dict]:
    with path.open() as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def load_overrides(path: Path | None) -> dict[tuple[str, str, str], str]:
    if not path or not path.exists():
        return {}
    out = {}
    for r in load_jsonl(path):
        out[(r["venue"], r["debate_id"], r["essay_id"])] = r["source_url"]
    return out


def write_essay(row: dict[str, Any], body: str, out_root: Path) -> Path:
    dest = out_root / row["venue"] / row["debate_id"] / f"{row['essay_id']}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    fm_lines = [
        "---",
        f"slug: {row['essay_id']}",
    ]
    if row.get("title"): fm_lines.append(f"title: {row['title']}")
    if row.get("authors"): fm_lines.append(f"authors: {row['authors']}")
    if row.get("date"): fm_lines.append(f"date: {row['date']}")
    if row.get("word_count"): fm_lines.append(f"word_count: {row['word_count']}")
    fm_lines.append(f"venue: {row['venue']}")
    fm_lines.append(f"debate_id: {row['debate_id']}")
    fm_lines.append("---\n")
    dest.write_text("\n".join(fm_lines) + body.strip() + "\n")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--out", type=Path, default=Path("human_essays_corpus"))
    ap.add_argument("--venue", choices=["nyt", "br"], help="restrict to one venue")
    ap.add_argument("--limit", type=int, help="cap on essays attempted")
    ap.add_argument("--url-overrides", type=Path)
    ap.add_argument("--rate-limit-s", type=float, default=1.0,
                    help="min seconds between requests per venue (default 1.0)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print planned URLs without fetching")
    args = ap.parse_args()

    if not args.dry_run and requests is None:
        print("`requests` is required for fetching. Install with: pip install requests",
              file=sys.stderr)
        return 1

    index_path = args.data / "human_essays.jsonl"
    if not index_path.exists():
        print(f"missing: {index_path}", file=sys.stderr)
        return 1

    overrides = load_overrides(args.url_overrides)
    rows = list(load_jsonl(index_path))
    if args.venue:
        rows = [r for r in rows if r["venue"] == args.venue]
    if args.limit:
        rows = rows[: args.limit]
    print(f"planning to recover {len(rows)} essays", file=sys.stderr)

    last_request = {"nyt": 0.0, "br": 0.0}
    n_ok = n_no_url = n_fail = 0
    for r in rows:
        url = overrides.get((r["venue"], r["debate_id"], r["essay_id"])) or construct_url(r)
        if not url:
            n_no_url += 1
            print(f"  NO-URL  {r['venue']}/{r['debate_id']}/{r['essay_id']}", file=sys.stderr)
            continue
        if args.dry_run:
            print(f"  WOULD-FETCH  {url}", file=sys.stderr)
            n_ok += 1
            continue
        # politeness gate
        wait = args.rate_limit_s - (time.time() - last_request[r["venue"]])
        if wait > 0:
            time.sleep(wait)
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT_S,
                                headers={"User-Agent": USER_AGENT})
            last_request[r["venue"]] = time.time()
        except Exception as exc:
            n_fail += 1
            print(f"  FAIL    {url}  ({exc})", file=sys.stderr)
            continue
        if resp.status_code != 200:
            n_fail += 1
            print(f"  HTTP {resp.status_code}  {url}", file=sys.stderr)
            continue
        body = extract_body(resp.text, r["venue"])
        if not body:
            n_fail += 1
            print(f"  EMPTY   {url}", file=sys.stderr)
            continue
        path = write_essay(r, body, args.out)
        n_ok += 1
        if n_ok % 50 == 0:
            print(f"  ... {n_ok} written", file=sys.stderr)

    print(f"\ndone: ok={n_ok} no_url={n_no_url} fail={n_fail}", file=sys.stderr)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

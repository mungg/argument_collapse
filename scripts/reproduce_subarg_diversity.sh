#!/usr/bin/env bash
# Reproduce the sub-argument diversity (U_m) numbers from the paper.
#
# What this reproduces: the sub-argument within-group unique rate U_m
# on the 16 NYT cohorts that satisfy the paper's shared-main-argument
# filter (Section 4). This is the single U_m table in the paper. The
# paper's main-argument analyses (cluster counts, recovery rates,
# convergence figures) live in separate per-figure scripts and are NOT
# part of this reproduction target.
#
# Inputs (already shipped with the dataset release):
#   <data_root>/nyt/toulmin.jsonl.gz
#   <data_root>/nyt/sub_argument_pairs.jsonl.gz
#
# Output:
#   results/subarg_diversity_16cohort_nyt.json + printed summary table.
#
# Expected loose-threshold numbers (sub-argument U_m):
#   Humans                            41.0%
#   Vanilla LLMs (medoid)              9.1%
#   Diversified (1-per-family)        22.8-22.9%  (combo-sampling noise)
#   Same position, different LLMs      6.8%
#   Different positions, same LLM     18.4%
#
# Set ARGUMENT_COLLAPSE_DATA_ROOT to point at the unpacked dataset, or pass
# --data-root <path>.  Defaults to ./data.
#
# Usage:
#   ./scripts/reproduce_subarg_diversity.sh                       # default root
#   ./scripts/reproduce_subarg_diversity.sh --data-root /tmp/ac   # custom root
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SPEC="configs/subarg_diversity_16cohort_nyt.yaml"
OUTPUT="results/subarg_diversity_16cohort_nyt.json"

if [[ ! -f "$SPEC" ]]; then
  echo "error: $SPEC not found"
  exit 1
fi

mkdir -p "$(dirname "$OUTPUT")"

python - "$@" <<'PY'
import gzip, json, sys
from pathlib import Path
root = Path("data")
args = sys.argv[1:]
if "--data-root" in args:
    root = Path(args[args.index("--data-root") + 1])
pairs = root / "nyt" / "sub_argument_pairs.jsonl.gz"
if pairs.exists():
    kinds = set()
    with gzip.open(pairs, "rt") as f:
        for line in f:
            r = json.loads(line)
            kinds.add(r.get("kind_i"))
            kinds.add(r.get("kind_j"))
    if not ({"vanilla", "diversified", "position-guided"} & kinds):
        print("error: released sub_argument_pairs.jsonl.gz does not contain LLM sub-argument pair rows.")
        print("       Regenerate/export the final LLM sub-argument pair annotations before reproducing the paper U_m table.")
        sys.exit(2)
PY

echo "==> Reproducing sub-argument U_m on the 16 NYT cohorts"
echo "    spec:   $SPEC"
echo "    output: $OUTPUT"
echo

# Pass through any user-provided flags (e.g. --data-root /tmp/ac).
if command -v ac-metric >/dev/null 2>&1; then
  ac-metric um --spec "$SPEC" --output "$OUTPUT" "$@"
elif command -v uv >/dev/null 2>&1; then
  uv run ac-metric um --spec "$SPEC" --output "$OUTPUT" "$@"
else
  echo "error: ac-metric not found. Run pip install -e . first, or install uv."
  exit 1
fi

echo
echo "==> Done. Headline numbers above should match the paper's sub-arg U_m table."
echo "    Detailed per-cohort rows saved to $OUTPUT."

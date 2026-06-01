#!/usr/bin/env bash
# Reproduce the sub-argument diversity (U_m) numbers from the paper.
#
# What this reproduces: the sub-argument within-group unique rate U_m
# for the NYT subset named in configs/subarg_diversity_16cohort_nyt.yaml.
# Sub-argument annotation is a targeted subset, not a full-corpus all-pairs
# table. The metric code verifies that every selected within-group
# sub-argument pair is annotated before it computes U_m.
#
# Inputs (already shipped with the dataset release):
#   <data_root>/nyt/toulmin.jsonl.gz
#   <data_root>/nyt/sub_argument_pairs.jsonl.gz
#
# Output:
#   results/subarg_diversity_16cohort_nyt.json + printed summary table.
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
        print("error: sub_argument_pairs.jsonl.gz does not contain LLM sub-argument pair rows.")
        print("       Use a data root with the selected sub-argument annotation subset.")
        sys.exit(2)
PY

echo "==> Reproducing sub-argument U_m on the 16 NYT cohorts"
echo "    spec:   $SPEC"
echo "    output: $OUTPUT"
echo

# Pass through any user-provided flags (e.g. --data-root /tmp/ac).
if command -v uv >/dev/null 2>&1; then
  uv run ac-metric um --spec "$SPEC" --output "$OUTPUT" "$@"
else
  echo "error: uv not found. Install uv, then run: uv sync"
  exit 1
fi

echo
echo "==> Done. Detailed per-cohort rows saved to $OUTPUT."

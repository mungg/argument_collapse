#!/usr/bin/env bash
# Reproduce the sub-argument diversity (U_m) numbers from the paper for BR.
#
# What this reproduces: the sub-argument within-group unique rate U_m on
# the 16 Boston Review forums that satisfy the paper's per-group modal-
# main-argument filter (Appendix D.2). Each forum independently picks the
# largest human and the largest vanilla (default LLM) connected component
# under loose main-arg overlap, then selects up to 5 vanilla medoids (one
# per LLM family). Forums qualify when both clusters carry >=3 essays,
# yielding 60 human and 70 vanilla essays across the 16 forums. BR was
# not run with position-grounded (v4a) generations, so the persona-S1 /
# persona-S2 columns are absent in this venue.
#
# Inputs (from the dataset release):
#   <data_root>/br/toulmin.jsonl.gz
#   <data_root>/br/sub_argument_pairs.jsonl.gz
#
# Output:
#   results/subarg_diversity_16forum_br.json + printed summary table.
#
# Set ARGUMENT_COLLAPSE_DATA_ROOT to point at the unpacked dataset, or pass
# --data-root <path>.  Defaults to ./data.
#
# Usage:
#   ./scripts/reproduce_subarg_diversity_br.sh                       # default
#   ./scripts/reproduce_subarg_diversity_br.sh --data-root /tmp/ac   # custom
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SPEC="configs/subarg_diversity_16forum_br.yaml"
OUTPUT="results/subarg_diversity_16forum_br.json"

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
pairs = root / "br" / "sub_argument_pairs.jsonl.gz"
if pairs.exists():
    kinds = set()
    with gzip.open(pairs, "rt") as f:
        for line in f:
            r = json.loads(line)
            kinds.add(r.get("kind_i"))
            kinds.add(r.get("kind_j"))
    if not ({"vanilla", "diversified"} & kinds):
        print("error: released data/br/sub_argument_pairs.jsonl.gz does not contain LLM sub-argument pair rows.")
        print("       Regenerate/export the final BR LLM sub-argument pair annotations before reproducing the paper U_m table.")
        sys.exit(2)
PY

echo "==> Reproducing sub-argument U_m on the 16 BR forums"
echo "    spec:   $SPEC"
echo "    output: $OUTPUT"
echo

if command -v uv >/dev/null 2>&1; then
  uv run ac-metric um --spec "$SPEC" --output "$OUTPUT" "$@"
else
  echo "error: uv not found. Install uv, then run: uv sync"
  exit 1
fi

echo
echo "==> Done. Headline numbers above should match the paper's BR sub-arg U_m table."
echo "    Detailed per-cohort rows saved to $OUTPUT."

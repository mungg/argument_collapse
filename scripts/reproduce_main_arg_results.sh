#!/usr/bin/env bash
# Reproduce headline main-argument results from the paper.
#
# Inputs (already shipped with the dataset release):
#   <data_root>/{nyt,br}/toulmin.jsonl.gz
#   <data_root>/{nyt,br}/llm_essays.jsonl.gz
#   <data_root>/{nyt,br}/main_argument_pairs.jsonl.gz
#
# Output:
#   results/main_arg_results.json + printed summary table.
#
# Usage:
#   ./scripts/reproduce_main_arg_results.sh
#   ./scripts/reproduce_main_arg_results.sh --data-root /tmp/ac
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p results

if command -v uv >/dev/null 2>&1; then
  uv run python scripts/reproduce_main_arg_results.py --output results/main_arg_results.json "$@"
else
  echo "error: uv not found. Install uv, then run: uv sync"
  exit 1
fi

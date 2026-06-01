#!/usr/bin/env bash
# End-to-end annotation pipeline on a local working-layout essay tree.
#
# Runs the annotation passes needed for the released content and sub-argument
# diversity report: toulmin extraction, main-arg judge, sub-arg judge, and
# structure labels. Stance labeling is available via `ac-stance` but is not
# required for the U_m report. The script then prints the sub-argument diversity (U_m)
# numbers. The final metric step uses
# ``configs/subarg_diversity_16cohort_nyt.yaml`` so the report at the end
# is the same one ``./scripts/reproduce_subarg_diversity.sh`` prints.
#
# This is the expensive path — it re-runs every LLM judge from scratch
# against your own API keys (~$50 of API spend, several hours on default
# settings). Most users should just run
# ./scripts/reproduce_subarg_diversity.sh, because the dataset release
# already ships the aggregate annotation JSONL files. To rerun annotators,
# reconstruct or provide a working-layout tree with human/ and generated/
# markdown essays.
#
# Required env vars (depend on which --provider you pick):
#   OPENAI_API_KEY            for --provider openai
#   OPENROUTER_API_KEY        for --provider openrouter
#   GOOGLE_APPLICATION_CREDENTIALS  for --provider vertex / vertex-claude
#
# Set ARGUMENT_COLLAPSE_DATA_ROOT to a working-layout data root before running.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENUE="${VENUE:-NYT-Room-for-Debate-filtered}"
PROVIDER="${PROVIDER:-vertex}"
MODEL="${MODEL:-gemini-3-flash-preview}"
WORKERS="${WORKERS:-20}"

echo "==> Step 1/5: extract main+sub arguments per essay"
ac-toulmin \
  --venue "$VENUE" \
  --kinds human,vanilla,diversified,position-guided \
  --provider "$PROVIDER" --model "$MODEL" \
  --num-workers "$WORKERS"

echo "==> Step 2/5: 4-label pairwise comparison over main arguments"
ac-pair-comparison-main-arg \
  --venue "$VENUE" \
  --kinds human,vanilla \
  --provider "$PROVIDER" --model "$MODEL" \
  --num-workers "$WORKERS"

echo "==> Step 3/5: 4-label pairwise comparison over sub-arguments"
ac-pair-comparison-sub-arg \
  --venue "$VENUE" \
  --kinds human,vanilla,diversified,position-guided \
  --provider "$PROVIDER" --model "$MODEL" \
  --num-workers "$WORKERS"

echo "==> Step 4/5: paragraph-level structure annotation"
ac-structure \
  --venue "$VENUE" \
  --kinds human,vanilla,diversified,position-guided \
  --layer both \
  --provider "$PROVIDER" --model "$MODEL" \
  --num-workers "$WORKERS"

echo "==> Step 5/5: compute sub-argument diversity (U_m) on the 16-cohort spec"
mkdir -p results
ac-metric um \
  --spec configs/subarg_diversity_16cohort_nyt.yaml \
  --output results/subarg_diversity_16cohort_nyt.json

echo
echo "==> Pipeline complete. Output: results/subarg_diversity_16cohort_nyt.json"

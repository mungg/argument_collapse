# Prompts

Every system and user prompt used to build the dataset. There are three ways to look at the prompts, depending on what you need:

1. **Browse rendered examples** under `examples/`. Each example shows one fully resolved call: the exact inputs used, the literal system and user prompts the model received, and (for extraction and judging) the structured output that ended up in the data. This is the easiest entry point.
2. **Load programmatically** from `prompts.jsonl`. Each row is one `prompt_version` tag (the same value that appears in the data tables), with the full system prompt and a pointer to the user-prompt template.
3. **Read the raw text** in the `.system.*.txt` and `.user_template.txt` files for the static prompts, or in `generation.py` for the dynamically composed generation prompts.

## Files

| Path | What it is |
|---|---|
| `prompts.jsonl` | Programmatic index. One row per `prompt_version`, with the full system prompt, the user-template file path, and notes. Joins to data tables on `prompt_version`. |
| `generation.py` | Reference implementation that composes per-essay generation prompts. The helper `render_generation_prompt(...)` reproduces the exact text sent for any LLM essay in the release. |
| `toulmin_annotation.md` | Documentation plus the literal prompt for Toulmin extraction. The literal text also lives in `toulmin_annotation.system.{question,lead}.txt` plus `toulmin_annotation.user_template.txt`. |
| `main_argument_judge.md` | Documentation plus the literal prompt for the four-label pairwise judge. The literal text also lives in `main_argument_judge.system.{question,lead}.txt` plus `main_argument_judge.user_template.txt`. A `main_argument_judge.user_template.cached.txt` variant is included for the cached-context call mode (used when the shared context is supplied via an explicit Vertex content cache so it must not be repeated in the live request). |
| `structure/argument.md` | Per-paragraph argument-role taxonomy. The file is the literal prompt. |
| `structure/discourse_mode.md` | Per-paragraph discourse-mode taxonomy. The file is the literal prompt. |
| `topic_classifier.system.txt` + `topic_classifier.user_template.txt` | Preprocessing prompt that produced `debates.topic`. |
| `question_type_classifier.system.txt` | Preprocessing prompt that produced `debates.question_type` (NYT only). |
| `sensitivity_classifier.system.txt` | Preprocessing prompt that produced `debates.sensitivity` (NYT only). |
| `persona_extraction.system.txt` | Preprocessing prompt that produced the rows in `personas.jsonl.gz`. |
| `temporal_change_filter.system.{question,lead}.txt` | FreshQA-style preprocessing filter applied during corpus selection. A debate was kept only if neither of two judges (gpt-5.4-mini and gemini-3-flash-preview) labeled it `fast_changing`. The judgment is not stored as a column in the release because debates that failed the filter were dropped from the corpus. |
| `examples/generation/*.md` | One rendered example per (condition, venue) combination: `vanilla`, `diversified`, and `position-guided`, each for NYT and BR. |
| `examples/toulmin__{nyt,br}.md` | One Toulmin extraction shown end-to-end: input essay, exact prompt sent, extracted output. |
| `examples/main_argument_judge__{nyt,br}.md` | One four-label judge call shown end-to-end. |

## `prompt_version` map (matches the field in the data tables)

| `prompt_version` (in data) | File |
|---|---|
| `toulmin_annotation_v2_question_aware` | `toulmin_annotation.system.question.txt` plus `.user_template.txt` |
| `toulmin_annotation_v2_question_aware_lead` | `toulmin_annotation.system.lead.txt` plus `.user_template.txt` |
| `main_argument_judge_v8_4label` | `main_argument_judge.system.question.txt` plus `.user_template.txt` |
| `main_argument_judge_v8_4label_lead` | `main_argument_judge.system.lead.txt` plus `.user_template.txt` |
| `structure_argument` | `structure/argument.md` |
| `structure_discourse_mode` | `structure/discourse_mode.md` |
| *(generation prompts)* | Composed by `generation.py`. See `examples/generation/` for rendered samples. |
| `topic_classifier` | `topic_classifier.system.txt` plus `topic_classifier.user_template.txt`. Produced `debates.topic`. |
| `question_type_classifier` | `question_type_classifier.system.txt`. Produced `debates.question_type`. |
| `sensitivity_classifier` | `sensitivity_classifier.system.txt`. Produced `debates.sensitivity`. |
| `persona_extraction` | `persona_extraction.system.txt`. Produced the rows in `personas.jsonl.gz`. |
| `temporal_change_filter` | `temporal_change_filter.system.question.txt`. Applied to NYT during corpus selection. |
| `temporal_change_filter_lead` | `temporal_change_filter.system.lead.txt`. Applied to BR during corpus selection. |

Programmatic lookup:

```python
import pandas as pd
prompts = pd.read_json("prompts/prompts.jsonl", lines=True).set_index("prompt_version")
print(prompts.loc["toulmin_annotation_v2_question_aware", "system_prompt"])
```

## Anatomy of a generation prompt

Each generation call sends:

- A condition-specific **system prompt**. A short instruction about voice, format, and length (in `generation.py::system_prompt`).
- A composed **user prompt** containing:
  - A **source label**. The debate question (NYT) or the lead essay text (BR), with the venue framing.
  - A **condition block** that varies by condition:
    - `vanilla`: minimal. Just the source label plus a generic write-a-response instruction.
    - `diversified`: adds an explicit diversification instruction. The model is asked to produce N distinct responses in a single call, separated by `===== ESSAY N =====` markers.
    - `position-guided`: persona-faithful. Grounded on the human responder's extracted main argument (pulled from `toulmin.jsonl.gz` at generation time). Anonymized: the human's name is not shown to the model.
  - A **length clause** matching the target essay's word count.
  - An **evidence-cutoff clause** restricting world-knowledge to the debate's publication date.

To reproduce the exact prompt sent for an essay in `llm_essays.jsonl.gz`, use the helper:

```python
from prompts.generation import render_generation_prompt
# the essay's metadata (debate_id, condition, persona_id, effort, model_short) is in the row
rendered = render_generation_prompt(
    condition="v4a",                                    # source-side condition
    prompt_kind="question",                             # "question" for NYT, "lead" for BR
    prompt_path=DEBATE_DIR / "human/00_question.md",    # the debate prompt file
    source_text=debate_question_text,
    agent_source_path=Path("/tmp/_unused"),
    agent_output_path=Path("/tmp/_unused"),
    target_words=persona["word_count"],
    persona=persona,                                    # only for position-guided
)
print(rendered.system_prompt, rendered.direct_user_prompt)
```

Or just open the matching file under `examples/generation/`.

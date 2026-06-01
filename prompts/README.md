# Prompts

This folder contains the prompts used to build the dataset. There are three useful entry points:

1. **Browse examples** under `examples/`. Each file shows one complete call: inputs, prompts, and output. This is the easiest place to start.
2. **Load prompts from code** with `prompts.jsonl`. Each row matches a `prompt_version` value in the data tables.
3. **Read the raw text** in `.system.*.txt`, `.user_template.txt`, or `generation.py`.

## Files

| Path | What it is |
|---|---|
| `prompts.jsonl` | One row per `prompt_version`, with prompt text, template path, and notes. Joins to data tables on `prompt_version`. |
| `generation.py` | Helper for rebuilding the exact generation prompt for an LLM essay. |
| `toulmin_annotation.md` | Documentation plus the literal prompt for extracting main and supporting arguments. The same text also appears in `toulmin_annotation.system.{question,lead}.txt` and `toulmin_annotation.user_template.txt`. |
| `main_argument_judge.md` | Documentation plus the literal prompt for the four-label pairwise judge. The literal text also lives in `main_argument_judge.system.{question,lead}.txt` plus `main_argument_judge.user_template.txt`. A `main_argument_judge.user_template.cached.txt` variant is included for the cached-context call mode (used when the shared context is supplied via an explicit Vertex content cache so it must not be repeated in the live request). |
| `structure/argument.md` | Per-paragraph argument-role taxonomy. The file is the literal prompt. |
| `structure/discourse_mode.md` | Per-paragraph discourse-mode taxonomy. The file is the literal prompt. |
| `topic_classifier.system.txt` + `topic_classifier.user_template.txt` | Prompt that produced `debates.topic`. |
| `question_type_classifier.system.txt` | Prompt that produced `debates.question_type` (NYT only). |
| `sensitivity_classifier.system.txt` | Prompt that produced `debates.sensitivity` (NYT only). |
| `position_guide_extraction.system.txt` | Prompt that produced the rows in `position_guides.jsonl.gz`. |
| `temporal_change_filter.system.{question,lead}.txt` | Filter used when selecting debates. A debate was kept only if neither of two judges labeled it `fast_changing`. Dropped debates are not included in the release. |
| `examples/generation/*.md` | One rendered example per (condition, venue) combination: `vanilla`, `diversified`, and `position-guided`, each for NYT and BR. |
| `examples/toulmin__{nyt,br}.md` | One argument-extraction call shown end-to-end: input essay, prompt, and output. |
| `examples/main_argument_judge__{nyt,br}.md` | One four-label judge call shown end-to-end. |

## `prompt_version` Map

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
| `position_guide_extraction` | `position_guide_extraction.system.txt`. Produced the rows in `position_guides.jsonl.gz`. |
| `temporal_change_filter` | `temporal_change_filter.system.question.txt`. Applied to NYT during corpus selection. |
| `temporal_change_filter_lead` | `temporal_change_filter.system.lead.txt`. Applied to BR during corpus selection. |

Load a prompt by version:

```python
import pandas as pd
prompts = pd.read_json("prompts/prompts.jsonl", lines=True).set_index("prompt_version")
print(prompts.loc["toulmin_annotation_v2_question_aware", "system_prompt"])
```

## Anatomy of a generation prompt

Each generation call sends:

- A condition-specific **system prompt** with short instructions about voice, format, and length.
- A composed **user prompt** containing:
  - The **source text**: the NYT debate question or the BR lead essay.
  - A **condition block** that varies by condition:
    - `vanilla`: a normal response instruction.
    - `diversified`: asks the model to produce several different responses in one call, separated by `===== ESSAY N =====` markers.
    - `position-guided`: asks the model to write from a human responder's extracted main argument. The human name is not shown to the model.
  - A **length clause** matching the target essay's word count.
  - An **evidence cutoff** telling the model to reason from the debate's publication date.

To reproduce the exact prompt sent for an essay in `llm_essays.jsonl.gz`, use the helper:

```python
from prompts.generation import render_generation_prompt
# The essay row provides debate_id, condition, position_source_id, effort, and model_short.
rendered = render_generation_prompt(
    condition="v4a",                                    # position-guided source condition
    prompt_kind="question",                             # "question" for NYT, "lead" for BR
    prompt_path=DEBATE_DIR / "human/00_question.md",    # the debate prompt file
    source_text=debate_question_text,
    agent_source_path=Path("/tmp/_unused"),
    agent_output_path=Path("/tmp/_unused"),
    target_words=position_guide["word_count"],
    position_guide=position_guide,                      # only for position-guided
)
print(rendered.system_prompt, rendered.direct_user_prompt)
```

Or just open the matching file under `examples/generation/`.

# Schema

Every file under `data/` is newline-delimited JSON. Use `(venue, debate_id)` to join debate-level rows and `(venue, debate_id, essay_id)` to join essay-level rows. `data/nyt/` and `data/br/` use the same table names, so you can combine venues when needed:

```python
pd.concat([
    pd.read_json("data/nyt/toulmin.jsonl.gz", lines=True),
    pd.read_json("data/br/toulmin.jsonl.gz",  lines=True),
])
```

Conventions used across all tables:

- `venue` is `"nyt"` or `"br"`, matching the parent directory.
- `debate_id` is the debate slug (for example, `are-americans-too-obsessed-with-cleanliness`, or `forum_after_911`).
- `essay_id` is the essay slug. For humans, it is the filename slug. For LLM essays, it is the generated filename stem: `{provider_api}__{model_family}__{effort}__{condition}[__{position_source_id}]__{timestamp}`.
- `kind` is one of `"human"`, `"vanilla"`, `"diversified"`, or `"position-guided"`.
- `model_short` is one of `"gpt"`, `"gemini"`, `"claude"`, `"minimax"`, `"deepseek"` for LLM-generated essays, and `null` for human essays.
- `null` is used for absent values. The field is always present.

---

## `debates.jsonl.gz`

One row per debate. 195 NYT debates plus 61 BR forums, for 256 rows total across the release.

| Field | Type | Description |
|---|---|---|
| `venue` | string | `"nyt"` or `"br"`. |
| `debate_id` | string | Debate slug (matches the directory name in the working repo). |
| `title` | string | Debate title. For NYT this is the question headline. For BR this is the lead essay title. |
| `date` | string or null | Publication date (`YYYY-MM-DD` where known). |
| `source` | string | `"nyt_room_for_debate"` or `"boston_review_forum"`. |
| `source_url` | string or null | URL of the original page. Currently `null` because URLs were not preserved during scraping. See `scripts/refetch_human_essays.py`. |
| `topic` | string or null | Coarse topic label (assigned by an LLM classifier). |
| `question_type` | string or null | `"stance"` for binary debates with a support/oppose axis, or `"open_ended"` for prompts that invite exploration. |
| `sensitivity` | string or null | `"low"`, `"medium"`, or `"high"`, where labeled. |
| `question_text` | string or null | The full NYT debate prompt (typically 50 to 200 words). `null` for BR rows. |
| `lead_essay_text` | string or null | The full BR lead essay text. `null` for NYT rows. |
| `lead_essay_authors` | array of strings, or null | BR lead essay authors. |
| `lead_essay_word_count` | int or null | BR lead essay word count. |
| `n_humans` | int | Number of human responder essays for this debate. |
| `n_vanilla` | int | Number of `vanilla` essays generated for this debate. |
| `n_diversified` | int | Number of `diversified` essays generated (summed across efforts; see the effort note in `llm_essays.jsonl.gz`). |
| `n_position_guided` | int | Number of `position-guided` essays generated. |

---

## `human_essays.jsonl.gz`

One row per human responder essay. **No body text.** Use the re-fetcher script to recover it locally.

| Field | Type | Description |
|---|---|---|
| `venue` | string | `"nyt"` or `"br"`. |
| `debate_id` | string | Debate slug. |
| `essay_id` | string | Essay slug (filename stem). |
| `title` | string or null | Essay title where present. |
| `authors` | array of strings | Author name(s). |
| `role_description` | string or null | A short description of the author's role or affiliation, where the original publisher provided one (for example, `"law professor, University of Maryland"`). |
| `author_bio` | string or null | A longer author bio, where present. |
| `date` | string or null | Publication date. |
| `word_count` | int | Word count of the original body text. |
| `source` | string | `"nyt_room_for_debate"` or `"boston_review_forum"`. |
| `source_url` | string or null | URL of the original page (see note in `debates.jsonl.gz`). |
| `body_text` | null | Always `null` in this release. Reconstruct with `scripts/refetch_human_essays.py`. |

---

## `llm_essays.jsonl.gz`

One row per LLM-generated essay. Full text included.

| Field | Type | Description |
|---|---|---|
| `venue` | string | |
| `debate_id` | string | |
| `essay_id` | string | Full generated stem with the format `{provider_api}__{model_family}__{effort}__{kind}[__{position_source_id}]__{timestamp}`. |
| `kind` | string | One of `"vanilla"`, `"diversified"`, `"position-guided"`. (`condition` is an alias.) |
| `condition` | string | Same value as `kind`. |
| `model_short` | string | `"gpt"`, `"gemini"`, `"claude"`, `"minimax"`, or `"deepseek"`. |
| `provider_api` | string | Inference API used (for example, `"openai-api"`, `"vertex-api"`, `"openrouter-api"`). |
| `model_family` | string | Full model family slug (for example, `"gpt-5.5"`, `"anthropic-claude-opus-4.7"`). |
| `effort` | string | `"medium"` for most rows. `"xhigh"` marks the GPT-5.5 `diversified` reasoning-effort ablation. |
| `position_source_id` | string or null | For `position-guided`, this is the human slug the essay was grounded on. For `diversified`, this is the within-batch index (`essay-01`, `essay-02`, and so on). `null` for `vanilla`. |
| `is_representative` | bool or null | For `vanilla` rows only. `true` marks the one answer per model used in the paper. `false` marks other vanilla samples. `null` for `diversified` and `position-guided`. |
| `generated_at_utc` | string | Timestamp of generation. |
| `word_count` | int | |
| `body_text` | string | Full generated essay text. |

**How representatives are selected.** `is_representative` is precomputed. To reproduce it, use `select_llm_representatives` in `src/argument_collapse/cluster.py`. For each debate and model, it finds the most common vanilla main-argument group and picks the essay most similar to the rest of that group. Ties use the lexicographically smallest essay id.

Quick filter to the representative set:

```python
import pandas as pd
llm = pd.read_json("data/nyt/llm_essays.jsonl.gz", lines=True)
reps = llm.query("condition == 'vanilla' and is_representative")
# 195 NYT debates x 5 models = 975 rows
```

---

## `position_guides.jsonl.gz`

One row per human source used for `position-guided` generation. The position source id matches the corresponding human responder's `essay_id`.

| Field | Type | Description |
|---|---|---|
| `venue` | string | |
| `debate_id` | string | |
| `position_source_id` | string | Matches the corresponding `human_essays.essay_id`. |
| `name` | string | Author's name. Recorded for traceability. **Not shown to the LLM during generation.** |
| `role` | string | Anonymized professional background (for example, `"legal scholar focused on data privacy"`). An LLM abstracts this from the author's bio with names and institutions stripped out. |
| `tone` | string | Stylistic register only (formality, person, emotional register). No structural or argumentative content. |
| `word_count` | int | Word count of the source human essay. The `position-guided` essay is length-matched to this number. |
| `schema_version` | int | `2` (current lean schema). |
| `position_prompt_version` | string | Version tag for the prompt that created the position guide. |

The central claim used for `position-guided` generation comes from the matching human row in `toulmin.main_argument`. It is not duplicated in this table.

---

## `toulmin.jsonl.gz`

For each essay, the extracted main argument plus an ordered list of distinct supporting sub-arguments.

| Field | Type | Description |
|---|---|---|
| `venue` | string | |
| `debate_id` | string | |
| `essay_id` | string | |
| `kind` | string | `"human"`, `"vanilla"`, `"diversified"`, or `"position-guided"`. |
| `model_short` | string or null | LLM family for generated essays. `null` for humans. |
| `main_argument` | string | One-sentence central claim. |
| `sub_arguments` | array of strings | Ordered list of distinct supporting claims. |
| `annotator_provider` | string | `"vertex"`. |
| `annotator_model` | string | `"gemini-3-flash-preview"`. |
| `annotator_effort` | string | `"minimal"`, with `"low"` used as a retry for empty-output cases. |
| `prompt_version` | string | Prompt slug. Matches a file under `prompts/`. NYT uses the question version; BR uses the lead-essay version (`_lead` suffix). |

---

## `main_argument_pairs.jsonl.gz`

Pairwise judgments over each pair's main arguments, using a four-label scheme.

| Field | Type | Description |
|---|---|---|
| `venue` | string | |
| `debate_id` | string | |
| `essay_i`, `essay_j` | string | The two essay ids being compared. |
| `kind_i`, `kind_j` | string | `"human"`, `"vanilla"`, `"diversified"`, or `"position-guided"`. |
| `model_i`, `model_j` | string or null | LLM family for generated essays. |
| `relation` | string | One of: `"equivalent"` (same proposal), `"strong_overlap"` (same proposal, differ in elaboration), `"weak_overlap"` (shared topic or stance, different central proposals), `"different"`. |
| `rationale` | string | A short justification from the judge. |
| `judge_provider` | string | `"vertex"`. |
| `judge_model` | string | `"gemini-3-flash-preview"`. |
| `judge_effort` | string | |
| `prompt_version` | string | `"main_argument_judge_v8_4label"` (with `_lead` suffix for BR). |

If you need numeric scores, we use: `equivalent = 1.0`, `strong_overlap = 0.7`, `weak_overlap = 0.3`, `different = 0.0`.

**Recommended threshold.** Treat `equivalent` and `strong_overlap` as substantial overlap. Treat `weak_overlap` and `different` as not substantial. Human annotators agreed most reliably at this split.

---

## `sub_argument_pairs.jsonl.gz`

Pairwise judgments over supporting sub-arguments. This table is intentionally a subset, not a full-corpus all-pairs export: sub-argument annotation was run for selected analysis subsets because every essay pair expands into many sub-argument pairs. The current export contains `374,414` NYT rows across `83` debates and `46,638` BR rows across `21` forums. It includes only public conditions (`human`, `vanilla`, `diversified`, and `position-guided`) and omits older internal conditions. The NYT rows cover the shared-main vanilla comparison; other sub-argument rows are available for selected checks.

Metric code checks that the configured subset is fully annotated before computing sub-argument unique rates. Missing pair labels should not be interpreted as `different`.

| Field | Type | Description |
|---|---|---|
| `venue` | string | |
| `debate_id` | string | |
| `sub_i`, `sub_j` | string | Sub-argument ids in the form `{essay_id}::subNN`. |
| `essay_i`, `essay_j` | string | Essay ids for the two sub-arguments. |
| `sub_index_i`, `sub_index_j` | int | Index of the sub-argument within each essay's `toulmin.sub_arguments` list. |
| `kind_i`, `kind_j` | string | `"human"`, `"vanilla"`, `"diversified"`, or `"position-guided"`. |
| `model_i`, `model_j` | string or null | LLM family for generated essays. |
| `main_argument_i`, `main_argument_j` | string | Main arguments for the two source essays. |
| `sub_argument_i`, `sub_argument_j` | string | The two supporting claims being compared. |
| `relation` | string | One of `"equivalent"`, `"strong_overlap"`, `"weak_overlap"`, or `"different"`. |
| `rationale` | string | A short justification from the judge. |
| `judged_at_utc` | string | Timestamp of judgment. |
| `judge_provider`, `judge_model`, `judge_effort` | string | Judge-call metadata. |
| `prompt_version` | string | Prompt slug for the sub-argument judge. |

---

## `grounding_pairs.jsonl.gz`

A subset of `main_argument_pairs.jsonl.gz`. Each row compares one human essay with the position-guided LLM essay based on that human. Same schema as `main_argument_pairs.jsonl.gz`.

You can reproduce this file from `main_argument_pairs.jsonl.gz`:

```python
import pandas as pd
df = pd.read_json("data/nyt/main_argument_pairs.jsonl.gz", lines=True)   # or data/br/
mask = (df.kind_i == "human") & (df.kind_j == "position-guided")
diag = mask & df.apply(lambda r: r.essay_j.split("__")[4] == r.essay_i, axis=1)
df[diag].to_json("grounding_pairs.jsonl", orient="records", lines=True)
```

---

## `structure_argument.jsonl.gz` and `structure_discourse_mode.jsonl.gz`

Per-paragraph annotations. One row per essay. The `annotations` field is an ordered list aligned with the essay's paragraphs.

| Field | Type | Description |
|---|---|---|
| `venue` | string | |
| `debate_id` | string | |
| `essay_id` | string | |
| `layer` | string | `"argument"` or `"discourse_mode"`. |
| `annotations` | array of objects | Per-paragraph label objects. Shape depends on layer; see below. |
| `judge_provider` | string | `"vertex"`. |
| `judge_model` | string | `"gemini-3-flash-preview"`. |
| `prompt_filename` | string | Source prompt. Matches `prompts/structure/*`. |
| `prompt_sha` | string | SHA-256 of the prompt text used at annotation time. |

For the `argument` layer, each paragraph object has the shape:

```json
{ "paragraph_index": int,
  "labels": [ "thesis" | "support" | "concession" | "rebuttal" | "reframing"
            | "proposal" | "implication" | "none", ... ],
  "rationale": string }
```

`labels` may have one or two entries. For example, `["concession", "rebuttal"]` for a paragraph that concedes a point and then rebuts it. At most one paragraph per essay is labeled `thesis`. Use `none` for content-empty fragments such as section headings, pull-quotes, or subscription footers.

For the `discourse_mode` layer, each paragraph object has a single `label`:

```json
{ "paragraph_index": int,
  "label": "argumentation" | "exposition" | "narration" | "description",
  "rationale": string }
```

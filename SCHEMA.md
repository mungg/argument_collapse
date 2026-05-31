# Schema

Every JSONL file under `data/` is newline-delimited JSON. Each row is self-contained. The only join keys you need are `(venue, debate_id)` for debate-level rows and `(venue, debate_id, essay_id)` for essay-level rows.

Data is partitioned by venue. `data/nyt/` and `data/br/` each contain the full set of tables for that venue. Rows still carry `venue` and `debate_id`, so files can be concatenated cross-venue without ambiguity. For example:

```python
pd.concat([
    pd.read_json("data/nyt/toulmin.jsonl.gz", lines=True),
    pd.read_json("data/br/toulmin.jsonl.gz",  lines=True),
])
```

Conventions used across all tables:

- `venue` is `"nyt"` or `"br"`, matching the parent directory.
- `debate_id` is the debate slug (for example, `are-americans-too-obsessed-with-cleanliness`, or `forum_after_911`).
- `essay_id` is the essay slug. For human responder essays, this is the filename slug. For LLM-generated essays, this is the full generated stem with the format `{provider_api}__{model_family}__{effort}__{condition}[__{persona_id}]__{timestamp}`.
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
| `essay_id` | string | Full generated stem with the format `{provider_api}__{model_family}__{effort}__{kind}[__{persona_id}]__{timestamp}`. |
| `kind` | string | One of `"vanilla"`, `"diversified"`, `"position-guided"`. (`condition` is an alias.) |
| `condition` | string | Same value as `kind`. |
| `model_short` | string | `"gpt"`, `"gemini"`, `"claude"`, `"minimax"`, or `"deepseek"`. |
| `provider_api` | string | Inference API used (for example, `"openai-api"`, `"vertex-api"`, `"openrouter-api"`). |
| `model_family` | string | Full model family slug (for example, `"gpt-5.5"`, `"anthropic-claude-opus-4.7"`). |
| `effort` | string | `"medium"` for most rows. `"xhigh"` marks the GPT-5.5 `diversified` reasoning-effort ablation. |
| `persona_id` | string or null | For `position-guided`, this is the human slug the essay was grounded on. For `diversified`, this is the within-batch index (`essay-01`, `essay-02`, and so on). `null` for `vanilla`. |
| `is_representative` | bool or null | For `vanilla` rows only. `true` if the essay is the model-level representative (medoid of the model's modal equivalent cluster) for its debate, `false` for the other vanilla samples. `null` for `diversified` and `position-guided`, where the concept does not apply. The paper compares one representative per model against humans; filter on this field to recover that set. |
| `generated_at_utc` | string | Timestamp of generation. |
| `word_count` | int | |
| `body_text` | string | Full generated essay text. |

**Reproducing the representative selection from raw samples.** The `is_representative` field is precomputed for convenience. The reference implementation is shipped in `src/argument_collapse/cluster.py` (the `select_llm_representatives` function (in `argument_collapse.cluster`)). For each (debate, model), it identifies the model's modal equivalent-cluster across its vanilla samples and picks the medoid, defined as the essay with the highest summed similarity to other members of that cluster, with lexicographically smallest stem as a deterministic tie-break. Inputs are the cohort's `main_argument_pairs` rows plus the essay records.

Quick filter to the representative set:

```python
import pandas as pd
llm = pd.read_json("data/nyt/llm_essays.jsonl.gz", lines=True)
reps = llm.query("condition == 'vanilla' and is_representative")
# 195 NYT debates x 5 models = 975 rows
```

---

## `personas.jsonl.gz`

One row per persona used to ground `position-guided` generation. Persona id matches the corresponding human responder's `essay_id`.

| Field | Type | Description |
|---|---|---|
| `venue` | string | |
| `debate_id` | string | |
| `persona_id` | string | Matches the corresponding `human_essays.essay_id`. |
| `name` | string | Author's name. Recorded for traceability. **Not shown to the LLM during generation.** |
| `role` | string | Anonymized professional background (for example, `"legal scholar focused on data privacy"`). An LLM abstracts this from the author's bio with names and institutions stripped out. |
| `tone` | string | Stylistic register only (formality, person, emotional register). No structural or argumentative content. |
| `word_count` | int | Word count of the source human essay. The `position-guided` essay is length-matched to this number. |
| `schema_version` | int | `2` (current lean schema). |
| `persona_prompt_version` | string | The version tag of the persona-extraction prompt. |

The full central claim that `position-guided` generation grounds on is pulled directly from `toulmin.main_argument` for the matching `(venue, debate_id, essay_id=persona_id, kind="human")` row at generation time. It is not stored in the persona itself.

---

## `toulmin.jsonl.gz`

For each essay, the main argument (one sentence) plus an ordered list of distinct supporting sub-arguments.

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
| `prompt_version` | string | Prompt slug. Matches a file under `prompts/`. NYT uses the question-aware variant; BR uses the lead-aware variant (`_lead` suffix). |

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

Continuous similarity weights, where useful for analyses: `equivalent = 1.0`, `strong_overlap = 0.7`, `weak_overlap = 0.3`, `different = 0.0`.

**Recommended cut for downstream analysis.** Treat `equivalent` plus `strong_overlap` as "substantial overlap" and `weak_overlap` plus `different` as "not substantial". This binary at `S ≥ 0.7` is the threshold our human annotators agreed on most reliably. The `equivalent`-vs-rest cut is lower-agreement.

---

## `grounding_pairs.jsonl.gz`

A convenience subset of `main_argument_pairs.jsonl.gz`. Each row is one (human, position-guided) pair where the position-guided essay was grounded on that specific human. This is the sanity check that the model preserved the assigned thesis under `position-guided` generation. Same schema as `main_argument_pairs.jsonl.gz`.

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

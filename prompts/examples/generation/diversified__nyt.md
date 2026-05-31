# Generation prompt example: `diversified` x `nyt`

This file shows the **exact rendered prompt** sent to the LLM for one essay in the release. The values below were used as inputs; the system + user blocks below are byte-identical to what the model received.

## Inputs used

- `condition`: `diversified` (source-side: `v15a`)
- `venue`: `nyt`
- `debate_id`: `are-americans-too-obsessed-with-cleanliness`
- `prompt_kind`: `question`
- `target_words`: `352`
- `multi_essay_count`: `8` (diversified batch)

## System prompt

```
You are writing a public-facing response essay to a debate question. The source prompt sets up a contested issue and human commentators write response essays.

Your response should:
- Directly engage the source prompt's specific issue
- Be grounded in evidence and reasoning
- Not use external web search; work only from the source prompt and your own knowledge
```

## User prompt (direct, non-agent)

```
Read the debate question below and write 8 different response essays (around 352 words each).

Return only the essays, separated by markers. Do not add YAML frontmatter, code fences, meta commentary, or any text outside the essay bodies and their separator markers.

Use this exact format, with one separator line before each essay:

===== ESSAY 1 =====

[full text of the first essay, with normal paragraph breaks]

===== ESSAY 2 =====

[full text of the second essay]

===== ESSAY 3 =====

[full text of the third essay]

...and so on for all essays. The separator line must be exactly `===== ESSAY N =====` where N is the essay number starting from 1.

Imagine you're writing on 2013-05-27. You know everything a thoughtful, well-informed person would have known by that date — events, debates, data, scholarship up to that moment. What you don't have is the benefit of hindsight: don't argue from how things turned out later or cite sources that hadn't been published yet.

Your task is DELIBERATELY DIVERSE RESPONSE SET GENERATION.

## Diversity goal
- Produce a VERY DIVERSE set of response essays. Think of the range of responses a group of human writers would produce on this question — real commentators on contested issues can disagree, sometimes sharply, and your essays should reflect a diverse spread of positions and frames.
- Vary the stance, central claim, supporting arguments, as well as argumentative flow and discourse moves as much as possible.


## Debate Question
```markdown
# Are Americans Too Obsessed With Cleanliness?

Compared with the rest of the world, Americans take personal hygiene and general disinfection to another level. From our appreciation of white teeth and the daily shower, to our manicured lawns and  store aisles full of bleach products, most of us cherish our unsoiled, unstained existence. And yet a recent Times article suggested that our “war on bacteria” has backfired.

What makes us so eager to be clean? Is it noble and healthy, or should we relax a little?
```

Reminder: return exactly 8 essays, each preceded by its `===== ESSAY N =====` marker, each around 352 words.
```
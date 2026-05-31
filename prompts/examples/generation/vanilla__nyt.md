# Generation prompt example: `vanilla` x `nyt`

This file shows the **exact rendered prompt** sent to the LLM for one essay in the release. The values below were used as inputs; the system + user blocks below are byte-identical to what the model received.

## Inputs used

- `condition`: `vanilla` (source-side: `v1a`)
- `venue`: `nyt`
- `debate_id`: `are-americans-too-obsessed-with-cleanliness`
- `prompt_kind`: `question`
- `target_words`: `352`

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
Read the debate question below and write a response essay (around 352 words).

Return only the essay body — no YAML frontmatter, no meta commentary, no title, no label, and no restatement of the prompt as a title. Preserve paragraph breaks.

Imagine you're writing on 2013-05-27. You know everything a thoughtful, well-informed person would have known by that date — events, debates, data, scholarship up to that moment. What you don't have is the benefit of hindsight: don't argue from how things turned out later or cite sources that hadn't been published yet.

## Debate Question
```markdown
# Are Americans Too Obsessed With Cleanliness?

Compared with the rest of the world, Americans take personal hygiene and general disinfection to another level. From our appreciation of white teeth and the daily shower, to our manicured lawns and  store aisles full of bleach products, most of us cherish our unsoiled, unstained existence. And yet a recent Times article suggested that our “war on bacteria” has backfired.

What makes us so eager to be clean? Is it noble and healthy, or should we relax a little?
```

Reminder: your response should be around 352 words.
```
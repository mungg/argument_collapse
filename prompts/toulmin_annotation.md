# Toulmin annotation prompts

Prompt version: `toulmin_annotation_v2_question_aware` (with `_lead` suffix for BR).

Two variants are used:
- **Question-aware** (NYT): the responder essay reacts to a short debate question.
- **Lead-aware** (BR): the responder essay reacts to a long lead essay.

## System prompt (question variant)

```
Given an op-ed essay and the debate question it responds to, extract the
essay's argumentative structure.

Field definitions:
- main_argument: The single central claim the essay makes in response to
  the debate question (1 sentence).
- sub_arguments: Distinct supporting claims that develop or back the
  main_argument. Each one sentence. Avoid restating the main_argument or another sub_argument.

Return strict JSON:
{
  "annotation": {
    "main_argument": "...",
    "sub_arguments": ["...", "..."]
  }
}
```

## System prompt (lead variant)

```
Given an op-ed essay and the lead essay it responds to, extract the
responding essay's argumentative structure.

Field definitions:
- main_argument: The single central claim the responding essay makes in
  response to the lead essay (1 sentence).
- sub_arguments: Distinct supporting claims that develop or back the
  main_argument. Each one sentence. Avoid restating the main_argument or another sub_argument.

Extract the structure of the RESPONDING essay only; the lead essay is
context for what the response is reacting to, not material to summarize.

Return strict JSON:
{
  "annotation": {
    "main_argument": "...",
    "sub_arguments": ["...", "..."]
  }
}
```

## User prompt template

```
{context_label}:
{question_or_lead_text}

Essay:
{essay_body}
```

Where `{context_label}` is `"Debate question"` (NYT) or `"Lead essay"` (BR).

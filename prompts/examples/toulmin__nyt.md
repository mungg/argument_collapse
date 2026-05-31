# Toulmin annotation example: `nyt`

This file shows the **exact toulmin extraction prompt** sent to the annotator for one human essay in the release, alongside the structured output stored in `toulmin.jsonl.gz`.

## Inputs used
- `venue`: `nyt`
- `debate_id`: `are-americans-too-obsessed-with-cleanliness`
- `essay_id`: `christopher-a-lowry`
- `prompt_version`: `toulmin_annotation_v2_question_aware`

## System prompt

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

## User prompt

```
Debate question:
# Are Americans Too Obsessed With Cleanliness?

Compared with the rest of the world, Americans take personal hygiene and general disinfection to another level. From our appreciation of white teeth and the daily shower, to our manicured lawns and  store aisles full of bleach products, most of us cherish our unsoiled, unstained existence. And yet a recent Times article suggested that our “war on bacteria” has backfired.

What makes us so eager to be clean? Is it noble and healthy, or should we relax a little?

Essay:
Modern hygiene has saved countless lives, but by eliminating microbes with antibiotics and increased cleanliness, have diverse beneficial microorganisms become “collateral damage"?

At the center of this argument is the hygiene hypothesis. The hypothesis, as originally conceived, was based on the observation that allergic diseases were less common in children from larger families compared to children in families with only one child, presumably because of increased exposure to infectious agents through their siblings. More recently, it has been suggested that protection does not come through exposure only to infectious agents, but through exposure to diverse organisms -- some of which are capable of causing disease but are relatively harmless -- and that this process can in turn regulate a body's immune response system and decrease inflammation.

Graham Rook, of University College London, has introduced the “old friends hypothesis” to distinguish between infectious agents and generally noninfectious agents with potential benefits to human health. These “old friends” include microbes in the human body and “pseudocommensals," which are harmless environmental organisms in mud, untreated water, and fermenting vegetable matter like lactobacillis and environmental saprophytes. These organisms may be the “collateral damage” of our war on microbes.

Microbes are affected by modern diets and environments, not to mention antibiotics, while we are less exposed to pseudocommensals in the modern urban realm. This can increase our risk for inflammation and inflammatory disease. Recent studies suggest that Americans have higher levels of inflammation than people living in primitive rural environments, like lowland Ecuador. Depression and some other psychiatric disorders are associated with a mild elevation in inflammation.

Clinical trials are ongoing to determine if reintroducing some of these “old friends” as therapies may improve symptoms of inflammatory disease, and future studies are likely to evaluate the effects in psychiatric disorders. A broader question is how to increase exposure to the “old friends” in everyday life. If we relax hygiene we will not necessarily be reunited with our "old friends"; rather, we will merely expose ourselves to our “old enemies."

In the meantime, would spending more time playing in the mud pay off in the short run? Perhaps.
```

## Output stored in `toulmin.jsonl.gz`

```json
{
  "main_argument": "While modern hygiene is essential for preventing disease, our extreme obsession with cleanliness has inadvertently eliminated beneficial microorganisms that are necessary for regulating the human immune system and preventing inflammatory conditions.",
  "sub_arguments": [
    "The hygiene hypothesis suggests that early exposure to diverse microorganisms is necessary to properly train the body's immune response and decrease inflammation.",
    "Modern urban environments and diets have reduced our exposure to 'old friends,' such as harmless environmental microbes found in mud and untreated water.",
    "The lack of microbial diversity in modern life may contribute to higher levels of inflammation, which is linked to both physical diseases and psychiatric disorders like depression.",
    "Simply relaxing hygiene standards is not a complete solution, as it could expose people to dangerous pathogens rather than just the beneficial organisms lost to modern cleanliness."
  ]
}
```
You are performing discourse mode analysis of an op-ed essay. For each paragraph, assign discourse_mode labels based on HOW the paragraph is written — its dominant mode of presentation — independent of the argument it makes.

## Per-paragraph annotation

Assign exactly one label per paragraph — the single mode that most dominates the paragraph's delivery. If two modes coexist, pick the one that most determines how the paragraph reads as a whole.

### Label set

**`argumentation`**
Claim-and-reason writing with explicit inferential force. The paragraph stakes a position and develops it through reasons, contrasts, causal links, or conclusions. Use `argumentation` when the paragraph's internal organization is driven by reasoning from one sentence to the next, not just by presenting relevant information. The key is whether the paragraph is performing inference (claims, projections, evaluations, conclusions, contrasts) rather than reporting (facts, scenes, processes, states). Explicit reasoning markers like "because" or "therefore" are common in argumentation but not required.

**The diagnostic is internal to the paragraph: does the paragraph itself perform an inferential move — make a claim, draw a conclusion, evaluate, project, or contrast — within its own boundaries? If yes → `argumentation`. If the paragraph reports facts, explains a state of affairs, or recounts events without itself drawing a conclusion → `exposition` or `narration`, even when those facts are positioned to support an argument made elsewhere in the essay.**

Examples:
- A paragraph that states a policy is flawed, then explains why the flaw matters.
- A paragraph that uses facts to build an explicit conclusion inside the paragraph.
- A paragraph that projects a chain of consequences from a premise, even without overt "because/therefore" markers.
- A paragraph that recounts a historical sequence and ends with an evaluative judgment ("X has proven insufficient", "this approach failed") — the closing judgment is the inferential move that makes it argumentation.

**`exposition`**
Explanation, clarification, or factual information without dominant inferential force. The paragraph informs about facts, concepts, processes, or states. Sentences are connected through descriptive or elaborative relations rather than argumentative ones — even when the content supports a broader argument elsewhere in the essay. **A paragraph that lists facts, describes a causal dynamic, or recounts background without drawing its own conclusion is `exposition`, even when its role within the essay is to support an argument. The test is internal to the paragraph: no inferential move inside it → `exposition`.**

Examples:
- A paragraph explaining how a program, institution, or process works.
- A paragraph giving background facts without pushing an explicit internal conclusion.
- A paragraph clarifying a concept (e.g., defining a technical term, describing a regulatory framework) without using it to evaluate or argue.
- A paragraph describing a causal dynamic (X led to Y led to Z) where the chain is presented as a factual description of what happened, not as the foundation of a new claim.

**`narration`**
A paragraph that recounts events or actions — what happened, who did what, or how events unfolded, whether as a single incident or as a sequence over time. **Reserved for paragraphs whose primary act is recounting events for their own sake. A historical or chronological recap that ends in (or organizes itself around) an evaluative claim — e.g., "this approach has failed," "the result was X" — is `argumentation`, not `narration`. The surface chronology doesn't determine the mode; the organizing purpose does.**

Examples:
- A paragraph describing what happened in a particular incident or case.
- A paragraph recounting a sequence of events leading up to a decision, without drawing an evaluative conclusion from them.

**`description`**
Depiction of a scene, state, person, object, or place. The paragraph is organized spatially, perceptually, or by attributes rather than temporally or inferentially. The organizing principle is the qualities of what is being depicted.

Examples:
- A paragraph depicting conditions in a neighborhood, classroom, workplace, or institution.
- A paragraph portraying a person, group, place, or state of affairs without a main sequence or inference.

## Return JSON

```json
{
  "layer": "discourse_mode",
  "annotations": [
    {
      "paragraph_index": 0,
      "label": "<argumentation | exposition | narration | description>",
      "rationale": "Brief explanation."
    }
  ]
}
```

Rules for output:

- Preserve paragraph order.
- Assign exactly one label per paragraph.
- Return valid JSON only.

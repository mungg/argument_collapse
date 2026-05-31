# Main-argument four-label judge example: `nyt`

This file shows the **exact pairwise judge prompt** sent for one judged pair in the release, alongside the relation and rationale stored in `main_argument_pairs.jsonl.gz`.

## Inputs used
- `venue`: `nyt`
- `debate_id`: `are-americans-too-obsessed-with-cleanliness`
- `essay_i`: `christopher-a-lowry` (`kind_i=human`)
- `essay_j`: `openrouter-api__anthropic-claude-opus-4.7__medium__v1a__christopher-a-lowry__20260515T040232321453Z` (`kind_j=v1a`)
- `prompt_version`: `main_argument_judge_v8_4label`

## System prompt

```
You compare two op-ed essays' main_argument statements (one sentence each)
about the SAME debate question, and decide the logical relation between them.

Return exactly one `relation` from a 4-way scale:

- "equivalent"     — both main_arguments commit to the SAME central position
                     on the question. Paraphrase or different wording is fine;
                     what matters is that a careful reader would say they
                     take the same stance and make the same essential claim.
                     Mutual entailment in the context of the question.

- "strong_overlap" — both main_arguments SHARE THE CORE PROPOSAL or claim,
                     but one (or both) adds elaborations, secondary
                     commitments, or extensions the other doesn't. The
                     central thing they propose / argue is the same; the
                     difference is in what each adds around it.

- "weak_overlap"   — both main_arguments share the same STANCE or
                     ORIENTATION toward the question (e.g., both favor
                     intervention, both reject a framing, both endorse a
                     general goal), but propose different central
                     mechanisms, reasons, or commitments. They agree at
                     the directional level but propose different
                     specifics.

- "different"      — no shared stance or substantive commitment beyond
                     responding to the same debate question. Covers
                     opposing positions on the same axis, disjoint
                     choices on open-ended questions, and pairs where
                     neither side's stance or central commitment aligns
                     with the other.

Critical rules:
- All pairs in a cohort share the debate question by construction, so
  "shared topic" alone is NEVER enough for any kind of overlap label.
  `weak_overlap` requires shared STANCE or ORIENTATION, not just
  shared question framing.
- OPPOSING positions are always `different`. Pro and con of the same
  proposition never count as `equivalent`, `strong_overlap`, or
  `weak_overlap`.
- The split between `strong_overlap` and `weak_overlap` is structural,
  not magnitudinal:
    * `strong_overlap`: shared CORE proposal/claim + extra elaborations.
    * `weak_overlap`:   shared STANCE + different central proposals.
- Different framings of the SAME position ARE equivalent.
- If in doubt between `equivalent` and `strong_overlap`: would a careful
  reader say these are "the same argument said differently" (equivalent)
  or "two related arguments sharing a core proposal" (strong_overlap)?
- If in doubt between `strong_overlap` and `weak_overlap`: do they share
  the CENTRAL PROPOSAL, or only the stance / orientation? If only the
  stance, it's weak.
- If in doubt between `weak_overlap` and `different`: do they share any
  stance or orientation beyond merely responding to the same question?
  If yes, it's `weak_overlap`; if no, it's `different`.
- OPEN-ENDED QUESTIONS that name a goal in the question itself (e.g.,
  "how should we improve X?", "what changes to X would make it better?",
  "what should we do to fix X?") require a STRICTER test for shared
  stance. The question already names the goal. Two main_arguments that
  both endorse that named goal have NOT shared a stance — they have
  just answered the question.
  CRITICAL: this includes "X over Y" framings where Y is what the
  question implicitly wants to move away from. If the question asks how
  to make debates "more substantive," then both essays saying "prioritize
  substance over spectacle" / "favor policy depth over theatricality" /
  "emphasize substantive discourse over performance" do NOT have a
  shared substantive orientation — they are both just restating the
  question's own framing in oppositional form. The same logic applies
  to "engagement over passivity," "quality over quantity," "equity over
  efficiency" when the named thing on the left is exactly what the
  question asked for.
  To qualify as `weak_overlap` on these questions, the shared
  orientation must go BEYOND the question's stated goal — e.g., both
  prefer market mechanisms over regulation, both prioritize the
  underserved over typical users, both reject institutional reform in
  favor of grassroots change, both blame a common root cause.
  If two main_arguments propose disjoint specific mechanisms but their
  only commonality is "we should achieve the goal the question asks
  about" (in any phrasing, including "X over Y"-style framings drawn
  from the question), the relation is `different`.

Return strict JSON:
{
  "relation": "equivalent" | "strong_overlap" | "weak_overlap" | "different",
  "rationale": "1-2 sentences explaining the relation, grounded in the actual main_argument text"
}

## Calibration examples

The example questions below are deliberately invented small-town policy
debates and do not correspond to any real cohort in the dataset. Each
example targets a specific boundary between adjacent labels.

Question: Should Brookline adopt a four-day workweek for municipal staff?
I: "Brookline should adopt the four-day workweek because the pilot data showed productivity held steady while sick leave dropped."
J: "The municipal four-day schedule should be made permanent; the pilot showed comparable output with fewer health absences."
→ {"relation": "equivalent", "rationale": "Both endorse adopting the four-day workweek and both ground that endorsement in the same pilot evidence (productivity + reduced absences). Paraphrase, same position."}

Question: Should the city of Brookline require electric scooters to be parked in marked corrals?
I: "Brookline should mandate corral parking and impose escalating fines on repeat violators."
J: "Brookline should mandate corral parking and require operators to provide real-time corral-availability maps in their apps."
→ {"relation": "strong_overlap", "rationale": "Both endorse mandating corral parking (the shared core proposal). I adds an enforcement mechanism (fines), J adds an operator-side usability mechanism (maps) — different secondary commitments around the same center."}

Question: How should Brookline reduce car traffic on Main Street?
I: "Brookline should redesign Main Street as a transit-and-bike priority corridor with reduced car lanes."
J: "Brookline should raise downtown parking prices and use the revenue to fund a free shuttle loop."
→ {"relation": "weak_overlap", "rationale": "Both share the stance that car traffic should be reduced, but propose completely different central mechanisms: I focuses on physical street redesign, J on pricing plus transit subsidy. Shared orientation, no shared central proposal."}

Question: Should Brookline adopt a four-day workweek for municipal staff?
I: "Brookline should adopt the four-day workweek to give public-sector workers the recovery time the private sector won't offer."
J: "Brookline should adopt the four-day workweek to make municipal jobs competitive with neighboring towns that already offer flexible scheduling."
→ {"relation": "weak_overlap", "rationale": "Both share the yes-stance on adopting the workweek, but ground it in different primary reasons (worker welfare vs hiring competitiveness). Shared yes-stance, different central WHY."}

Question: Should the Riverton library extend weekend hours?
I: "The library should extend weekend hours because current hours leave working residents unable to use the building."
J: "Weekend hours should stay as they are; further extension diverts limited staff from the children's programming the library is known for."
→ {"relation": "different", "rationale": "Directly opposing positions on the question."}

Question: How could the Brookline garden club make its monthly programs more substantive?
I: "The club should invite guest horticulturalists once per quarter to prioritize substantive instruction over informal show-and-tell."
J: "The club should organize hands-on workshops at members' gardens to prioritize substantive practice over slideshow lectures."
→ {"relation": "different", "rationale": "Open-ended question asking what changes would make the programs 'more substantive.' Both arguments use 'substantive X over Y' framing, but the 'substantive' half is just the question's named goal and the Y half (show-and-tell / slideshow lectures) describes the current shortcoming the question implicitly asks them to fix — i.e., the entire 'substantive X over Y' framing is a restatement of the question's own setup. The specific commitments (guest horticulturalists vs hands-on workshops) are disjoint mechanisms with no substantive shared orientation. Per the open-ended-question rule, this is `different`, not `weak_overlap`."}
```

## User prompt

```
Debate question:
# Are Americans Too Obsessed With Cleanliness?

Compared with the rest of the world, Americans take personal hygiene and general disinfection to another level. From our appreciation of white teeth and the daily shower, to our manicured lawns and  store aisles full of bleach products, most of us cherish our unsoiled, unstained existence. And yet a recent Times article suggested that our “war on bacteria” has backfired.

What makes us so eager to be clean? Is it noble and healthy, or should we relax a little?

I: While modern hygiene is essential for preventing disease, our extreme obsession with cleanliness has inadvertently eliminated beneficial microorganisms that are necessary for regulating the human immune system and preventing inflammatory conditions.
J: While historical hygiene practices were essential for public health, modern Americans have reached a point of diminishing returns where hyper-sanitization now poses risks to our immune systems and global health.

Return strict JSON: {"relation": ..., "rationale": ...}
```

## Output stored in `main_argument_pairs.jsonl.gz`

```json
{
  "relation": "equivalent",
  "rationale": "Both arguments take the same stance that while hygiene was historically/is essentially important, modern American 'extreme obsession' or 'hyper-sanitization' has become counterproductive by harming the human immune system. They use different wording to describe the same central claim and biological mechanism."
}
```
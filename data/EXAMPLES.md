# Data examples

One sample row from every JSONL table per venue, pretty-printed. Long text fields (`body_text`, `question_text`, `lead_essay_text`, `main_argument`, `rationale`, `author_bio`, `role`, `tone`, `role_description`) are truncated to keep the page readable; the actual `.jsonl.gz` files carry the full text. See `SCHEMA.md` for column-level docs.

## NYT  (`data/nyt/`)

### `debates.jsonl.gz`: Per-debate metadata

```json
{
  "venue": "nyt",
  "debate_id": "23andme-and-the-promise-of-anonymous-genetic-testing-10",
  "title": "A Path to Better Health Care Research",
  "date": "2015-03-02",
  "source": "nyt_room_for_debate",
  "source_url": null,
  "topic": "science_tech",
  "question_type": "stance",
  "sensitivity": null,
  "question_text": "# 23andMe and the Promise of Anonymous Genetic Testing\n\nThe F.D.A. has allowed 23andMe to market genetic tests for mutations directly to the public. The agency said that, for the most part, so-called carrier tests would no longer need advance approval before being marketed this way. But 23andMe is also offering access to its data for research, opening up questions about privacy and anonymity.\n\nSho …",
  "lead_essay_text": null,
  "lead_essay_authors": null,
  "lead_essay_word_count": null,
  "n_humans": 4,
  "n_vanilla": 20,
  "n_diversified": 24,
  "n_position_guided": 20
}
```

### `human_essays.jsonl.gz`: Human responder essay index (no body)

```json
{
  "venue": "nyt",
  "debate_id": "23andme-and-the-promise-of-anonymous-genetic-testing-10",
  "essay_id": "frank-pasquale",
  "title": "Insure People Against Genetic Data Breaches",
  "authors": [
    "Frank Pasquale"
  ],
  "role_description": "author, \"The Black Box Society\"",
  "author_bio": "Frank Pasquale, a law professor at the University of Maryland, is the author of \"The Black Box Society: The Secret Algorithms That Control Money and Information.\"",
  "date": "2015-03-02",
  "word_count": 276,
  "source": "nyt_room_for_debate",
  "source_url": null,
  "body_text": null
}
```

### `llm_essays.jsonl.gz`: LLM-generated essay (full text; truncated here for display)

```json
{
  "venue": "nyt",
  "debate_id": "23andme-and-the-promise-of-anonymous-genetic-testing-10",
  "essay_id": "openai-api__gpt-5.5__medium__diversified__essay-01__20260517T030137063642Z",
  "kind": "diversified",
  "condition": "diversified",
  "model_short": "gpt",
  "provider_api": "openai-api",
  "model_family": "gpt-5.5",
  "effort": "medium",
  "position_source_id": "essay-01",
  "is_representative": null,
  "generated_at_utc": "20260517T030137063642Z",
  "word_count": 380,
  "body_text": "Commercial genetic companies should be allowed—even encouraged—to share genetic information for research, provided that customers give informed consent and that the data are stripped of direct identifiers. The potential public benefit is too large to dismiss because of hypothetical fears.\n\nGenetics research has long suffered from scale. A university lab might spend years assembling a cohort of a f …"
}
```

### `position_guides.jsonl.gz`: Position-guidance descriptor

```json
{
  "venue": "nyt",
  "debate_id": "23andme-and-the-promise-of-anonymous-genetic-testing-10",
  "position_source_id": "frank-pasquale",
  "name": "Frank Pasquale",
  "role": "Legal scholar and professor specializing in the intersection of law, information technology, and algorithmic systems.",
  "tone": "Formal, cautionary, and authoritative. The register is third-person and analytical, maintaining a serious and ethically concerned emotional quality.",
  "word_count": 276,
  "schema_version": 2,
  "position_prompt_version": "cross_venue_position_guide_v2_lean"
}
```

### `toulmin.jsonl.gz`: Toulmin extraction

```json
{
  "venue": "nyt",
  "debate_id": "23andme-and-the-promise-of-anonymous-genetic-testing-10",
  "essay_id": "somalee-datta",
  "kind": "human",
  "model_short": null,
  "main_argument": "Commercial companies and hospitals should utilize secure technology platforms to share genetic data for research because privacy and scientific progress are not mutually exclusive.",
  "sub_arguments": [
    "Sharing genetic information is essential for accelerating healthcare research and finding cures for patients.",
    "Existing institutional data, such as that held by the Veteran Affairs, represents a massive untapped resource for medical breakthroughs.",
    "Current regulatory and consent processes are inefficient and slow down the pace of vital research.",
    "Advanced technology platforms can streamline patient consent and allow for distributed data analysis without compromising security or moving data from its original location.",
    "Technology companies are better equipped than individual hospitals to build and maintain the secure infrastructure needed for large-scale data sharing."
  ],
  "annotator_provider": "vertex",
  "annotator_model": "gemini-3-flash-preview",
  "annotator_effort": "minimal",
  "prompt_version": "toulmin_annotation_v2_question_aware"
}
```

### `main_argument_pairs.jsonl.gz`: Pairwise 4-label main-argument judgment

```json
{
  "venue": "nyt",
  "debate_id": "23andme-and-the-promise-of-anonymous-genetic-testing-10",
  "essay_i": "frank-pasquale",
  "essay_j": "openai-api__gpt-5.5__medium__vanilla__marcy-darnovsky__20260514T025145998943Z",
  "kind_i": "human",
  "kind_j": "vanilla",
  "model_i": null,
  "model_j": "gpt",
  "relation": "different",
  "rationale": "The two arguments address different aspects of the debate with no shared stance or mechanism: Argument I focuses on financial liability and insurance for data breaches/discrimination, while Argument J focuses on the regulatory and ethical f …",
  "judge_provider": "vertex",
  "judge_model": "gemini-3-flash-preview",
  "judge_effort": "minimal",
  "prompt_version": "main_argument_judge_v8_4label"
}
```

### `grounding_pairs.jsonl.gz`: Diagonal (human, position-guided) grounding pair

```json
{
  "venue": "nyt",
  "debate_id": "23andme-and-the-promise-of-anonymous-genetic-testing-10",
  "essay_i": "somalee-datta",
  "essay_j": "openrouter-api__anthropic-claude-opus-4.7__medium__position-guided__somalee-datta__20260521T190106865535Z",
  "kind_i": "human",
  "kind_j": "position-guided",
  "model_i": null,
  "model_j": "claude",
  "relation": "equivalent",
  "rationale": "Both arguments take the same central position that companies should share genetic data for research, and both rely on the same core justification: that the tension between privacy and progress is a false dichotomy that can be resolved throu …",
  "judge_provider": "vertex",
  "judge_model": "gemini-3-flash-preview",
  "judge_effort": "minimal",
  "prompt_version": "main_argument_judge_v8_4label"
}
```

### `structure_argument.jsonl.gz`: Per-paragraph argument-role labels

```json
{
  "venue": "nyt",
  "debate_id": "23andme-and-the-promise-of-anonymous-genetic-testing-10",
  "essay_id": "frank-pasquale",
  "layer": "argument",
  "annotations": [
    {
      "paragraph_index": 0,
      "labels": [
        "thesis"
      ],
      "rationale": "The paragraph introduces the central position of the essay: while data selling has benefits, it creates significant vulnerabilities for users and their families."
    },
    {
      "paragraph_index": 1,
      "labels": [
        "support"
      ],
      "rationale": "The author provides evidence and reasoning regarding the frequency of data breaches to support the claim that sharing genetic information endangers security."
    },
    {
      "paragraph_index": 2,
      "labels": [
        "implication"
      ],
      "rationale": "This paragraph draws out the consequences and stakes for individuals whose data is breached, specifically the risk of long-term discrimination and worry."
    },
    {
      "paragraph_index": 3,
      "labels": [
        "concession",
        "proposal"
      ],
      "rationale": "The paragraph acknowledges the industry's view that risks are speculative before pivoting to a specific recommendation for insurance-based compensation."
    },
    {
      "paragraph_index": 4,
      "labels": [
        "proposal"
      ],
      "rationale": "The author offers an alternative specific course of action (revenue set-asides) and concludes with a call for companies to share risks equitably."
    }
  ],
  "judge_provider": "vertex",
  "judge_model": "gemini-3-flash-preview",
  "prompt_filename": "PROMPT_ARGUMENT.md",
  "prompt_sha": "8cf612db52466e666d2a1763d5e37ef62219c8742dbfd0518948c217e3107419"
}
```

### `structure_discourse_mode.jsonl.gz`: Per-paragraph discourse-mode labels

```json
{
  "venue": "nyt",
  "debate_id": "23andme-and-the-promise-of-anonymous-genetic-testing-10",
  "essay_id": "frank-pasquale",
  "layer": "discourse_mode",
  "annotations": [
    {
      "paragraph_index": 0,
      "label": "argumentation",
      "rationale": "The paragraph uses a 'may/but' structure to weigh competing outcomes and establish a cautionary claim about the potential risks of data sales."
    },
    {
      "paragraph_index": 1,
      "label": "exposition",
      "rationale": "This paragraph provides factual background information and statistics regarding medical data breaches and existing black markets to illustrate the current state of data security."
    },
    {
      "paragraph_index": 2,
      "label": "argumentation",
      "rationale": "The paragraph draws a contrast between temporary corporate reputation damage and long-term individual harm, concluding with an evaluative claim about the irony of altruistic donation leading to discrimination."
    },
    {
      "paragraph_index": 3,
      "label": "argumentation",
      "rationale": "The author presents a conditional logic/thought experiment (if/then) to argue for insurance mandates, using a specific financial scenario to derive a conclusion about security measures."
    },
    {
      "paragraph_index": 4,
      "label": "argumentation",
      "rationale": "This paragraph makes a direct prescriptive claim (normative argument) about how companies 'should' behave and concludes with a moral justification for equitable risk-sharing."
    }
  ],
  "judge_provider": "vertex",
  "judge_model": "gemini-3-flash-preview",
  "prompt_filename": "PROMPT_DISCOURSE_MODE.md",
  "prompt_sha": "e07d3e3747ba83a5676aa04b60c97d2f334b9c0e35e3255bca441651cfca20f5"
}
```

## BR  (`data/br/`)

### `debates.jsonl.gz`: Per-debate metadata

```json
{
  "venue": "br",
  "debate_id": "forum_africas_turn",
  "title": "Africa’s Turn — Forum Response",
  "date": "2008-05-01T20:21:00+00:00",
  "source": "boston_review_forum",
  "source_url": null,
  "topic": "economy",
  "question_type": null,
  "sensitivity": null,
  "question_text": null,
  "lead_essay_text": "# Is It Africa’s Turn?\n\nThings were certainly looking up when I last visited Busia, a small city in Kenya, in mid-2007. Busia, home to about 60,000 residents, spans Kenya’s western border with Uganda: half the town sits on the Kenyan side and half in Uganda. As befits a border town, Busia is well endowed with gas stations, seedy bars, and hotels catering to the truckers who spend the night on the …",
  "lead_essay_authors": [
    "Paul Collier"
  ],
  "lead_essay_word_count": 536,
  "n_humans": 8,
  "n_vanilla": 40,
  "n_diversified": 40,
  "n_position_guided": 40
}
```

### `human_essays.jsonl.gz`: Human responder essay index (no body)

```json
{
  "venue": "br",
  "debate_id": "forum_africas_turn",
  "essay_id": "elections-themselves-need-not-force-leaders-serve-public-good",
  "title": "Africa’s Turn — Forum Response",
  "authors": [
    "Smita Singh"
  ],
  "role_description": null,
  "author_bio": null,
  "date": "2008-05-01T20:20:00+00:00",
  "word_count": 908,
  "source": "boston_review_forum",
  "source_url": null,
  "body_text": null
}
```

### `llm_essays.jsonl.gz`: LLM-generated essay (full text; truncated here for display)

```json
{
  "venue": "br",
  "debate_id": "forum_africas_turn",
  "essay_id": "openai-api__gpt-5.5__medium__diversified__essay-01__20260519T190312470947Z",
  "kind": "diversified",
  "condition": "diversified",
  "model_short": "gpt",
  "provider_api": "openai-api",
  "model_family": "gpt-5.5",
  "effort": "medium",
  "position_source_id": "essay-01",
  "is_representative": null,
  "generated_at_utc": "20260519T190312470947Z",
  "word_count": 1045,
  "body_text": "Edward Miguel is right to resist both Afro-pessimism and development triumphalism. The most compelling feature of his essay is not the claim that Africa is “turning,” but the insistence that the turn, if real, remains politically fragile. The image of Busia’s paved road is therefore apt: a road is a development achievement, but also a reminder that prosperity depends on public order, state capacit …"
}
```

### `position_guides.jsonl.gz`: Position-guidance descriptor

```json
{
  "venue": "br",
  "debate_id": "forum_africas_turn",
  "position_source_id": "elections-themselves-need-not-force-leaders-serve-public-good",
  "name": "Smita Singh",
  "role": "Policy researcher and development specialist focused on governance and public accountability.",
  "tone": "Formal, analytical, and earnest. The writing utilizes a third-person perspective with occasional first-person plural to address a professional or academic community. The register is sober and measured …",
  "word_count": 908,
  "schema_version": 2,
  "position_prompt_version": "cross_venue_position_guide_v2_lean"
}
```

### `toulmin.jsonl.gz`: Toulmin extraction

```json
{
  "venue": "br",
  "debate_id": "forum_africas_turn",
  "essay_id": "we-might-ask-whether-africas-new-democracies-are-democracies-all",
  "kind": "human",
  "model_short": null,
  "main_argument": "While Africa has seen recent economic growth, it is likely driven by external factors like commodity prices rather than democratization, which remains fragile and institutionally weak across the continent.",
  "sub_arguments": [
    "Social scientists have failed to find robust, consistent evidence that democratic reforms directly cause economic dividends in Africa.",
    "Many African nations are 'pseudo-democracies' or 'hybrid regimes' where elections are held to appease donors without a true leveling of the political playing field.",
    "The lack of peaceful transfers of power between parties in Africa's top economic performers suggests that growth is occurring independently of democratic maturity.",
    "In ethnically diverse societies, democratic competition can devolve into ethnic headcounts and conflict, which can actually destabilize the economy.",
    "Unconditional Chinese aid and rising commodity prices may be providing short-term growth while undermining the incentives for leaders to implement necessary democratic reforms.",
    "Sustained development will only occur when transparency mechanisms, such as independent media and community monitoring, allow voters to hold politicians accountable for their performance."
  ],
  "annotator_provider": "vertex",
  "annotator_model": "gemini-3-flash-preview",
  "annotator_effort": "minimal",
  "prompt_version": "toulmin_annotation_v2_question_aware_lead"
}
```

### `main_argument_pairs.jsonl.gz`: Pairwise 4-label main-argument judgment

```json
{
  "venue": "br",
  "debate_id": "forum_africas_turn",
  "essay_i": "elections-themselves-need-not-force-leaders-serve-public-good",
  "essay_j": "foreign-aid-can-strengthen-governments",
  "kind_i": "human",
  "kind_j": "human",
  "model_i": null,
  "model_j": null,
  "relation": "different",
  "rationale": "The two arguments take disjoint angles on the lead essay: Argument I focuses on the internal requirements for progress (robust accountability and climate adaptation), while Argument J focuses on critiquing the lead essay's analysis of exter …",
  "judge_provider": "vertex",
  "judge_model": "gemini-3-flash-preview",
  "judge_effort": "minimal",
  "prompt_version": "main_argument_judge_v8_4label_lead"
}
```

### `grounding_pairs.jsonl.gz`: Diagonal (human, position-guided) grounding pair

```json
{
  "venue": "br",
  "debate_id": "forum_africas_turn",
  "essay_i": "there-simple-process-work-africa-learning-its-mistakes",
  "essay_j": "openrouter-api__minimax-minimax-m2.7__medium__position-guided__there-simple-process-work-africa-learning-its-mistakes__20260521T223107472870Z",
  "kind_i": "human",
  "kind_j": "position-guided",
  "model_i": null,
  "model_j": "minimax",
  "relation": "equivalent",
  "rationale": "Both arguments make the exact same claim: that Africa's economic progress is driven by institutional knowledge and policy learning from past failures, specifically contrasting this against democratization as the primary driver.",
  "judge_provider": "vertex",
  "judge_model": "gemini-3-flash-preview",
  "judge_effort": "minimal",
  "prompt_version": "main_argument_judge_v8_4label_lead"
}
```

### `structure_argument.jsonl.gz`: Per-paragraph argument-role labels

```json
{
  "venue": "br",
  "debate_id": "forum_africas_turn",
  "essay_id": "elections-themselves-need-not-force-leaders-serve-public-good",
  "layer": "argument",
  "annotations": [
    {
      "paragraph_index": 0,
      "labels": [
        "none"
      ],
      "rationale": "Title/header text with no argumentative content."
    },
    {
      "paragraph_index": 1,
      "labels": [
        "none"
      ],
      "rationale": "Introductory roadmap paragraph that identifies the subjects to be discussed without yet taking a stance or presenting an argument."
    },
    {
      "paragraph_index": 2,
      "labels": [
        "concession",
        "rebuttal"
      ],
      "rationale": "Acknowledges Miguel's point about democratization but then challenges the sufficiency of elections, arguing they can lead to patronage instead of growth."
    },
    {
      "paragraph_index": 3,
      "labels": [
        "thesis"
      ],
      "rationale": "Establishes the author's central position: that Africa's economic success depends on transparency and accountability mechanisms to provide checks and balances."
    },
    {
      "paragraph_index": 4,
      "labels": [
        "support"
      ],
      "rationale": "Develops the author's case by explaining why public spending and resource allocation incentives are critical for the average citizen."
    },
    {
      "paragraph_index": 5,
      "labels": [
        "support"
      ],
      "rationale": "Provides further affirmative evidence by identifying specific watchdog functions and offering an example from India to support the utility of these mechanisms."
    },
    {
      "paragraph_index": 6,
      "labels": [
        "concession",
        "proposal"
      ],
      "rationale": "Admits that accountability is harder to implement than elections, then calls for increased investment in learning which mechanisms work best."
    },
    {
      "paragraph_index": 7,
      "labels": [
        "implication"
      ],
      "rationale": "Draws out the stakes, arguing that the outcome of the current commodity boom depends on whether these checks and balances are established."
    },
    {
      "paragraph_index": 8,
      "labels": [
        "support"
      ],
      "rationale": "Introduces the second theme (climate change) and affirms Miguel's point about the vulnerability of African countries to strengthen the context of the argument."
    },
    {
      "paragraph_index": 9,
      "labels": [
        "support"
      ],
      "rationale": "Uses evidence from the IPCC and Miguel to establish the necessity of adaptation measures."
    },
    {
      "paragraph_index": 10,
      "labels": [
        "reframing"
      ],
      "rationale": "Shifts the focus from specific technical tools (insurance/research) to a broader lens: the debate over climate adaptation is actually about equitable economic growth and resource access."
    },
    {
      "paragraph_index": 11,
      "labels": [
        "implication"
      ],
      "rationale": "Spells out the consequences of failing to understand the link between development and adaptation, warning that financing for one might wrongly displace the other."
    },
    {
      "paragraph_index": 12,
      "labels": [
        "proposal",
        "implication"
      ],
      "rationale": "Calls for a simultaneous policy approach to poverty and climate change, then concludes by projecting the negative consequences of failing to account for development in climate policy."
    }
  ],
  "judge_provider": "vertex",
  "judge_model": "gemini-3-flash-preview",
  "prompt_filename": "PROMPT_ARGUMENT.md",
  "prompt_sha": "8cf612db52466e666d2a1763d5e37ef62219c8742dbfd0518948c217e3107419"
}
```

### `structure_discourse_mode.jsonl.gz`: Per-paragraph discourse-mode labels

```json
{
  "venue": "br",
  "debate_id": "forum_africas_turn",
  "essay_id": "elections-themselves-need-not-force-leaders-serve-public-good",
  "layer": "discourse_mode",
  "annotations": [
    {
      "paragraph_index": 0,
      "label": "exposition",
      "rationale": "This is a title/header identifying the subject of the text."
    },
    {
      "paragraph_index": 1,
      "label": "exposition",
      "rationale": "The paragraph summarizes Miguel's points and identifies the two specific topics the author intends to elaborate on without yet making an argumentative claim."
    },
    {
      "paragraph_index": 2,
      "label": "argumentation",
      "rationale": "The author takes a position on the limitations of democratization, arguing that elections alone are insufficient and can lead to patronage rather than public good."
    },
    {
      "paragraph_index": 3,
      "label": "argumentation",
      "rationale": "The paragraph uses a rhetorical question-and-answer structure to arrive at a specific claim: that transparency and accountability mechanisms are the necessary solution."
    },
    {
      "paragraph_index": 4,
      "label": "argumentation",
      "rationale": "The paragraph evaluates the importance of public spending and makes a claim about the necessity of creating incentives for efficient allocation."
    },
    {
      "paragraph_index": 5,
      "label": "exposition",
      "rationale": "The paragraph describes the functions of watchdog organizations and provides a factual example of a cost survey in India to illustrate the point."
    },
    {
      "paragraph_index": 6,
      "label": "argumentation",
      "rationale": "The author concludes that more investment in learning about accountability mechanisms is necessary, based on a contrast between donor history and current research needs."
    },
    {
      "paragraph_index": 7,
      "label": "argumentation",
      "rationale": "The paragraph makes a predictive claim that Africa's economic future depends on the checks and balances established to manage revenues."
    },
    {
      "paragraph_index": 8,
      "label": "argumentation",
      "rationale": "The paragraph makes an evaluative judgment about the irony of climate change and labels developing countries as the most vulnerable."
    },
    {
      "paragraph_index": 9,
      "label": "exposition",
      "rationale": "This paragraph reports on the findings of the IPCC report and Miguel's specific suggestions for adaptation."
    },
    {
      "paragraph_index": 10,
      "label": "argumentation",
      "rationale": "The author uses a 'therefore' structure to argue that equitable economic growth is a prerequisite for climate change adaptation."
    },
    {
      "paragraph_index": 11,
      "label": "argumentation",
      "rationale": "The paragraph warns against a potential policy mistake and argues for the necessity of understanding the complementarity between development and adaptation."
    },
    {
      "paragraph_index": 12,
      "label": "argumentation",
      "rationale": "The paragraph draws a final conclusion that policy solutions must consider development consequences to avoid harming the poor, using the biofuels example as evidence for this stance."
    }
  ],
  "judge_provider": "vertex",
  "judge_model": "gemini-3-flash-preview",
  "prompt_filename": "PROMPT_DISCOURSE_MODE.md",
  "prompt_sha": "e07d3e3747ba83a5676aa04b60c97d2f334b9c0e35e3255bca441651cfca20f5"
}
```

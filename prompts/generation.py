from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def parse_frontmatter(path: Path) -> dict[str, str]:
    """Read YAML-ish frontmatter (between leading `---` markers) from a
    Markdown file and return it as a flat string-keyed dict. Returns an
    empty dict if the file doesn't exist or has no frontmatter.
    Inlined here so this module is self-contained for the release."""
    if not path.exists():
        return {}
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fm[key.strip()] = value.strip()
    return fm


STANCES = {
    "strong_agree": "Strongly agree with the source prompt's central claim or framing.",
    "mostly_agree": "Mostly agree with the source prompt, while acknowledging limited reservations.",
    "mixed": (
        "Take a mixed stance: agree with some central parts and disagree with others, "
        "or reframe the issue without clearly landing in agreement or disagreement."
    ),
    "mostly_disagree": "Mostly disagree with the source prompt, while acknowledging limited agreement.",
    "strong_disagree": "Strongly disagree with the source prompt's central claim or framing.",
}


@dataclass(frozen=True)
class RenderedGenerationPrompt:
    system_prompt: str
    agent_user_prompt: str
    direct_user_prompt: str
    combined_agent_prompt: str
    source_label: str
    source_title: str
    length_clause: str
    evidence_cutoff: str
    condition_block: str


def _day_level_date(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return value


def source_label(prompt_kind: str) -> str:
    return "lead essay" if prompt_kind == "lead" else "debate question"


def system_prompt(condition: str, prompt_kind: str, target_words: int) -> str:
    label = source_label(prompt_kind)
    if condition == "v0":
        return f"You're writing a public argument in response to a {label}."

    # Conditions ending in "a" (v1a, v15a, v25a, v3a, v4a) are ablation variants —
    # the only system-prompt difference is that they drop the "Have a clear thesis"
    # bullet, to test whether structural homogeneity in the outputs comes from
    # that prescription or is a deeper model default. v4a is a v3a variant
    # (writer-guided) grounded on the human's toulmin main_argument instead of
    # thesis_1line.
    is_ablation = condition.endswith("a")

    # v25/v3 (and ablations) inject a position-source-specific word count via the user
    # prompt's length_clause, so suppress the venue-mean bullet here. v1a
    # likewise uses a position-source-specific length when one is supplied (the
    # length-matched v1a variant), so suppress for v1a too — length_clause
    # will inject the right value.
    word_bullet = (
        "" if condition in {"v25", "v3", "v25a", "v3a", "v4a", "v1a", "v15a"}
        else f"- Be around {target_words} words\n"
    )
    thesis_bullet = "" if is_ablation else "- Have a clear thesis\n"
    return (
        f"You are writing a public-facing response essay to a {label}. "
        "The source prompt sets up a contested issue and human commentators "
        "write response essays.\n\n"
        "Your response should:\n"
        f"{thesis_bullet}"
        "- Directly engage the source prompt's specific issue\n"
        "- Be grounded in evidence and reasoning\n"
        f"{word_bullet}"
        "- Not use external web search; work only from the source prompt and your own knowledge"
    )


def evidence_cutoff_clause(prompt_path: Path, prompt_kind: str) -> str:
    meta = parse_frontmatter(prompt_path)
    published = _day_level_date(meta.get("date", ""))
    label = source_label(prompt_kind)
    when = published or f"the day the {label} was published"
    return (
        f"Imagine you're writing on {when}. You know everything a thoughtful, "
        "well-informed person would have known by that date — events, debates, "
        "data, scholarship up to that moment. What you don't have is the benefit "
        "of hindsight: don't argue from how things turned out later or cite "
        "sources that hadn't been published yet."
    )


def length_clause(condition: str, target_words: int, position_guide: dict[str, Any] | None = None) -> str:
    # v1a uses position-source length when supplied (length-matched ablation variant);
    # otherwise falls back to the venue-mean target_words.
    if condition in {"v25", "v3", "v25a", "v3a", "v4a", "v1a"} and position_guide:
        try:
            wc = int(position_guide.get("word_count") or 0)
        except (TypeError, ValueError):
            wc = 0
        if wc > 0:
            return f"around {wc} words"
    return f"around {target_words} words"


def thesis_conditioned_block(position_guide: dict[str, Any]) -> str:
    thesis = str(position_guide.get("thesis_1line", "")).strip()
    if not thesis:
        raise ValueError("selected position guide is missing thesis_1line")
    return (
        "Your task is THESIS-CONDITIONED RESPONSE.\n\n"
        "## Target thesis\n"
        f"- Defend and develop this thesis: {thesis}\n\n"
        "## Instructions\n"
        "- Build an original argument that clearly advances this thesis.\n"
        "- Do not imitate the original author's voice or biography."
    )


def thesis_conditioned_block_ablation(position_guide: dict[str, Any]) -> str:
    """v25a — strips the prescriptive language: drops 'Defend and develop',
    drops 'Build an original argument that clearly advances this thesis',
    and drops the vestigial 'Do not imitate the original author' instruction
    (v25 doesn't pass the author's name/voice/profile to the model anyway)."""
    thesis = str(position_guide.get("thesis_1line", "")).strip()
    if not thesis:
        raise ValueError("selected position guide is missing thesis_1line")
    return (
        "Your task is THESIS-CONDITIONED RESPONSE.\n\n"
        "## Central claim\n"
        f"- {thesis}"
    )


def _writer_guided_block_body(
    position_guide: dict[str, Any], *, claim_label: str, claim_text: str | None = None
) -> str:
    """Shared body for v3, v3a, and v4a. v3/v3a ground the central claim on the
    position guide's `thesis_1line`; v4a passes `claim_text` = the human's toulmin
    `main_argument`. The other difference (v3 vs v3a) is the claim bullet label
    (`Main argument…` vs `Central claim`)."""
    claim = (claim_text if claim_text is not None
             else str(position_guide.get("thesis_1line", ""))).strip()
    if not claim:
        raise ValueError("selected position guide is missing a central claim "
                         "(thesis_1line for v3/v3a, main_argument for v4a)")

    bullets: list[str] = []
    name = str(position_guide.get("name") or position_guide.get("slug") or "").strip()
    if name:
        bullets.append(f"- Name: {name}")
    role = str(position_guide.get("role") or "").strip()
    if role:
        bullets.append(f"- Bio / role: {role}")
    stance = str(position_guide.get("stance") or "").strip()
    if stance:
        bullets.append(f"- Stance toward the source prompt: {stance}")
    bullets.append(f"- {claim_label}: {claim}")
    voice = str(position_guide.get("voice_abstract") or "").strip()
    if voice:
        bullets.append(f"- Voice: {voice}")
    moves = [str(m).strip() for m in (position_guide.get("signature_moves_abstract") or []) if str(m).strip()]
    if moves:
        moves_block = "\n".join(f"  - {m}" for m in moves)
        bullets.append(f"- Signature moves:\n{moves_block}")
    perspective = str(position_guide.get("perspective_abstract") or "").strip()
    if perspective:
        bullets.append(f"- Perspective: {perspective}")

    return (
        "Your task is WRITER-GUIDED RESPONSE SIMULATION. Write as the following "
        "writer would write — matching their voice, evidence preferences, "
        "and rhetorical habits — not as yourself.\n\n"
        "## The writer\n"
        + "\n".join(bullets) + "\n\n"
        "## Instructions\n"
        "- Imitate the writer's voice: register, sentence rhythm, and "
        "point-of-view should feel like theirs.\n"
        "- Let your evidence choices and emphases reflect this perspective. "
        "Do not invent kinship, quotes, statistics, or named people that "
        "you cannot recall with confidence — stay silent or abstract rather than fabricate."
    )


def writer_guided_block(position_guide: dict[str, Any], prompt_kind: str) -> str:
    return _writer_guided_block_body(
        position_guide,
        claim_label="Main argument (write the essay that makes this claim)",
    )


def writer_guided_block_ablation(position_guide: dict[str, Any], prompt_kind: str) -> str:
    """v3a — same as v3 except the central-claim bullet drops the
    prescriptive '(write the essay that makes this claim)' parenthetical."""
    return _writer_guided_block_body(position_guide, claim_label="Central claim")


def position_guided_block_main_arg(position_guide: dict[str, Any], prompt_kind: str) -> str:
    """v4a — anonymized, de-leaked position-guide block. Uses ONLY an anonymized
    background (role), tone (pure register), and the central claim (the human's
    toulmin `main_argument`, attached as position_guide['main_argument'] by the driver).

    Deliberately omits: the author's NAME (to avoid the model recalling the real
    person and reproducing their actual published arguments — NYT essays are old,
    public, likely-in-training text), and the v3a block's stance / voice /
    signature_moves / perspective (which leaked the human's sub-arguments). Reads
    the lean position-guide schema in position_guides.json (role is already anonymized)."""
    main_arg = str(position_guide.get("main_argument", "")).strip()
    if not main_arg:
        raise ValueError(
            "v4a requires the human's toulmin main_argument on position_guide['main_argument']")

    bullets: list[str] = []
    role = str(position_guide.get("role") or "").strip()
    if role:
        bullets.append(f"- Background: {role}")
    bullets.append(f"- Central claim: {main_arg}")
    tone = str(position_guide.get("tone") or "").strip()
    if tone:
        bullets.append(f"- Tone: {tone}")

    return (
        "Your task is POSITION-GUIDED RESPONSE GENERATION: write a response essay from the "
        "position profiled below.\n\n"
        "## The position guide\n"
        + "\n".join(bullets) + "\n\n"
        "## Instructions\n"
        "- The central claim above is the main argument you should stay faithful to when writing your response. Don't shift to a "
        "different position or thesis.\n"
        "- Match the background and tone described above.\n"
    )


def condition_block(
    condition: str,
    *,
    prompt_kind: str,
    position_guide: dict[str, Any] | None = None,
    stance: str = "",
) -> str:
    if condition in {"v0", "v1", "v1a"}:
        return ""
    if condition == "v15a":
        return (
            "Your task is DELIBERATELY DIVERSE RESPONSE SET GENERATION.\n\n"
            "## Diversity goal\n"
            "- Produce a VERY DIVERSE set of response essays. Think of the range of responses a group of human writers would produce on this question — real commentators on contested issues can disagree, sometimes sharply, and your essays should reflect a diverse spread of positions and frames.\n"
            "- Vary the stance, central claim, supporting arguments, as well as argumentative flow and discourse moves as much as possible.\n"
        )
    if condition == "v2":
        if not stance or stance not in STANCES:
            raise ValueError(f"v2 requires a valid stance: {sorted(STANCES)}")
        return (
            "Your assigned stance for this response is:\n\n"
            f"**{STANCES[stance]}**\n\nDefend this stance."
        )
    if condition == "v25":
        if not position_guide:
            raise ValueError("v25 requires position-guide data")
        return thesis_conditioned_block(position_guide)
    if condition == "v25a":
        if not position_guide:
            raise ValueError("v25a requires position-guide data")
        return thesis_conditioned_block_ablation(position_guide)
    if condition == "v3":
        if not position_guide:
            raise ValueError("v3 requires position-guide data")
        return writer_guided_block(position_guide, prompt_kind)
    if condition == "v3a":
        if not position_guide:
            raise ValueError("v3a requires position-guide data")
        return writer_guided_block_ablation(position_guide, prompt_kind)
    if condition == "v4a":
        if not position_guide:
            raise ValueError("v4a requires position-guide data")
        return position_guided_block_main_arg(position_guide, prompt_kind)
    raise ValueError(f"unknown condition: {condition}")


def render_generation_prompt(
    *,
    condition: str,
    prompt_kind: str,
    prompt_path: Path,
    source_text: str,
    agent_source_path: Path,
    agent_output_path: Path,
    target_words: int,
    position_guide: dict[str, Any] | None = None,
    stance: str = "",
    multi_essay_count: int = 1,
    word_range: tuple[int, int, int] | None = None,
) -> RenderedGenerationPrompt:
    label = source_label(prompt_kind)
    title = parse_frontmatter(prompt_path).get("title", "")
    length = length_clause(condition, target_words, position_guide)
    evidence = evidence_cutoff_clause(prompt_path, prompt_kind)
    block = condition_block(condition, prompt_kind=prompt_kind, position_guide=position_guide, stance=stance)
    system = system_prompt(condition, prompt_kind, target_words)
    # For v15a, prefer asking for essays spread across the cohort's
    # human-response length range; fall back to "around X words each"
    # (venue mean) if the range isn't available.
    if condition == "v15a" and word_range:
        low, median, high = word_range
        length_inline = (
            f"with lengths varying between {low} and {high} words — "
            f"typical responses run around {median} words"
        )
        v15a_reminder = (
            f"Reminder: return exactly {multi_essay_count} essays, each preceded by its "
            f"`===== ESSAY N =====` marker, with lengths spread across the {low}–{high} "
            f"word range, centered around {median} words."
        )
    else:
        length_inline = f"{length} each"
        v15a_reminder = (
            f"Reminder: return exactly {multi_essay_count} essays, each preceded by its "
            f"`===== ESSAY N =====` marker, each {length}."
        )
    if condition == "v15a":
        output_contract_example = (
            "Use this exact format, with one separator line before each essay:\n\n"
            "===== ESSAY 1 =====\n\n"
            "[full text of the first essay, with normal paragraph breaks]\n\n"
            "===== ESSAY 2 =====\n\n"
            "[full text of the second essay]\n\n"
            "===== ESSAY 3 =====\n\n"
            "[full text of the third essay]\n\n"
            "...and so on for all essays. The separator line must be exactly "
            '`===== ESSAY N =====` where N is the essay number starting from 1.'
        )
        output_contract_agent = (
            "The output file should contain only the essays, separated by markers. "
            "Do not add YAML frontmatter, code fences, meta commentary, or any text "
            "outside the essay bodies and their separator markers.\n\n"
            + output_contract_example
        )
        output_contract_direct = (
            "Return only the essays, separated by markers. Do not add YAML frontmatter, "
            "code fences, meta commentary, or any text outside the essay bodies and their "
            "separator markers.\n\n"
            + output_contract_example
        )
        parts_agent = [
            (
                f"Read the {label} at {agent_source_path} and write {multi_essay_count} "
                f"different response essays ({length_inline}) to {agent_output_path}."
            ),
            output_contract_agent,
            evidence,
        ]
        parts_direct = [
            f"Read the {label} below and write {multi_essay_count} different response essays ({length_inline}).",
            output_contract_direct,
            evidence,
        ]
    else:
        output_contract_agent = (
            "The output file should contain only the essay body — no YAML frontmatter, "
            "no meta commentary, no headers like 'Response:', and no restatement of "
            "the prompt as a title. Preserve paragraph breaks."
        )
        output_contract_direct = (
            "Return only the essay body — no YAML frontmatter, no meta commentary, "
            "no title, no label, and no restatement of the prompt as a title. "
            "Preserve paragraph breaks."
        )
        parts_agent = [
            f"Read the {label} at {agent_source_path} and write a response essay ({length}) to {agent_output_path}.",
            output_contract_agent,
            evidence,
        ]
        parts_direct = [
            f"Read the {label} below and write a response essay ({length}).",
            output_contract_direct,
            evidence,
        ]

    if block:
        parts_agent.append(block)
        parts_direct.append(block)

    direct = (
        "\n\n".join(parts_direct)
        + f"\n\n## {label.title()}\n"
        "```markdown\n"
        f"{source_text.strip()}\n"
        "```"
        + (
            f"\n\n{v15a_reminder}"
            if condition == "v15a"
            else f"\n\nReminder: your response should be {length}."
        )
    )
    agent = "\n\n".join(parts_agent)
    return RenderedGenerationPrompt(
        system_prompt=system,
        agent_user_prompt=agent,
        direct_user_prompt=direct,
        combined_agent_prompt=system + "\n\n" + agent,
        source_label=label,
        source_title=title,
        length_clause=length,
        evidence_cutoff=evidence,
        condition_block=block,
    )

"""Render an immutable, question-routed OfficeQA experience bank as one Skill.

Routing uses lexical question features only. Task identifiers, labels, source
filenames, rewards and evaluation answers are never routing inputs. The seed bank
is development-diagnosed design; later banks may contain Train-derived cards.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SKILL_NAME = "officeqa-evidence-contract"
FRONTMATTER = (
    "---\n"
    f"name: {SKILL_NAME}\n"
    "description: Answer Treasury document questions with checked evidence, explicit operations, and a precise output schema.\n"
    "---\n\n"
)

CONTRACT_INSTRUCTIONS = r'''## Executable evidence contract

For common numeric operations or an expression within the checker's whitelist,
create `/work/contract.json` with the requested operation and named operands, then
run:

```sh
python /skill-runtime/contract.py /work/contract.json
```

Each operand must carry `label`, numeric `value`, `unit`, `period`, `source`, and
`quote`. Copy the relevant source row, including the period and column heading
when necessary, from the Oracle pages or local candidate document. Check it
against the original evidence yourself. The checker can check numeric anchors
and perform the requested arithmetic; it cannot establish that a supplied quote
is authentic, that a column is the intended measure, or that the selected
formula answers the question. A passing check is not proof of those facts.

Illustrative, fictional sum of two counts (not OfficeQA evidence):

```json
{
  "operation": "sum",
  "operands": [
    {"label": "a", "value": 3, "unit": "count", "period": "period A", "source": "fictional example", "quote": "period A: 3 items"},
    {"label": "b", "value": 5, "unit": "count", "period": "period B", "source": "fictional example", "quote": "period B: 5 items"}
  ],
  "precision": 0
}
```

The interface also accepts `expression`, `percentile_p`, and
`percentile_method` when relevant to the supported operation. Use named labels
in an expression and distinguish Hazen, linear interpolation, and nearest-rank
percentiles explicitly. Consult `python /skill-runtime/contract.py --help` for
supported operations, permitted functions, and field conventions. Use only the
operations and expression functions listed there.

For a custom statistic, an unsupported operation, or a mathematical function
outside the `--help` whitelist, use a native Python executable program instead.
Keep the same explicit operand ledger with each label, value, source, quote,
unit, and period, and write the actual formula into that program. Execute it and
inspect its output. This fallback applies to every complex formula in the
routed experience cards; do not repeatedly retry an unsupported checker
operation or pretend an arbitrary formula is supported.

Keep the answer in the units and scale requested by the question. If a supported
check fails, correct the operand evidence or operation, rerun the contract, and
inspect the result. Copy only the checked value requested by the task into the
final answer. A checker `final_answer` may be copied only after confirming that
its shape, operand order, units, scaling, and precision match the question. Do
not include intermediate results or a ledger in the final wrapper. Never invent
an anchor or change a sound formula solely to obtain a preferred number.
'''


def _tokens(text: str) -> tuple[str, ...]:
    """Alphabetic Unicode tokens: dates and numerical task IDs are not features."""
    return tuple(re.findall(r"[^\W\d_]+", text.casefold(), flags=re.UNICODE))


def _trigger_score(question_tokens: tuple[str, ...], triggers: list[str]) -> int:
    # Compare contiguous token sequences, so punctuation/case do not change a
    # phrase match and "rate" cannot spuriously match "corporate".
    seen: set[tuple[str, ...]] = set()
    for trigger in triggers:
        if trigger == "*":
            continue
        tokens = _tokens(trigger)
        if not tokens or tokens in seen:
            continue
        if any(question_tokens[i:i + len(tokens)] == tokens
               for i in range(len(question_tokens) - len(tokens) + 1)):
            seen.add(tokens)
    return len(seen)


def _frontmatter(markdown: str) -> str:
    # The entrypoint enables one canonical Skill. Normalize only the top-level
    # name of a direct Markdown reference, retaining its other metadata/body.
    match = re.match(
        r"\A(?P<opening>\ufeff?---\r?\n)(?P<yaml>[\s\S]*?)"
        r"(?P<closing>^---[ \t]*(?:\r?\n|\Z))",
        markdown, flags=re.MULTILINE,
    )
    if match is None:
        return FRONTMATTER + markdown
    newline = "\r\n" if match["opening"].endswith("\r\n") else "\n"
    lines = match["yaml"].splitlines(keepends=True)
    output: list[str] = []
    found = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.match(r"^(?:name|\"name\"|'name')\s*:", line):
            if not found:
                output.append(f"name: {SKILL_NAME}{newline}")
                found = True
            name_value = line.split(":", 1)[1].strip()
            index += 1
            # A YAML name can use an indented or block scalar. Remove its value
            # continuation too, without consuming the next top-level field.
            if not name_value or name_value.startswith(("|", ">")):
                while index < len(lines) and (
                    lines[index].startswith((" ", "\t")) or not lines[index].strip()
                ):
                    index += 1
            continue
        output.append(line)
        index += 1
    if not found:
        output.insert(0, f"name: {SKILL_NAME}{newline}")
    return (match["opening"] + "".join(output) + match["closing"] +
            markdown[match.end():])


def _validate_bank(bank: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(bank, dict):
        raise ValueError("Experience bank must be an object")
    if not isinstance(bank.get("version"), str) or not bank["version"].strip():
        raise ValueError("Bank requires a nonempty version")
    if not isinstance(bank.get("base_skill"), str) or not bank["base_skill"].strip():
        raise ValueError("Bank requires the preserved SkillOpt base_skill")
    cards = bank.get("cards")
    if not isinstance(cards, list):
        raise ValueError("Bank cards must be a list")
    known: set[str] = set()
    for card in cards:
        if not isinstance(card, dict):
            raise ValueError("Each experience card must be an object")
        for field in ("id", "title", "body"):
            if not isinstance(card.get(field), str) or not card[field].strip():
                raise ValueError(f"Experience card requires a nonempty {field}")
        if card["id"] in known:
            raise ValueError(f"Duplicate card id: {card['id']}")
        known.add(card["id"])
        triggers = card.get("trigger")
        if not isinstance(triggers, list) or not triggers or any(
            not isinstance(t, str) or not t.strip() or
            (t != "*" and not _tokens(t)) for t in triggers
        ):
            raise ValueError(f"Card {card['id']} requires lexical trigger strings or '*'")
        if not isinstance(card.get("provenance"), list):
            raise ValueError(f"Card {card['id']} requires a provenance list")
    config = bank.get("config", {})
    if not isinstance(config, dict):
        raise ValueError("Bank config must be an object")
    if config.get("routing", "topk") not in {"all", "topk"}:
        raise ValueError("routing must be 'all' or 'topk'")
    topk = config.get("topk", 6)
    if isinstance(topk, bool) or not isinstance(topk, int) or topk < 0:
        raise ValueError("topk must be a nonnegative integer")
    if not isinstance(config.get("contract", True), bool):
        raise ValueError("contract must be a boolean")
    if not isinstance(config.get("progress", False), bool):
        raise ValueError("progress must be a boolean")
    return cards, config


def render_skill(bank_path: Path, question: str) -> tuple[str, dict[str, Any]]:
    """Return one Skill Markdown document plus reproducible routing metadata.

    A Markdown input is a direct reference Skill: its YAML name is normalized
    for entrypoint compatibility while other metadata is retained; absent YAML
    receives canonical metadata. JSON inputs are self-contained
    banks with their exact upstream base Skill and independently routed cards.
    """
    path = Path(bank_path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if not isinstance(question, str):
        raise TypeError("question must be a string")
    if path.suffix.casefold() == ".md":
        return _frontmatter(raw.decode("utf-8")), {
            "card_ids": [], "scores": {}, "bank_sha256": digest,
            "contract": False, "routing": "direct", "version": "markdown",
        }
    bank = json.loads(raw)
    cards, config = _validate_bank(bank)
    question_tokens = _tokens(question)
    scores = {c["id"]: _trigger_score(question_tokens, c["trigger"]) for c in cards}
    routing = config.get("routing", "topk")
    universal = [c for c in cards if "*" in c["trigger"]]
    if routing == "all":
        selected = cards
    else:
        candidates = [c for c in cards if "*" not in c["trigger"] and scores[c["id"]] > 0]
        # Stable input order breaks tied scores; output uses the same bank order
        # so a higher score does not unnecessarily reorder procedural steps.
        candidates.sort(key=lambda c: -scores[c["id"]])
        picked = {c["id"] for c in universal + candidates[:config.get("topk", 6)]}
        selected = [c for c in cards if c["id"] in picked]
    use_contract = config.get("contract", True)
    parts = [FRONTMATTER,
             "<!-- Base Skill preserved from SkillOpt/skillopt/envs/officeqa/skills/initial.md. -->\n",
             bank["base_skill"],
             "\n\n## Routed experience\n"]
    for card in selected:
        parts.append(f"\n### {card['title']}\n\n{card['body'].strip()}\n")
    if use_contract:
        parts.append("\n" + CONTRACT_INSTRUCTIONS)
    markdown = "".join(parts)
    metadata = {
        "card_ids": [c["id"] for c in selected],
        "scores": scores,
        "bank_sha256": digest,
        "contract": use_contract,
        "routing": routing,
        "version": bank["version"],
        "progress": config.get("progress", False),
    }
    return markdown, metadata

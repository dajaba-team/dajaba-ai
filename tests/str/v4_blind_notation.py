"""표기 사전의 코드만 치환하고, 이미 표기한 구절과 숫자는 보존한다."""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

from tests.str.v4_blind_notation_cleanup import attached_paren, paren_choice, particle_fix, tidy

if TYPE_CHECKING:
    from aml_ai.shared.schemas.str import Facts

LABEL_FIELDS = (
    "entity_type",
    "industry",
    "account_purpose",
    "risk_level",
    "payment_format",
    "typology",
    "currency",
)
CODE_WITH_LABEL = {"typology", "currency"}
UNKNOWN_CODE = r"[A-Z_]{3,}"
LEFT_BOUNDARY = r"(?<![A-Za-z0-9_])"
RIGHT_BOUNDARY = r"(?![A-Za-z0-9_])"
DIRECTION_LABELS = {
    "INBOUND": "입금",
    "OUTBOUND": "출금",
    "INTERNAL": "내부 거래",
    "MIXED": "입금·출금 혼합",
}
GENERIC_ITEM = "관측 항목"
KOREAN_PARTICLES = frozenset(
    (
        "은",
        "는",
        "이",
        "가",
        "을",
        "를",
        "의",
        "도",
        "만",
        "과",
        "와",
        "에",
        "에서",
        "으로",
        "로",
        "이며",
        "이고",
        "임",
        "이다",
    )
)


def _dictionary(labels: dict[str, dict[str, str]]) -> dict[str, str]:
    dictionary = {
        code: f"{label}({code})" if field in CODE_WITH_LABEL else label
        for field in LABEL_FIELDS
        for code, label in labels.get(field, {}).items()
    }
    for code, label in DIRECTION_LABELS.items():
        dictionary[code] = label
        for space in ("", " "):
            dictionary[f"{label}{space}({code})"] = label
    return dictionary


def _feature_labels(labels: dict[str, dict[str, str]], facts: Facts) -> dict[str, str]:
    """피처 이름 표기 — 사전 `observation_name`(실제 이름, SCRUM-264·265) → 관측값 basis 표기 → "관측 항목"."""
    basis_labels = labels.get("observation_basis", {})
    names = labels.get("observation_name", {})
    dictionary = {
        observation.name: names.get(observation.name)
        or (
            basis_labels.get(observation.basis, GENERIC_ITEM)
            if observation.basis is not None
            else GENERIC_ITEM
        )
        for observation in facts.observations
        if observation.name
    }
    for name in facts.model_signals:
        if name:
            dictionary.setdefault(name, names.get(name, GENERIC_ITEM))
    return dictionary


def _pattern(dictionary: dict[str, str]) -> re.Pattern[str]:
    """이미 표기한 구절을 먼저 보호하고 긴 원문부터 찾는다."""
    protected = [re.escape(label) for code, label in dictionary.items() if label.endswith(f"({code})")]
    codes = [re.escape(code) for code in sorted(dictionary, key=len, reverse=True)]
    return re.compile(
        "(?P<protected>"
        + "|".join(protected or [r"(?!)"])
        + ")|"
        + LEFT_BOUNDARY
        + "(?P<code>"
        + "|".join([*codes, UNKNOWN_CODE])
        + ")"
        + RIGHT_BOUNDARY
    )


def _replacement(
    match: re.Match[str],
    dictionary: dict[str, str],
    replaced: list[tuple[str, str]],
    unknown: list[str],
) -> str:
    """이미 표기된 구절을 보존하고 바꾼 원문과 미등록 코드를 기록한다."""
    if match.group("protected") is not None:
        return match.group()
    code = match.group("code")
    label = dictionary.get(code)
    if label is None:
        if code not in unknown:
            unknown.append(code)
        return code
    if label != code and (code, label) not in replaced:
        replaced.append((code, label))
    return label


def _merged_word_length(text: str, cursor: int, label: str) -> int:
    """바로 뒤 낱말이 끝 낱말과 같거나 조사 하나만 붙었을 때 중복 길이를 구한다."""
    if not text.startswith(" ", cursor):
        return 0
    start = cursor + 1
    end = start
    while end < len(text) and not text[end].isspace() and not unicodedata.category(text[end]).startswith("P"):
        end += 1
    word = text[start:end]
    last_word = label.split()[-1]
    if word == last_word or (word.startswith(last_word) and word[len(last_word) :] in KOREAN_PARTICLES):
        return len(last_word) + 1
    return 0


def translate(
    text: str,
    labels: dict[str, dict[str, str]],
    facts: Facts | None = None,
) -> tuple[str, list[tuple[str, str]], list[str]]:
    """긴 표기부터 치환하며 바꾼 자리 바로 뒤의 조사 받침·끝 낱말 중복을 맞추고 흔적을 정리한다(SCRUM-265)."""
    dictionary = _dictionary(labels)
    if facts is not None:
        dictionary.update(_feature_labels(labels, facts))
    replaced: list[tuple[str, str]] = []
    unknown: list[str] = []
    parts: list[str] = []
    cursor = 0
    for match in _pattern(dictionary).finditer(text):
        if match.start() < cursor:
            continue
        choice = _paren(text, match, dictionary)
        if choice == "keep":
            continue
        if choice == "drop":
            parts.append(text[cursor : match.start() - 1])
            cursor = match.end() + 1
            if (match.group(), "") not in replaced:
                replaced.append((match.group(), ""))
            continue
        label = _replacement(match, dictionary, replaced, unknown)
        parts.extend((text[cursor : match.start()], label))
        cursor = match.end()
        if label and label != match.group():
            particle, length = particle_fix(text, cursor, label)
            parts.append(particle)
            cursor += length or _merged_word_length(text, cursor, label)
    parts.append(text[cursor:])
    plain = {label for code, label in dictionary.items() if not label.endswith(f"({code})")}
    return tidy("".join(parts), plain), replaced, unknown


def _paren(text: str, match: re.Match[str], dictionary: dict[str, str]) -> str | None:
    """한글 낱말에 붙은 괄호 속 사전 코드면 "keep"·"label"·"drop", 아니면 None."""
    code = match.group("code")
    if code is None or code not in dictionary:
        return None
    word = attached_paren(text, match.start(), match.end())
    return None if word is None else paren_choice(text[: match.start() - 1], code, dictionary[code])

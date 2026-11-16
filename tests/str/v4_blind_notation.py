"""표기 사전의 코드만 치환하고, 이미 표기한 구절과 숫자는 보존한다."""

from __future__ import annotations

import re

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


def _dictionary(labels: dict[str, dict[str, str]]) -> dict[str, str]:
    return {
        code: f"{label}({code})" if field in CODE_WITH_LABEL else label
        for field in LABEL_FIELDS
        for code, label in labels.get(field, {}).items()
    }


def translate(
    text: str,
    labels: dict[str, dict[str, str]],
) -> tuple[str, list[tuple[str, str]], list[str]]:
    """긴 표기부터 한 번만 탐색하여 치환 순서와 미등록 코드 순서를 보존한다."""
    dictionary = _dictionary(labels)
    protected = [re.escape(label) for code, label in dictionary.items() if label.endswith(f"({code})")]
    codes = [re.escape(code) for code in sorted(dictionary, key=len, reverse=True)]
    pattern = re.compile(
        "(?P<protected>"
        + "|".join(protected or [r"(?!)"])
        + ")|"
        + LEFT_BOUNDARY
        + "(?P<code>"
        + "|".join([*codes, UNKNOWN_CODE])
        + ")"
        + RIGHT_BOUNDARY
    )
    replaced: list[tuple[str, str]] = []
    unknown: list[str] = []

    def replace(match: re.Match[str]) -> str:
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

    return pattern.sub(replace, text), replaced, unknown

"""참고 사례 응답 구절 (docs/shared/01, SCRUM-425)."""

import unicodedata

from aml_ai.shared.schemas.str.reference_search import REFERENCE_EXCERPT_MAX
from aml_ai.str.domain.constants_references import REFERENCE_EXCERPT_ELLIPSIS


def excerpt_of(chosen: str | None) -> str | None:
    """고른 구절의 공백을 정리하고 NFC 뒤 UTF-16 상한에 맞춘다 (docs/shared/01, SCRUM-425)."""
    normalized = " ".join(unicodedata.normalize("NFC", chosen or "").split())
    if not normalized:
        return None
    encoded = normalized.encode("utf-16-le")
    if len(encoded) // 2 <= REFERENCE_EXCERPT_MAX:
        return normalized
    prefix = encoded[: (REFERENCE_EXCERPT_MAX - 1) * 2]
    # 인코딩한 문자열이므로 경계에서 잘린 대리쌍만 제외된다.
    return prefix.decode("utf-16-le", errors="ignore") + REFERENCE_EXCERPT_ELLIPSIS

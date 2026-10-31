"""텍스트 길이 — 규약 §5.3 수정본 섹션 세기 기준.

Java `String.length()` · JS `.length` 와 같은 **UTF-16 코드 단위**(NFC 뒤)로 센다.
NFC 는 세기 위해서만 쓴다 — 원본 text 는 바꾸지 않는다(해시 규칙 docs/shared/01).
한글·영문은 코드포인트와 같고, 이모지(BMP 밖)만 2 단위로 세진다.
"""

from __future__ import annotations

import unicodedata


def utf16_len_nfc(s: str) -> int:
    """NFC 정규화 후 UTF-16 코드 단위 길이. 규약 §5.3·docs/str/06. SCRUM-46 — Codex 구현."""
    return len(unicodedata.normalize("NFC", s).encode("utf-16-le")) // 2

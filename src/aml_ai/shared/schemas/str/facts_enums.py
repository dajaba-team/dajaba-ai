"""facts 모델이 쓰는 StrEnum 모음 — 200줄 관문 때문에 facts.py 에서 분리 (SCRUM-47).

내용·값 변경은 facts.py 와 같은 PR 안에서. 백엔드 enum과 이름·값이 같아야 한다
(규약 §5, 백엔드 V002 `ops.entities.entity_type`).
"""

from __future__ import annotations

from enum import StrEnum


class Direction(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    MIXED = "MIXED"
    INTERNAL = "INTERNAL"  # inbound·outbound 둘 다 0 (법인 내 이동만)


class EntityType(StrEnum):
    """ops.entities.entity_type 6종 (백엔드 V002, SCRUM-47 안건 5-6).

    서식 표기(개인사업자·법인…)로 바꾸지 않는다 — AI 는 원값만, 백엔드가 서식에 꽂음.
    COUNTRY·DIRECT 는 개인·법인으로 추정하지 않는다.
    """

    CORPORATION = "CORPORATION"
    PARTNERSHIP = "PARTNERSHIP"
    SOLE_PROPRIETORSHIP = "SOLE_PROPRIETORSHIP"
    INDIVIDUAL = "INDIVIDUAL"
    COUNTRY = "COUNTRY"
    DIRECT = "DIRECT"


class PathKind(StrEnum):
    CYCLE = "CYCLE"
    STACK = "STACK"


class PathStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"

"""SCRUM-304 판정 입력 고정·대조 (docs/str/10 "코퍼스 확장 판정 (holdout_v2)" — 추가 검토 1·2 반영).

실행 전 고정값·이전 판정 기록은 만들 때 복사해 안쪽까지 못 바꾸고 정규화 해시로 대조한다. 결과는 고정 질의
목록·D07~D10 과 빠짐·중복·목록 밖 없이 맞아야 판정한다 — 실패 행만 빼거나 이전 미달을 지우는 길을 막음.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any

JUDGED_TYPOLOGIES = ("CYCLE", "SCATTER_GATHER", "GATHER_SCATTER")
EMPTY_CANDIDATES = ("SCATTER_GATHER", "GATHER_SCATTER", "FX_RELAY")  # 지금 태그 0 — 적재 뒤 다시 셈
TAGGED_KEYS = frozenset((*JUDGED_TYPOLOGIES, *EMPTY_CANDIDATES))
FAN_CASE_IDS = ("D07", "D08", "D09", "D10")
STATUSES = ("pass", "fail", "not_judged")


def normalized_sha256(value: Any) -> str:
    """키 정렬·공백 없는 JSON 의 sha256 — 파일 들여쓰기·키 순서와 무관."""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PreRun:
    """실행 전에 세어 고정 — 유형별 태그된 청크 수 · 확인자 확인 완료 여부. 안쪽까지 읽기 전용."""

    tagged: Mapping[str, int]
    checked: Mapping[str, bool]

    def __post_init__(self) -> None:
        tagged = {str(k): int(v) for k, v in dict(self.tagged).items()}
        checked = {str(k): bool(v) for k, v in dict(self.checked).items()}
        if set(tagged) != TAGGED_KEYS or set(checked) != set(JUDGED_TYPOLOGIES):
            raise ValueError("pre-run must list every typology exactly")
        object.__setattr__(self, "tagged", MappingProxyType(tagged))
        object.__setattr__(self, "checked", MappingProxyType(checked))

    def sha256(self) -> str:
        return normalized_sha256({"tagged": dict(self.tagged), "checked": dict(self.checked)})


@dataclass(frozen=True)
class Prior:
    """이전 판정 기록 — 유형별 상태(CYCLE·SG·GS 정확히, 값은 STATUSES). 안쪽까지 읽기 전용. 미달 고정은 여기서만 옴."""

    statuses: Mapping[str, str]

    def __post_init__(self) -> None:
        statuses = dict(self.statuses)
        if set(statuses) != set(JUDGED_TYPOLOGIES) or not set(statuses.values()) <= set(STATUSES):
            raise ValueError("prior must list CYCLE·SCATTER_GATHER·GATHER_SCATTER with known statuses")
        object.__setattr__(self, "statuses", MappingProxyType(statuses))

    @classmethod
    def from_verdict(cls, out: Mapping[str, Any]) -> Prior:
        return cls({t: v["status"] for t, v in out["typology"].items()})

    def sha256(self) -> str:
        return normalized_sha256(dict(self.statuses))


@dataclass(frozen=True)
class Run:
    """질의 하나 결과 — chunk_id 순서만(본문 없음). typology None = 무관한 질의."""

    id: str
    typology: str | None
    text: str
    top: list[str]


@dataclass(frozen=True)
class FanCase:
    """③ D07~D10 하나 — 확장 전·뒤 top 과 준혁 등급(chunk_id → 등급)."""

    id: str
    before: list[str]
    after: list[str]
    grades: dict[str, int]


Manifest = list[tuple[str, str | None, str]]  # (id, 유형, 질의 문자열)


def check_snapshots(pre: PreRun, pre_sha256: str, prior: Prior | None, prior_sha256: str | None) -> None:
    """실행 전 고정값·이전 판정 기록이 원장에 적힌 해시와 같은지. 첫 판정은 prior·prior_sha256 둘 다 None."""
    if pre.sha256() != pre_sha256:
        raise ValueError("pre-run differs from the reserved snapshot")
    if (prior is None) != (prior_sha256 is None):
        raise ValueError("prior and prior_sha256 must be given together")
    if prior is not None and prior.sha256() != prior_sha256:
        raise ValueError("prior differs from the recorded verdict")


def check_inputs(runs: list[Run], fan: list[FanCase], *, manifest: Manifest) -> None:
    """판정 전 거절 — 질의 빠짐·중복·목록 밖 · D07~D10 각각 정확히 한 번이 아님."""
    ids = Counter(r.id for r in runs)
    if [i for i, n in ids.items() if n > 1]:
        raise ValueError(f"duplicate runs: {sorted(i for i, n in ids.items() if n > 1)}")
    got = {(r.id, r.typology, r.text) for r in runs}
    if got != set(manifest) or len(manifest) != len(set(manifest)):
        missing = sorted(i for i, _, _ in set(manifest) - got)
        extra = sorted(i for i, _, _ in got - set(manifest))
        raise ValueError(f"runs must match the fixed query list: missing {missing} extra {extra}")
    if sorted(c.id for c in fan) != sorted(FAN_CASE_IDS):
        raise ValueError(f"fan cases must be {FAN_CASE_IDS} once each")

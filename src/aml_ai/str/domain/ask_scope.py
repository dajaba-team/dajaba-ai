"""질문 답변 근거 범위 (docs/str/04 "답 자리표" `direction`, SCRUM-362 추가 검토 3 H3). 순수 함수.

서비스가 요청·경보·계좌 법인 매핑에서 셈 — 렌더링 전용(프롬프트에 안 감). 녹화 도구·평가는 범위를 모름(None).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class AskScope:
    """근거 거래 범위(추가 검토 3 H3) — 배타·부재 이름표(`대외 입금만`·`대외 입출금 없음`)는 둘 다 참일 때만."""

    whole_alert: bool  # 요청 근거 = 경보 거래 전체
    ownership_known: bool  # 경보 거래의 모든 계좌에 법인 매핑이 있음(내부·대외 판정 가능)


def ask_scope(
    evidence_ids: Sequence[int],
    alert_ids: Sequence[int],
    accounts: Iterable[str],
    entities: Mapping[str, str | None],
) -> AskScope:
    return AskScope(set(evidence_ids) >= set(alert_ids), all(entities.get(a) for a in accounts))

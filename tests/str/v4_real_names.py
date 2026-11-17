"""v4 테스트 입력의 지어낸 피처 이름 → 실제 피처 이름 (SCRUM-264, docs/str/05 "표기 사전" observation_name).

공용 픽스처·few-shot 은 v1~v3 동결 녹화 키라 파일은 그대로 두고, v4 테스트가 읽을 때만 바꾼다.
이름·basis(`model_feature`)·unit(null — v4 는 이름 기준 단위)만 바꾸고 값·관측 구간·기준값은 그대로
(구간·기준값 조합 문장을 계속 검사). 전부 null 인 실제 형식은 test_v4_observation_names·claims 실제 축.
"""

from __future__ import annotations

from typing import Any

from aml_ai.shared.schemas.str import Facts

# 값 종류(개수 → 개수, 비율 → 비율)를 맞춘 대응. 이미 실제 이름이면 그대로(여러 번 불러도 같음).
# 표에 없는 지어낸 이름은 그대로 남아 v4 조립에서 display_label_missing — 조용히 넘어가지 않음.
REAL_NAME = {
    "account_in_counterparties_24h": "focal_distinct_senders",
    "distinct_senders_24h": "focal_distinct_senders",
    "distinct_recipients_24h": "focal_distinct_receivers",
    "inflow_outflow_ratio_2h": "evidence_paid_max_share",
    "inflow_ratio_window": "evidence_received_max_share",
    "outflow_ratio_2h": "evidence_received_max_share",
}


def real_names(facts: Facts) -> Facts:
    d: dict[str, Any] = facts.model_dump(mode="json")
    for o in d["observations"]:
        o.update(name=REAL_NAME.get(o["name"], o["name"]), basis="model_feature", unit=None)
    d["model_signals"] = [REAL_NAME.get(n, n) for n in d["model_signals"]]
    return Facts.model_validate(d)


def side_facts(facts: Facts, side: str) -> Facts:
    """블라인드 하네스 — v4 쪽은 실제 이름으로 조립했으므로 코드 검사도 같은 facts 로(v2 쪽은 그대로)."""
    return real_names(facts) if side == "v4" else facts

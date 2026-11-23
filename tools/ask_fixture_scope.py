"""평가 픽스처의 근거 범위 — 서비스와 같은 `ask_scope` 로 (docs/str/04 "집계 값의 범위 표시", SCRUM-362 ★B8). 판정·재생·녹화 도구용.

근거·경보 거래 ID 는 요청(예시 `ask_request.json`)에서. 소유 정보는 픽스처에 있는 만큼만 — facts 픽스처는 대상 계좌의 법인만
싣고 상대 계좌 → 법인 매핑이 없어, 상대 계좌가 있으면 그 계좌는 매핑 없음으로 넘긴다(서비스가 DB 에서 못 찾은 계좌와 같음).
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import AskRequest, Facts
from aml_ai.str.domain.ask_scope import AskScope, ask_scope

_UNLISTED = "<픽스처에 없는 상대 계좌>"


def fixture_scope(facts: Facts, req: AskRequest) -> AskScope:
    subject = facts.subject.account_key
    others = facts.counterparties.count + facts.internal.count + facts.indirect.count
    accounts = [subject, *([_UNLISTED] if others else [])]
    entities = {subject: facts.subject.entity_id}
    return ask_scope(req.evidence_transaction_ids, req.alert.transaction_ids, accounts, entities)

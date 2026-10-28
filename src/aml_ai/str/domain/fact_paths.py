"""경로형 경보(R04_CYCLE·R05_STACK)의 rule_facts.paths 확인 — 정본 docs/str/04 "경로". 순수 함수.

detection 이 준 순서를 그대로 확인만 한다. 고치거나 다시 정렬하지 않는다. 하나라도 어긋나면 전체 UNVERIFIED.
"""

from __future__ import annotations

from aml_ai.shared.schemas.alerts import Alert
from aml_ai.shared.schemas.str import PathFacts, PathKind, PathStatus
from aml_ai.str.domain.constants import PATH_MIN_TRANSACTIONS, PATH_RULE_KIND
from aml_ai.str.domain.models import Transaction


def paths_problem(alert: Alert) -> str | None:
    """규칙 1: 경로의 모든 ID ∈ alert.transaction_ids. 어기면 400 메시지."""
    paths = alert.rule_facts.paths or []
    allowed = set(alert.transaction_ids)
    if any(i not in allowed for path in paths for i in path):
        return "paths id not in transaction_ids"
    return None


def build_paths(alert: Alert, txs: list[Transaction], s: str) -> PathFacts | None:
    """rule_facts.paths 가 없거나 빈 배열이면 None. 있으면 규칙 2~7 을 확인해 VERIFIED / UNVERIFIED."""
    paths = alert.rule_facts.paths or []
    if not paths:
        return None
    kind_name = PATH_RULE_KIND.get(alert.rule_id)
    kind = PathKind(kind_name) if kind_name else None
    by_id = {t.transaction_id: t for t in txs}
    hops = [[by_id[i] for i in path if i in by_id] for path in paths]
    verified = kind is not None and all(
        len(h) == len(p) and _path_ok(h, s, kind) for h, p in zip(hops, paths, strict=True)
    )
    return PathFacts(
        kind=kind,
        status=PathStatus.VERIFIED if verified else PathStatus.UNVERIFIED,
        count=len(paths),
        max_hops=max(len(p) for p in paths),
        max_accounts=max(len(_accounts(h)) for h in hops),
        transaction_ids=sorted({i for p in paths for i in p}),
    )


def _path_ok(path: list[Transaction], s: str, kind: PathKind) -> bool:
    """규칙 3~7: 거래 2개 이상·ID 중복 없음·self-transfer 없음, 시간순, 연결, S 에서 시작, CYCLE 은 S 로 닫힘."""
    ids = [t.transaction_id for t in path]
    if len(path) < PATH_MIN_TRANSACTIONS or len(set(ids)) != len(ids):
        return False
    if any(t.is_self_transfer for t in path):
        return False
    for prev, nxt in zip(path, path[1:], strict=False):
        if prev.ts > nxt.ts or prev.to_account_key != nxt.from_account_key:
            return False
    if path[0].from_account_key != s:
        return False
    return kind is not PathKind.CYCLE or path[-1].to_account_key == s


def _accounts(path: list[Transaction]) -> set[str]:
    """경로 하나에 나오는 서로 다른 계좌 (CYCLE A→B→C→A = 3, STACK A→B→C→D = 4)."""
    return {k for t in path for k in (t.from_account_key, t.to_account_key)}

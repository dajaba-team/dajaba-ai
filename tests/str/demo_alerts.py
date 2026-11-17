"""SCRUM-254 — 시연 후보 경보(임시 — 확정은 따로)를 실제 흐름과 같은 facts 로 (손 실행, 읽기만).

경보·점수·규칙·스냅샷은 app_ai 가 못 읽음(원천 4개만) → DB 컨테이너 관리자 계정 psql **읽기 전용** 내보내기
(`tests/str/demo_alerts.sql`, SELECT 만) → `_tmp/demo_requests_<ids>.json`. 하네스는 그 파일로 백엔드 스냅샷과 같은
모양의 요청을 조립(reasons = 최신 alert_scores.payload.reasons, 없으면 [] · prior · evidence = 경보 거래 전체)하고,
facts 는 app_ai 로 `TransactionReader` + `build_facts`(DraftService 와 같음). DB 쓰기 0.

내보내기(경보 id 만 바꿔 다시):
    docker exec -i aml-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -X -q -At -v ON_ERROR_STOP=1 -v ids=7,48 \
      -c "set default_transaction_read_only = on" -f /dev/stdin' < tests/str/demo_alerts.sql \
      > tests/str/recorded/_tmp/demo_requests_7-48.json
확인:
    uv run --frozen --extra dev python -m tests.str.demo_alerts --demo-alerts 7,48 \
      --demo-requests tests/str/recorded/_tmp/demo_requests_7-48.json
출력: 경보마다 SQL 판정 ↔ AI 코드 판정 · 저장된 백엔드 스냅샷과 조립 요청이 다른 칸 이름
전수 대조(R02 전부 — 확정 경보가 바뀔 때도 이걸로 다시): ids 를 전체 경보 id 로 내보낸 뒤
    … --demo-alerts all --demo-requests <파일> --summary   → 일치·불일치 건수, 불일치는 경보 id·칸 이름만
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from aml_ai.shared.schemas.str import DraftRequest, Facts
from aml_ai.str.domain import facts as facts_domain
from aml_ai.str.domain import masking
from aml_ai.str.domain.typology_support import typology_support
from aml_ai.str.infrastructure.transaction_reader import TransactionReader

DEFAULT_DEMO_ALERTS = (7, 48)  # 임시 후보 — 09 SCRUM-254 사전 기준 ③(판정별 id 최소)
_SNAPSHOT_SKIP = ("draft_id", "case_no")  # 케이스·요청마다 다른 칸(요청 최상위만)


def parse_alert_ids(raw: str) -> list[int]:
    parts = [p.strip() for p in raw.split(",")]
    if not raw.strip() or any(not p.isdigit() or int(p) <= 0 for p in parts) or len(set(parts)) != len(parts):
        raise ValueError("경보 id 는 쉼표로 나눈 서로 다른 양의 정수")
    return [int(p) for p in parts]


def request_from_rows(alert: dict[str, Any], rule: dict[str, Any], tx_ids: list[int],
                      score_payload: dict[str, Any] | None, *, prior_alert_count: int) -> DraftRequest:  # fmt: skip
    ids = sorted(tx_ids)
    payload = {
        "draft_id": "DRF-DEMO", "case_no": "CASE-DEMO",
        "alert": {"alert_id": alert["alert_no"], "account_key": alert["account_key"], "entity_id": alert["entity_id"],
                  "rule_id": rule["rule_id"], "rule_version": str(rule["version"]), "typology_hint": rule["typology_hint"],
                  "window_start": alert["window_start"], "window_end": alert["window_end"],
                  "reference_ts": alert["reference_ts"], "transaction_ids": ids, "rule_facts": alert["rule_facts"],
                  "created_at": alert["created_at"]},
        "evidence_transaction_ids": ids, "reasons": (score_payload or {}).get("reasons", []),
        "prior_alert_count": prior_alert_count, "investigator_notes": None, "reporting_institution": None,
    }  # fmt: skip
    return DraftRequest.model_validate(payload)


def load_exports(path: Path, alert_ids: list[int] | None) -> dict[int, dict[str, Any]]:
    """내보낸 파일 → 경보 id 별 {request, snapshot, sql_counts}. `--demo-alerts` 와 id 집합이 다르면 거절
    (None = 전수 대조 — 파일의 경보 전부)."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    by_id = {int(r["alert_id"]): r for r in rows}
    if len(by_id) != len(rows) or (alert_ids is not None and set(by_id) != set(alert_ids)):
        raise ValueError(f"--demo-alerts {sorted(alert_ids)} 와 내보낸 파일 경보 {sorted(by_id)} 가 다름")
    return {
        i: {
            "request": request_from_rows(r["alert"], r["rule"], r["tx_ids"] or [], r["score_payload"],
                                         prior_alert_count=r["prior_alert_count"]),
            "snapshot": r["snapshot"],
            "sql_counts": r["sql_counts"],
        }
        for i, r in by_id.items()
    }  # fmt: skip


def demo_facts(session: Session, req: DraftRequest) -> Facts:
    """DraftService 와 같은 순서 — 거래 읽기 → 대상 → build_facts(app_ai 원천 4개만 읽음)."""
    reader = TransactionReader(session)
    txs = reader.load_transactions(req.evidence_transaction_ids)
    return facts_domain.build_facts(req.to_facts_input(), txs, reader.load_subject(req.alert, txs))


def snapshot_diff(req: DraftRequest, snapshot: dict[str, Any] | None) -> list[str] | None:
    """저장된 백엔드 요청과 조립 요청의 다른 칸 이름(`alert.x` 꼴). 스냅샷 없으면 None, 같으면 []."""
    if snapshot is None:
        return None
    mine = req.model_dump(mode="json")
    # AI 가 실제로 받을 때처럼 같은 모델로 검증한 뒤 비교(기본값 칸 — 예 rule_facts.paths — 차이를 데이터 차이로 안 셈)
    theirs = DraftRequest.model_validate(snapshot).model_dump(mode="json")
    out = []
    for key in sorted((set(mine) | set(theirs)) - set(_SNAPSHOT_SKIP)):
        if key == "alert":
            sub = set(mine[key]) | set(theirs.get(key, {}))
            out += [f"alert.{k}" for k in sorted(sub) if mine[key].get(k) != theirs.get(key, {}).get(k)]
        elif mine.get(key) != theirs.get(key):
            out.append(key)
    return out


def sql_support(counts: dict[str, int], typology: str | None) -> str | None:
    """SQL 재료로 같은 판정 식(05) — AI 코드 판정과 대조용."""
    d = {"typology": typology, "counterparties": {"count": counts["counterparties"]},
         "inbound": {"count": counts["inbound"]}, "outbound": {"count": counts["outbound"]},
         "internal": {"count": counts["internal"]}, "paths": None}  # fmt: skip
    return typology_support(d)


def compare_one(session: Session, export: dict[str, Any]) -> list[str]:
    """SQL 판정·수 ↔ AI(build_facts → typology_support) — 다른 칸 이름만(값은 안 돌려줌)."""
    req = export["request"]
    f = demo_facts(session, req)
    ai = {"inbound": f.inbound.count, "outbound": f.outbound.count, "internal": f.internal.count,
          "counterparties": f.counterparties.count}  # fmt: skip
    diff = [k for k in ai if ai[k] != export["sql_counts"][k]]
    if sql_support(export["sql_counts"], req.alert.typology_hint) != typology_support(
        masking.mask_for_llm(f)
    ):
        diff.append("support")
    return diff


def _summary(session: Session, exports: dict[int, dict[str, Any]]) -> None:
    """전수 대조 — 일치·불일치 건수, 불일치는 경보 id 와 칸 이름만. 진행은 200건마다."""
    bad: dict[int, list[str]] = {}
    for n, (alert_id, e) in enumerate(sorted(exports.items()), start=1):
        diff = compare_one(session, e)
        if diff:
            bad[alert_id] = diff
        if n % 200 == 0:
            print(f"… {n}/{len(exports)}", flush=True)
    print(
        json.dumps(
            {"total": len(exports), "match": len(exports) - len(bad), "mismatch": bad}, ensure_ascii=False
        )
    )


def main(argv: list[str] | None = None) -> int:
    from aml_ai.shared.db import get_session

    parser = argparse.ArgumentParser(description="시연 후보 경보 facts·판정 확인(읽기만)")
    parser.add_argument("--demo-alerts", default=",".join(map(str, DEFAULT_DEMO_ALERTS)))
    parser.add_argument("--demo-requests", type=Path, required=True)
    parser.add_argument("--summary", action="store_true", help="전수 대조 — 건수와 불일치 경보 id·칸 이름만")
    args = parser.parse_args(argv)
    ids = parse_alert_ids(args.demo_alerts) if args.demo_alerts != "all" else None
    exports = load_exports(args.demo_requests, ids)
    session = next(get_session())
    if args.summary:
        _summary(session, exports)
    for alert_id, e in ({} if args.summary else exports).items():
        f = demo_facts(session, e["request"])
        ai = typology_support(masking.mask_for_llm(f))
        sql = sql_support(e["sql_counts"], e["request"].alert.typology_hint)
        print(json.dumps({"alert_id": alert_id, "sql": sql, "ai": ai, "match": sql == ai, "diff": compare_one(session, e),
                          "snapshot_diff": snapshot_diff(e["request"], e["snapshot"])}, ensure_ascii=False))  # fmt: skip
    session.rollback()  # 읽기만
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

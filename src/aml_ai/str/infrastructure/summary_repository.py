"""요약·질문 답변 `generations` 행 저장 (SCRUM-129·290) — 선점·펜싱 없음, 매번 새 행.

질문 답변 성공 저장만 `timeout_s`·`before_commit` 을 넘긴다(docs/str/03 10단계) — 요약 호출은 그대로.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import func, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.logging import current_request_id
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.infrastructure.orm import Generation

_META_COLS = ("llm_model", "prompt_version", "few_shot_ids", "tokens_in", "tokens_out", "latency_ms")
# 트랜잭션 한정 — commit·rollback 뒤엔 원래 값(SET LOCAL 과 같음). 값은 바인드 파라미터로
_SET_TIMEOUTS = text("SELECT set_config('statement_timeout', :v, true), set_config('lock_timeout', :v, true)")
_TIMEOUT_SQLSTATES = ("57014", "55P03")  # query_canceled · lock_not_available


@dataclass
class SummaryRepository:
    session: Session

    def save(
        self,
        *,
        generation_id: str,
        case_no: str,
        request: dict[str, object],
        facts: Facts | None,
        response_payload: dict[str, object],
        meta: dict[str, object],
        status: str,
        error: str | None = None,
        kind: str = "SUMMARY",
        timeout_s: float | None = None,
        before_commit: Callable[[], None] | None = None,
    ) -> None:
        """status=SUCCEEDED 또는 FAILED. facts 는 실패 저장에서 None 가능(ORM 칸이 nullable).

        kind 는 SUMMARY(기본) 또는 ASK(SCRUM-290) — draft_id 없이 case_no 로 남는 두 종류.
        timeout_s 를 주면 이 트랜잭션의 문장·잠금 대기를 그 시간으로 묶고, 걸리면 rollback 뒤 LlmUnavailable.
        before_commit 이 raise 하면 rollback 뒤 그대로 올린다(마감 재확인).
        """
        values = {k: meta[k] for k in _META_COLS if k in meta}
        row = Generation(
            generation_id=generation_id,
            kind=kind,
            draft_id=None,
            case_no=case_no,
            request=request,
            request_hash="",  # 요약·질문 답변은 해시 없음(선점 안 함)
            facts=facts.model_dump(mode="json") if facts is not None else None,
            response=response_payload,
            status=status,
            error=error,
            request_id=current_request_id(),
            finished_at=func.now(),
            **values,
        )
        try:
            if timeout_s is not None:
                self.session.execute(_SET_TIMEOUTS, {"v": f"{max(1, int(timeout_s * 1000))}ms"})
            self.session.add(row)
            self.session.flush()
            if before_commit is not None:
                before_commit()
            self.session.commit()
        except DBAPIError as exc:
            self.session.rollback()
            if timeout_s is not None and getattr(exc.orig, "sqlstate", None) in _TIMEOUT_SQLSTATES:
                raise LlmUnavailable("ask save timed out") from None
            raise
        except Exception:
            self.session.rollback()
            raise

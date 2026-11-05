"""동시 요청 풀 묶임 재현 (SCRUM-122, `-m db`). 운영 설정(5+5·30s) 그대로, 테스트 전용 엔진만
`pool_size=2·max_overflow=0·pool_timeout=3s` + LLM 진입 Event 로 결정적 재현. 자세히는 docs/str/09.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.str.concurrent_pool_support import (
    POOL_SIZE,
    LlmGate,
    concurrent_client,  # noqa: F401 — fixture reexport
    llm_gate,  # noqa: F401
    short_timeout_engine,  # noqa: F401
    wait_entered,
    watch_pool_max,
)
from tests.str.integration_support import INTEGRATION_INTERNAL_KEY

pytestmark = pytest.mark.db

_CONCURRENT_DRAFTS = 4
_VERIFY_DEADLINE_S = 1.0  # 브랜치에선 즉시, develop 에선 pool_timeout 3s 뒤 TimeoutError

_MIN_NARRATIVE_V2 = [
    {"section": s, "text": "x", "cites": [], "evidence_ids": []}
    for s in ("SUBJECT", "DATE", "PLACE", "INSTRUMENT", "METHOD", "GROUNDS", "OPINION")
]


def _draft_body(sample: dict, draft_id: str) -> dict:
    return {
        **sample,
        "draft_id": draft_id,
        "alert": {
            **sample["alert"],
            "account_key": "010_8000EBD30",
            "entity_id": "80062E240",
            "transaction_ids": [1, 2, 3],
        },
        "evidence_transaction_ids": [1, 2, 3],
        "investigator_notes": None,
    }


def _post_draft(client: TestClient, sample: dict, idx: int) -> int:
    body = _draft_body(sample, draft_id=f"DRF-CONC-{idx:02d}")
    res = client.post("/v1/str/drafts", json=body, headers={"X-Internal-Key": INTEGRATION_INTERNAL_KEY})
    return res.status_code


def _verify_404(client: TestClient) -> float:
    """존재하지 않는 generation_id 로 verify — DB 세션 체크아웃·반납만. 404 가 정상."""
    t0 = time.monotonic()
    res = client.post(
        "/v1/str/verify",
        json={"generation_id": "a" * 32, "revision_no": 1, "narrative": _MIN_NARRATIVE_V2},
        headers={"X-Internal-Key": INTEGRATION_INTERNAL_KEY},
    )
    elapsed = time.monotonic() - t0
    assert res.status_code == 404, f"verify 응답 코드: {res.status_code} body={res.text[:200]}"
    return elapsed


def _run_scenario(client: TestClient, sample: dict, gate: LlmGate) -> tuple[list[int], float, int]:
    """초안 N 개 submit → LLM 진입 대기 → verify 호출 → gate release → 결과 수집."""
    draft_results: list[int] = []
    with ThreadPoolExecutor(max_workers=_CONCURRENT_DRAFTS + 2) as ex:
        drafts = [ex.submit(_post_draft, client, sample, i) for i in range(_CONCURRENT_DRAFTS)]
        entered = wait_entered(gate, POOL_SIZE)
        assert entered >= POOL_SIZE, f"LLM 진입 보장 실패: entered={entered}"
        verify_elapsed = ex.submit(_verify_404, client).result()
        gate.release.set()
        draft_results.extend(fut.result() for fut in as_completed(drafts))
    return draft_results, verify_elapsed, gate.entered


def test_concurrent_drafts_do_not_block_verify(
    short_timeout_engine: Engine,  # noqa: F811
    concurrent_client: TestClient,  # noqa: F811
    draft_request_sample: dict,
    llm_gate: LlmGate,  # noqa: F811
) -> None:
    """초안 N 개 동시 — pool_size 개가 LLM 에 진입해 대기 중임을 Event 로 확인한 뒤 verify 요청.

    결정적 assert: ① draft 전부 200 · verify 404, ② pool 최대 ≤ `POOL_SIZE`, ③ verify < `_VERIFY_DEADLINE_S`.
    develop 흉내(end_read 두 줄 주석) 에서는 verify 가 `pool_timeout=3s` 안에 연결 못 받아 TimeoutError 500.
    """
    pool_max = {"value": 0}
    stop = threading.Event()
    watcher = threading.Thread(
        target=watch_pool_max, args=(short_timeout_engine.pool, stop, pool_max), daemon=True
    )
    watcher.start()
    try:
        draft_results, verify_elapsed, entered = _run_scenario(
            concurrent_client, draft_request_sample, llm_gate
        )
    finally:
        llm_gate.release.set()
        stop.set()
        watcher.join(timeout=1)

    print(
        f"\n[pool] max checkedout={pool_max['value']}, verify elapsed={verify_elapsed:.3f}s, llm entered={entered}"
    )
    assert all(code == 200 for code in draft_results), f"초안 실패 응답: {draft_results}"
    assert pool_max["value"] <= POOL_SIZE, f"pool checkedout 가 {POOL_SIZE} 초과: {pool_max['value']}"
    assert verify_elapsed < _VERIFY_DEADLINE_S, f"verify 응답이 느림: {verify_elapsed:.3f}s"

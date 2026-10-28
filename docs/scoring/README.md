# scoring/ — 준영 폴더 문서

준영이 자기 방식으로 쓰는 자리. 진희가 비워 두고 틀만 제안한다 — 지우고 다시 써도 된다.

같이 지키는 것은 `docs/shared/`의 여섯 개(특히 `00_server_rules.md`, `02_ml_package.md`). 그 밖에 이 폴더에 있으면 좋은 것:

- **구조** — `src/aml_ai/scoring/` 4계층(`api/router.py`, `application/score_service.py`, `domain/`(비어 있음), `infrastructure/orm.py`·`prediction_repository.py`)의 책임 한 줄씩. 피처·모델 코드는 여기 없고 `aml_ml` 안이라는 것. 뼈대에는 라우터와 `AI_SCORING_MOCK` 고정 점수 service가 들어 있다.
- **처리 순서** — `POST /v1/scores`: 요청 검증 → `transaction_reader.load_transactions` → `aml_ml.score()` → `predictions`·`alert_features` 저장 → 응답 + 버전. 경보 500건 기준 시간 예산(90초 안, 동기 — 안건 10 확정, 배치 크기는 W4 실측 뒤 설정값만). 입력 범위는 `shared/02` "입력 범위"(10/28 확정: 대상 계좌 24h + 경보 근거 거래, 이웃 확장 없음).
- **실패 처리** — 경보 하나 실패 시 그 경보만 `data_quality_status=FAILED, score=null`, 전체는 살림(`shared/02`, 안건 4). FAILED 경보는 저위험이 아니라 보존·재처리 대상. 백엔드 재실행과의 관계(안건 21은 회의 제외 — 현값: `alert_scores` `alert_id` UNIQUE, `prediction_id` 새로 발급).
- **정합성 검사** — W4에 백엔드 경보(준혁 룰 엔진)와 학습용 경보(pandas)가 같은지 축소본 `expected.json`으로 맞추는 절차(안건 13 확정: 백엔드 적재 A안 · 20은 회의 제외, 현 표 유지).
- **모델 교체 절차** — 준영 리포 tag → `pyproject.toml` → `model_versions` 행 → `/v1/health` 확인(`shared/02`).
- **결정 기록** — `str/09_decisions.md`와 같은 표.

진희 폴더(`docs/str/`)의 `01_code_rules.md`·`02_structure.md`를 참고하면 모양이 맞는다.

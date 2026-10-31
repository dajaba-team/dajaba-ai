# 09. 결정 기록

한 줄씩. 날짜 · 결정 · 이유 · 버린 대안. 바꾸면 줄을 지우지 말고 아래에 새 줄.

| 날짜 | 결정 | 이유 | 버린 대안 |
|---|---|---|---|
| 10/14 | AI 서버 FastAPI 한 대, `scoring/`·`str/` 폴더 분리 | 두 명이 두 서버 운영 못 함 | 서버 둘 |
| 10/14 | STR 검증 = 코드 + LLM 평가자 | 숫자는 코드가, 서술은 LLM이. 코드가 잡은 건 LLM이 뭐라 해도 fail | LLM 단독 검증 |
| 10/14 | RAG는 MVP 제외, 2차 1번 | 코퍼스가 몇 페이지라 프롬프트에 넣으면 같음 | — |
| 10/22 | 평가자 항목 4 → 5 (`NO_INSTRUCTION_TEXT` 추가) | 메모 주입 방어를 채점에도 | — |
| 10/23 | 에스컬레이션·초안 생성 별도 버튼(방식 B) | 지윤 질문. 초안 생성은 ESCALATED에서만 | 에스컬레이션 시 자동 생성 |
| 10/23 | AI 호출 재시도 1회 | 규약 6.2·레퍼런스 8.5 동일. 10/23에 잠깐 2회로 잘못 적었다가 바로잡음 | 2회 |
| 10/26 | ~~facts 기준 통화 = 건수 최다 `currency_paid`~~ → 10/27 폐기 | — | — |
| 10/26 | facts 금액은 문자열(소수 2자리) | JSON number는 백엔드·LLM이 다르게 반올림 | number |
| 10/26 | 코드 검증 허용 오차 0, 거짓 양성 감수 | 지어낸 금액 통과가 훨씬 비쌈. "약 3억"은 fail | ±1% |
| 10/26 | `prior_alerts` 내용은 LLM에 안 줌, 건수만 | "전에도 걸렸다"가 추측의 근거가 됨 | 과거 룰 ID 전달 |
| 10/26 | 코드 검증 실패 시 평가자 안 부름 | 비용·시간, 어차피 fail | 항상 둘 다 |
| 10/26 | 평가자 호출 실패 = `VERIFY_UNAVAILABLE`(passed=false 아님) | 백엔드가 "다시 검증" 띄우게 | passed=false |
| 10/26 | 생성기에 CoT 안 씀, 평가자만 comment-first | 추론 문제가 아니라 제약 문제. 토큰·JSON 오염 | 생성기 CoT |
| 10/26 | Generate→Check→Revise 루프 보류 | 흐름 단순 유지, 재생성이 숫자를 또 바꿀 위험 | 1회 자동 재생성 |
| 10/26 | LangChain·LangGraph 안 씀 | LLM 호출 2번의 직선 파이프라인, 추상화 비용만 | LangChain |
| 10/26 | **RAG 1차 포함, 범위 고정** (안건 22) | AI 파트가 "LLM 2번 + 정규식"으로 보이면 얇음. 유형 설명 구체화·출처 인용 | 2차 유지 |
| 10/26 | RAG 코퍼스 = 공개 FATF·FinCEN 문서(`10`) | KoFIU 참고유형 사례집은 비공개(2025.12 금융위) | KoFIU 목록 |
| 10/26 | RAG 저장 = pgvector, 같은 PostgreSQL | 인프라 안 늘림 | Chroma·Pinecone |
| 10/26 | 검색 실패·0건이면 `references=[]`, 초안은 만듦 | RAG는 품질용, 가용성에 영향 주지 않음 | 502 |
| 10/26 | RAG 되돌림 조건: 11/11까지 평가 표 없으면 2차로 | W4 압박 시 탈출구 | — |
| 10/26 | ML 리포 분리, `aml-ml` 패키지로 연결 (준영 동의) | 피처 코드 한 벌 → train/serve skew 방지 | 모델 파일만 넘김 / 서버 분리 |
| 10/26 | AI 서버는 **별도 리포 `dajaba-AI`** (백엔드 `dajaba`와 다른 폴더·git) | 서버가 다르고 담당이 다르다 — 진희 결정. DB·네트워크는 백엔드 compose 것을 쓴다 | 백엔드 하위 폴더(잠깐 그렇게 적었다가 바로잡음) |
| 10/26 | 폴더는 기능 우선 × 4계층 `api/application/domain/infrastructure` + `src/` 레이아웃 | 백엔드와 같은 모양, 두 명이 폴더 나눠 맡기, `domain` 순수 함수 테스트 | 계층 우선 |
| 10/26 | uv, SDK 직접, pydantic v2, SQLAlchemy 동기 | 단순함 | poetry, async |
| 10/26 | **Python 3.12 고정** (`requires-python >=3.12,<3.13`) | 3.11은 보안 패치만, 3.13은 shap·numba 호환 위험. 준영 `aml-ml`과 같은 인터프리터 | 3.11, 3.13 |
| 10/26 | 평가자 모델은 가능하면 생성 모델과 다른 것 | 자기 글에 너그러움 | 같은 모델 |
| **10/27 회의** | `transaction_id` bigint, JSON 숫자 (안건 1) | 적재 시 부여하는 순번. 원본 추적은 준혁 `source_files` | 문자열 |
| 10/27 회의 | 점수 응답 `score`+`threshold`, 등급은 백엔드 `CasePolicy` (안건 2) | 모델 버전과 정책 버전을 따로 기록 | AI가 `score_band` |
| 10/27 회의 | `data_quality_status` = OK/SHORT_HISTORY/MISSING_INPUT/FAILED, FAILED는 score null·케이스 안 만듦·저위험 아님 (안건 4) | 실패와 저위험을 구분. 판정 조건은 준영 | PARTIAL/INSUFFICIENT |
| 10/27 회의 | 근거 거래 `evidence`(경보 안) / `context`(경보 밖) 분리, STR은 evidence만 (안건 7) | 참고 거래 등장만으로 상대방을 혐의자로 쓰지 않게 | 한 배열 |
| 10/27 회의 | `typology_source` RULE만 (안건 8) | 라벨은 서빙에 없음 | PATTERN_LABEL |
| 10/27 회의 | `passed` = 코드 전부 ∧ 평가자 전부 ≥4, VERIFY_UNAVAILABLE도 한 줄 저장 (안건 9) | "검증 못 함"이 보여야 함 | — |
| 10/27 회의 | 점수 500건 동기, 배치 크기는 설정값 (안건 10) | W4 실측 뒤 조정 | 비동기·큐 |
| 10/27 회의 | ESCALATED·DRAFTED·REJECTED → CLOSED, 사유 필수 (안건 11) | "보고 안 하기로" 결론이 가능해야 | — |
| 10/27 회의 | 축소본 적재는 백엔드 A안 (안건 13) | — | AI 적재 |
| 10/27 회의 | 초안·검증 **별도 버튼·별도 호출**, 초안 응답 `verification: null` (안건 17) | 90초 안에 둘 다 빠듯. 조사역이 고친 뒤 검증이 자연스러움 | 초안 직후 자동 검증 |
| 10/27 회의 | **facts는 AI가 계산** (안건 23 A안) — 백엔드 `flows/03` "백엔드가 facts 계산" 폐기 | 원천을 읽는 쪽이 계산해야 검증과 같은 기준. 백엔드는 경보·근거·이유·메모만 보냄 | 백엔드 계산 |
| 10/27 회의 | `draft_id` 백엔드 시퀀스 선발급, `generation_id` AI 발급 → `str_drafts` 저장(V008), 검증은 `generation_id`로 (안건 23 세부, 채영) | 재전송·검증이 한 생성본을 정확히 가리킴 | AI가 draft_id |
| 10/27 회의 | 검증 응답 `narrative_sha256`, `verification_results`에 `revision_no`·해시(V009), `ApprovalGate`는 "이 본문의 passed 검증" | "최신 검증 passed"는 본문을 고친 뒤에도 승인되는 구멍 | 최신 검증 |
| 10/27 회의 | 409 `GENERATION_IN_PROGRESS`, 백엔드 재시도 없음 | 같은 draft_id 재진입 | 대기·폴링 |
| 10/27 (2차 검토) | **facts 대상 계좌 관점 `inbound/outbound/internal`, 통화별 집계, 환산 없음** | 15종 통화에서 기준 통화 1개는 사실을 지움 | 기준 통화 + 총액(10/26) |
| 10/27 (1차 검토) | facts `observations[]`(관측값) + `model_signals[]`(이름만), SHAP 기여값은 facts에 안 넣음 | 기여값을 관측값처럼 쓰던 `top_reasons`는 설계 오류 | `top_reasons` 문자열 |
| 10/27 (1차 검토) | LLM은 `cites`(fact 키)만, `evidence_ids`는 코드가 cites에서 연결. 거래 ID 목록을 LLM에 안 줌 | ID 목록을 주면 아무 ID나 옮겨 적음 | LLM이 evidence_ids |
| 10/27 (1차 검토) | 코드 검사는 **유형별 대조** 5종(금액+통화, 날짜↔기간·개설일, 건수·상대 수, 계좌 식별자, 근거 범위), 못 읽은 표현은 `UNPARSED` fail | "금액이냐 아니냐"로 숫자를 나누면 개설일·건수에서 오탐·누락 | 금액 정규식 1종 + 날짜 |
| 10/27 (2차 검토) | 코드 검사 경계 문구: "지원하는 표현에서 추출한 사실값을 해당 유형의 facts와 대조" — "모든 숫자 검증"이라 말하지 않음 | 과장은 발표에서 바로 찔림 | — |
| 10/27 (1차 검토) | 생성기·평가자 모두 **마스킹 facts** | 평가자는 숫자 대조를 안 함. 입력 한 벌 | 평가자만 원본 |
| 10/27 (2차 검토) | 평가자 루브릭에 **4점 기준** 추가 | 통과선이 4점인데 4의 뜻이 없었음 | 5·3·1만 |
| 10/27 (2차 검토) | AI 안 LLM 연결 재시도 **삭제**, 재시도는 백엔드 1회만. 예산 80초/호출 35초/재생성은 남은 40초↑ (가정값) | 백엔드 1회 × AI 1회 = 실질 4회, 90초 초과 | AI 1회 + 백엔드 1회 |
| 10/27 (2차 검토) | `generations` PROCESSING 선점 + `UNIQUE(draft_id)`, FAILED 행 보존, 재생성은 **새 draft_id** | 중복 생성 방지의 키는 draft_id 하나. "같은 draft_id에 새 generation_id" 안은 철회 | AI가 재생성 판단 |
| 10/27 (2차 검토) | 프롬프트 v1 동결 = 첫 녹화 커밋 시점. 그 전엔 자유 수정 | "쓰고 나면 수정 금지"는 녹화 전엔 뜻이 없음 | 작성 즉시 동결 |
| 10/27 (2차 검토) | pgvector 확장은 superuser — 새 DB는 `db/init`, 기존 DB는 수동 1회, Alembic 0004는 확인만 | `app_migrate`로 `CREATE EXTENSION` 안 됨 | Alembic이 확장 생성 |
| 10/27 (2차 검토) | RAG 평가는 **청크 단위**, 참고 사례 **0~3건**(유형 일치 + 최소 유사도) — 3건 채우기 안 함 | 문서 단위 recall은 "맞는 문서의 엉뚱한 쪽"을 정답으로 침. 억지 3건은 규칙 8 위반을 유도 | 문서 단위 recall@3, 항상 3건 |
| 10/27 (3차 검토) | 중복 방지 = 선점 전 `request_hash` 비교(상태 무관) + 부분 UNIQUE(`status<>'FAILED'`) + 110초 넘은 PROCESSING은 FAILED로 정리 — 위 2차 줄의 `UNIQUE(draft_id)`를 대신함 | 부분 UNIQUE만으론 FAILED 뒤 다른 내용이 통과, 서버가 죽으면 영원히 409 | UNIQUE 하나로 전부 |
| 10/27 (3차 검토) | `ApprovalGate` = `generation_id` 일치 + 본문 해시 일치 + passed. `revision_no`는 비교 안 함. 규약 4절 "검증이 승인 요청을 막지 않음" 문구 폐기 | 해시만이면 다른 생성본 검증이 통함. revision_no까지면 같은 본문도 재검증 강요 | 해시만 / 해시+revision_no |
| 10/27 (3차 검토) | 초안 요청 `evidence_transaction_ids` = `alert.transaction_ids` 전체 | 근거 부분집합으로 facts를 내면 건수·금액이 경보와 다름 | 점수의 근거 부분집합 |
| 10/27 (3차 검토) | fact 키 `*.amount.{currency}` → 그 통화 거래 ID만(`by_currency[].transaction_ids`) | 달러 합계에 유로 거래가 근거로 붙던 것 | 방향 전체 ID |
| 10/27 (3차 검토) | 통화는 ISO 코드, 로더가 고정 표로 변환, Bitcoin→`BTC` 예외, 표 밖 이름은 에러 | 계약(ISO)과 원천(`US Dollar`)이 달랐음 | 원천 문자열 그대로 |
| 10/27 (3차 검토) | `DATE_MATCH` 용도 분리(개설 단어 문맥 → onboarded_at, 그 밖 → 기간) | 합집합이면 개설일을 거래 날짜로 써도 통과 | 기간 ∪ 개설일 |
| 10/27 (3차 검토) | 한글 수사 + 단위는 `UNPARSED`("한" 제외), 그 밖 표현은 평가자·사람 범위라고 명시 | "표현이 없으면 통과"가 "숨기지 않는다" 원칙과 충돌 | 조용히 통과 |
| 10/27 (3차 검토) | self-transfer만 남는 경보 → 400 (가정) | 기간·금액이 빈 초안은 쓸 게 없음 | 빈 facts로 생성 |
| 10/27 (3차 검토) | RAG 켬/끔 비교 표 추가(W4) | hit@3는 초안 품질을 말해 주지 않음 | hit@3만 |
| 10/27 (4차 검토) | 선점 1~3을 짧은 트랜잭션 하나 + `pg_advisory_xact_lock(draft_id)`, SUCCEEDED 반환 전 해시 재확인, finish는 `status='PROCESSING'` 조건(펜싱) | 해시 비교와 INSERT 사이에 끼어든 다른 내용 요청이 남의 결과를 받거나 새로 생성할 수 있었음. 110초 뒤 늦게 끝난 작업이 결과를 덮어쓸 수 있었음 | `draft_requests` PK 테이블(테이블 9개가 됨) |
| 10/27 (4차 검토) | 대상 계좌가 없는 경보 거래는 400이 아니라 facts `path`로 보존, 대상 계좌 관점 집계에는 안 섞음. `period`는 path 포함 | R04_CYCLE의 중간 거래(B→C)가 400이 되던 것 | 400 유지 / path 거래를 inbound·outbound에 섞기 |
| 10/27 (4차 검토) | `DATE_MATCH` 개설 단어는 가장 가까운 날짜 하나에만, 거리가 같으면 `UNPARSED` | 한 문장에 두 날짜가 있으면 둘 다 개설일로 분류됨 | ±10자 안 날짜 전부 |
| 10/27 (5차 검토) | `path`는 최소로: `count`·`transaction_ids`만, 인용 키 없음, LLM에 안 보냄. 고리 사실은 준혁 답 뒤 별도 fact(AI가 연결 직접 확인) | 인용 키를 먼저 열면 검증 대조 규칙이 없고, `account_count`는 고리 계좌 수로 오해됨. 경로라는 보장도 없음 | path 인용 키 + COUNT_MATCH 확장 |
| 10/27 (5차 검토) | 초안 요청 `evidence_transaction_ids` ≠ `alert.transaction_ids`(집합)면 400 | 무관한 거래가 path로 섞여 드는 걸 막음 | 확인 없음 |
| 10/27 (5차 검토) | 선점 INSERT는 `ON CONFLICT … DO NOTHING RETURNING`. 펜싱은 "중복 저장 방지"이지 "LLM 1회 보장" 아님(겹치는 호출 비용은 감수) | unique 오류를 잡으면 트랜잭션이 aborted | 오류 잡기 / savepoint |
| 10/27 (5차 검토) | 범위 표현(`A와 B 사이`)에 걸린 개설 단어는 `UNPARSED` | 4차의 테스트 22 예시가 "거리가 같은 경우"가 아니었음 | 거리 규칙만 |
| 10/27 (안건 24 확정, 지윤·채영) | 반려 두 갈래: NEED_REVISION → DRAFTED, NOT_REPORTABLE → CLOSED. 보완 요청 뒤 같은 본문 재요청은 409 `NARRATIVE_UNCHANGED`(백엔드 `ApprovalGate`, 반려 당시 해시 = `approvals.narrative_sha256`). 반려 요청 형식 오류는 400 `INVALID_REQUEST`. AI 서버 변경 없음 | 반려 판단이 글에만 남고, 고치지 않은 본문이 예전 검증으로 다시 통과하던 구멍 | 반려 버튼 하나 |
| 10/28 (준혁 답) | 경로형 경보: `rule_facts.paths`(경로별 거래 ID, 시간순, R04·R05)를 AI가 **확인만** 해서 `paths` fact로. 시작·연결·시간순·(CYCLE) 닫힘을 전부 통과해야 `VERIFIED`, 하나라도 어긋나면 전체 `UNVERIFIED`(인용·LLM 전달 없음). `VERIFIED`일 때만 `paths.count·max_hops·max_accounts`를 인용 가능, `COUNT_MATCH` 대조 집합에 추가. 기존 `path`는 `indirect`로 이름 변경. 홉 = 거래 개수(복귀 포함) | 5차에서 버린 "COUNT_MATCH 확장"은 순서·연결 보장이 없어서였는데, 이제 detection이 순서를 주고 AI가 연결을 확인하므로 확인된 경우에만 연다 | 경로 사실 없이 계속 막기 / AI가 순서 재구성 |
| 10/28 (준영 답) | 안건 3·5·6 확정: `reasons` = `name` + `observation`/`baseline`/`contribution`(확인 못 한 값 null), `feature_version`은 응답 문자열 하나·묶음 관리는 패키지 내부, 서비스 필드명 유지(`reference_ts`=`as_of`, `account_key` 분해 안 함, `alert_id` 문자열) | 10/27 제안서 + 이력 부족·조회 범위 답으로 조건이 풀림 | 기여값 숫자를 관측값처럼 / `account_key` `_` 분해 |
| 10/28 (준영 답) | ML 입력 범위 = 대상 계좌 `[reference_ts−24h, reference_ts)` + 경보 근거 거래 전체, 이웃 확장 없음. `account_aliases` 인자 삭제, coverage는 내부 메타데이터(`COMPLETE/PARTIAL/UNKNOWN`) | 24h 중심 모델이면 7일 이력이 필요 없고, 데이터가 HI-Small 하나라 별칭 표가 없음 | 7일 이력 / 이웃 조회 |
| 10/28 (준영 답) | 품질 판정: `SHORT_HISTORY`·`MISSING_INPUT`은 모델이 지원·검증한 경우 **점수 있음**, 필수 입력 누락·미지원 이력 부족·`UNKNOWN`·계산 실패는 `FAILED`. 설명만 실패 → 점수 유지 + `reasons=[]`. baseline만 없음 → null, 점수 안 막음 | "이력 부족 = 점수 null"이면 HI-Small 앞부분 경보 대부분이 점수 없이 끝남 | 이력 부족 일괄 null / 일괄 점수 |
| 10/28 (안건 23 세부) | 수정본 검증 때 `cites`·`evidence_ids` 재계산 (a): `judge_v2`가 섹션별 cites, 코드가 `attach_evidence`, 응답 `narrative_refs`, 평가자 안 돌면 null. 백엔드가 수정본 저장에 반영 | 채영 "반영 가능" — 근거 번호는 서버 관리라 해시 규칙과 충돌 없음 | (b) 생성 때 값 유지 |
| 10/28 (SCRUM-12) | `Typology`는 규약 2절 패턴 8종 + 룰 전용 5종(PASS_THROUGH·STRUCTURING·NEW_ACCOUNT_LARGE·HIGH_VALUE·DORMANT_BURST)의 합집합, `typology_hint`·`facts.typology`는 null 허용 | 규약은 "pattern_type과 같은 열거값"인데 R07·교체 후보 룰은 패턴 라벨이 없음. 좁게 잡으면 백엔드 경보가 400 | 패턴 8종만 / 자유 문자열 |
| 10/28 (SCRUM-12) | LLM 출력 섹션(`LlmNarrativeSection`: section·text·cites)과 응답·검증 섹션(`NarrativeSection`: + evidence_ids)을 다른 모델로. LLM 출력에 `evidence_ids`가 있으면 스키마 실패 | 거래 ID는 LLM이 고르지 않는다(05) — 같은 모델이면 LLM이 써 넣은 ID가 그대로 통과 | 한 모델 + evidence_ids 무시 |
| 10/28 (SCRUM-12) | `mask_for_llm`은 `Facts`가 아니라 프롬프트용 dict를 돌려준다 | transaction_ids·indirect를 빼면 `Facts` 스키마를 만족하지 않음(04 마스킹 표) | ID를 빈 배열로 채운 Facts |
| 10/28 (SCRUM-13) | `internal`은 S가 낀 거래 중 상대 계좌가 S와 같은 법인인 것만. S 없는 같은 법인 계좌끼리는 `indirect` | 대상 계좌 관점 집계라 S가 안 낀 거래를 "법인 안 이동"으로 세면 경로 중간 거래와 섞인다 | from·to 법인만 비교 |
| 10/28 (SCRUM-13) | 요청 안 목록 확인(`evidence` = `alert.transaction_ids`, paths ID ⊆)은 domain 순수 함수가 메시지를 내고 `draft_service`가 400으로. 라우터·스키마 validator에 두지 않음 | 규칙이 04에 있고 테스트도 domain 단위로. Pydantic validator면 422 모양이 섞이고 `shared/schemas`에 업무 규칙이 들어간다 | `DraftRequest` model_validator |
| 10/28 (SCRUM-13) | `facts.py`를 `facts.py`·`fact_paths.py`·`fact_keys.py` 셋으로 | 한 파일 200줄 규칙, 경로 확인·인용 키는 각자 바뀌는 이유가 다름 | 한 파일 |
| 10/29 (최종 점검) | ML 입력은 **넘기는 거래**(24h + 경보 근거 전체)와 **피처 계산 거래**(`ts < reference_ts`)를 나눠 적음. 기준 시각 이후 근거는 보존만 | "전체를 넘긴다"와 "이후 거래는 안 준다"가 한 절에서 부딪혔음 | 근거를 기준 시각에서 자름 / 이후 거래도 피처에 |
| 10/29 (최종 점검) | `COUNT_MATCH`는 숫자 종류(과거 경보·모델 관측값·경로 수·상대 수·거래 건수)를 먼저 정하고 그 종류 집합하고만 대조, 못 정하면 `UNPARSED`. 출금 통화별 건수 추가 | 한 집합이면 "과거 경보 3건" 같은 정상 문장이 오탐되고, 종류가 다른 숫자가 우연히 같으면 틀린 문장이 통과 | 모든 건수를 한 허용 집합에 |
| 10/29 (최종 점검) | `03` 검증 파이프라인에 `narrative_refs` 단계(5b)·저장·응답 필드를 넣어 `01`·`06`과 맞춤 | 파이프라인만 보고 구현하면 수정본에 예전 근거가 남음 | — |
| 10/29 (최종 점검 재확인) | `COUNT_MATCH` 문맥 범위는 **숫자가 든 절**(±10자 창 아님), 거래 건수는 방향 단어로 입금·출금·내부 집합까지 좁힘 | ±10자면 "모델 관측값(24시간 기준) 31개"를 못 잡고, 문장 전체면 같은 문장의 다른 숫자까지 관측값이 됨. 한 집합이면 "입금 3건"이 출금 3건으로 통과 | ±10자 창 / 문장 전체 / 방향 무시 |
| 10/29 (최종 점검 재확인 2) | 절 구분자에서 숫자 안의 `,`·`.`는 제외(`1,000건`), 상대 수는 "상대 31개"처럼 단어가 앞에 와도 추출. `UNPARSED`는 `CODE_FAILED`로 끝나고 평가자를 부르지 않음 — 조사역이 고쳐 다시 검증 | 쉼표로 먼저 자르면 `입금 1`·`000건`으로 갈림. 파이프라인은 코드 실패 시 평가자를 안 부르는데 06에 "평가자 몫"으로 적혀 있었음 | UNPARSED만 평가자로 보내기 |
| 10/29 (준혁 확인, SCRUM-41) | `/v1/scores`는 항목별 실패 — 없는 거래 ID는 그 경보만 `FAILED`(`TRANSACTION_NOT_FOUND`), JSON 형식 오류만 400. 응답에 `failure_code`(FAILED일 때만, 4값) | 500건 중 1건 때문에 499건이 같이 실패하면 안 됨. 재처리할 가치가 있는 실패(`COMPUTE_ERROR`)를 백엔드가 구별해야 함 | 규약 6.3대로 요청 전체 400 / 사유를 내부 기록에만 |
| 10/29 (준혁 확인, SCRUM-41) | AI 서버 DB 조회 장애는 요청 전체 503 **`DB_UNAVAILABLE`**(새 코드), 요청 하나 = 트랜잭션 하나. 백엔드 재시도 1회 대상에 추가 | 일시 장애라 재시도로 풀릴 수 있고, 일부만 저장되면 재실행 때 중복·누락. `MODEL_UNAVAILABLE`을 같이 쓰면 "모델 문제"와 "DB 문제"가 로그에서 구분 안 됨 | `MODEL_UNAVAILABLE` 재사용 / 항목별 FAILED |
| 10/29 (준혁 확인, SCRUM-41) | 서비스 DB 적재 = HI-Small 전체 5,078,345건, 점수는 경보당 1건(`alert_id` UNIQUE) — 모델 버전별 이력은 `ai.predictions` | DB 안 24시간 조회 = 전체 이력이라는 전제가 필요. 백엔드는 최신 1건만 쓰고 이력은 AI에 이미 남음 | 일부 기간만 적재 / 백엔드에 버전별 점수 행 |
| 10/29 (최종 점검 재확인) | RAG 평가에 `recall@3`(질의별 비율의 단순 평균, 0건은 0) 보조 지표로 추가 | MVP 정의서가 hit@3·recall@3를 가리키는데 `10`에 계산식이 없었음 | recall 없이 hit@3만 |
| 2026-10-29 | claim/finish 설계 결정 — advisory lock·해시 비교·PROCESSING 펜싱, 테이블 추가 안 함 | 같은 draft_id 경합과 늦은 결과 저장을 차단 | draft_requests 별도 테이블 |
| 2026-10-29 (SCRUM-16) | `narrative_sha256`은 섹션 6개가 각각 한 번씩이 아니면 ValueError, Java도 동일. 오류 메시지에 `text` 금지(섹션 이름·개수만) | 호출자가 스키마 검증을 거친 값만 넘긴다는 보장이 늘 있지는 않음. 뒤틀린 입력을 조용히 해시하면 ApprovalGate가 "같은 값"을 다른 본문에 붙여 승인할 수 있음 | 스키마 검증에만 맡김 / 있는 것만 해시 |
| 2026-10-29 (SCRUM-16) | `LlmNarrativeSection.text`는 StrictModel의 자동 strip을 off(`StringConstraints(strip_whitespace=False)`), 대신 공백만 text는 field_validator로 거부. 길이 제한(1200)은 공백 포함으로 셈. Java도 trim 금지·공백만 거부 | 해시는 "앞뒤 공백 그대로"(shared/01). pydantic이 자르면 Java 바이트와 어긋나 ApprovalGate가 못 통과 | 양쪽 다 strip(docs 수정) / 해시에서만 strip |
| 2026-10-29 (SCRUM-16) | `shared/schemas/str.py`는 이번 PR에서 1회 200줄 가이드 예외 — strip-off override는 쪼개도 피할 수 없음. 분리는 후속 이슈(SCRUM-<후속>)로 | SCRUM-16 범위는 해시 + 벡터. 스키마 쪼개기는 별도 설계·테스트가 필요 | 이번에 분리 |
| 2026-10-29 (SCRUM-15) | LLM provider 1종 = **OpenAI Responses API**, `text.format=json_schema`로 `NarrativeOut` 강제. `temperature=0` 거부되면 **reasoning effort 가장 낮게·온도 제외**(모델이 받는 파라미터 조합 하나). provider용 스키마로 변환, 최종 검증은 Pydantic `NarrativeOut` + cites ⊆ fact_keys | Responses API가 strict `json_schema`를 공식 지원. provider 1종으로 좁혀야 녹화·테스트가 단순. 온도 거부되는 모델이 있어도 결정성은 reasoning_effort로 유지 | Anthropic tool_use / Chat Completions legacy / 온도만 조정 |
| 2026-10-29 (SCRUM-15) | 녹화 키 = `sha256(stable_json({"s":system,"u":user}))[:16]`, 함수는 `shared/infrastructure/llm_client.recording_key()` 하나. `record.py`와 `RecordedLlmClient`가 같은 걸 쓴다 | md(08·recorded/README·docstring)와 코드가 어긋나 있어 "녹화는 됐는데 재생이 못 찾는 경우"가 생길 수 있음. 단순 이어 붙이기는 system·user 경계가 모호 | sha256(system+user) / 각 리더가 자기 키 계산 |
| 2026-10-29 (SCRUM-15) | 동결 강제 = `str/domain/constants.FROZEN_PROMPTS = {"narrative_v1": "<파일 sha256>"}` → 기동 때 파일 해시 다르면 실패(DB 없이도 걸림). `prompt_versions.frozen_at`은 색인 때 FROZEN_PROMPTS에 있으면 채움(정보용) | 05/04 "동결 뒤 수정 금지"를 기계로 막음. DB 없이 걸리는 쪽이 CI·로컬에서 동일. 녹화 커밋 = 동결 커밋 | DB 테이블에만 저장(기동이 DB에 의존) / 사람 눈 |
| 2026-10-29 (SCRUM-15) | 생성 재시도의 **시간 예산**(남은 40초 미만이면 재생성 안 함)은 **이번 범위 밖**, 별도 이슈로 | SCRUM-15 범위는 provider·녹화·동결. 예산은 draft_service에 시간 측정이 없어 손 커짐 | 이번에 포함 |
| 2026-10-29 (SCRUM-15) | 온도 거부 자동 재시도 **삭제**, 결정성은 설정 하나로 고정 — `LLM_TEMPERATURE_SUPPORTED` + `LLM_REASONING_EFFORT`(기본 false·low). gpt-6.1-sol은 reasoning 모델이라 `temperature` 지원 안 함(녹화로 확인) | 호출마다 폴백하면 지원 안 하는 모델은 매번 400 → 재호출 (실질 2배). 설정으로 고정하면 1호출. 지원 모델로 바꾸면 `.env`에서만 토글 | 호출마다 폴백 유지 / 온도만 조정 |
| 2026-10-29 (SCRUM-15) | 공급자 `insufficient_quota` 는 **LLM_BUDGET_EXCEEDED**(재시도 0), 그 외 429 rate_limit 은 **LLM_UNAVAILABLE**(재시도 1). 4xx 중 `insufficient_quota` 도 BudgetExceeded | 일 토큰 한도는 재시도 소용 없음, 짧은 간격 rate_limit 은 재시도 1회로 풀릴 수 있음. 규약 6.3 두 에러 코드의 재시도 열과 맞춤 | 429 전부 Budget / 429 전부 Unavailable |
| 2026-10-30 | 위 10/27 회의 안건 11 줄(`ESCALATED·DRAFTED·REJECTED → CLOSED, 사유 필수`) 바로잡음 — **REJECTED → CLOSED는 `NOT_REPORTABLE` 반려일 때만**, `NEED_REVISION` 반려는 수정·재생성만. 어긋나면 백엔드가 409 `INVALID_CASE_TRANSITION`으로 막고 AI는 상태를 보지 않음 | 같은 날 오후 안건 24 확정(규약 v0.2 §4)이 더 최근 — 반려 두 갈래 분리와 맞춰야 함 | REJECTED 전부 종료 허용 |
| 2026-10-30 (노션 백엔드 미결 23) | HIGH/MEDIUM/LOW는 백엔드 CasePolicy가 계산(HIGH = `medium_to_high` 이상). AI `threshold`는 모델별 **추천값**으로 응답에 담기만 하고 운영 판정에 쓰지 않음. 규약 §3 문구 변경 요청 반영 | 추천 0.7·정책 0.9·점수 0.8이면 규약 옛 문장대로는 HIGH, 정책대로는 MEDIUM — 판정 위치를 한 곳으로 | AI threshold로 HIGH 판정 |
| 2026-10-30 (노션 백엔드 미결 24) | 생성 스키마(`NarrativeOut`)는 섹션당 1~1,200자 유지, **수정본 검증 요청은 섹션당 5,000자**로 스키마 분리. 글자 수는 **NFC 정규화 뒤 UTF-16 코드 단위**(규약 §5.3, Java `String.length()`·JS `.length`와 같음). 구현·경계 테스트는 SCRUM-46 | 백엔드는 5,000자까지 저장하는데 AI가 생성 스키마로 검증하면 1,201~5,000자 수정본이 400. Python `len()`은 코드포인트라 이모지 등에서 Java와 어긋남 | 양쪽 1,200자 / 코드포인트 기준 |
| 2026-10-30 (노션 백엔드 미결 25) | `revision_no` 1 = AI 원문, 첫 수정 = 2. 원문·첫 수정·재수정 예시 JSON은 `contracts/examples/`에 | 규약 §5.3·AI 설계와 같음. `null`이면 요청 스키마(정수)에 걸림 | AI 원문 = null |
| 2026-10-30 (노션 백엔드 미결 26) | `rule_facts.paths`: ① `transaction_ids` 밖 ID → **400** ② R04·R05인데 paths 누락·경로 ID 합집합 ≠ `transaction_ids`·R04 4홉 이상 → 초안은 만들되 `paths` **`UNVERIFIED`**(경로 숫자는 STR에 안 씀), 이런 경보는 detection 테스트에서 먼저 막음(준혁) ③ R05 홉 한도는 임의로 두지 않고 미결 15 룰 명세에서. ML은 기존 FAILED·null 규칙을 따로 적용(준영) | 400은 입력 계약 위반에만, 잘못된 경로는 보고서에서 빼는 쪽이 안전. 경로 재구성·삭제는 하지 않음(10/28 원칙) | 전부 400 / R05도 3홉 |
| 2026-10-30 (노션 백엔드 미결 27) | 시각은 두 종류. **데이터 시각**(`ts`·`window_start`·`window_end`·`reference_ts`·facts `period`·reasons `observation.window_*`)은 시간대 없음 그대로, **시스템 시각**(`created_at`·`updated_at`·`produced_at`·`reported_at`·`report_due_at` 등)은 전부 **UTC + `Z`, 초 단위**. 규약 §0 표·§2·§3·§4·§5.3 예시 반영(10/30). 전원 동의<br>거절은 기존 400 INVALID_REQUEST (FastAPI 기본 422 미사용). | IBM 원천 시각은 시간대 정보가 없어 추정하면 틀림. 시스템이 찍는 시각은 서버마다 시간대가 달라 Z 없이는 비교 불가 | 모든 시각 시간대 없음(규약 v0.2 §0 옛 문구) |
| 2026-10-31 (SCRUM-52) | `SystemTimestamp`는 `AwareDatetime` 입력을 UTC 초 단위로 정규화·Z 직렬화하고 `DraftResponse.produced_at`을 필수로 추가. 데이터 `Timestamp` 동작은 유지. 세 서비스는 공용 `utc_now()` 사용. develop부터 51줄이던 verify를 관문 때문에 `_decide`로 순수 이동, 동작 변경 없음 | 미결 27·규약 §0의 시스템 시각 계약 통일. `str.py` 분리는 SCRUM-46으로 유지 | naive 시각을 UTC로 추정 / 데이터 시각까지 변경 |

## 미결 (회의·측정 뒤)

| 항목 | 누가·언제 |
|---|---|
| 서비스 DB 실제 첫 거래 시각, 점수 테이블 마이그레이션 번호 (항목별 실패·`failure_code`·503은 10/29 확정) | **준혁**, 적재 개발 후 |
| 규약 §3·§6.3에 `/v1/scores` 항목별 실패·`failure_code`·`DB_UNAVAILABLE` 반영 | 진희, 규약 변경 요청 → 다음 월요일 |
| `reasons` 정렬·동률·기여 척도, `feature_version` 실제 이름 | 준영, 모델 검증 뒤 |
| 시간 예산 80/35/40초, `direction` 2배 규칙 | W2 수 첫 실측·축소본 분포 뒤 |
| 평가자 통과 기준 4점 유지 여부 | W4 오류 주입 7~12 표 뒤 |
| RAG 최소 유사도 상수 초기값 | W4 청크 평가 표 뒤 |
| `aml-ml` 시그니처 세부(`ScoreResult` 필드, 실패 처리, polars) | 준영 첫 tag |
| KoFIU 서식 항목명 ↔ 섹션 6개 대응 확정 | W3, 특금법 시행규칙 별지 확인 |
| 안건 19·20·21 (금액 정밀도, 룰 표 "정할 것" 칸, 재시도·409·UNIQUE) | 회의 제외 — **현값 유지**, 준영 매핑 표 뒤 재확인 |
| R06_BIPARTITE 대체 룰 (안건 20) — 정해지면 규약 2절 룰 표·`rule_facts`, 준영 학습 룰을 같이 맞춤 | **준혁** |
| 수정 저장 ↔ 승인 요청이 동시에 올 때(승인 트랜잭션 안에서 현재 해시 재확인) | 채영, 백엔드 V009 |
| 통화 표 15줄 확인(HI-Small `DISTINCT currency_*`) | 진희, 축소본 만들 때 |
| 미결 27 후속 — 시스템 시각 Z: 스키마에 데이터용 `Timestamp`와 시스템용 시각 타입 분리, `produced_at`을 `datetime.now()` → UTC 기준으로, `contracts/examples/` 시스템 시각(`score_request`·`draft_request`의 `alert.created_at`, `score_response`·`verify_response`의 `produced_at`)에 `Z` | SCRUM-52에서 반영(2026-10-31) — `SystemTimestamp`, 초안 `produced_at` 포함. naive 입력은 기존 400 `INVALID_REQUEST`로 거절 |
| SCRUM-52 이전에 저장된 성공 초안(`produced_at` 없음)은 재사용 시 스키마 불일치 → 개발 DB만 해당. 로컬은 `generations` 비우거나 DB 볼륨 초기화. 운영 DB 없음(시연은 새 DB)이라 백필 안 함 | 진희 |
| 노션 미결 23~26 후속 — 23·24·25·26은 10/30 확정(위 결정 표). 남은 것: 수정본 검증 스키마 5,000자·UTF-16 경계 테스트(**SCRUM-46**), `paths` 누락·합집합 불일치·R04 4홉 → `UNVERIFIED`·경로 숫자 미인용 테스트 고정, 규약 §2 `paths` 행 변경 요청(11/2 반영), 원문·수정 예시 JSON `contracts/examples/` | 진희 |
| R05 홉 한도 (미결 26 ③) | **준혁**, 미결 15 룰 명세(W2) |
| self-transfer만 남는 경보 400 유지 여부, `STALE_PROCESSING_S` 110초 | 축소본 분포·W2 실측 뒤 |

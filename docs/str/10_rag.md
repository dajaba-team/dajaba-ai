# 10. 참고 사례 검색 (RAG)

10/26 1차 포함, 안건 22에서 확인. 범위는 안건 22 표대로 **고정** — 여기 없는 건 2차. 정본: `str/infrastructure/retriever.py`, `shared/infrastructure/embedding_client.py`, `tools/ingest_corpus.py`, `corpus/manifest.json`, `tests/str/retrieval_eval.json`.

한 줄로: 경보 유형에 맞는 공개 사례·적색신호 문단 3개를 찾아 프롬프트 REFERENCES 자리에 붙인다. **유형 설명을 구체적으로 만들기 위한 것**이고, 검증을 대신하지 않으며, 실패해도 초안은 나온다.

## 코퍼스

`corpus/manifest.json`에 문서 목록(id·제목·발행처·연도·URL·sha256·쪽수·언어). PDF는 `corpus/pdf/`에 두되 **.gitignore**(저작권·용량). manifest만 커밋 → 같은 manifest면 누구나 같은 코퍼스를 다시 만든다.

1차 후보 (10/26 링크 확인한 것만 — 인수인계 문서에 URL):

| id | 문서 | 왜 |
|---|---|---|
| `fincen-sar-narrative-2003` | FinCEN, Guidance on Preparing a Complete & Sufficient SAR Narrative (2003, ~31쪽) | **5W1H 정본**, 부록에 충분/불충분 서술 예시 — few-shot·평가자 루브릭 근거 |
| `fatf-tbml-2020` | FATF/Egmont, Trade-Based Money Laundering: Trends and Developments (2020, ~63쪽) | 유형 설명·사례 박스·위험 지표 |
| `fatf-tbml-2006` | FATF, Trade Based Money Laundering (2006, 38쪽) | 사례 12개 |
| `fatf-pml-2018` | FATF, Professional Money Laundering (2018) | 계정 관리망·현금 운반망·대리 네트워크 → PASS_THROUGH·STACK |
| `fincen-funnel-2014` | FinCEN Advisory FIN-2014-A005, Funnel Accounts (2014, 6쪽) | **FAN_IN** 정의 + 적색신호 |
| `ffiec-redflags` | FFIEC BSA/AML Manual Appendix F, Red Flags (~113개, 16 범주) | 적색신호 목록 — KoFIU 목록 대체 |
| `fincen-msb-ko-2007` | FinCEN, 금전 서비스 업체 지침 (한국어, 2007, ~44쪽) | 유일한 국문 공개 자료 — 적색신호·사례. 한국어 질의 매칭 확인용 |

KoFIU 「자금세탁 의심거래 참고유형 사례집」은 금융회사 AML 담당자에게만 배포되고 공개본이 없다(2025.12.22 금융위 보도자료). 안 넣는다. 적색신호의 국문 표현은 FFIEC 부록 F를 번역한 청크로.

## 적재 (`tools/ingest_corpus.py`)

```
manifest 읽기 → PDF sha256 검증 → 텍스트 추출(pymupdf, 쪽 번호 유지)
→ 청크: 문단 단위, 목표 500토큰, 겹침 50, 표는 행 단위, 쪽 경계 넘지 않음
→ 태깅: 청크마다 typologies[] (우리 유형 enum). 1차는 문서·절 단위 일괄 태깅(manifest의 sections 맵) — 수동 태깅 표는 corpus/tags.csv
→ 임베딩: shared/embedding.embed(texts) 배치 64
→ ai.reference_chunks INSERT ... ON CONFLICT (content_hash) DO NOTHING
```

같은 manifest·같은 임베딩 모델이면 재실행해도 결과 동일(멱등). 임베딩 모델을 바꾸면 `--truncate`로 비우고 전부 다시. 적재 로그는 문서별 청크 수·건너뛴 수.

## 테이블

`ai.reference_chunks` — `shared/03`. 인덱스 HNSW(cosine) + GIN(typologies). pgvector 확장은 백엔드 `db/init`(준혁에게 알림, compose 이미지 `pgvector/pgvector:pg16`). 그 전엔 이 마이그레이션을 돌리지 않는다.

## 검색 (`infrastructure/retriever.py`)

```python
def retrieve(facts: Facts, k: int = 3) -> list[Reference]:
    query = build_query(facts)        # "{유형 한국어 이름} {typology 영문 코드} {top_reasons 이름 3개} {customer.industry}"
    vec = embedding.embed([query])[0] # 실패 → RetrievalUnavailable → 호출자가 [] 로
    rows = (filter typologies @> ARRAY[facts.typology], order by cosine, limit k)
    if len(rows) < k: rows += (no filter, order by cosine, limit k-len, exclude rows)
    return [Reference(doc_id, doc_title, page, text[:600], score)]
```

- 유사도 임계값 없음, top-3 고정. 임계값은 recall@3 표 뒤에(`09` 미결).
- 질의문에 영문 유형 코드를 함께 넣는 이유: 코퍼스가 대부분 영문. 임베딩은 멀티링구얼 1종.
- 실패·0건 → `[]`. `draft_service.py`는 `RetrievalUnavailable`을 잡아 그대로 진행하고 `generations.references = []`. 오류 주입 13.

## 프롬프트에서

REFERENCES 자리에 `[n] {doc_title} p.{page}: {text}` 3줄(`05`). system 규칙 8이 숫자·이름 반입 금지. 응답 `generation_meta.references = [{doc_id, doc_title, page, score}]` → 화면 "참고 유형 사례 3건(출처·쪽)". `generations.references jsonb`에 같은 값(재현).

## 평가

`tests/str/retrieval_eval.json`: 질의 10개(유형 8 + 혼합 2) × 기대 `doc_id`(+page). `recall@3` 표를 W4에 한 번 돌려 `docs/str/08`과 발표 자료에 남긴다. 0.7 미만 → 태깅·청크 크기 조정. **11/11(화)까지 표가 없으면 안건 22 되돌림: REFERENCES를 `(없음)`으로 고정하고 2차로.** 코드는 지우지 않고 플래그(`RAG_ENABLED=false`, `Retriever(enabled=False)` → 항상 `[]`)로.

## 버전

`retrieval_version = f"{EMBEDDING_MODEL}@{manifest_sha256[:8]}"` → `generation_meta`, `generations.retrieval_version`.

## 일정 (W4 전반, 3~4일)

| 날 | 할 일 |
|---|---|
| 1 | manifest 작성, PDF 수집(브라우저로 받아 `corpus/pdf/`), `ingest_corpus.py`, 태깅 표 |
| 2 | 마이그레이션 `reference_chunks`, `embedding.py`, `retrieval.py`, 단위 테스트 |
| 3 | `generate.py`에 REFERENCES 연결, 규칙 8, 오류 주입 13·14, 녹화 |
| 4 | `retrieval_eval.json` 10개 작성 → recall@3 표 → `08`·발표 자료 |

W3 초안 생성·검증이 먼저 서 있어야 한다. 순서를 바꾸지 않는다.

## 2차로 넘기는 것

APG 연례보고서·우리가 승인한 STR 추가, 하이브리드(BM25 + 벡터), 리랭커, 유사도 임계값, 사례 검색 화면, 청크 자동 태깅(LLM). `retrieve()` 시그니처는 그대로라 `generate.py`는 안 바뀐다.

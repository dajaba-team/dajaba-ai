# 10. 참고 사례 검색 (RAG)

10/26 1차 포함, 10/27 회의 채택(안건 22). 범위는 안건 22 표대로 **고정** — 여기 없는 건 2차. 정본: `str/infrastructure/retriever.py`, `shared/infrastructure/embedding_client.py`, `tools/ingest_corpus.py`, `corpus/manifest.json`, `tests/str/retrieval_eval.json`. 10/27 2차 검토 반영: 참고 사례 **0~3건**(억지로 3건 안 채움), 평가는 **청크 단위**, pgvector는 superuser 절차. 2026-11-11 SCRUM-125 반영: 코퍼스 유형 태그를 **백엔드 룰 v2 `typology_hint`** 값(FAN_IN·FAN_OUT·CYCLE·SCATTER_GATHER·GATHER_SCATTER) 로 재태그 — PDF 본문에서 근거 쪽을 찾은 문서만.

한 줄로: 경보 유형에 맞는 공개 사례·적색신호 문단을 **최대 3개** 찾아 프롬프트 REFERENCES 자리에 붙인다. **유형 설명을 구체적으로 만들기 위한 것**이고, 검증을 대신하지 않으며, 실패해도 초안은 나온다.

## 코퍼스

`corpus/manifest.json`에 문서 목록(id·제목·발행처·연도·URL·sha256·쪽수·언어). PDF는 `corpus/pdf/`에 두되 **.gitignore**(저작권·용량). manifest만 커밋 → 같은 manifest면 누구나 같은 코퍼스를 다시 만든다.

manifest는 Docker 이미지에도 복사한다(`Dockerfile` `COPY corpus/manifest.json`, PDF는 안 넣음) — 컨테이너의 `retrieval_version`(`{embedding_model}@{manifest sha256 앞 8자}`)이 health·`generation_meta`·`ai.generations`에 남도록. 없으면 RAG를 켜도 null(2026-11-17 SCRUM-256).

문서 8개 (2026-11-09 sha256·pages 확인):

| id | 문서 | 왜 |
|---|---|---|
| `fincen-sar-narrative-2003` | FinCEN, Guidance on Preparing a Complete & Sufficient SAR Narrative (2003, 33쪽) | **5W1H 정본**, 부록에 충분/불충분 서술 예시 — few-shot·평가자 루브릭 근거 |
| `fatf-tbml-2020` | FATF/Egmont, Trade-Based Money Laundering: Trends and Developments (2020, 66쪽) | 유형 설명·사례 박스·위험 지표 |
| `fatf-tbml-2006` | FATF, Trade Based Money Laundering (2006, 44쪽) | 사례 12개 |
| `fatf-pml-2018` | FATF, Professional Money Laundering (2018, 53쪽) | 계정 관리망·현금 운반망·대리 네트워크 |
| `fincen-funnel-2014` | FinCEN Advisory FIN-2014-A005, Funnel Accounts (2014, 6쪽) | **FAN_IN** 정의 + 적색신호 |
| `ffiec-redflags` | FFIEC BSA/AML Manual Appendix F, Red Flags (웹→PDF, 8쪽) | 적색신호 목록 — 원본 PDF 없음, 웹 본문을 PDF 로(2026-11-09, 머리에 출처 URL) |
| `fincen-msb-ko-2007` | FinCEN, 금전 서비스 업체 지침 (한국어, 2007, 52쪽) | 코퍼스의 국문 자료 1개(유형 태그 없음 — 필터를 켜면 검색에 안 나옴) — 한국어 질의 매칭 재료 |
| `fincen-money-mule-2020` | FinCEN Advisory FIN-2020-A003, Money Mule Schemes (2020, 8쪽) | 머니 뮬 정의·수법. 레드플래그 목록은 PDF 텍스트로 안 뽑힘(정의·수법 문단만) |

KoFIU 「자금세탁 의심거래 참고유형 사례집」은 금융회사 AML 담당자에게만 배포되고 공개본이 없다(2025.12.22 금융위 보도자료). 안 넣는다. 적색신호의 국문 표현은 FFIEC 부록 F를 번역한 청크로.

### 코퍼스 태그 근거 (SCRUM-125, 2026-11-11)

PDF 본문에서 v2 유형(FAN_IN·FAN_OUT·CYCLE·SCATTER_GATHER·GATHER_SCATTER) 근거 쪽을 찾은 문서만 태그. 못 찾으면 빈 태그(검색 결과에 안 나옴). **큰 문서(fatf-*)와 `ffiec-redflags`는 쪽 단위 태그** — manifest `typology_pages: {유형: [쪽, ...]}` 에 적힌 쪽에서 나온 청크만 그 태그, 나머지 청크는 빈 태그. 유일한 문서 단위 태그는 `fincen-funnel-2014`(전 쪽이 FAN_IN). 절 단위 `sections` 맵은 2차 태그 검수로(SCRUM-146 은 합치기 층만 — 11/18). **ffiec 는 SCRUM-125 때 문서 단위 3태그(FAN_IN·FAN_OUT·CYCLE) 였으나, 같은 청크가 세 유형 결과에 모두 올라와 precision 떨어뜨림(★L-1 baseline FAN_IN 0.33 · FAN_OUT·CYCLE 0) → SCRUM-126 에서 쪽 단위 재태그 (FAN_IN p2·3·8 / FAN_OUT p4·5·7 / CYCLE p6).**

CYCLE 기준(R04 = "4홉 안에 시작 계좌로 돌아오는 거래", 백엔드 rules.md): "**계좌가 순환하는 서술**(같은 돈이 계좌들을 돌아 출발 계좌로)" 이 원문에 있을 때만. "범죄 수익을 범죄자·의뢰인에게 돌려준다"(통합 단계) 는 CYCLE 근거 아님 — fatf-tbml-2020 p14 · fatf-pml-2018 p21·27·29 · fatf-tbml-2006 p19·20(비유적 상품 재수출) 모두 CYCLE 에서 제외.

FAN_IN 기준: "여러 출처 → 한 계좌(또는 소수)" 집중 입금 서술이 원문에 있을 때만. "cash controller network·account settlement mechanism"(fatf-pml-2018 p22) 은 국경 간 현금 통제망·계정 상계 — 여러 곳에서 한 계좌로 모으는 서술이 아니라 **CYCLE 에서 제외**(이어하기 11/11): p22 는 FAN_IN 근거 아님. p43·44 는 money mule 피해자 다수 → funnel account 집중으로 FAN_IN.

| doc_id | 태그 | 쪽 | 근거 원문 (pymupdf 추출, 영문 그대로) |
|---|---|---|---|
| `fincen-sar-narrative-2003` | `[]` | — | 그래프 유형 설명 없음 (p7·p9 "layering/structuring/smurfing" 용어 열거만) |
| `fatf-tbml-2020` | `typologies=[]`, `typology_pages={}` | — | CYCLE 기준 엄격화로 제외 (p14 "passing them back to the OCG" 은 계좌 순환 아니라 통합 단계 뜻). 다른 v2 유형 근거 없음 |
| `fatf-tbml-2006` | `typologies=[]`, `typology_pages={}` | — | Case Study 5·6 (p19~20) 금괴·현금 재수출은 상품-현금 치환이라 계좌 순환 아님. 다른 v2 유형 근거 없음 |
| `fatf-pml-2018` | `typologies=[]`, `typology_pages={"FAN_IN": [43, 44]}` | 43 | `"All of the victims of these various fraud schemes were instructed to wire money into funnel accounts held by other co-conspirators (money mules), who then quickly transferred the money to other US accounts as well as accounts around the world before victims could discover the fraud."` |
| | | 43–44 | `"For example, during a one-year period, a key money mule opened 38 fraudulent bank accounts. … met with individual money mules to retrieve cash from their funnel accounts."` (쪽 경계 걸침) |
| `fincen-funnel-2014` | `["FAN_IN"]` (문서 단위) | 1 | `"Funnel Account: An individual or business account in one geographic area that receives multiple cash deposits, often in amounts below the cash reporting threshold, and from which the funds are withdrawn in a different geographic area with little time elapsing between the deposits and withdrawals."` |
| | | 1 | `"In some instances, multiple funnel accounts have been observed to transfer funds into a single consolidated account from where the funds are subsequently withdrawn."` |
| | | 2 | `"Multiple individuals acting on behalf of representatives of the criminal organization deposit the cash proceeds of narcotics sales into this account at different bank or credit union branches, often in multiple states geographically distant from the branch in which the account was opened or domiciled."` |
| | | 3 | `"An account opened in one state (typically along the Southwest border) receives multiple cash deposits of less than $10,000 by unidentified persons at branches outside of the geographic region where the account is domiciled."` |
| | | 5 | `"where the use of funnel accounts and or TBML is suspected in the laundering of criminal proceeds, including specific reference to the terms 'Funnel Account' and or 'TBML' in the Narrative and Suspicious Activity Information sections of SARs is also requested."` |
| `ffiec-redflags` | `typologies=[], typology_pages={"FAN_IN": [2, 3, 8], "FAN_OUT": [4, 5, 7], "CYCLE": [6]}` (SCRUM-126 쪽 단위 재태그) | 2 (FAN_IN) | `"A customer deposits funds into several accounts, usually in amounts of less than $3,000, which are subsequently consolidated into a master account and transferred outside of the country"` |
| | | 2 (FAN_IN) | `"Many small, incoming transfers of funds are received, or deposits are made using checks and money orders. Almost immediately, all or most of the transfers or deposits are wired to another city or country in a manner inconsistent with the customer's business or history."` |
| | | 3 (FAN_IN) | `"Unusual transfers of funds occur among related accounts or among accounts that involve the same or related principals."` |
| | | 4·5·7 (FAN_OUT) | `"Unusually large number and variety of beneficiaries are receiving funds transfers from one company."` (p5) + p4·p7 FAN_OUT bullet (★L-0 진희 확인) |
| | | 6 (CYCLE) | `"Suspicious movements of funds occur from one bank to another, and then funds are moved back to the first bank."` (bank 수준이지만 돈이 "시작 은행" 으로 돌아오는 폐구조 서술) |
| | | 8 (FAN_IN) | 추가 FAN_IN bullet (★L-0 진희 확인) |
| `fincen-msb-ko-2007` | `[]` | — | 한국어 "분산" 매칭 전부 STRUCTURING(분할 거래) 뜻 (p50 "분산 거래" 정의로 확정). v2 그래프 유형 설명 없음 |
| `fincen-money-mule-2020` | `[]` | — | pymupdf 로도 p6~7 머니 뮬 레드플래그 bullet 본문은 빈 줄로 추출. 뽑히는 본문(p5~6)은 분류·모집 수법 설명만 — 그래프 유형 매핑 없음 |

**최종 태그 분포** (적재 8개 중 유형 태그가 붙어 검색에 나오는 문서는 3개, **SCRUM-126 재태그 뒤**): FAN_IN — `fincen-funnel-2014`(문서 단위) + `ffiec-redflags` p2·3·8(쪽 단위) + `fatf-pml-2018` p43·44(쪽 단위). FAN_OUT — `ffiec-redflags` p4·5·7(쪽 단위). CYCLE — `ffiec-redflags` p6(쪽 단위). 빈 태그 5 문서(sar-narrative·tbml-2020·tbml-2006·msb-ko·money-mule) + 큰 문서 2건과 ffiec 의 목록 밖 쪽 전부. **SCATTER_GATHER·GATHER_SCATTER 태그 0건** — "pass-through"(다단 경유)·"collect and distribute"(사업 모델) 개념은 있지만 "한 계좌 → N개 → 한 계좌" 폐구조 교과서 사례 없음. R05·R06 경보 오면 `references=[]` (0~3건 허용, 알고 남김).

**옛 태그(PASS_THROUGH·STACK·STRUCTURING) 전부 폐기** — v2 룰 `typology_hint` 값이 아니라 검색 필터에 안 걸림(죽은 태그). 09 2026-11-11 결정 줄 참조. `FX_RELAY` 는 R03 typology_hint FX_RELAY(11/16 준혁 확정) — 태그는 이번 PR 안 붙임. 182(11/16)에서 `Typology` enum·`TYPOLOGY_KO` "환전 중계"만 추가, 태그·영문 패턴은 193 확정 뒤.

## 적재 (`tools/ingest_corpus.py`)

```
manifest 읽기 → PDF sha256 검증(안 맞으면 그 문서만 건너뛰고 로그) → 텍스트 추출(pymupdf, 쪽 번호 유지)
→ 청크: 문단 단위, 목표 500 토큰, 겹침 50, 표는 행 단위, 쪽 경계 넘지 않음
→ 태깅: manifest 에 `typology_pages` 가 있으면 **쪽 단위**(목록 안 쪽에서 나온 청크만 그 유형, 나머지 청크는 빈 태그),
       없고 `typologies` 가 있으면 **문서 단위**(청크마다 같은 값). 둘 다 없으면 빈 태그. 절 단위 맵은 2차 태그 검수로(SCRUM-146 은 합치기 층만 — 11/18)
→ 임베딩: shared/embedding.embed(texts) 배치 64
→ ai.reference_chunks INSERT ... ON CONFLICT (content_hash) DO NOTHING
```

같은 manifest·같은 임베딩 모델이면 재실행해도 결과 동일(멱등). 임베딩 모델을 바꾸면 `--truncate` 로 비우고 전부 다시. 적재 로그는 문서별 청크 수·건너뛴 수(본문 안 찍음).

**`ON CONFLICT DO NOTHING` 이라 manifest 태그나 임베딩 모델을 바꾸면 그대로 재적재해도 옛 청크의 태그·벡터는 그대로 — `--truncate` 로 비우고 다시 돌려야 반영된다.**

**`page` 는 PDF 쪽 번호(1부터). 인쇄 쪽 번호와 다를 수 있음** — 예: `fatf-pml-2018` PDF 43·44 = 인쇄 41·42. pymupdf 가 1-indexed 쓰므로 manifest·태그 표·검색 결과·화면 표시 전부 PDF 쪽 번호 기준.

**청크 토큰 세는 법 (SCRUM-125, 2026-11-11)** — 토크나이저 라이브러리 안 넣음(`tiktoken` 은 OpenAI 전용이라 provider 바꾸면 깨짐, 유지보수 대비 효과 작음). 글자 수 근사:

```
tokens ≈ max(ceil(chars_total / 4), chars_korean)
```

영문 1토큰 ≈ 4자, 한글 1자 ≈ 1토큰(안전측). CJK 문자(`가-힣`·`぀-ヿ`·`一-鿿`) 수가 전체 ÷ 4 보다 크면 그 값을 토큰 수로 봄. 09 2026-11-11 결정 줄 참조.

## 테이블

`ai.reference_chunks` — `shared/03`. 인덱스 HNSW(cosine) + GIN(typologies). pgvector 확장은 **superuser만** 만들 수 있다: 새 DB는 백엔드 `db/init/00_extensions.sql`(준혁, compose 이미지 `pgvector/pgvector:0.8.2-pg16-trixie`), 이미 있는 DB는 `psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"` 1회(`shared/05`). Alembic `0004_reference_chunks` 는 `pg_extension` 을 확인만 하고 없으면 `RuntimeError("pgvector 확장 없음 — shared/03 절차")` 로 멈춘다(조용히 넘어가지 않음).

`embedding vector(1536)` 로 고정 — 임베딩 차원은 `.env` `EMBEDDING_DIM` 이지만 마이그레이션은 Settings 를 import 하지 않음(환경변수가 CI·테스트 DB·운영 DB 마다 달라져 Alembic 결과가 어긋나는 걸 막는다). 차원을 바꾸려면 테이블을 비우고 전부 재적재 + 다음 번호 마이그레이션. 09 2026-11-11 결정 줄 참조.

`content_hash` = `sha256(doc_id + "\n" + page + "\n" + text_norm)` (text_norm = text 의 유니코드 NFKC + 좌우 공백 정돈, 09 2026-11-11). **`chunk_id` 는 `content_hash` 와 같은 값** — 두 문서에 같은 문단이 있어도 `doc_id`·`page` 가 다르면 두 청크 다 남고 id 가 다름. 같은 문서·같은 쪽에 같은 정규화 본문이면 멱등 삽입(`ON CONFLICT (content_hash) DO NOTHING`). 임베딩 모델을 바꿔도 `content_hash` 는 안 바뀌지만 벡터는 다르니 `--truncate` 뒤 재적재.

### 인덱스 (HNSW + 사후 필터 트레이드오프, SCRUM-125)

pgvector 0.8 **README "Filtering"** 섹션 원문: *"With approximate indexes, filtering is applied after the index is scanned. If a condition matches 10% of rows, with HNSW and the default `hnsw.ef_search` of 40, only 4 rows will match on average."* — HNSW 가 거리 top-N 후보를 먼저 뽑고 그 안에서 `WHERE typologies @>` 를 적용하므로, 좁은 유형(예: FAN_OUT 태그 1 문서) 은 후보 40 안에 안 들면 **결과 0건**이 정상 동작(README "Troubleshooting: Why are there less results for a query after adding an HNSW index?" 과 일치).

**해결책 — `hnsw.iterative_scan = relaxed_order` + `MATERIALIZED` CTE 바깥 재정렬** (pgvector 0.8.0, 0.8.2 지원, 11/11 ★L 결과):
- pgvector README: `strict_order` = 정확한 거리 순서지만 recall 손해, `relaxed_order` = 순서 조금 어긋나도 recall 더 좋음.
- ★L live(425 청크) `strict_order` 는 FAN_IN 정답 top-3 중 `fatf-pml-2018` p44 를 놓치고 `fincen-funnel-2014` p1 을 끌어올림(순서는 깔끔하지만 recall 손해). `relaxed_order` + `WITH r AS MATERIALIZED (... LIMIT :cand) SELECT ... ORDER BY d + 0 LIMIT :k`(후보 10) 로 받은 후보를 **바깥에서 거리순으로 다시 정렬** → 세 유형 전부 전수 스캔 정답과 일치.
- `MATERIALIZED` 가 CTE 안 정렬을 그대로 물리 저장하게 하고 `ORDER BY d + 0` 트릭이 플래너의 재최적화를 막아 **바깥 ORDER BY 가 반드시 다시 돎**. 세션 단위로 `SET LOCAL hnsw.iterative_scan = relaxed_order;` 를 레퍼런스 조회 트랜잭션에만.
- 후보 수 `RAG_CANDIDATES = 10`(`domain/constants.py`) — 3 건 top-K 한테 2~3배 여유로 relaxed 흔들림 흡수.

링크: <https://github.com/pgvector/pgvector#filtering> · <https://github.com/pgvector/pgvector#iterative-index-scans> · CHANGELOG 0.8.0 (2024-10-30).

★L 에서 **인덱스 결과 vs 전수 비교** — FAN_IN·FAN_OUT·CYCLE 세 유형 각각 (1) 기본 / (1') HNSW 강제 / (2) strict_order / (4) relaxed_order + resort / (3) 인덱스 끔(정답). ★L 명령은 `../_claude/ai/live_SCRUM-125.md` ③.

**11/11 ★L live(425 청크) 결과 요약** (PDF 쪽 번호):

| 유형 | (1) basic | (1p) hnsw 강제 | (2) strict | (4) relaxed+resort | (3) 전수 정답 |
|---|---|---|---|---|---|
| FAN_IN | ffiec p7·pml p44·funnel p3 | 0건 | ffiec p7·funnel p3·funnel p1 (pml p44 누락) | ffiec p7·pml p44·funnel p3 | ffiec p7·pml p44·funnel p3 |
| FAN_OUT | ffiec p1·p2·p7 | 0건 | ffiec p1·p2·p7 | ffiec p1·p2·p7 | ffiec p1·p2·p7 |
| CYCLE | ffiec p3·p4·p8 | ffiec p3(1건) | ffiec p3·p4·p8 | ffiec p3·p4·p8 | ffiec p3·p4·p8 |

→ **`relaxed_order + MATERIALIZED 재정렬` 채택**. `strict_order` 는 09 고르지 않은 안.

11/11 ★L live 초안 1회(FAN_IN 픽스처) — `references` 3건: `fincen-funnel-2014` p3(score 0.325)·p1(0.313)·`ffiec-redflags` p7(0.301). `run_code_checks` 23건 전부 `match=True`.

아래 SQL 은 (1)·(2)·(3) 참조용 — 실제 `_search` 는 (4) 사용:

```sql
-- 공통 — 질의 벡터 :vec 는 "{유형 한국어} {유형 영문}" 임베딩 결과
-- (1) 인덱스 켠 채 기본 (iterative_scan 미설정 = off)
SELECT doc_id, page FROM ai.reference_chunks
WHERE typologies @> ARRAY['FAN_IN']::text[]
ORDER BY embedding <=> :vec LIMIT 3;

-- (2) strict_order 로 반복 스캔 — 거리 순서 보장
BEGIN;
SET LOCAL hnsw.iterative_scan = strict_order;
SELECT doc_id, page FROM ai.reference_chunks
WHERE typologies @> ARRAY['FAN_IN']::text[]
ORDER BY embedding <=> :vec LIMIT 3;
COMMIT;

-- (3) 전수(인덱스 끔) — 정답 3건
BEGIN;
SET LOCAL enable_indexscan = off;
SET LOCAL enable_bitmapscan = off;
SELECT doc_id, page FROM ai.reference_chunks
WHERE typologies @> ARRAY['FAN_IN']::text[]
ORDER BY embedding <=> :vec LIMIT 3;
COMMIT;

-- (4) relaxed_order + MATERIALIZED CTE 후보 다시 정렬 — _search 가 실제 쓰는 경로
BEGIN;
SET LOCAL hnsw.iterative_scan = relaxed_order;
WITH r AS MATERIALIZED (
  SELECT chunk_id, doc_id, doc_title, page,
         embedding <=> CAST(:vec AS vector) AS d
  FROM ai.reference_chunks
  WHERE typologies @> ARRAY['FAN_IN']::text[]
  ORDER BY embedding <=> CAST(:vec AS vector) LIMIT 10
) SELECT doc_id, page FROM r ORDER BY d + 0 LIMIT 3;
COMMIT;

-- FAN_OUT·CYCLE 반복 (질의 벡터만 바꿈)
```

**판정**: (3) 이 "정답". (1) vs (3) 은 플래너가 GIN 을 탄 정상 결과 — 사후 필터 누락은 **(1') vs (3)** 로 본다. (2) 는 recall 손해로 (3) 과 어긋날 수 있고, **(4) == (3)** 이면 relaxed+resort 로 해결(코드가 쓰는 경로).

## 검색 (`infrastructure/retriever.py`)

```python
def retrieve(facts: Facts, k: int = 3) -> list[Reference]:
    if facts.typology is None:
        return []                      # typology None 이면 필터할 값이 없음 — 백필 안 함
    query = build_query(facts)         # "{유형 한국어 이름} {typology 영문 코드} {model_signals 이름} {customer.industry}"
    vec = embedding.embed([query])[0]  # 실패 → RetrievalUnavailable → 호출자가 [] 로
    # SCRUM-125 relaxed_order + MATERIALIZED 후보 다시 정렬 — 위 "인덱스" 절
    rows = execute("SET LOCAL hnsw.iterative_scan = relaxed_order;"
                   "WITH r AS MATERIALIZED ("
                   "  SELECT chunk_id, doc_id, doc_title, page, text, "
                   "         embedding <=> :vec AS d "
                   "  FROM ai.reference_chunks WHERE typologies @> ARRAY[:typology]::text[] "
                   "  ORDER BY embedding <=> :vec LIMIT :cand"
                   ") SELECT chunk_id, doc_id, doc_title, page, text, 1 - d AS score "
                   "FROM r ORDER BY d + 0 LIMIT :k")
    rows = [r for r in rows if r.score >= MIN_SIMILARITY]      # 0~3건. 모자라도 채우지 않음
    return [Reference(chunk_id=content_hash, doc_id, doc_title, page, text[:REFERENCE_TEXT_MAX_CHARS], score)]
```

- **0~3건**. 유형 필터를 통과하고 최소 유사도(`domain/constants.MIN_SIMILARITY`, 초기값 `0.0` — W4 청크 평가 뒤 SCRUM-126 에서 조정)를 넘는 것만. 유형이 안 맞는 청크로 3건을 채우던 백필은 **없음** — 엉뚱한 유형 사례는 규칙 8 위반(숫자·이름 반입)을 유도하고 `TYPOLOGY_CONSISTENT` 를 떨어뜨린다(오류 주입 14).
- 질의문에 영문 유형 코드를 함께 넣는 이유: 코퍼스가 대부분 영문. 임베딩은 멀티링구얼 1종. `model_signals` 이름(관측 신호)을 같이 넣어 유형 외 맥락도 반영.
- 태그 분포는 위 "코퍼스 태그 근거" 절 — R05·R06 경보는 늘 `[]`(0~3건 규칙과 일치).
- 실패·0건 → `[]`. `draft_service.py` 는 `RetrievalUnavailable` 을 잡아 그대로 진행하고 `generations.references = []`. 오류 주입 13.

## 프롬프트에서

REFERENCES 자리에 `[n] {doc_title} p.{page}: {text}` 0~3줄, 없으면 `(없음)`(`05`). system 규칙 8 이 숫자·이름 반입 금지. 응답 `generation_meta.references = [{chunk_id, doc_id, doc_title, page, score}]` → 화면 "참고 유형 사례 N건(출처·쪽)". `generations.references jsonb` 에 같은 값(재현).

**narrative_v4 (SCRUM-228, 11/18 기본값)** — 참고 사례는 **화면 표시만(본문 영향 없음)**: 검색은 돌고 응답 `generation_meta.references` 는 채워지지만 본문에는 안 씀(생성기 요청 기록엔 `reference_ids` 만, 아래 "다중 질의·합치기" 절).

**narrative_v3 (SCRUM-225)** — 프롬프트에는 검색 결과 앞 **최대 2건**, 본문은 청크 전체 대신 **유형 패턴 문장 1~2개**(`TYPOLOGY_PATTERN_EN` 과 영단어 겹침 기준, 없으면 앞 300자) — `str/infrastructure/reference_snippet.py`, 자세히는 `05` narrative_v3 절. 자르기는 `draft_service` 한 번이라 **`generation_meta.references`·`generations.references` 도 같은 2건**(화면 "참고 사례 N건" 최대 3→2, 모양은 그대로). 검색(`retriever.py`·`RAG_TOP_K=3`)은 안 바뀜. v1·v2 는 0~3건·청크 전체 그대로.

`Reference.chunk_id` 는 선택 칸(`str | None = None`, SCRUM-125) — 값은 `content_hash`(재적재해도 같은 id). 126 평가가 chunk_id 단위라 필요. 옛 저장 응답(chunk_id 없는 JSON) 은 라운드트립 그대로 통과. 백엔드 `AiDtos.java` 는 `references` 안 읽어 하위 호환.

실패 처리(SCRUM-125): 임베딩 키 없음·`EMBEDDING_MODEL` 빈 값·배치 차원 불일치·DB 검색 예외 **전부 `RetrievalUnavailable` → `[]`**. 기동 때 `RAG_ENABLED=true` + `EMBEDDING_MODEL` 빈 값이면 경고 로그 한 줄만(`judge_model_fallback` 과 같은 모양, 기동 계속).

## 평가

**청크 단위**(2차 검토 반영 — 문서 단위 recall은 "맞는 문서의 엉뚱한 쪽"을 정답으로 친다). `tests/str/retrieval_eval.json`: 질의 10개(FAN_IN 4·FAN_OUT 2·CYCLE 2·빈 집합 2) × 2단계 점수(2=그래프 패턴 / 1=관련 약함) 기대 `chunk_id` 집합(적재 뒤 `content_hash`로 고정 — 재적재해도 같은 id). 지표 셋:

- `hit@3` = 기대 청크 중 하나라도 top-3에 든 질의 비율 (주 지표, 목표 0.7)
- `precision@3` = top-3 중 기대 청크 비율. 기대 청크는 **2단계 점수**(2=그래프 패턴 문장 / 1=같은 유형 관련 약함) — 엄격(2점만) · 넓은(1점 이상) 두 벌로 계산 (SCRUM-126). **분모는 "돌려준 건수"**(0~3) — 위 "검색" 절 0~3건 표시 규칙과 같음. 3건 못 채워도 돌려준 건수 기준으로 나눔.
- `recall@3` = 질의마다 `|기대 청크 ∩ top-3| ÷ |기대 청크|`, 질의 10개의 **단순 평균**(macro) (보조 지표 — MVP 정의서 4절 "hit@3·recall@3 표"). 기대 청크가 3개보다 많은 질의는 1에 닿을 수 없으니 표에 질의별 기대 청크 수를 같이 적는다
- 검색 결과가 0건인 질의(유사도 미달)는 세 지표 모두 0으로 센다 — 0~3건 허용은 화면 표시 규칙이고, 평가에서 빼지 않는다

표를 W4에 한 번 돌려 `docs/str/08`과 발표 자료에 남긴다. 미달 → 태깅·청크 크기·`MIN_SIMILARITY` 조정. **11/11(화)까지 표가 없으면 안건 22 되돌림: REFERENCES를 `(없음)`으로 고정하고 2차로.** 코드는 지우지 않고 플래그(`RAG_ENABLED=false`, `Retriever(enabled=False)` → 항상 `[]`)로.

### RAG 켬/끔 비교 — 같은 사건 (3차 검토 반영)

hit@3는 검색이 맞았는지만 본다. **초안이 실제로 나아졌는지**는 따로 본다. 픽스처 facts 5건(유형 5개) × `RAG_ENABLED=true/false` 각 1회 생성(온도 0, 같은 few-shot, verify 평가자는 207 `votes=3` 중앙값) → 표 (SCRUM-126 ★L-2, 2026-11-12):

| 사건 | 유형 | 코드 5 통과 | `TYPOLOGY_CONSISTENT` | `NO_UNSUPPORTED_CLAIM` | `FIVE_W_ONE_H_COMPLETE` | GROUNDS 신호 언급 | status | 반입(unsupported) | references (ON) |
|---|---|---|---|---|---|---|---|---|---|
| case_1_fan_in | FAN_IN | ON ✓ · OFF ✓ | 5 · 5 | 5 · 5 | **4 · 5** | 1 · 0 | PASSED · PASSED | 0 · 0 | fincen-funnel p.3·p.2·p.1 |
| case_2_fan_in | FAN_IN | ON ✓ · OFF ✓ | 5 · 5 | 5 · 5 | 5 · 5 | 0 · 0 | PASSED · PASSED | 0 · 0 | fincen-funnel p.3·p.2, ffiec p.2 |
| case_3_fan_out | FAN_OUT | ON ✓ · OFF ✓ | 5 · 5 | 5 · 5 | **4 · 5** | 0 · 0 | PASSED · PASSED | 0 · 0 | ffiec p.5·p.7·p.7 |
| case_4_cycle | CYCLE | ON ✓ · OFF ✓ | 3 · 3 | 5 · 5 | 4 · 4 | 0 · 0 | LLM_FAILED · LLM_FAILED | 0 · 0 | ffiec p.6·p.6 |
| case_5_scatter_gather (대조군) | SCATTER_GATHER | ON ✓ · OFF ✓ | **3 · 5** | 5 · 5 | **5 · 4** | 1 · 1 | **LLM_FAILED · PASSED** | 0 · 0 | — (태그 0청크·입력 동일) |

**사람 선호 (블라인드)** — 세 사람(**AI 보조 판단(진희 확인)** · 준영 · 채영) 이 어느 쪽이 RAG 인지 모르고 A/B 중 고름. 선택표 4칸: 선택·유형 설명·반입(규칙 8 금지)·한 줄 이유. 대조군 SG(case_5) 제외 **12표** 집계: **끈 쪽 8 · 켠 쪽 2 · 같음 2**. case_2·case_3 는 세 사람 모두 끈 쪽(3/3). **반입 0** — 세 사람 모두 "A·B 어느 쪽도 참고 사례 금액·이름·국가 반입 없음". `unsupported_candidate_count`(영문 대문자·숫자) 도 10 초안 전부 0.

**대조군 SG 쌍 차이 = 흔들림 기준선** — 입력 동일(`references=[]`·query 는 SG 태그 0청크 적중)인데 TYPO 3 vs 5, status LLM_FAILED vs PASSED 로 갈림. 207 case 23 verify 흔들림과 같은 성격. SCRUM-131 재검토.

**결론 (★B)** — "지금 프롬프트에선 RAG 가 초안을 낫게 하지 않음(facts 를 덜 씀, FIVE_W case_1·3 ON 쪽 1점 낮음) — 반입은 없음. 프롬프트 v3 로 참고 사례 역할 좁혀 재비교(후속 이슈), 화면 참고 사례는 유지. SG 대조군 판정 흔들림은 SCRUM-131."

해석 전제: **n=5·1회, 방향성 근거, SG 쌍 차이(흔들림)와 비교**. 1차 판단자는 AI 보조(진희 확인), 2차는 준영·채영. RAG 를 켠 쪽이 `NO_UNSUPPORTED_CLAIM` 을 떨어뜨리진 않음(5·5·5·5·5 일치) — 규칙 8 반입 방어는 유지됨. 되돌림 조건(11/11 hit@3 표)은 **11/3 결정으로 폐기**(2차 전환 아님 — 프롬프트 역할 좁힘). 결과 `08`·발표 자료에 반영.

### RAG 켬/끔 2차 — narrative_v3 (SCRUM-225)

1차 결론을 받아 프롬프트를 고친 뒤(`05` narrative_v3 — 규칙 8 GROUNDS 한 문장으로 좁힘·규칙 12 facts 필수 항목·REFERENCES 2건×패턴 문장) **같은 facts 5건 × 켬/끔 1회**를 `NARRATIVE_PROMPT=narrative_v3` 로 다시 돌림. 모델·평가자(judge_v3, votes=3)·few-shot 선택 규칙·픽스처는 1차와 같음. `rag_onoff_live` 는 고쳐 쓰기를 거치지 않으므로 v3 고쳐 쓰기 미적용(`05`)은 비교에 영향 없음.

**하네스 고침(재비교 전에)** — 1차에서 알고 남긴 두 건:

- **결과 JSON 분리**: 선택 확정 전 공개용 `rag_onoff_<stamp>.json` 에는 A/B 지표(코드 검사·평가자 점수·커버리지·`unsupported_candidate_count`)만. `retrieval_status`·`references`·`references_count` 는 **진단 파일** `rag_onoff_diag_<stamp>.json` 으로 따로, reveal 단계에서 블라인드 키와 같이 엶. 결과에 `retrieval_status` 가 없는 새 형식은 reveal 에 진단 파일이 **필수**이고 모든 사건 × A/B 진단이 있어야 함 — 하나라도 없으면 멈춤(검색 실패 초안이 ON 표본으로 섞이지 않게, 추가 검토 1차). 126 옛 형식만 두 인자 호출 허용. 테스트: 공개용 JSON 만으로 A/B→ON/OFF 를 맞힐 수 있는 칸이 없음.
- **사후 파서 여러 줄**: 블라인드 md 섹션 본문의 둘째 줄부터를 다음 섹션·구분자 전까지 이어 붙임. 테스트: `_blind_md` 로 쓴 md 를 다시 읽어 본문 글자와 `unsupported_candidate_count` 가 같음(둘째 줄에 영문 이름 넣은 경우 포함).

**facts 커버리지**(`tests/str/rag_onoff_coverage.py` `fact_coverage(narrative, facts)` 순수 함수) — 규칙 12 필수 항목 중 본문에 나온 비율. 찾는 범위는 observations 값·관측 구간만 **GROUNDS 본문**, 나머지는 7섹션 전체(DATE 의 거래 날짜·다른 섹션 숫자가 관측값 누락을 가리지 않게 — 추가 검토 1차). 코드는 원문 일치(`SALES_DEPOSIT`), 숫자는 쉼표 무시(`42,750.50` = `42750.50`), 건수는 방향 낱말 뒤 20자 안의 첫 `{n}건`(예: "출금 거래는 0건이며"·"내부 거래는 0건") 또는 거꾸로 `{n}건` 바로 뒤 3자 안에서 시작하는 방향 낱말(예: "3건이 입금"·"0건 출금" — "0건이며 입금"처럼 더 멀면 안 셈, 입금·출금 숫자 섞임 방지), 관측 구간은 `window_start`·`window_end` 의 날짜. null·빈 항목은 분모에서 뺌. **한계**: 코드를 한국어로만 옮겨 쓴 경우("매출대금 입금")는 못 셈(09). 1차(v2 끔) 기준선은 결과 JSON 에 본문이 없어 블라인드 md + 키로 소급 계산.

**성공 기준 (고치기 전에 고정 — 결과 보고 바꾸지 않음)**:

1. ~~블라인드: v3 켬이 v3 끔과 **동률 이상**(대조군 제외 표 수)~~ → **이번엔 생략**(진희 11/12, ★L-2 결과 파일을 열기 전 기록). 팀원 의견상 v2·v3 모두 서술이 구체적이지 않아 켬/끔 사람 선호 비교는 의미가 없음. 사람 평가는 다음 버전(narrative_v4) vs v2 에서 함. 하네스가 만든 블라인드 md 는 그대로 두되 배포하지 않음. **판정은 기준 2·3·4 로만**
2. 평가자: v3 켬 점수가 v3 끔·v2 끔보다 낮지 않음(`FIVE_W_ONE_H_COMPLETE` 포함), 코드 검사 전부 통과
   - 비교 단위: 기준별(`TYPOLOGY_CONSISTENT`·`NO_UNSUPPORTED_CLAIM`·`FIVE_W_ONE_H_COMPLETE`) **5건 중앙값 점수의 합계**. v3 켬 합계 ≥ v3 끔 합계, v3 켬 합계 ≥ v2 끔 합계(1차 v2 끔: TYPO 23 · NO_UNSUPPORTED 25 · FIVE_W 23). `LLM_FAILED` 건도 점수 그대로 합산. 코드 검사는 5건 전부 통과
   - COUNT_MATCH PLACE 에서 상대 계좌 총수를 자행 수로 읽은 불일치(09 검사기 오판)는 사건별로 따로 적고 판정에서 뺌. 그 외 코드 검사 불일치는 0 이어야 통과. v3 켬·v3 끔·v2 끔에 같은 규칙
3. 반입 0 — ~~사람 "반입" 칸~~(블라인드 생략으로 없음) → **`unsupported_candidate_count` 0 + GROUNDS 유형 이유 문장·METHOD 문장 원문 확인**(참고 사례의 숫자·이름·기관·국가·날짜·기준 금액이 들어왔는지). 원문 확인은 "AI 보조 확인(진희 확인)"으로 표기(진희 11/12, 결과 열기 전 결정)
4. 규칙 12 커버리지: v3 켬 ≥ v2 끔
   - 비교 단위: 5건 합산 `covered ÷ required`
5. 기준 2·3·4 중 하나라도 못 넘으면 초안 프롬프트엔 참고 사례를 넣지 않음(REFERENCES 렌더링 끔, 화면 표시는 유지) — 09 에 기록

**표** (★L-2 `narrative_v3_20261112-141001`, 2026-11-12 — 숫자는 결과 파일 원본 값만. 평가자는 사건 1~5 순서 중앙값 · 합계):

| 줄 | 코드 5 통과 | 검사기 오판 | TYPO | NO_UNSUPPORTED | FIVE_W | 커버리지 | 반입 | status |
|---|---|---|---|---|---|---|---|---|
| v3 켬 | 5/5 (오판 뺀 불일치 0) | 5 (사건마다 PLACE 1) | 5·5·5·4·5 (합 24) | 5 전부 (합 25) | 4·5·5·5·4 (합 23) | 70/70 | 0 | PASSED 5 |
| v3 끔 | 5/5 (오판 뺀 불일치 0) | 5 (사건마다 PLACE 1) | 5·5·5·1·5 (합 21) | 5 전부 (합 25) | 4·4·4·4·4 (합 20) | 70/70 | 0 | PASSED 4 · LLM_FAILED 1 (case_4) |
| v2 끔 (1차) | 5/5 | 0 | 5·5·5·3·5 (합 23) | 5 전부 (합 25) | 5·5·5·4·4 (합 23) | 65/70 (소급) | 0 | PASSED 4 · LLM_FAILED 1 |

커버리지 소급(1차 블라인드 md + 키, 관측값 GROUNDS 한정으로 다시 셈 — 값 그대로): v2 끔 65/70 · 참고로 v2 켬 61/70 — 켠 쪽 누락은 계좌 목적 3·amount_range 4·내부 거래 1·반대 방향 0건 1.

검색 진단: 켬 쪽 case_1~4 `ok`(참고 사례 2건씩 — case_1·2 fincen-funnel p.3·p.2, case_3 ffiec p.5·p.7, case_4 ffiec p.6·p.6), case_5 SG `empty`(태그 0청크, 대조군), 끔 쪽 5건 `disabled`, failed 0. 검사기 오판 10건 모두 `COUNT_MATCH PLACE draft "3개" / source {0}`("상대 계좌는 3개이며 자행 (계좌) 0개…").

**성공 기준 판정** (기준 1 블라인드는 생략):

- 기준 2 **통과** — v3 켬 vs v3 끔: TYPO 24 ≥ 21 · NO_UNSUPPORTED 25 ≥ 25 · FIVE_W 23 ≥ 20. v3 켬 vs v2 끔: TYPO 24 ≥ 23 · NO_UNSUPPORTED 25 ≥ 25 · FIVE_W 23 ≥ 23. 코드 검사 오판 뺀 불일치 0(5/5)
- 기준 3 **통과** — `unsupported_candidate_count` 켬 0·0·0·0·0. 켬 쪽 GROUNDS 유형 이유·METHOD 원문에 참고 사례의 숫자·이름·기관·국가·날짜·기준 금액 없음 — AI 보조 확인(진희 확인)
- 기준 4 **통과** — 커버리지 v3 켬 70/70 ≥ v2 끔 65/70

**해석**:

- 켬 쪽 GROUNDS 유형 이유 문장이 확인할 점(자금 출처·거래 목적 연관성, 사업활동 관련성, 수취인 식별정보)을 담고, 끔 쪽은 유형 설명의 동어반복 — v3 목표(참고 사례는 유형 이유 한 문장에만) 달성
- TYPO 차이 +3 은 대부분 case_4 끔 LLM_FAILED 1건(TYPO 1, 1회 실행), FIVE_W 차이 +3 은 사건 2·3·4 에 고르게. 커버리지 상승(65→70)은 규칙 12 효과(v3 끔도 70/70)
- 한계: n=5·1회, 픽스처 5건이 같은 고객·금액의 변형이라 다양성 낮음 — 방향성 근거

METHOD 사람 대조(09 추가 검토 2차 ①): 켬·끔 10건 METHOD·INSTRUMENT·SUBJECT 원문의 건수·금액·코드가 모두 FACTS 값 — 커버리지 오탐 0.

## 다중 질의·합치기 (SCRUM-146, 2026-11-18 — 붙이되 기본 끔)

2차(「RAG 2차 — 방향 설계」 5.2 하이브리드 + 다중 질의)에서 그대로 쓸 **"여러 후보 목록 → 합치기" 층**을 지금 만든다. **기본 끔** — 시연 경로(초안 생성)의 검색 결과는 develop 과 같다(09 같은 날 줄). SCRUM-275(Elasticsearch 키워드)는 이 층에 **후보 목록 하나**로 들어온다.

```
facts → 검색어 N개(상한 RAG_MAX_QUERIES) → 임베딩 한 번에(embed([...]) 배치 1회) → 검색어별 후보 목록(지금 SQL 그대로, 후보 RAG_CANDIDATES)
      → RRF 합치기 · chunk_id 중복 제거 → MIN_SIMILARITY(합친 뒤, 최대 cosine) → 상위 RAG_TOP_K
```

- **검색어 만들기**(`str/domain/` 새 파일, 순수 — DB·LLM·설정 0): `(언어, 문장)` 목록, 상한 `RAG_MAX_QUERIES = 3`
  - (a) 지금 `build_query(facts)` 한 줄 **그대로** — 첫 번째 검색어 = 기준선 질의(테스트로 고정)
  - (b) 유형 영문 패턴 문장만(`TYPOLOGY_PATTERN_EN[typology]`) — (a) 안에도 같은 패턴 문장이 들어 있어 RRF 가 패턴 쪽에 가중됨(알고 남김 — 기본 끔이라 2차 평가 세트에서 봄)
  - (c) facts 특징 영문 문장 — 숫자·계좌·금액 없이 범주만(아래 ★A 표). 쓸 칸이 하나도 없으면 (c) 없음(빈 문장 안 만듦)
  - 한국어 문장 칸은 **모양만** 둔다(지금 코퍼스 영문 7 · 국문 1). 벡터 검색은 영문만 보낸다. 275 키워드는 언어별로 고른다
  - `build_query`·`TYPOLOGY_PATTERN_EN` 위치(지금 `infrastructure/retriever.py`)는 02 구조 규칙대로 — 옮기면 import 경로만, 문장 0 변경
- **임베딩**: 검색어 N개를 한 번의 `embed([...])` 로. 외부 호출 중 DB 연결을 들고 있지 않음(SCRUM-122) — 임베딩이 끝난 뒤 검색. 실패는 지금처럼 `RetrievalUnavailable` → `[]`
- **검색**: 검색어마다 위 "검색" 절 SQL 그대로. 평가용 인자 `typology_filter: bool`(기본 True — 끄면 `WHERE typologies @>` 없이). **초안 경로는 늘 True**
- **합치기**(`str/domain/` 순수): 입력 = **후보 목록 여러 개** `list[list[(chunk_id, rank, cosine)]]`(목록마다 1부터 순위). RRF 점수 = Σ 1 / (`RAG_RRF_K` + rank), `RAG_RRF_K = 60`(Cormack·Clarke·Büttcher 2009). 정렬: RRF 큰 순 → 같으면 그 청크의 최대 cosine 큰 순 → 그래도 같으면 `chunk_id` 오름차순(결정적). `chunk_id` 하나에 한 번. 275 키워드 목록도 같은 입력 모양(순위만 있고 cosine 이 없으면 — 275 에서 정함)
- **`Reference.score` = 지금처럼 cosine 유사도**(그 청크가 여러 목록에서 받은 값 중 최대). RRF 점수는 안에서 순서만 정하고 밖(`generation_meta.references`·`generations.references`·화면)에 내보내지 않음 — 규약·`references` 모양·`retrieval_version` 형식 그대로
- **스위치**: 상수 `domain/constants.RAG_MULTI_QUERY = False` + `Retriever(..., multi_query=...)` 인자(기본 = 상수). `.env` 아님 — 시연 전 켤 일이 없음(judge_v4 스위치와 같은 판단). **평가 하네스만 True 로 부른다.** 끔이면 질의 문장·SQL·결과가 develop 과 같음(기존 retriever 테스트 수정 0 + "끔이면 임베딩 1회·검색 1회" 테스트)
- **켤 기준**(09 같은 날 줄 — 결과 보기 전 기록): 이번 실측과 관계없이 기본은 끔. 2차 평가 세트(30~50개, 보류용 질의 포함)에서 **유형 필터 끈 조건의 recall@10 상승 + 정답 없는 질의 오탐 증가 없음**일 때 켬 → **2026-11-19 SCRUM-275 로 대체**: 합치기 층은 지금 경로에 켜지 않고 "빈칸만 채우기"의 채우는 쪽으로만 씀(아래 절 · 09 같은 날 줄). `RAG_MULTI_QUERY` 상수는 평가 하네스용으로 그대로
- **v4 에서 참고 사례 쓰임**: **화면 표시만(본문 영향 없음)** — `narrative_v4_builder` 는 본문에 안 쓰고 요청 기록에 `reference_ids`(doc_id)만 남김. 응답 `generation_meta.references` 는 `draft_service` 가 검색 결과로 채움 → 화면(문서명·쪽·점수, SCRUM-252). v2·v3 는 프롬프트 REFERENCES 에 들어감(v3 는 앞 2건 발췌, 위 "프롬프트에서")

### ★A — 검색어 (c) 에 쓸 facts 칸 (제안, 숫자·계좌·금액 0)

범주 낱말만 쓰고, 칸 값에서 바로 나오는 것만(추정·판단 낱말 없음). 순서대로 이어 한 문장(영문). 쓸 조각이 없으면 (c) 없음.

| facts 칸 | 범주 → 영문 조각 | 쓰나 | 이유 |
|---|---|---|---|
| `direction` | INBOUND → `incoming funds only` · OUTBOUND → `outgoing funds only` · MIXED → `both incoming and outgoing funds` · INTERNAL → (없음) | **씀** | 방향은 FAN_IN·FAN_OUT 코퍼스 문단의 핵심 낱말. INTERNAL 은 코퍼스에 대응 문단 없음 |
| `counterparties.count` | 0 → (없음) · 1~2 → `few counterparties` · 3~9 → `several counterparties` · 10 이상 → `many counterparties` | **씀** | 숫자 대신 규모 범주(경계는 상수로 — R02 송금인 5·R01 수취인 10 과 따로, 검색어 전용) |
| `payment_formats` | IBM 원문 7종 → 영문 낱말(`Wire` → `wire transfers` · `ACH` → `ACH transfers` · `Cash` → `cash` · `Cheque` → `cheques` · `Credit Card` → `credit card payments` · `Bitcoin` → `virtual currency` · `Reinvestment` → (없음)), 여러 개면 `via A and B` | **씀** | 적색신호 문단(FFIEC·FinCEN)이 결제 수단 낱말로 쓰임. Reinvestment 는 코퍼스 대응 낱말 없음 |
| `counterparty_banks.other_bank_accounts` > 0 | `accounts at other financial institutions` | **씀** | 퍼널 계좌(FinCEN 2014) 문단 낱말. 0 이면 없음 |
| `inbound.by_currency` ∪ `outbound.by_currency` 통화 종류 ≥ 2(또는 `unmapped_currencies` 있음) | `multiple currencies` | **씀** | TBML·국제 송금 문단 낱말. 통화 이름·금액은 안 씀 |
| `paths` VERIFIED | CYCLE → `funds routed through intermediary accounts` · SG → 같음 | 보류 | (b) 유형 패턴 문장과 거의 같은 뜻 — 검색어가 겹쳐 RRF 가 한쪽으로 쏠림. 2차 평가 세트에서 다시 |
| `internal.count` > 0 | `transfers between related accounts` | 보류 | "내부 = 같은 법인" 은 facts 04 의 정의(코퍼스의 related accounts 와 다를 수 있음) — 뜻이 어긋날 위험 |
| `customer.account_purpose` | 사전 영문 대응(예: SALES_DEPOSIT → `business sales deposits`) | 보류 | 영문 대응표가 없음(표기 사전은 한국어만) — 새 사전이 필요 |
| 금액·합계·`amount_range`·`period`·계좌·`transaction_ids`·`prior_alert_count`·`observations`(값)·`customer.onboarded_at`·`risk_level` | — | 안 씀 | 숫자·계좌·금액 금지(지시서) · 과거 경보·위험등급은 코퍼스 문단과 무관 · `model_signals`·`industry` 는 이미 (a) 에 있음 |

### 코퍼스 크기 (11/18, 읽기 전용 SQL — 진희 실행)

| 문서 | 언어 | 청크 수 | 태그 빈 청크 | 글자 수 | 청크 평균 글자 |
|---|---|---|---|---|---|
| `fatf-pml-2018` | en | 92 | 88 | 140,434 | 1,526 |
| `fatf-tbml-2006` | en | 68 | 68 | 103,167 | 1,517 |
| `fatf-tbml-2020` | en | 117 | 117 | 174,644 | 1,493 |
| `ffiec-redflags` | en | 15 | 2 | 24,333 | 1,622 |
| `fincen-funnel-2014` | en | 10 | 0 | 15,844 | 1,584 |
| `fincen-money-mule-2020` | en | 13 | 13 | 19,323 | 1,486 |
| `fincen-msb-ko-2007` | ko | 60 | 60 | 38,450 | 641 |
| `fincen-sar-narrative-2003` | en | 50 | 50 | 59,114 | 1,182 |
| **전체** | en 7 · ko 1 | **425** | 398 (태그 27 · 6%) | 575,309 (en 536,859 · ko 38,450) | 1,354 |

토큰은 미측정(`tiktoken` 없음) — 언어별 글자 수로 대신. 태그 27 = `fatf-pml-2018` 4 · `ffiec-redflags` 13 · `fincen-funnel-2014` 10.

| 유형 태그 | 청크 수 |
|---|---|
| FAN_IN | 19 |
| FAN_OUT | 6 |
| CYCLE | 2 |
| SCATTER_GATHER | 0 |
| GATHER_SCATTER | 0 |

- **태그 청크 27/425(6%)** — 유형 필터 켬 조건은 후보가 거의 고정(FAN_IN 19 · FAN_OUT 6 · CYCLE 2)이라 다중 질의 비교가 의미 없음. **볼 숫자는 필터 끔 조건**
- **토큰은 미측정**(`tiktoken` 없음) — 글자 575,309(en 536,859 · ko 38,450). 2차 "자료 확장 먼저"의 근거

### 기준선 (11/18, `rag_baseline_live` — 결과 보기 전 자리)

조건 4개 = {한 번 찾기, 여러 번 찾기} × {유형 필터 켬, 끔}, 질의 10개 그대로(`retrieval_eval.json` 수정 0). 지표(판정용, 위 "판정 기준"): hit@3(엄격) · recall@3 · **recall@10**(한 번 = top-10, 여러 번 = 합친 순위 top-10) · 정답 없는 질의 2개의 top-3 최대 cosine · 조건별 임베딩 호출·검색어 수. **해석은 "만점 세트라 개선 판정 못 함 · 방향만"**.

**기록(판정에 안 씀 — 2차 비교 재료, 11/18 진희 추가)**:
- 질의별·조건별 **top-10 원자료**(평균만 남기지 않음)
- 정답 청크가 **필터 끔 전체 425개 중 몇 등**인지(10등 밖이어도) — 검색어 벡터마다, 그리고 여러 번 찾기는 전체 순위 목록을 RRF 로 다시 합친 순위
- 정답 없는 질의 2개: **top-10 cosine 분포**(최소·사분위·중앙·최대)
- 검색어 조합 **{a}·{a,c}·{a,b,c}** — 하네스 인자로 바꿔 돌림. (a)·(b) top-10 **겹침을 정답 / 오답 청크로 나눠** 기록(위 "RRF 가 패턴 쪽에 가중" 확인용)
- 언어: 조건별 top-10 안 **국문 청크 수** · **언어별 cosine 분포**(필터 끔 전체 순위 기준) · 언어별 글자 수(토큰 대신)
- 필터 켬 질의의 **`EXPLAIN`(ANALYZE 없이, 읽기 전용)** 유형별 1번 — 지금 `relaxed_order` 라 깨진 게 아니라 2차 비교용 기록

**결과 파일은 리포에 커밋**(1차 "기준선 얼려 두기"): `tests/str/rag_baseline_20261118.json`. 청크마다 `chunk_id` 만 쓰지 않고 **`doc_id` · `page` · 쪽 안 순번**(같은 `doc_id`·`page` 안에서 적재 순서로 몇 번째 — 적재 도구와 같은 청크 나누기(`tools/corpus_chunks.chunk_pdf_pages`)를 PDF 에 다시 돌려 `content_hash` 로 맞춤, 임베딩·DB 쓰기 0. 적재는 한 트랜잭션이라 `created_at` 으로는 순서를 못 앎)과 `lang` 을 같이 — 2차에서 청크를 다시 자르면 `chunk_id`(= `content_hash`)가 전부 바뀌어 기준선 비교가 안 되기 때문. 정답 청크도 같은 칸. **정답 위치는 doc_id·page·쪽 안 순번으로 다시 찾을 수 있음(원문 지문은 이용 조건 때문에 안 남김).** PDF 가 없는 문서는 순번 칸 비우고 이유를 적음. 함께 남기는 것: 설정값 `RAG_CANDIDATES`·`RAG_TOP_K`·`MIN_SIMILARITY`·`REFERENCE_TEXT_MAX_CHARS`·`RAG_RRF_K`·`RAG_MAX_QUERIES` · `retrieval_version` · 임베딩 모델 이름 · 코퍼스 manifest 해시. 토큰 수는 이번에 안 함(`tiktoken` 없음).

**결과(11/18 진희 터미널, 검색어 {a,b,c})** — 정답 있는 질의 8개, 지표는 유형별 평균의 평균(macro, 지금 평가와 같은 방식). 임베딩 호출 = 배치 호출 수(질의마다 1회 — 검색어 수와 무관).

| 조건 | hit@3 | recall@3 | recall@10 | 정답 없는 질의 top-3 최대 cosine (Q09 · Q10) | 임베딩 호출 · 검색어 |
|---|---|---|---|---|---|
| 한 번 · 필터 켬 (지금 초안 경로) | 1.000 | 0.741 | 0.944 | 결과 0건 · 0건 | 10 · 10 |
| 한 번 · 필터 끔 | 0.000 | 0.000 | 0.037 | 0.477 · 0.392 | 10 · 10 |
| 여러 번 · 필터 켬 | 1.000 | 0.741 | 0.907 | 결과 0건 · 0건 | 10 · 30 |
| 여러 번 · 필터 끔 | 0.167 | 0.167 | **0.611** | 0.526 · 0.526 | 10 · 30 |

검색어 조합별 recall@10(macro) — 여러 번 찾기만 달라짐:

| 조합 | 여러 번 · 필터 켬 | 여러 번 · 필터 끔 |
|---|---|---|
| {a} (= 한 번 찾기와 같음) | 0.944 | 0.037 |
| {a,c} | 0.889 | 0.241 |
| {a,b,c} | 0.907 | 0.611 |

파일: `tests/str/rag_baseline_20261118.json`({a,b,c}) · `rag_baseline_20261118_ac.json` · `rag_baseline_20261118_a.json`. 실행 한 번에 임베딩 호출 50 = 조건 4개 × 질의 10(배치 1회씩) + (a)·(b) 겹침 진단 10 — 검색어 조합과 무관.

**진단(판정 아님 — 2차 비교 재료)**:
- **정답 청크(2점) 중 가장 앞 순위, 필터 끔 · 425개 중**: 한 번 찾기 FAN_IN 7~16 · FAN_OUT 26·52 · CYCLE 123·160 → 여러 번 찾기(RRF) FAN_IN 5~6 · FAN_OUT 4·10 · CYCLE 12·14. 검색어별로는 (b) 4~5 · (c) 2~7 · (a) 7~160 — 필터 끄면 (a)(지금 질의)가 가장 약함
- **top-10 안 국문 청크**: 한 번 · 필터 끔 30개(질의 10 × 3) · 여러 번 · 필터 끔 12 · 필터 켬 0(국문 문서는 태그 없음). 필터 끔 전체 순위의 언어별 cosine(질의 Q01 (a)): en 365개 중앙 0.267 · 최대 0.448 / ko 60개 중앙 0.270 · 최대 0.361 — 국문 청크가 영문과 비슷한 대역이라 필터 끄면 위로 올라옴
- **(a)·(b) top-10 겹침**(질의 10개 합): 필터 켬 정답 31 · 오답 18 / 필터 끔 정답 4 · 오답 36 — 필터 끄면 겹치는 청크 대부분이 오답(위 "RRF 가 패턴 쪽에 가중"은 필터 끔에서 오답 쪽으로 작용할 수 있음)
- **정답 없는 질의 top-10 cosine**: 필터 끔 한 번 Q09 0.386~0.477(중앙 0.397) · Q10 0.345~0.392(중앙 0.354) / 여러 번 Q09 0.393~0.610(중앙 0.483) · Q10 0.367~0.609(중앙 0.412). 필터 켬은 결과 0건(태그가 없는 유형)
- **EXPLAIN(필터 켬, 유형 5개)**: 다섯 유형 모두 `Bitmap Index Scan on ix_reference_chunks_typologies`(GIN) → `Sort` — **HNSW 인덱스는 안 탐**(태그 청크가 적어 플래너가 유형 필터 먼저 + 정렬을 고름). 결과는 정확한 거리 순서라 지금 문제 아님
- **알고 남김**: 평가 질의 10개는 같은 픽스처(`facts_fan_in.json`)에서 유형·신호·업종만 바꾼 것이라 **(c) 문장이 10개 모두 같음**("incoming funds only, several counterparties, via ACH transfers, accounts at other financial institutions") — (c) 의 순위 개선은 질의별 facts 차이를 반영한 게 아님. 2차 평가 세트는 질의마다 facts 를 달리해야 (c) 를 볼 수 있음

## 빈칸만 채우기 · ES 키워드 · 평가 세트 (SCRUM-275, 2026-11)

11/18 원칙 "시연 경로 검색 결과는 바꾸지 않는다"를 **"지금 결과는 그대로 두고 빈칸만 채운다, 측정으로 판정해 통과하면 기본 켬"** 으로 바꾼다(09 2026-11-19 SCRUM-275 줄). 판정 전까지 **기본 끔**.

### 규칙 (세 개 — 이것만)

1. 지금 경로(한 번 찾기 · 유형 필터 켬 · 위 "검색" 절 SQL 그대로)의 결과를 **순서·`chunk_id`·`score` 그대로 앞에** 둔다
2. `RAG_TOP_K`(3)건이 안 찼을 때만, **필터 끈 합치기**(벡터 검색어 여러 개 + ES 키워드) 결과로 남는 칸을 채운다. 이미 있는 `chunk_id` 는 건너뜀
3. 지금 경로가 **0건이면 채우지 않고 0건**(태그 없는 유형 — SCATTER_GATHER·GATHER_SCATTER·FX_RELAY 등)

- 지금 결과가 늘 앞이라 hit@3 이 떨어질 수 없고, 0건 유형은 계속 0건이라 cosine 컷오프 없이 오탐이 생기지 않는다(정답 없는 질의 cosine 0.35~0.61 이 정답 쪽과 같은 대역 — 위 기준선).
- **지금 코퍼스에서 규칙 2가 도는 유형은 CYCLE 하나**(11/19 읽기 전용 SQL): 태그 청크 FAN_IN 19 · FAN_OUT 6 · CYCLE 2 · 그 밖 0 → 지금 경로 결과 FAN 3건 · CYCLE 2건 · 그 밖 0건. **CYCLE 사건의 참고 사례 칸이 2건 → 3건**(화면 캡처·시연 대본 다시 맞춤), FAN 은 그대로, 0건 유형도 그대로.
- **v4 경로에만**(`NARRATIVE_PROMPT=narrative_v4`). v2·v3(참고 사례를 프롬프트에 넣음)는 지금 검색 그대로 — `DraftService.build` 가 `RAG_GAP_FILL_ENABLED and narrative_prompt == narrative_v4` 를 `Retriever(..., gap_fill=)` 로 넘김. Retriever 인자 기본 `gap_fill=False`(기존 retriever 테스트 수정 0).

### 흐름

```
facts → (a) build_query 임베딩 1회 → PG 1차(필터 켬, 지금 SQL) → n건
   n = 0          → []                                 (규칙 3 — 추가 호출 0)
   n = RAG_TOP_K  → 그대로                              (규칙 1 — 추가 호출 0)
   0 < n < K, gap_fill 켬
     → release()  (DB 연결 반납 — SCRUM-122, 외부 호출 중 연결 안 듦)
     → 검색어 (b)(c) 임베딩 1회(배치) + ES 키워드(언어별, 짧은 타임아웃)
     → PG 2차(필터 끔, 별도 짧은 세션): 벡터 검색어 (a)(b)(c) 마다 후보 RAG_CANDIDATES + 키워드로만 찾은 청크의 (a) cosine
     → RRF 합치기(rag_fusion.rrf_fuse 그대로) → 1차 chunk_id 건너뜀 → 남는 칸만 → 1차 + 채운 칸
```

- **채운 청크의 `score` = (a) 검색어 기준 cosine**(`1 - (embedding <=> (a)벡터)`) — 키워드로만 찾은 청크도 PG 2차에서 이 값을 계산. RRF 점수는 안에서 순서만, 밖에 안 나감(규약·`references` 모양 그대로). 키워드 목록은 RRF 에 **순위만** 넣는다.
- `MIN_SIMILARITY` 는 지금처럼 0.0(채운 칸에도 같은 값 적용 — 컷오프는 2차).
- **ES 키워드 검색어 — 언어별**: 영문 검색어는 `lang=en` 청크의 `text_en` 에만, 국문 검색어는 `lang=ko` 청크의 `text_ko` 에만(`match`, 결과 `RAG_CANDIDATES` 개, 목록 둘). 문장은 개발용 질의 실험(아래 "판정 순서" 2)으로 고르고 09 에 적는다 — 출발점: 영문 = (b) 유형 영문 패턴, 국문 = `TYPOLOGY_KO[유형]` + 국문 패턴(새 상수). 숫자·계좌·금액 0.

### 실패하면 (fail-open — 각각 테스트)

| 실패 | 결과 |
|---|---|
| ES 타임아웃 · 연결 실패 · 401 · 404(색인 없음) · `ELASTIC_PASSWORD` 빈 값 | 키워드 목록 없이 벡터 목록만으로 채움. 경고 1줄(`keyword_unavailable reason=…`, 값·본문 없음) |
| (b)(c) 임베딩 실패 · PG 2차 실패(연결 끊김 포함) · 합치기 층 예외 | **1차 결과만** 반환(경고 1줄). PG 2차는 `draft_service` 가 주입한 같은 엔진의 **별도 짧은 세션**에서만 돌아, 실패해도 그 세션만 닫히고 초안 세션은 1차 상태 그대로(추가 검토 1 — 공유 세션이면 연결이 끊긴 뒤 다음 `end_read` 에서 초안 전체가 실패) |
| (a) 임베딩·PG 1차 실패 | 지금처럼 `RetrievalUnavailable` → `[]` |

색인 문서 수와 DB 행 수가 다른지는 **색인 도구에서만** 확인(요청마다 `_count` 안 부름 — 시간).

### Elasticsearch 연결

- 백엔드 compose 의 `elasticsearch`(9.5.6, 보안 켬, `elastic` 계정, `ops` 프로필, 호스트 포트 없음). AI 컨테이너는 `dajaba_default` 네트워크에서 `elasticsearch:9200`. AI 리포 compose 는 `env_file: .env` — 백엔드 리포 변경 0.
- 클라이언트: **기존 `httpx` 로 REST 직접**(`_search`·`_bulk`·색인 생성/삭제·`_count` 뿐 — 새 라이브러리 0). 설정 이름·기본값은 `shared/05` "RAG" 표. 비밀값은 `.env` 만, 로그에 값 0.
- **원본은 PostgreSQL, ES 에는 검색 색인만**. 색인 도구 `tools/index_es.py`: `ai.reference_chunks` 를 읽어 색인을 지우고 다시 만든 뒤 `_bulk` → `refresh` → `_count` = DB 행 수(다르면 종료 코드 1). 실행은 AI 컨테이너 안(호스트에서 ES 에 못 닿음).

| 필드 | 타입 | 비고 |
|---|---|---|
| `chunk_id` (= `_id`) | keyword | DB `chunk_id` |
| `doc_id` · `lang` · `typologies` | keyword | |
| `page` | integer | |
| `text_en` | text, `english` 분석기 | `lang=en` 청크만 |
| `text_ko` | text, `cjk` 분석기(바이그램) | `lang=ko` 청크만. nori 는 이미지에 없음(플러그인 0개) → 2차 |

- **`_source` 에서 `text_en`·`text_ko` 제외** — 본문은 역색인에만, ES 에 원문을 저장하지 않음. 검색 응답에서 받는 건 `chunk_id`·순위뿐.

### 평가 세트 (30개, 합성 픽스처)

- facts 는 **합성 픽스처**(`tests/str/fixtures/facts_*.json` 모양) — 로컬 ops 경보는 전부 R02_FAN_IN 이라 유형이 안 나뉨. **질의마다 facts 범주를 달리**(industry·`model_signals`·방향·결제 방식·통화 수·상대 규모·다른 은행 계좌 유무) — 계좌·금액·이름 0. 11/18 기준선 질의 10개로는 검색어를 고르지 않음(탐색용 기록으로만).
- 배분 — **판정 분모가 CYCLE 의 채운 칸뿐이라 CYCLE 에 몰음**:

| 유형 | 개발용 | 보류용 | 합 | 보는 것 |
|---|---|---|---|---|
| CYCLE | 6 | 8 | 14 | 채운 칸 정답 비율 |
| FAN_IN | 2 | 2 | 4 | 지금 경로 결과 그대로 |
| FAN_OUT | 2 | 2 | 4 | 지금 경로 결과 그대로 |
| 정답 없음 (SCATTER_GATHER 3 · GATHER_SCATTER 3 · FX_RELAY 2) | 4 | 4 | 8 | 0건 유지 |
| 합 | 14 | 16 | 30 | |

- 파일: `tests/str/rag_eval_v2/queries_dev.json` · `queries_holdout.json`(질의 = 기존 facts 픽스처 + 범주 칸 overrides — industry·`model_signals`·방향·결제 방식·자행/타행 수) · `answers_dev.json` · `answers_holdout.json`.
- 정답 모양 — 위치(청크를 다시 잘라도 비교되게, 11/18 기준선과 같은 칸) **와** 지금 `chunk_id` 를 같이(판정 실행은 ES 때문에 AI 컨테이너 안에서 도는데 이미지에 PDF·pymupdf 가 없어 위치를 다시 못 셈 — 지금 청크로는 `chunk_id` 로 맞춤). **원문 0**:
  `{query_id, answers: [{chunk_id, doc_id, page, pos, grade}], draft, checked_by, checked_at}` — `pos` = 쪽 안 청크 순번, `grade` 2(그래프 패턴 직접) / 1(관련 약함), `draft` = `llm:rag_answer_v1` 또는 `human`. 표에 없는 청크는 0(오답).
- **초벌**: 질의마다 425 가 아니라 **(유형 × 청크) 한 번**(정답 있는 3유형 CYCLE·FAN_IN·FAN_OUT × 425) → 질의별로 facts 특징 때문에 갈리는 것만 사람이 고침. 프롬프트는 평가 도구용 `tools/prompts/rag_answer_v1.md`(서비스 프롬프트 폴더 밖 · 기동 해시 검사 대상 아님 · 결과 파일에 sha256 · 바꾸면 v2). 청크 본문을 외부 LLM(임베딩과 같은 공급자)에 보내는 건 **이용 조건 ⑤와 같은 처리로 봄**(09 2026-11-19) — 출력은 `doc_id`·`page`·`pos`·`grade` 만, 원문 반입 0.
- **정답 확인**: 설계자(진희)가 아닌 팀원 한 명이 **425개 전체**에서 확인(확인 칸·확인자·날짜). **2차 블라인드 태깅(`rag2/03_sampling.md`) 두 사람과 다른 사람**. 확인자는 확인 단계 전에 진희가 정함.
- **확인 범위(SCRUM-275-2, 09 2026-11-19)**: 판정에 쓰이는 정답은 보류용 채운 칸의 등급뿐이고 지금 채울 칸이 생기는 유형은 CYCLE 하나 → **CYCLE 은 425 전부**, FAN_IN·FAN_OUT 은 **LLM 등급 ≥ 1 행만** 사람이 봄(판정에 안 쓰임 · 개발용 실험 참고용). 정답 파일 질의 칸 `check_scope` 로 범위를 남김 — `all_chunks`(전부 봄) / `llm_positive_rows`(LLM 1·2 행만 봄, LLM 0 행은 사람 확인 없이 0). `checked_by`·`checked_at` 은 그 범위를 본 사람·날짜
- **한계**: 확인자는 시트에서 LLM 등급을 보고 확인함 — 그쪽으로 기울 수 있음. 정답은 유형 단위(같은 유형 질의는 같은 정답) — 등급 정의가 "그 유형의 계좌 구조가 청크에 있나"라 facts 범주와 무관하다고 봄(결제 방식·통화 같은 특징이 관련성을 바꾸는 경우는 안 잡음)

### 판정 기준 (정답 보기 전 — 09 2026-11-19 같은 줄)

아래를 **모두** 넘고 "켤 때 갖출 것"이 다 있으면 `RAG_GAP_FILL_ENABLED` 기본값을 `true` 로:

1. **채운 칸 중 정답(grade ≥ 1) 비율 ≥ 0.75** — **보류용 질의로만, 한 번**
2. **정답 없는 질의 8개 전부 0건** — 개발용 + 보류용(정답을 안 봐도 되는 코드 성질)
3. **지금 경로(한 번 · 필터 켬)의 상위 결과가 30개 질의 모두에서 순서·`chunk_id` 그대로** — 개발용 + 보류용(코드 성질)
4. 채운 칸이 **6개 미만이면 판정하지 않음** — 끈 채로 두고 숫자만 기록

- 지금 코퍼스면 보류용 CYCLE 8개 × 1칸 = 채운 칸 최대 8 → 0.75 = 6/8. 30개로는 큰 차이만 잡힘 — "통계적으로 유의하다"가 아니라 **"미리 적은 규칙을 넘었다"**로 말한다.
- 미달이면 끈 채로 두고 숫자만 기록(이 절 · 09 · Jira).

**판정 순서**: ① 이 기준을 09·10 에 커밋 → ② 개발용 질의로 검색어 실험(언어별 키워드 문장 · (b)를 첫 검색어로 등) → 고른 설정을 09 에 적음 → ③ 보류용 한 번 판정 → ④ 통과면 기본 켬.

**도구**(손 실행, pytest 수집 안 됨 — 판정 숫자는 `tests/str/rag_eval_v2_support.py` 상수 = 위 기준):
- 정답 초벌 `tests/str/rag_answer_draft_live.py` — 호스트에서(PDF 쪽 안 순번 복원에 pymupdf). `answer_draft.json` → `--expand` 로 `answers_*.json`(이미 있으면 덮어쓰지 않음 — 확인 내용 보호). 초벌 파일에는 1·2 등급 `by_typology` 와 함께 **0 등급까지 전 행** `graded_by_typology`(SCRUM-275-2 — 시트에서 "LLM 0"과 "안 매김"을 가름)
- **확인 시트**(SCRUM-275-2) `tests/str/rag_answer_sheet_live.py` — 호스트에서, DB 읽기 전용:
  - `export --out <리포 밖 폴더>`: 초벌 + DB `ai.reference_chunks.text`(초벌이 LLM 에 보낸 그 본문, `chunk_id` 로) → CSV 하나 + 등급 안내 md. 초벌이 전체 초벌이 아니면(`limit` · 3유형 중 빠짐 · DB 청크 전부가 아님 · 같은 청크 두 번 · 등급 0·1·2 밖 · 위치 불일치) 멈춤. **본문이 든 파일은 리포 밖에만** — `--out` 이나 존재하는 조상 폴더가 리포와 같은 폴더(파일 시스템 비교 — 대소문자 변형·상대 경로·심볼릭 링크 포함)면 거절(추가 검토 1)
  - 칸: `row_id · 유형 · 문서 · 쪽 · 쪽안순번 · LLM등급 · 확인등급(빈 칸) · 메모 · 본문 · chunk_id · 초벌지문`(초벌 파일·manifest sha256 앞부분 — 어느 초벌·코퍼스 위의 시트인지), 순서 유형(CYCLE → FAN_IN → FAN_OUT) → 문서 → 쪽 → 순번, 본문 전체, UTF-8 BOM, `=`·`+`·`-`·`@` 로 시작하는 본문은 앞에 `'`
  - `apply --csv <확인된 CSV> --checker <이름>`: 확인 등급을 정답으로(1·2 만 목록에, `draft: human`, `llm_draft`·`check_scope`·`checked_by`·`checked_at`) → `answers_dev.json`·`answers_holdout.json`. apply 도 export 와 같은 초벌 완전성 점검을 다시 함. 행 빠짐 · 같은 행 두 번 · 등급이 0·1·2 아님(빈 칸 포함) · `chunk_id`·LLM 등급·유형·문서·쪽·순번이 초벌과 다름 · 본문이 그 청크 원문과 다름 · 초벌지문이 지금 초벌 파일·manifest 와 다름이면 **반영 안 하고 거절**(CSV 행 번호·row_id 출력, 본문은 안 찍음). **CSV 형식**도 먼저 봄 — 머리글이 export 칸 목록과 이름·순서까지 같아야 하고(같은 이름 칸 중복·빠짐·추가 거절), 칸 수가 머리글과 다른 행 거절(추가 검토 2). 정답 두 파일은 **둘 다 바뀌거나 둘 다 그대로** — 임시 파일에 둘 다 완성(fsync) → 기존 파일 백업 → 차례 교체, 중간 실패면 둘 다 되돌림. 본문 비교 전 정규화: CRLF→LF · 앞뒤 공백 무시 · 원문이 `'` 로 시작하지 않으면 맨 앞 `'` 하나 제거(수식 방지로 붙인 것) 정답 파일이 없으면 새로, 모두 확인 전(같은 초벌)이면 대체, 하나라도 확인됨이면 거절
  - `apply --csv <CSV> --check-only`: 위 점검(초벌 완전성·CSV 형식·지문·행 대조)만 하고 파일은 안 씀 — 오류마다 (종류, 행 번호, row_id, 설명)이고 집계·종료 코드는 **종류로만**(row_id 글자로 분류가 바뀌지 않음) — 종류별 개수(확인등급 빈 칸 · 확인등급 이상 · 본문 다름 · 유형/위치 다름 · chunk_id/LLM등급 다름 · 지문 다름 · 행 빠짐 · 행 중복 · 초벌에 없는 행 · 시트 형식)와 앞 몇 행 번호. 확인등급 빈 칸 말고 오류가 있으면 종료 코드 1
  - **확인자에게 넘기기 전**: 시트를 구글 시트에 올렸다 CSV 로 내려받는 왕복을 한 번 하고 `--check-only` 로 **본문 다름 0**(빈 칸만 남음)을 확인 — 시트가 본문·`'` 를 바꾸면 반영 때 전부 거절되므로
  - 확인이 끝나면 시트·CSV(본문 사본)는 지움(진희)
  - **한계**(추가 검토 3 — 알고 남김): ① 교체와 되돌리기가 연달아 실패하면 정답 두 파일이 서로 다른 상태로 남을 수 있음 — 그때는 정답 두 파일을 지우고 초벌 `--expand` 부터 다시, 시트를 다시 반영 ② apply 는 한 번에 하나만 돌림(잠금 없음, 손 실행 도구 — 같은 폴더에서 두 apply 가 겹치면 서로의 임시·백업 파일을 지울 수 있음)
- 색인 `tools/index_es.py` · 평가 `tests/str/rag_eval_v2_live.py --split dev|holdout [--no-keyword]` — AI 컨테이너 안에서(ES 호스트 포트 없음). 결과 `result_{split}.json` 은 chunk_id·시간·채운 칸 cosine 만. **Dockerfile 은 안 바꿈**(이미지에는 서비스 코드만 — SCRUM-256): 실행 때 `tools`·`tests` 를 **읽기 전용**으로 붙이고, 결과를 쓰는 `tests/str/rag_eval_v2` 만 쓰기로 겹쳐 붙임(이미지 WORKDIR `/app`):
  - 색인: `docker compose run --rm -v "$PWD/tools:/app/tools:ro" -e PYTHONPATH=/app/src:/app ai python -m tools.index_es`
  - 평가: `docker compose run --rm -v "$PWD/tests:/app/tests:ro" -v "$PWD/tests/str/rag_eval_v2:/app/tests/str/rag_eval_v2" -e PYTHONPATH=/app/src:/app ai python -m tests.str.rag_eval_v2_live --split dev`
  - 정답 초벌은 컨테이너가 아니라 **호스트**(이미지에 pymupdf·`corpus/pdf` 없음, ES 안 씀)
- **보류용 한 번만**(추가 검토 1 반영): 실행 전 거절 — 개발용 결과 없음 · 개발용 결과가 끝난 상태(`done`)가 아님 · 개발용 마지막 결과와 키워드 설정이 다름 · 보류용 정답 확인 안 끝남. 그다음 **검색 전에 보류용 원장 `tests/str/rag_eval_v2/holdout_ledger.jsonl` 에 예약**(추가 검토 2 반영 — 결과 파일과 분리) — 덧붙이기만 하는 git 추적 파일(빈 파일로 시작)에 잠금(flock) 안에서 보류용 세트 해시(`queries_holdout.json` sha256)·시각·상태(reserved → done | aborted)를 한 줄. 같은 해시가 원장에 있으면 거절(끝났든 중단됐든, 결과 파일을 지웠든 출력 경로를 바꿨든), 동시 실행도 하나만 통과, 원장이 없으면 만들지 않고 "원장 복구 필요"로 거절. 원장을 지우거나 고치면 git 에 드러남(git 기록까지 지우는 우회는 못 막음 — 원장은 git 으로 감사). 중간 실패해도 결과 파일(`status: aborted` · 본 질의 id)과 원장에 남음. 개발용은 중간 실패 때 지난 결과를 덮어쓰지 않음. 보류용 판정 = 개발용 + 보류용 실행 결과로(②③ 은 30개 전부)

**켤 때 갖출 것**(통과해도 다 있어야 켬): 0건 규칙 테스트(SG·GS) · fail-open 테스트(위 표) · 스위치 env(`RAG_GAP_FILL_ENABLED`, 앱 재시작으로 끔) · 키워드 호출 짧은 타임아웃 + 초안 80초 예산 안 늘어난 시간 실측 · 채운 칸 `score` = (a) cosine · `retrieval_version` 꼬리(아래 "버전") · 오류 주입 13·14 통과 · 외부 호출 중 DB 연결 안 듦 · v4 에만.

## 버전

`retrieval_version = f"{EMBEDDING_MODEL}@{manifest_sha256[:8]}"` → `generation_meta`, `generations.retrieval_version`.

- **SCRUM-275**: `RAG_GAP_FILL_ENABLED` 가 켜져 있으면 꼬리를 붙임 — `{EMBEDDING_MODEL}@{manifest_sha256[:8]}+fill:{검색어 종류}+kw:{ELASTIC_INDEX}` (예 `text-embedding-3-small@ac39ff86+fill:abc+kw:ai_reference_chunks_v1`, 128자 안 — `generations.retrieval_version` String(128)). 끄면 지금 그대로. 백엔드는 health 로그에만 찍고 파싱하지 않음(`AiHealthCheck`) — 백엔드 변경 0. v2·v3 프롬프트면 켜져 있어도 채우지 않으므로 꼬리를 붙이지 않음.

## 일정 (W4 전반, 3~4일)

| 날 | 할 일 |
|---|---|
| 1 | manifest 작성, PDF 수집(브라우저로 받아 `corpus/pdf/`), `ingest_corpus.py`, 태깅 표 |
| 2 | 마이그레이션 `0004_reference_chunks`(pg_extension 확인), `embedding_client.py`, `retriever.py`, 단위 테스트 |
| 3 | `narrative_generator.py`에 REFERENCES 연결, 규칙 8, 오류 주입 13·14, 녹화 |
| 4 | `retrieval_eval.json` 10개 작성(기대 `chunk_id`) → hit@3·precision@3 표 → `MIN_SIMILARITY` 초기값 → `08`·발표 자료 + RAG 켬/끔 비교 표 |

W3 초안 생성·검증이 먼저 서 있어야 한다. 순서를 바꾸지 않는다.

## 2차로 넘기는 것

**평가 세트 확장과 태그 검수가 선행**(09 2026-11-18 "RAG 2차 순서" — 11/18 실측: 425청크 중 유형 태그 27(6%) · SG·GS 0, 지금 만점은 태그 필터 덕분).

1. **평가 세트 확장** — 질의 10개 → 30~50개, 정답 없는 질의 포함, **질의마다 facts 를 달리**(146 기준선에서 (c) 문장이 10개 모두 같았음), 유형 필터 켬/끔 둘 다(주 비교는 끔), 지표에 recall@10 · 정답 없는 질의 오탐. 정답 위치는 `chunk_id` 가 아니라 doc_id·page·쪽 안 순번. 개발용/보류용 나눔. 11/18 기준선 파일(`tests/str/rag_baseline_20261118{,_ac,_a}.json`)로 재채점 가능.
2. **태그 검수** — 용어 대응표(공개 자료 용어 → FAN_IN·FAN_OUT·CYCLE·SG·GS)부터. 태그 없는 398청크 검토 목록은 SCRUM-281. 두 사람 표본 일치율 → LLM 후보 비교(태그별 놓친 비율) → 사람 승인 뒤에만 적용.
3. **자료 확장** — 2 뒤에도 SG·GS 근거가 비면. 1순위 후보 **APG Yearly Typologies Report**(Annual Report 와 다른 문서). 넣기 전 이용 조건 확인 → 쪽수·해시 검증 → 문단별 역할·태그 검수.
4. **하이브리드 + 다중 질의** — 합치기 층은 SCRUM-146 에서 기본 끔으로 이미 있음, 키워드(Elasticsearch)는 SCRUM-275 로 같은 층. 켤 기준은 09 2026-11-19 "SCRUM-275 판정 기준" 줄로 대체(빈칸만 채우기).
5. **리랭커 · 유사도 임계값** — 후보가 넓어진 뒤. cosine 절댓값 컷오프는 정답 없는 질의와 정답 쪽 점수가 겹쳐 안 됨(11/12 · 11/18 실측).
6. **사례 검색 화면** — 사람 평가(참고 사례가 도움 되는지) 기준을 넘은 뒤. 규약 변경 요청 먼저.
7. **청크 자동 태깅(LLM)** — 자료를 여러 권 넣게 될 때. 사람 일치율 기준 뒤.
8. **승인 STR 재사용** — 재사용 승인·철회 흐름과 자체 임베딩이 준비된 뒤(맨 뒤).

- 목표는 청크 수가 아니라 유형별 커버리지(유형마다 출처 2곳 이상, 관련 청크 N개 — N 은 팀이 정함).
- SCATTER_GATHER·GATHER_SCATTER 는 규제기관 용어가 아니라 합성 데이터(IBM·AMLSim) 이름이라, 공개 자료에서는 funnel account·pass-through·경유 계좌 같은 말로 찾는다 — 태그 기준에 용어 대응표가 필요.
- **2차 준비 자료(SCRUM-281, 11/19 — 적용 0)**: `docs/str/rag2/00_tagging_criteria.md`(두 사람 태깅용 공통 기준 사본 — 위치·후보 없음) · `01_term_map.md`(용어 대응표 초안) · `02_untagged_review.csv`(태그 없는 398청크 검토 목록, 키 `chunk_id`=`content_hash`) · `03_sampling.md`(표본 60~80개 뽑는 법·Cohen's κ). 청크는 DB 가 아니라 `corpus/pdf/` + `tools/corpus_chunks.chunk_pdf_pages` 로 다시 나눠 만듦(425 · 빈 398, DB `chunk_id` 425/425 일치). **원문 문장은 옮기지 않고 위치만**(`doc_id · page · 쪽 안 문장 순번`, 문장 순번 = 그 쪽 `get_text()` NFKC 후 문장 끝 `.`·`?`·`!`·`다.` + 공백 / 빈 줄로 나눈 1부터). 목록의 "후보 유형"은 2차 사람 태깅의 출발점일 뿐 **태그가 아님** — manifest·DB 에 안 들어감. 검색·적재 경로는 `docs/` 를 읽지 않음.
- **이용 조건 원칙**(진희 11/18 — 법률 판단 아님, 허가가 필요할 수 있는 건 하지 않는 쪽, 09 같은 날 줄):
  ① 원문 PDF·추출 텍스트는 리포·이미지에 넣지 않음(리포 공개 · .gitignore corpus/pdf·corpus/text · Dockerfile PDF 제외 — SCRUM-256)
  ② 화면·응답은 문서명·발행기관·연도·쪽·공식 링크만. 문단 발췌는 허가가 확인됐거나 공공 정보인 자료만 — 2차
  ③ FATF·APG·Egmont 자료는 번역본 만들지 않음
  ④ 초안 본문에 원문 문장 반입 금지(v4 는 안 씀 · 규칙 8)
  ⑤ 임베딩 외부 API 전송은 처리용으로 보고 유지, 승인 STR 은 자체 임베딩(2차)
  ⑥ 새 자료는 이용 조건 확인 뒤 적재(manifest 이용 조건·확인일 칸은 2차 자료 확장 때)
  ⑦ 발표 자료 출처는 '문서명 · 발행기관 · 연도'
  ⑧ 상업화·외부 서비스 땐 원 기관 허가부터 다시 봄
  ⑨ 법률 해석은 진희가 멘토에게 확인 예정 — 답을 받으면 이 줄 갱신

`retrieve()` 시그니처는 그대로라 `narrative_generator.py`는 안 바뀐다.

# 10. 참고 사례 검색 (RAG)

10/26 1차 포함, 10/27 회의 채택(안건 22). 범위는 안건 22 표대로 **고정** — 여기 없는 건 2차. 정본: `str/infrastructure/retriever.py`, `shared/infrastructure/embedding_client.py`, `tools/ingest_corpus.py`, `corpus/manifest.json`, `tests/str/retrieval_eval.json`. 10/27 2차 검토 반영: 참고 사례 **0~3건**(억지로 3건 안 채움), 평가는 **청크 단위**, pgvector는 superuser 절차. 2026-11-11 SCRUM-125 반영: 코퍼스 유형 태그를 **백엔드 룰 v2 `typology_hint`** 값(FAN_IN·FAN_OUT·CYCLE·SCATTER_GATHER·GATHER_SCATTER) 로 재태그 — PDF 본문에서 근거 쪽을 찾은 문서만.

한 줄로: 경보 유형에 맞는 공개 사례·적색신호 문단을 **최대 3개** 찾아 프롬프트 REFERENCES 자리에 붙인다. **유형 설명을 구체적으로 만들기 위한 것**이고, 검증을 대신하지 않으며, 실패해도 초안은 나온다.

## 코퍼스

`corpus/manifest.json`에 문서 목록(id·제목·발행처·연도·URL·sha256·쪽수·언어). PDF는 `corpus/pdf/`에 두되 **.gitignore**(저작권·용량). manifest만 커밋 → 같은 manifest면 누구나 같은 코퍼스를 다시 만든다.

문서 8개 (2026-11-09 sha256·pages 확인):

| id | 문서 | 왜 |
|---|---|---|
| `fincen-sar-narrative-2003` | FinCEN, Guidance on Preparing a Complete & Sufficient SAR Narrative (2003, 33쪽) | **5W1H 정본**, 부록에 충분/불충분 서술 예시 — few-shot·평가자 루브릭 근거 |
| `fatf-tbml-2020` | FATF/Egmont, Trade-Based Money Laundering: Trends and Developments (2020, 66쪽) | 유형 설명·사례 박스·위험 지표 |
| `fatf-tbml-2006` | FATF, Trade Based Money Laundering (2006, 44쪽) | 사례 12개 |
| `fatf-pml-2018` | FATF, Professional Money Laundering (2018, 53쪽) | 계정 관리망·현금 운반망·대리 네트워크 |
| `fincen-funnel-2014` | FinCEN Advisory FIN-2014-A005, Funnel Accounts (2014, 6쪽) | **FAN_IN** 정의 + 적색신호 |
| `ffiec-redflags` | FFIEC BSA/AML Manual Appendix F, Red Flags (웹→PDF, 8쪽) | 적색신호 목록 — 원본 PDF 없음, 웹 본문을 PDF 로(2026-11-09, 머리에 출처 URL) |
| `fincen-msb-ko-2007` | FinCEN, 금전 서비스 업체 지침 (한국어, 2007, 52쪽) | 유일한 국문 공개 자료 — 한국어 질의 매칭 재료 |
| `fincen-money-mule-2020` | FinCEN Advisory FIN-2020-A003, Money Mule Schemes (2020, 8쪽) | 머니 뮬 정의·수법. 레드플래그 목록은 PDF 텍스트로 안 뽑힘(정의·수법 문단만) |

KoFIU 「자금세탁 의심거래 참고유형 사례집」은 금융회사 AML 담당자에게만 배포되고 공개본이 없다(2025.12.22 금융위 보도자료). 안 넣는다. 적색신호의 국문 표현은 FFIEC 부록 F를 번역한 청크로.

### 코퍼스 태그 근거 (SCRUM-125, 2026-11-11)

PDF 본문에서 v2 유형(FAN_IN·FAN_OUT·CYCLE·SCATTER_GATHER·GATHER_SCATTER) 근거 쪽을 찾은 문서만 태그. 못 찾으면 빈 태그(검색 결과에 안 나옴). **큰 문서(fatf-*)와 `ffiec-redflags`는 쪽 단위 태그** — manifest `typology_pages: {유형: [쪽, ...]}` 에 적힌 쪽에서 나온 청크만 그 태그, 나머지 청크는 빈 태그. 유일한 문서 단위 태그는 `fincen-funnel-2014`(전 쪽이 FAN_IN). 절 단위 `sections` 맵은 SCRUM-146 으로. **ffiec 는 SCRUM-125 때 문서 단위 3태그(FAN_IN·FAN_OUT·CYCLE) 였으나, 같은 청크가 세 유형 결과에 모두 올라와 precision 떨어뜨림(★L-1 baseline FAN_IN 0.33 · FAN_OUT·CYCLE 0) → SCRUM-126 에서 쪽 단위 재태그 (FAN_IN p2·3·8 / FAN_OUT p4·5·7 / CYCLE p6).**

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

**옛 태그(PASS_THROUGH·STACK·STRUCTURING) 전부 폐기** — v2 룰 `typology_hint` 값이 아니라 검색 필터에 안 걸림(죽은 태그). 09 2026-11-11 결정 줄 참조. `FX_RELAY` 는 `Typology` enum 에 없고 R03 〔제안〕 — 182·193 로 넘김, 이번 PR 안 붙임.

## 적재 (`tools/ingest_corpus.py`)

```
manifest 읽기 → PDF sha256 검증(안 맞으면 그 문서만 건너뛰고 로그) → 텍스트 추출(pymupdf, 쪽 번호 유지)
→ 청크: 문단 단위, 목표 500 토큰, 겹침 50, 표는 행 단위, 쪽 경계 넘지 않음
→ 태깅: manifest 에 `typology_pages` 가 있으면 **쪽 단위**(목록 안 쪽에서 나온 청크만 그 유형, 나머지 청크는 빈 태그),
       없고 `typologies` 가 있으면 **문서 단위**(청크마다 같은 값). 둘 다 없으면 빈 태그. 절 단위 맵은 SCRUM-146·126 으로
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

## 버전

`retrieval_version = f"{EMBEDDING_MODEL}@{manifest_sha256[:8]}"` → `generation_meta`, `generations.retrieval_version`.

## 일정 (W4 전반, 3~4일)

| 날 | 할 일 |
|---|---|
| 1 | manifest 작성, PDF 수집(브라우저로 받아 `corpus/pdf/`), `ingest_corpus.py`, 태깅 표 |
| 2 | 마이그레이션 `0004_reference_chunks`(pg_extension 확인), `embedding_client.py`, `retriever.py`, 단위 테스트 |
| 3 | `narrative_generator.py`에 REFERENCES 연결, 규칙 8, 오류 주입 13·14, 녹화 |
| 4 | `retrieval_eval.json` 10개 작성(기대 `chunk_id`) → hit@3·precision@3 표 → `MIN_SIMILARITY` 초기값 → `08`·발표 자료 + RAG 켬/끔 비교 표 |

W3 초안 생성·검증이 먼저 서 있어야 한다. 순서를 바꾸지 않는다.

## 2차로 넘기는 것

APG 연례보고서·우리가 승인한 STR 추가, 하이브리드(BM25 + 벡터), 리랭커, 유사도 임계값 튜닝, 사례 검색 화면, 청크 자동 태깅(LLM). `retrieve()` 시그니처는 그대로라 `narrative_generator.py`는 안 바뀐다.

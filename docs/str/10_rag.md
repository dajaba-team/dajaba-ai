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

2026-11-20 SCRUM-305 채택으로 3개 추가 → **11개 · 722 청크**: `fincen-cmln-2025`(FinCEN FIN-2025-A003, 15쪽) · `fintrac-underground-banking-2023`(FINTRAC-2023-OA002, 8쪽) · `apg-typologies-2025`(APG 2025, 102쪽) — CYCLE·SG·GS 근거, 쪽 단위 태그(아래 "305 실행 기록").

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

### 결과 (11/19)

- **정답 확인**: 준혁 · 범위는 `check_scope`(CYCLE 425 전부 · FAN_IN·FAN_OUT 은 LLM ≥ 1 행) · LLM 과 다른 16행(FAN_IN 12 · FAN_OUT 4, 전부 낮춤) · **CYCLE 변경 0** · 메모 `?` = "조금 애매함"(등급 그대로) · 시트·CSV 는 반영 뒤 지움 · 반영은 #78 직전 manifest 로(09 같은 날)
- **개발용**(같은 정답):

| 설정 | 채운 칸 | 정답 | 채운 청크 | 정답 없는 질의 | 지금 경로 |
|---|---|---|---|---|---|
| 키워드 끔 | 6 | 0 | 6칸 `ffiec-redflags` p8 | 0건 | 그대로 |
| 키워드 켬 | 6 | 0 | 5칸 `ffiec-redflags` p8 · D04 `fincen-funnel-2014` p3 | 0건 | 그대로 |

  켬 첫 실행은 ES 가 쉬던 직후라 `keyword_unavailable` 1회 → 버리고 다시 돌린 결과. 차이가 없어 설계대로 **키워드 켬**
  키워드 켬은 보류용 실행 전에 고름(11/19 개발용 켬/끔 결과를 본 뒤 15:46) — 판정 순서 ②의 "고른 설정을 09 에 적음"과 달리 09 기록은 판정 뒤 이 PR 로 함(09 같은 날 판정 줄)
- **보류용**(1회, 키워드 켬): 채운 칸 8 · 정답 0 · 비율 0.0 · 정답 없는 질의 0건 · 지금 경로 그대로 · 판정함 → **기준 미달, `RAG_GAP_FILL_ENABLED` 기본 끔 유지**
- **원인**: CYCLE 정답 청크가 425 중 3개(`ffiec-redflags` p6 두 개 · `fincen-msb-ko-2007` p33)이고 앞의 둘은 원래 검색 1·2위 — 빈칸 정답은 msb-ko p33 하나인데 켬·끔 모두 못 가져옴 → 검색 방법보다 코퍼스 문제
- **다음 후보**: "2차로 넘기는 것" 3번 자료 확장 — 후보로만, 하는지는 11/20 외부 의견 뒤 따로 정함
- **결과 파일**(`tests/str/rag_eval_v2/`, 원문 0): `answer_draft.json`(LLM 초벌) · `answers_dev.json` · `answers_holdout.json` · `result_dev.json`(마지막 = 켬) · `result_holdout.json` · `holdout_ledger.jsonl`
- **원장 테스트**: 원장 테스트를 실행 뒤 상태도 받게 고침 — 빈 파일 검사(`test_repo_ledger_exists_and_is_empty`) → `test_repo_ledger_is_well_formed`(`tests/str/test_rag_eval_v2_ledger_format.py`). ① 형식: 파일 있음 · 빈 파일 통과 · 줄마다 JSON · `set_sha256`·`status`·`at` 필수 · 같은 해시는 `reserved` 1줄 → `done`|`aborted` 1줄 순서대로 · 짝 없는 `reserved` 금지 · 해시 ∈ {지금 `queries_holdout.json` sha256} ∪ 이미 쓴 세트(새 보류용 세트로 바꿔도 과거 줄은 남김) ② **이미 쓴 세트**: 테스트 안 고정 목록 `CONSUMED_HOLDOUT_SETS`(11/19 `a7562b45…` → `done`)의 해시마다 리포 원장에 `reserved` 1줄 → 기대 상태 1줄이 남아 있어야 함 · 지금 보류용 세트가 그 목록에 있으면 원장에도 있어야 함 — 결과 파일 유무·출력 경로와 무관(원장을 통째로 비우거나 지워도 잡힘). 보류용을 새로 돌리면 그 세트 해시를 목록에 추가(같은 PR). 원장 코드·판정 기준 변경 0

## 코퍼스 확장 판정 (holdout_v2) — SCRUM-304, 결과 보기 전 (09 2026-11-19 같은 줄)

SCRUM-275 판정 미달(위 "결과 (11/19)") 원인이 코퍼스라서, SCRUM-305 에서 공개 자료 3개(FinCEN FIN-2025-A003 · FINTRAC-2023-OA002 · APG 2025)를 넣고 판정한다. 275 보류용 세트(`a7562b45…`)는 원장에 `done` 이라 다시 못 돌림 → **새 보류용 세트 `holdout_v2`**. 판정 대상은 빈칸 채우기가 아니라 **원래 검색(유형 태그 필터 → top-3)의 유형별 결과** — `RAG_GAP_FILL_ENABLED` 는 꺼 둔 채(기본 false), 판정에 안 씀. 이 절·질의 파일·판정 함수·확인자 기준서·기준 맞추기 표본은 **한 커밋으로, 305 적재보다 먼저** 고정한다.

### 확정 기준 (11/19 22:00 진희 — 문구·숫자 그대로)

**기준 ① 유형별 hit@3** — CYCLE·SCATTER_GATHER·GATHER_SCATTER 각각, top-3 안에 등급 1 이상 청크가 1개 이상인 질의 수
- 유형별 질의 8개 중 6개 이상이면 통과. 질의 수가 다르면 **⌈0.75 × 질의 수⌉** 개 이상(8→6, 7→6, 6→5)
- 한계로 적음: 질의 8개는 오차가 커서 "0.75 달성"이 아니라 "자료가 없던 유형에서 근거를 찾기 시작했다"까지만 주장한다

**기준 ② 0건이어야 하는 질의**
- "없는 유형"은 이름으로 정하지 않는다 — **적재 뒤 태그된 청크가 0개인 유형**
- FX_RELAY 를 포함해 **지금 태그가 0인 유형(SCATTER_GATHER·GATHER_SCATTER·FX_RELAY)** 의 질의를 전부 미리 써 둔다(SG·GS 는 ① 질의를 그대로 씀, FX_RELAY 는 따로 만듦)
- 적재 뒤(실행 전) 태그 수를 세서, 0개인 유형은 "결과 전부 0건"으로 판정, 1개 이상 생긴 유형은 ②에서 빼고 참고 기록으로
- **무관한 질의(자금세탁과 상관없는 거래)는 판정하지 않고 참고 기록만** — 유형이 없으면 `retrieve()` 가 검색 없이 `[]`(아무것도 확인 못 함), 유형이 있으면 `MIN_SIMILARITY=0.0` 이라 늘 3건(자동 실패). 컷오프 판정은 SCRUM-308
- 판정이 끝날 때까지 `MIN_SIMILARITY`·`RAG_TOP_K` 값은 바꾸지 않는다

**기준 ③** — FAN_IN·FAN_OUT 기존 개발용 질의(D07~D10) hit@3 이 확장 전(1.000)보다 낮아지지 않음. 확장 전 top-3 에 있던 정답 청크가 밀려난 건수도 기록
- **새 문서 3개에는 FAN_IN·FAN_OUT 태그를 붙이지 않는다**(305 지킬 것) — 필터 경로에서 FAN 결과가 바뀌는 길은 새 청크에 FAN 태그가 붙는 것뿐
- 한계로 적음: ③은 새 문서에 FAN 태그를 붙이지 않아서 지켜지는 항목이다. 새 자료의 FAN 근거는 이번에 평가하지 않았다. 수치 재확인은 그대로 1회 돌린다

**판정 안 함** — `holdout_v2` 를 돌리기 **전에** 세어서 정한다. 하나라도 해당하면 그 유형은 판정 안 함
- 질의가 6개 미만(질의 문자열이 겹치면 하나로 치고 다시 셈)
- 태그된 청크가 10개 미만 — **SG 가 걸릴 것 같아도 이 숫자는 낮추지 않는다**
- 외부 확인자의 등급 확인이 끝나지 않음 — 확인 단위는 **청크 × 유형**: 그 유형으로 태그된 청크 전부를 실행 전에 확인하면 끝(질의별 확인 아님. 유형 필터 경로라 결과에는 태그된 청크만 나와 빠짐없이 덮임 — 275 CYCLE 425 전부와 같은 방식)

**미달** — 위 조건이 다 찼는데 개수를 못 넘은 경우
- 한 번 돌려서 미달이 나온 유형을 나중에 판정 안 함으로 바꾸지 않는다
- SCATTER_GATHER 도 같은 규칙: 청크가 모자라면 판정 안 함(자료 부족), 청크가 충분한데 못 넘으면 미달

**전체 결론**
- ② 또는 ③이 깨지면 복원
- ①은 세 유형 중 **2개 이상 통과하면 채택, 1개 이하면 복원**. 판정 안 함은 통과로 세지 않는다
- 미리 알고 가는 모양: SG 근거는 APG 사례 84·FINTRAC 그림 1 정도라 판정 안 함이 될 가능성이 큼 → 그 경우 채택은 CYCLE·GS 둘 다 통과일 때만

**질의 만드는 법**
- 손으로 쓰지 않는다. 합성 사건의 facts 에서 `build_query(facts)` 가 만드는 한 줄을 그대로 쓴다(질의 파일에는 지금처럼 `base`+`overrides` 를 저장하고, 문자열은 그걸로 다시 만듦)
- 새로 넣을 문서 3개의 본문은 이 커밋 전에 열어 보지 않는다(CLI)
- 한계로 적음: 설계자(진희)는 확장안을 쓰면서 새 문서를 읽었지만, 질의는 facts 에서 기계적으로 만들었다
- 정답은 질의 파일에 적지 않는다
- 기존 dev·holdout 30개와 질의 문자열이 겹치지 않게

**기준 맞추기(외부 확인자)** — 기존 확인된 425행에서 25행(유형·등급 층별, 고정 시드). 외부 확인자 등급과 준혁 님 등급의 "1 이상인가" 일치가 **20행 이상**이면 같은 잣대. 못 넘으면 기준서를 고치고 다른 25행으로 한 번 더, 그래도 못 넘으면 305 판정은 "판정 안 함". 외부 확인자는 정해짐(진희가 넘기면 바로 해 줌, 이름은 305 `apply --checker` 때). 설계자 진희는 등급 판단에서 빠짐.

### 한계 (위 셋에 더해)

- 같은 유형 질의는 앞부분이 같고 끝의 신호·업종 단어만 달라 top-3 가 크게 겹칠 수 있다 — 질의 8개가 독립 8번의 시험은 아니다(숫자는 그대로)
- 재판정 때 `prior` 를 빼고 첫 판정처럼 부르는 길은 판정 함수만으로는 못 막는다 — 원장(첫 판정 기록 해시·같은 세트 첫 판정 한 번)으로 막는다(305)
- **태그를 확인자 등급으로 정해(SCRUM-305 ★A 4) 기준 ① 은 순위 품질보다 "관련 근거가 있고 태그됐는가"를 주로 잰다** — 유형 필터 경로라 태그된 청크만 후보이고, 태그가 곧 확인자가 등급 ≥ 1 을 준 청크의 쪽이다(결과 보기 전, 09 2026-11-20)

### 질의 세트 (`tests/str/rag_eval_corpus/queries_holdout.json`)

| 유형 | 질의 | 쓰임 |
|---|---|---|
| CYCLE | 8 | ① |
| SCATTER_GATHER | 8 | ① · ②(적재 뒤 태그 0 이면) |
| GATHER_SCATTER | 8 | ① · ②(적재 뒤 태그 0 이면) |
| FX_RELAY | 4 | ② |
| 무관한 질의(유형 없음) | 2 | 참고 — 유형 없으면 [] 경로 확인용, 컷오프 연구는 SCRUM-308 |

- `build_query(facts)` 가 쓰는 칸은 **유형(한국어·코드·영문 패턴) + `model_signals` + `customer.industry`** 뿐. 그래서 overrides 는 `industry`·`model_signals` 두 칸만 저장(방향·결제 방식·자행/타행 수·base 픽스처는 질의 문자열도, 기본 검색 경로 `RAG_MULTI_QUERY = False` 의 결과도 바꾸지 않음)
- **기계 추출**: 시드 `304` · 후보 = 신호 1~2개 순열(275 질의에 나온 신호 6개) × 업종 5칸(RETAIL·WHOLESALE·TRADING·RESTAURANT·없음) · 섞은 순서대로, 기존 dev·holdout 30개 또는 이미 뽑은 것과 같은 문자열은 건너뜀. 유형 순서 CYCLE → SG → GS → FX_RELAY 로 같은 난수열을 이어 씀. base 는 CYCLE 이 `facts_cycle_nopaths.json`·`facts_multi_currency.json` 번갈아, SG·GS `facts_scatter_gather.json`, FX_RELAY `facts_multi_currency.json`(문자열에 영향 없음). 무관한 질의 = 유형 null · 신호 0 · 업종 RETAIL·MANUFACTURING. 테스트가 같은 규칙으로 다시 만들어 파일과 같은지 확인
- 정답 칸 없음 · 계좌·금액 없음 · 검색은 305 에서 원장 예약 뒤 한 번
- 원장 `tests/str/rag_eval_corpus/holdout_ledger.jsonl`(빈 파일로 시작) — 275 원장 모듈 `tests/str/rag_eval_v2_ledger.py` 를 폴더만 바꿔 그대로 씀 → **SCRUM-305 ★A 6 에서 새 모듈 `tests/str/rag_eval_corpus_ledger.py` 로**(275 모듈은 예약 줄에 `pre_sha256`·판정 줄을 못 담음 — 아래 "305 실행 기록")

### 판정 함수 (`tests/str/rag_eval_corpus_support.py` · 입력 고정·대조 `rag_eval_corpus_guard.py` — 숫자는 상수, 합성 입력 테스트만)

- 입력: 실행 전 고정값 `PreRun`(유형별 태그 청크 수 — CYCLE·SG·GS·FX_RELAY 넷 다 · 확인 완료 여부 — CYCLE·SG·GS 셋 다) · 질의별 결과(id·유형·질의 문자열·top-3 `chunk_id`) · 확인자 등급표((유형, `chunk_id`) → 등급, 없으면 0) · ③ D07~D10 확장 전·뒤 top-3 와 준혁 등급 · **고정 질의 목록**(`query_manifest()` — 질의 파일의 id·유형·`build_query` 문자열 30개) · **실행 전 고정값 해시**(`PreRun.sha256()` — 키 정렬·공백 없는 JSON 의 sha256) · 이미 나온 유형별 상태(`pinned` — 미달은 그대로)
- **판정 전에 거절(추가 검토 1)** — 결과를 본 뒤 입력을 바꿔 결론을 돌리는 길을 막음:
  - `PreRun` 은 만들 때 입력을 복사해 안쪽까지 읽기 전용 · 유형이 빠지거나 더 있으면 거절 · 해시가 받은 해시와 다르면 거절(실행 뒤 태그 수·확인 완료를 바꾸는 길)
  - 결과가 고정 질의 목록과 id·유형·문자열까지 같아야 함 — 빠짐(실패 행만 빼고 내기)·같은 id 두 번·목록 밖이면 거절
  - ③ 은 D07·D08·D09·D10 각각 정확히 한 번 — 빠짐·두 번·목록 밖이면 거절
  - **이전 판정 기록 `prior`(추가 검토 2)** — 호출자가 미달 고정을 직접 주는 길은 없음. `verdict` 는 `prior`·`prior_sha256` 을 키워드로 꼭 받고(첫 판정은 둘 다 None 명시), 미달 고정은 `prior` 에서만 계산. `prior` 는 만들 때 복사해 안쪽까지 읽기 전용 · 유형 키는 CYCLE·SG·GS 정확히(소문자·빠짐·모르는 키 거절) · 값은 통과·미달·판정 안 함만 · 해시가 원장 값과 다르면 거절(미달을 통과로 바꾼 기록 거절). 이전 미달은 태그 부족·질의 부족 입력에서도 미달
  - **305 에서 지킬 것**: 원장 예약 줄(검색 전)에 `PreRun.sha256()` 을 같이 적고, 판정 때 그 값을 `pre_sha256` 으로 넘김 · 첫 판정 결과의 `Prior.from_verdict(...).sha256()` 을 원장에 적고, 재판정은 원장에서 읽은 `prior` 만 허용 · 같은 세트에 `prior=None`(첫 판정) 두 번은 원장이 거절 · `prior_sha256`·`pre_sha256` 은 원장에서 읽은 값만 — 호출 쪽에서 `prior`·`PreRun` 으로 계산한 값은 안 됨
- 출력: 유형별 상태(통과·미달·판정 안 함)와 이유·질의 수(같은 문자열은 하나)·hit 수·필요 수 · ②(판정한 유형·뺀 유형·실패 질의) · 무관한 질의 참고 기록 · ③(hit@3 전·뒤, 밀려난 정답 청크 수) · 전체 결론(채택·복원)
- **추출 규칙 고정(추가 검토 1)**: 테스트가 시드 `304`·신호 6개·업종 5칸·무관 업종 2개·유형별 배분과 base(순서 포함)를 모듈과 따로 적은 값으로 검사하고, 질의 파일·기준 맞추기 표본 파일의 정규화 해시를 고정 — 시드·범위를 바꿔 다시 만들면 실패
- 275 `rag_eval_v2_support.verdict` 는 그대로

### 확인자 기준서·기준 맞추기

- 기준서 `docs/str/rag2/04_checker_guide.md` — 유형별 계좌 구조·등급 0·1·2(275 와 같은 말)·확인 단위 청크 × 유형. 원문 인용 0
- 기준 맞추기 표본 `tests/str/rag_eval_corpus/calibration_rows.json` — 모집단 = 준혁 님이 확인한 487행(CYCLE 425 전부 + FAN_IN·FAN_OUT 의 LLM ≥ 1 행 43·19), 층(유형 × 준혁 등급) 8개에서 25행, 층 안은 `chunk_id` 정렬 뒤 고정 시드. 1차 시드 `304`, 2차(1차 미달 때) 시드 `3042` · 1차와 안 겹치게 · 모자란 층은 다시 씀(다시 쓴 행 수를 파일에 기록). 파일에는 위치·`chunk_id`·유형만 — 준혁 등급은 기존 `rag_eval_v2/answers_*.json`·`answer_draft.json` 에서 읽음(새 키 파일 없음), 확인자 시트에 LLM 등급 칸 없음(275 한계 — 확인자가 LLM 등급을 보고 기울 수 있음 — 를 피함)

### 305 참고 기록 (판정에 안 씀)

- ②에서 빠진 유형(적재 뒤 태그 ≥ 1)의 결과 · 무관한 질의 결과 · ③ 밀려난 정답 청크 수
- **유형별 질의 간 top-3 겹침(평균 Jaccard)** — 위 한계 줄의 크기를 숫자로 남김
- **태그된 청크 중 확인자 등급 0 비율(유형별)** — 태그가 쪽 단위라 같은 쪽의 다른 청크도 함께 태그됨, 그 크기를 남김(SCRUM-305 ★A 4, 결과 보기 전)

### 305 실행 기록 (SCRUM-305 — 위 기준·질의·판정 함수·표본은 그대로, 실행만)

**자료** (공식 주소에서 받음 11/20 — 원문 PDF 는 리포에 안 올림, `corpus/pdf/` 에만)

| `id` | 발행 | 쪽 | sha256 앞 8 | 청크(예상, 기존 규칙) | 비고 |
|---|---|---|---|---|---|
| `fincen-cmln-2025` | FinCEN Advisory FIN-2025-A003 (2025-08-28) | 15 | `5a2654b1` | 34 | 이름이 비슷한 "FIN-2025-Alert003"(다른 문서)과 다름 |
| `fintrac-underground-banking-2023` | FINTRAC-2023-OA002 (2023-07) | 8 | `17956599` | 17 | 그림 1(p2)은 이미지 — 단계 글자가 추출 텍스트에 없음, 바로 앞 문단이 흐름을 글로 설명. OCR 안 함 |
| `apg-typologies-2025` | APG Yearly Typologies Report 2025 | 102 | `94c66a4c` | 246 | 공식 파일 이름 "for adoption" · PDF 메타 "revised" · 사이트의 유일한 2025 판(11/20 진희 확인) → manifest `note` |

- 전체 청크 425 → 722(예상). 이용 조건: PDF 안에 문구 없음 → ⑨(11/19 멘토 확인) · manifest 새 3줄에만 `terms`·`terms_checked`(⑥ 이행)

**태그** (★A 3·4) — 기준은 `rag2/00_tagging_criteria.md`·`01_term_map.md` 그대로, 기구는 manifest `typology_pages`(쪽 단위) 그대로
1. 새 297청크 × CYCLE·SG·GS 를 LLM 초벌(275 평가 도구와 같은 방식 — 기준서 문장, 출력 `doc_id`·`page`·`pos`·`grade` 만, 실제 호출은 진희 터미널)
2. 초벌 ≥ 1 청크를 외부 확인자가 등급으로 확인(확인 단위 청크 × 유형 — 기준서 `rag2/04_checker_guide.md`, 시트에 LLM 등급 칸 없음)
3. 확인 등급 ≥ 1 청크가 있는 쪽만 그 유형으로 `typology_pages` → **새 3문서 청크만 지우고 다시 적재**(기존 425 청크·벡터 그대로, `ON CONFLICT DO NOTHING` 이라 태그를 바꾸려면 지워야 함)
4. 쪽 단위라 같은 쪽의 다른 청크도 태그됨 → 그 청크까지 실행 전에 확인해야 "확인 완료"(판정 안 함 조건). 초벌 0 청크는 확인하지 않음(275 FAN 범위와 같은 방식) — 한계·참고 기록은 위
- **새 3문서에 FAN_IN·FAN_OUT 태그 0**: 테스트(manifest 3줄의 `typologies`·`typology_pages`) + 실행 도구 사전 점검(DB 집계 ≠ 0 이면 예약 전에 거절). 적재 도구는 안 고침

**태그 도구** (적재 뒤 — 진희 OK 11/20)
- **초벌**: `tests/str/rag_corpus_draft_live.py`(손 실행, 진희 터미널) — DB 의 새 3문서 청크(297)만 × CYCLE·SCATTER_GATHER·GATHER_SCATTER 로 LLM 에 등급(0·1·2)만 물음. 프롬프트 **`tools/prompts/rag_answer_v2.md`**(새 버전 — v1 은 FAN_IN·FAN_OUT·CYCLE 정의뿐이라 SG·GS 정의를 `rag2/00_tagging_criteria.md` 와 같은 뜻으로 더함, v1 은 안 고침). 결과 `tests/str/rag_eval_corpus/answer_draft_corpus.json` = chunk_id·doc_id·page·grade + 프롬프트 sha256·모델(본문 0). FAN·FX_RELAY 는 안 물음
- **확인 시트 범위**(청크 × 유형): 유형마다 ① 초벌 ≥ 1 청크가 있는 **쪽(후보 쪽)의 새 문서 청크 전부**(쪽 단위 태그라 같은 쪽 다른 청크도 태그될 수 있음) ② **이미 그 유형으로 태그된 기존 청크 전부**(CYCLE 2 — 확인 완료 = 그 유형 태그 청크 전부). 시트는 기준 맞추기와 같은 모양(등급·LLM 칸 없음, 기준서 04·00 사본, 리포 밖) — `rag_answer_sheet_live.py` 하위 명령 `export-corpus --out <리포 밖>` · `apply-corpus --csv <확인된 CSV> --checker <이름>`
- **반영**: `apply-corpus` = 시트를 초벌 범위와 대조(행·유형·chunk_id·등급 0·1·2·확인자 이름) → `answers_corpus.json`(checked_by·checked_at·초벌 sha256·grades) + 새 3문서의 **`typology_pages`**(확인 등급 ≥ 1 청크가 있는 쪽) → `corpus/manifest.json` 의 새 3줄만 바꿈(기존 8줄은 글자 그대로, FAN 키 거절)
- **다시 적재 = 새 3문서 행만 지우고 넣음**(★A 3-① 그대로) — `ON CONFLICT DO NOTHING` 이라 그냥 적재하면 이미 있는 297행의 `typologies` 가 안 바뀜. `UPDATE typologies` 대신 지우고 넣는 이유: 태그 계산을 적재 도구(manifest `typology_pages` → 쪽 단위) 한 곳에 두어 manifest 와 DB 가 어긋나지 않게. `chunk_id`(= content_hash)는 태그와 무관해 확인 등급·초벌의 chunk_id 가 그대로 맞음. 기존 8문서 행은 `DELETE … WHERE doc_id IN (새 3문서)` 밖이라 안 건드림. 적재 도구는 11문서를 다시 임베딩하지만 기존 425행은 충돌로 건너뜀
- **태그 도구 지킬 것**(추가 검토 1): ① 초벌 전체 실행 전에 새 3문서가 34·17·246 으로 다 적재됐는지 ② export·apply 양쪽에서 유형별 초벌의 (chunk_id, 문서, 쪽) 전체 = 지금 DB 의 새 3문서 청크 전체, 기존 CYCLE 태그 청크 = 기준선 2개(`ffiec-redflags` p6) — 다르면 시트·반영 안 함 ③ apply 는 행마다 문서·쪽·본문을 그 chunk_id 의 DB 원본과 대조(275 `body_matches`) ④ 새 3 id 가 manifest 에 한 번씩·한 줄 한 문서 모양이어야 하고, 새 3줄에 FAN·FX_RELAY 가 있으면 거절. 새 3문서 × 3유형의 쪽 목록은 매번 새로 계산(0 이 된 쪽은 지움), 쓴 뒤 다시 파싱해 확인 ⑤ 등급 파일·manifest 는 manifest 잠금 하나 안에서 임시 파일로 만든 뒤 등급 파일은 덮지 않게 게시(hard link), manifest 는 원자적 교체 — 중단 뒤 같은 입력(확인자·등급·초벌 해시)으로 다시 돌리면 남은 반영만, 다른 입력은 거절, 다 반영됐으면 "할 일 없음"(1) ⑥ 초벌은 시험·전체 모두 결과 파일이 있으면 거절, LLM 호출 전에 `.running` 표식을 배타 생성(동시 실행 하나만), 완성본은 임시 파일 → 덮지 않게 게시
- **추가 검토 2**: ⑦ 확인 시트의 `확인등급` 칸은 `행ID=` 로 미리 채워 내보내고(예 `CY-001=` — 추가 검토 3 에서 ⑯ 계산 ID 로 바꿈), 확인자는 뒤에 0·1·2 만 붙임 — 반영은 칸의 행ID 가 그 행과 같고 숫자가 0·1·2 일 때만(등급 열만 정렬한 시트 거절). 칸 앞뒤 공백과 `=` 앞뒤 공백은 허용(`CY-001= 2`·` CY-001=2 `), 그 밖(숫자 둘·다른 글자·행ID 다름)은 거절 ⑧ `run`·`preflight` 는 PreRun 을 만들기 전에 같은 DB 스냅샷에서 등급 파일로 계산한 새 3문서 쪽 = manifest `typology_pages`, 그 쪽의 새 청크 + 기존 CYCLE 2 = DB 유형별 태그 청크 ID 인지 대조 — 다르면(등급 게시 뒤 manifest 교체 실패·재적재 안 함) 예약 전에 거절 ⑨ 반영한 등급 해시를 `CORPUS_DIR/pdf/.applied_corpus_grades.json`(git 무시 폴더 — `.gitignore` 안 고침)에 기록하고, 교체하지 않는 공용 잠금 `CORPUS_DIR/pdf/.apply_corpus.lock` 아래에서 대조 — 다른 작업 트리가 다른 등급으로 반영하면 거절 ⑩ 새 3문서는 문서 단위 `typologies` 가 비어 있어야 반영(쪽 단위만) ⑪ 기준 맞추기 `check-calibration` 도 같은 원본 대조(문서·쪽은 회차 원본, 본문은 DB 원문) ⑫ PDF 의존(`pymupdf`)은 쪽 복원 함수 안에서만 import — `--extra dev` 만으로 시트·초벌 CLI 가 뜸
- **추가 검토 3**: ⑬ `preflight`·`reserve`·`run` 은 예약·실행 전에 `answers_corpus.json` 과 공용 반영 표식(`CORPUS_DIR/pdf/.applied_corpus_grades.json`)이 둘 다 있고 확인자·초벌 해시·등급 해시가 같은지 확인 — `apply-corpus` 재시도는 표식까지 복구해야 완료 ⑭ 등급 파일의 `draft_sha256` = 실제 초벌 파일 해시, 초벌의 유형별 새 3문서 전체 (chunk_id, 문서, 쪽) = 같은 스냅샷 DB 의 새 3문서 청크(후보 없던 문서 포함, 34·17·246) · 기존 태그 = 기준선 ⑮ 따로 실행하는 `preflight`·`reserve` 도 `snapshot_session()` 하나에서 모든 DB 읽기 ⑯ 등급 칸 앞 ID 는 (유형, chunk_id)로 계산(`CY-<chunk_id 앞 8>=`) — 행 열의 순번(`CY-001`)은 표시용, 반영은 계산값과 대조(다른 초벌 시트의 등급 칸 복사 거절) ⑰ DB 의 FX_RELAY 태그 청크 = manifest 로 계산한 FX_RELAY 청크(305 는 빈 집합)
- **추가 검토 4**: ⑱ 예약 전, 같은 스냅샷에서 **기대 코퍼스 전체 = DB 전체** — manifest 를 문서 표로 바꾸기 전에 새 3 id 가 한 번씩·모든 id 가 한 번씩·새 3문서 문서 단위 `typologies` 빔을 확인. 기대 = 기존 425(275 초벌 `rag_eval_v2/answer_draft.json` 에 기록된 (chunk_id, 문서, 쪽) + manifest 기존 줄로 `resolve_typologies` — FAN_IN 19·FAN_OUT 6·CYCLE 2, 전체 해시를 상수로 고정) + 초벌의 새 297 (chunk_id, 문서, 쪽) + manifest 새 줄로 `resolve_typologies`. (chunk_id, 문서, 쪽, 태그 집합) 전체가 DB 스냅샷과 같아야 `reserve`·`run`. 다르면 문서별 개수(빠짐·더 있음·태그 다름)를 알리고 멈춤 — ⑰ FX_RELAY 대조는 이 안에 들어감. 알고 남김: 반영 표식은 작업 트리별 `corpus` 경로에 생김(305 태그 반영·preflight·reserve·run 은 한 리포에서만) · `preflight` 스냅샷과 예약 줄 사이 재적재 커밋은 `run` 이 검색 전에 불일치로 멈춤(예약만 쓰임)
- **추가 검토 5(마지막)**: ⑲ 태그 계산 전에 manifest 문서 id 집합 = 기존 425 의 문서 id ∪ 새 3 id(정확히 11개) — 빠진·더 있는 id 를 알리고 멈춤(태그 없는 기존 문서 줄이 빠져도 잡힘). 검증 뒤에는 없는 문서를 빈 태그로 치지 않음
- 테스트(DB·LLM 0): `test_rag_corpus_tags.py`(초벌 범위·시트 범위·쪽 목록 다시 계산·manifest 새 3줄만·FAN·FX_RELAY·8문서/압축 manifest 거절·청크 집합·기존 태그 기준선) · `test_rag_corpus_sheet.py`(blind 시트·열만 정렬한 CSV 거절·두 번째 쓰기 실패 뒤 재시도·다른 입력 거절·동시 apply 하나만) · `test_rag_corpus_draft.py`(결과 파일 덮지 않음·동시 실행 하나만)
- 다시 적재 뒤 확인: 전체 722 · 문서별 청크 수·태그 청크 수(기존 8문서는 4·13·10 그대로) · 새 3문서 FAN 0 · 유형별 태그 수 = `typology_pages` 쪽의 청크 수. **ES v2 다시 색인 필요**(ES 문서에 `typologies` 칸이 있음 — v1 은 안 건드림, 판정은 PG 라 판정 전 필수는 아니지만 채택 뒤 전환용)

**적재·되돌리기** (진희 터미널, 시연 녹화와 안 겹치게)
- 적재 전 `ai.reference_chunks` 를 `pg_dump`(리포 밖) · ES 는 원래 색인 `ai_reference_chunks_v1` 을 둔 채 새 색인 `ai_reference_chunks_v2`(판정은 유형 필터 → pgvector top-3 라 ES 안 씀, `.env` `ELASTIC_INDEX` 전환은 채택 뒤에만)
- 복원 = 표 비우고 덤프 되살림 + `corpus/manifest.json` 을 develop 으로 되돌림(`retrieval_version` 이 manifest 해시라 같이) · **복원 확인**: 청크 425 · 태그 FAN_IN 19·FAN_OUT 6·CYCLE 2·SG 0·GS 0 · manifest 해시 = 304 때 · 304 기준선 FAN D07~D10 hit@3 1.0 · ES v1 문서 수 425

**원장** `tests/str/rag_eval_corpus_ledger.py`(새, 275 모듈 안 고침 — 같은 덧붙이기) · 파일은 위 `holdout_ledger.jsonl` · **세트 식별 = 질의 목록의 정규화 해시**(304 가 고정한 `QUERIES_SHA256` 과 같은 함수 — 질의 파일 서식만 바꿔 다시 예약하는 길을 막음, 추가 검토 2). **원장이 예약·판정 줄 전에 그 해시가 304 고정값인지 직접 대조**(축소·재정렬·id 변경 세트는 예약·판정 0, `judge` 는 받은 질의와 `eval_dir` 둘 다 대조 — 추가 검토 5) · `record` 는 done·aborted 만, 판정 줄은 `judge_locked` 만 · `judge_locked` 는 **잠근 파일에서 원장 전체를 한 번만 읽고** 그 목록으로 `problems`·예약 줄·prior 를 고름(경로를 다시 열지 않음 — 추가 검토 3) — 위반이 있으면 판정 안 함

| 305 지킬 것 | 어디서 |
|---|---|
| ① 새 문서 FAN 태그 0 | 테스트 + 실행 도구 사전 점검 |
| ② 예약 줄(검색 전)에 `PreRun.sha256()` + **등급표 해시**, `holdout_v2` 한 번 | `reserve(eval_dir, pre_sha256, grades_sha256)` — 같은 세트 해시가 있으면 거절. 등급표 해시 = 예약 전에 검증한 확인자 등급 파일의 정규화 sha256(추가 검토 1) |
| ③ 첫 판정 `Prior.from_verdict(...).sha256()` 기록, 재판정은 원장 `prior` 만 | `judge_locked` — **원장 읽기(예약 줄·마지막 판정 줄)부터 판정·판정 줄 기록까지 한 잠금 안**. 판정 줄에 계산에 쓴 `from_prior_sha256` — 잠금 안 최신 값과 다르면 거절. 앞 판정의 미달(fail)을 뒤 판정이 풀면 거절(추가 검토 1) |
| ④ `prior_sha256`·`pre_sha256`·등급표 해시는 원장 값만 | `judge(eval_dir, runs, pre, grades_doc, fan)` — 해시·prior 인자 없음. 등급표 스냅샷의 해시가 예약 줄과 다르면 판정 전에 거절 |
| ⑤ 같은 세트 `prior=None` 두 번 거절 | 상태 전이 표 — 첫 판정은 `reserved` 바로 뒤에만 |

**상태 전이**(기록 함수와 형식 점검 `problems` 가 같은 표 `TRANSITIONS` — 추가 검토 1): (없음) → `reserved` → `judged`(첫 판정) → `done` · `done` → `judged`(재판정, 원장 prior) → `done` · `reserved`·`judged` → `aborted` · **`aborted` 뒤에는 아무 줄도 안 됨**(판정 금지)

**검색 시작 문**(추가 검토 3, `tests/str/rag_eval_corpus_gate.py`) — `holdout_v2` 를 두 번 검색하는 길을 작업 트리 밖에서도 막음
1. **질의 스냅샷**: 질의 파일을 한 번 읽어 304 가 고정한 정규화 해시(`QUERIES_SHA256`)와 대조 — 다르면(id 만 바꿔도) 예약 전에 거절. 검색·판정은 그 스냅샷으로. **`judge` 도 manifest 를 만들기 전에 같은 대조**(받은 질의 목록, 생략하면 `eval_dir` 에서 읽음) — 질의·결과에서 같은 행을 함께 빼도 판정 줄 전에 거절(추가 검토 4)
2. **예약 → 커밋 → 검색**: `reserve` 가 원장에 예약 줄을 쓰고 멈춤 → 진희가 원장 파일을 커밋 → `run` 은 `git show HEAD:원장` 에 같은 예약 줄(세트·실행 전 고정값·등급표 해시)이 있고, 작업 트리 원장의 이 세트 줄이 예약 한 줄뿐일 때만 검색
3. **같은 코퍼스 스냅샷**(추가 검토 4): `run` 은 태그 집계(`PreRun`)·전체 검색(질의 30 + D07~D10)을 **한 `REPEATABLE READ` 읽기 전용 트랜잭션·한 세션**에서 함 — 집계 직후 다른 세션이 복원·적재를 커밋해도 검색은 집계 당시 코퍼스를 봄. 그 스냅샷의 `PreRun`·등급표 해시가 커밋된 예약 줄과 같아야 표식을 만들고 검색. 검색은 PG 만(유형 필터 → pgvector top-3, `RAG_MULTI_QUERY`·빈칸 채우기 끔이라 ES 안 씀)
4. **검색 표식**: 검색 직전에 git ref `refs/holdout-v2/<세트 해시 앞 16>` 를 "없을 때만 만들기"(`git update-ref <ref> HEAD 0…0`)로 원자적으로 만듦 — 이미 있으면 거절. ref 는 같은 클론의 모든 작업 트리가 공유하고 원장 파일 복원과 무관 → 새 작업 트리·빈 원장 복원·중단 뒤 다시 돌리기 모두 검색 0회

**실행 도구** `tests/str/rag_eval_corpus_live.py`(새, 손 실행·pytest 수집 X — 275 `rag_eval_v2_live` 방식) — 하위 명령 `reserve`(질의 스냅샷 대조·preflight → 예약 줄 → 커밋 명령 출력, 검색 0) · `preflight`(DB 읽기 전용 집계 + 확인자 등급 파일 → `PreRun`·문제, 원장 0) · `run`(질의 스냅샷 대조 · 문제·결과 파일이 있으면 멈춤 → **preflight 에서 검증한 등급표를 스냅샷으로** — 그 해시·실행 전 고정값이 커밋된 예약 줄과 같아야 함 → 검색 시작 문 → 질의 30개 원래 검색 + D07~D10 확장 뒤 검색 → **등급 파일을 다시 읽어 스냅샷과 다르면(삭제·변경) 판정 안 하고 aborted·종료 코드 3** → 스냅샷으로 판정 → 결과 파일 → done, 중간 실패는 aborted) · `rejudge`(결과 파일로 다시 판정 — 원장 prior, 지금 등급 파일 해시가 예약 줄과 다르면 거절, 끝나면 done) · `check-restore`(425·태그 수·manifest 해시 + **D07~D10 실제 검색**(임베딩 호출) · 준혁 등급 hit@3 1.0 — 하나라도 다르거나 검색이 실패하면 종료 코드 1, 추가 검토 1)
- 순수 부분: `rag_eval_corpus_preflight.py`(FAN 점검·`PreRun`·복원 확인·참고 기록) · `rag_eval_corpus_run.judge`(원장 값으로만 `verdict` → 판정 줄 — `pre_sha256`·`prior`·`prior_sha256` 인자 없음) · 원장 `rag_eval_corpus_ledger.py`
- 파일: 확인자 등급 `tests/str/rag_eval_corpus/answers_corpus.json`(`checked_by`·`checked_at`·`grades{유형: [{chunk_id, grade}]}` — 확인자 이름이 없으면 확인 안 끝남) · 결과 `result_holdout_v2.json`(chunk_id 만, 본문 0). ③ 확장 전 = 275 `result_dev.json` 의 원래 검색, 등급 = `answers_dev.json`(준혁)
- 확인자 시트: `tests/str/rag_answer_sheet_live.py` 하위 명령 `export-calibration --out <리포 밖> [--round 1|2]`(시트 + 기준서 `04_checker_guide.md`·`00_tagging_criteria.md` 사본 — 04 가 함정 목록을 00 으로 가리킴, 등급 칸 이름은 기준서와 같은 `확인등급`. 출력 경로는 `expanduser().resolve()` 한 번으로 검사·쓰기 같은 값, 셸이 안 푼 `~` 가 든 경로는 거절 — 추가 검토 2) · `check-calibration --csv <확인된 CSV>`(본체 `rag_calibration_sheet.py` — 25행, 등급·LLM 칸 없음, 기준서 사본, 대조는 준혁 등급과 "1 이상인가" 20행). 태그 후보 청크 시트는 LLM 초벌 뒤(다음 단계)
- 테스트(DB·검색 0): `test_rag_eval_corpus_ledger.py`(예약 줄 실행 전 고정값·등급표 해시 · 같은 세트 두 번·중단 뒤 거절 · 첫 판정은 예약 바로 뒤에만 · 정상 재판정 뒤 형식 통과 · 중단 뒤 판정 거절 · 미달 해제 거절 · **동시 재판정 둘 — 뒤엣것 거절** · 계산에 쓴 prior 가 최신이 아닌 줄·판정 줄 고친 값 거절) · `test_rag_eval_corpus_preflight.py`(manifest·DB FAN · `PreRun` 확인 완료 · 복원 집계 · `judge` 가 예약과 다른 `PreRun`·등급표 스냅샷 거절 · 재판정은 원장 prior) · `test_rag_eval_corpus_live_guard.py`(FAN·결과 파일이면 예약 전에 멈춤 · **검색 중 등급 파일 삭제·변경 → 판정 없이 aborted·종료 코드 3** · **복원 확인 D07~D10 hit@3 0.75·검색 실패 → 1**) · `test_rag_calibration_sheet.py`(25행 · `확인등급` 빔 · 기준서 04·00 사본 · 리포 안·덮어쓰기 거절 · 일치 20행 경계 · 1↔2 일치) · D07~D10 입력 읽기는 `rag_eval_corpus_fan.py` · DB 읽기(`snapshot_session`·태그 집계)는 `rag_eval_corpus_db.py` · 추가 검토 4: `test_rag_eval_corpus_preflight.py`(질의·결과에서 같은 행 2개를 빼면 판정 줄 전 거절 · 질의 생략 재판정도 대조) · `test_rag_eval_corpus_snapshot_db.py`(`-m db` — 스냅샷 세션의 집계는 다른 세션이 커밋한 적재를 안 봄, `repeatable read`·읽기 전용)

**결과 (11/20)** — `holdout_v2` 1회(원장 reserved → judged → done, 검색 표식 `refs/holdout-v2/cd66f3b7c4e9c1f4`) → **채택(adopt)**

- 적재: 전체 722 = 기존 425(그대로) + 새 297(34·17·246). 확인자 김종민 · 기준 맞추기 1회차 25행 중 22행 일치 · 확인 시트 46행(CYCLE 12 · SG 6 · GS 28)
- 새 3문서 `typology_pages`: `apg-typologies-2025` CYCLE p53·79 · SG p51·53 · GS p23·31·39·44·47·81 / `fincen-cmln-2025` GS p9 / `fintrac-underground-banking-2023` CYCLE p4·6 · GS p3·4·5·7
- 태그 청크: CYCLE 12(새 10 + 기존 2) · SG 6 · GS 28 · FAN_IN 19 · FAN_OUT 6(그대로) · 새 문서 FAN 0 · FX_RELAY 0

| 기준 | 유형 | 질의 | hit@3 | 필요 | 태그 청크 | 결과 |
|---|---|---|---|---|---|---|
| ① | CYCLE | 8 | 8 | 6 | 12 | **통과** |
| ① | SCATTER_GATHER | 8 | (8) | 6 | 6 | **판정 안 함**(태그 10 미만 — 결과 전에 정해짐, hit 는 참고) |
| ① | GATHER_SCATTER | 8 | 8 | 6 | 28 | **통과** |
| ② | 태그 0 유형 = FX_RELAY | 4 | 빈 결과 4/4 | 전부 0건 | 0 | 통과 |
| ③ | FAN D07~D10 | 4 | 1.0 → 1.0 | ≥ 1.0 | — | 통과(밀려난 정답 0) |

- 결론: ① 통과 2(≥ 2) · ② · ③ 통과 → **adopt**. 무관한 질의 2개(NR01·NR02)는 0건
- **참고 기록**(판정에 안 씀): 태그 청크 중 확인자 등급 0 비율 CYCLE 0.42(5/12) · SG 0.67(4/6) · GS 0.46(13/28) · 같은 유형 질의 간 top-3 겹침(평균 Jaccard) CYCLE 0.875 · SG 0.73 · GS 0.56 · FX_RELAY 1.0(모두 빈 결과) · top-3 3건 미만 유형 FX_RELAY
- 읽는 법(위 한계 그대로): 태그 후보가 유형마다 6~28개라 질의가 달라도 top-3 가 거의 같음 — CYCLE 8개 질의 모두 1위가 `fintrac-underground-banking-2023` p6(등급 1) · SG 는 모두 1위 `apg-typologies-2025` p53. 기존 CYCLE 2개(`ffiec-redflags` p6)는 top-3 밖으로 밀림. 기준 ① 은 "확인된 근거가 태그됐는가"를 잰 것 — 순위 품질은 따로 안 봄
- GS 8개 질의 모두 1위가 확인 등급 0 청크(FINTRAC p5) — 쪽 단위 태그의 한계로, 화면 근거 1순위가 관련 약한 청크일 수 있음
- 화면에 나올 CYCLE 근거(캡처 후보): `fintrac-underground-banking-2023` p6 · p4 · `apg-typologies-2025` p79
- 결과 파일: `tests/str/rag_eval_corpus/result_holdout_v2.json`(chunk_id 만) · `answers_corpus.json` · `answer_draft_corpus.json` · 원장 `holdout_ledger.jsonl`
- 채택 뒤 남은 것: `.env` `ELASTIC_INDEX` 를 `ai_reference_chunks_v2` 로(머지 뒤 · v1·덤프는 지우지 않음) · 시연 서버가 보는 코퍼스가 425 → 722 로 바뀌므로 녹화 화면 근거 영향 확인

## 하이브리드·다중 질의 판정 (SCRUM-307, 2026-11-21 — 결과 보기 전, 09 같은 날 줄)

합치기 층(SCRUM-146, RRF `RAG_RRF_K=60`)과 ES 키워드(SCRUM-275, 언어별)는 이미 있고 기본 끔이다. 307 은 새 검색 기능을 만들지 않고 **필터 끈 경로에서 검색어 조합·키워드를 켤지**만 정한다. 이 절·09 줄은 **실행보다 먼저 한 커밋**으로 고정하고, 결과 파일에 그 커밋 해시를 남긴다. 결과를 본 뒤 기준을 고칠 일이 생기면 고치지 않고 멈춘다.

- **이름은 "개발용 결정"** — 평가 세트 v3(`tests/str/rag_eval_v3/`, 질의 34 · 정답 58)는 개발용뿐이라 결과 문구는 "통계적으로 유의" 대신 **"미리 적은 규칙을 넘었다/못 넘었다"**. 보류용 세트는 발표 뒤 새로 만든다(이번엔 안 만듦 · 275 보류용·holdout_v2 재사용 0)
- **바꾸는 범위**: 필터 끈 경로(평가·2차 하네스 기본 검색어 조합·키워드 켬/끔)와 빈칸 채우기의 **채우는 쪽 설정에 대한 결정 한 줄**만. 초안 경로(유형 필터 켬 · 한 번 찾기)·`RAG_GAP_FILL_ENABLED`(false)·`typology_filter=True`·`constants.py` 검색 상수는 그대로 → 시연 검색 결과 변경 0, **`retrieval_version` 은 안 바뀌는 게 예상값**. 결론이 "채우는 쪽 검색어 종류(`QUERY_KINDS`) 바꾸기"로 나와도 **이번엔 09 결정 한 줄만, src 상수 변경 0** — 바꾸는 건 따로 이슈

### 조건 (9개)

질의마다 검색어 (a)(b)(c) 를 **한 번 임베딩**(배치 1회)해 모든 조건이 같은 벡터를 쓴다(조건 차이 = 조건 때문만). 키워드 결과도 질의마다 한 번 받아 키워드 켬 조건에 같이 쓴다.

| 경로 | 검색어 조합 | 키워드 | 조건 수 |
|---|---|---|---|
| 필터 끔 | {a} · {a,c} · {a,b,c} | 끔 · 켬 | 6 |
| 필터 켬 | {a} · {a,c} · {a,b,c} | 끔 | 3 |
| 필터 켬 + 키워드 켬 | — | — | 해당 없음 — 지금 키워드 검색에 유형 필터 인자가 없음(넣으려면 src 변경, 범위 밖) |

- 필터 켬 · {a} · 키워드 끔 = **지금 초안 경로**(top-3 이 같음). 필터 끔 · {a} · 키워드 끔 = 필터 끈 한 번 찾기
- 목록: 벡터 검색어마다 `Retriever._candidates`(지금 SQL 그대로, 후보 `RAG_CANDIDATES`=10) · 키워드 켬이면 `keyword_queries`(275 코드 그대로 — 영문 `TYPOLOGY_PATTERN_EN` · 국문 `TYPOLOGY_KO` + `TYPOLOGY_PATTERN_KO`, 새로 고르지 않음)를 `KeywordSearch.search` 로 언어별 목록 → `[벡터 목록(조합 순)] + [키워드 en, ko]` 를 `rrf_fuse` 그대로(`fill_gaps` 와 같은 순서·모양). 키워드로만 찾은 청크 cosine = (a) 벡터 기준. **top-10 = 합친 순위 앞 10**, top-3 = 그 앞 3. 검색 SQL·`rrf_fuse`·키워드 코드 변경 0(부르기만)
- 키워드 실패(타임아웃·인증·색인 없음)는 평가에선 fail-open 하지 않고 **실행 중단**(결과 파일 안 씀 — "켬인데 실제론 끔" 결과가 섞이지 않게)
- 무관한 질의 2개(유형 null)는 `Retriever.retrieve` 가 `[]` 라, 필터 끔은 `build_queries` + `_candidates(필터 끔)` 를 직접 불러 기록. FX_RELAY 는 (b)·영문 키워드 문장이 없음(국문 `환전 중계` 하나)

### 지표

- **hit@3** = top-3 안에 정답(확인 등급 ≥ 1) 1개 이상이면 1. **recall@10** = |top-10 ∩ 정답| / |정답|. 유형별 = 그 유형 질의 6개의 평균, **정답 있는 질의만 분모**
- 정답: 필터 끔 = 58 전부(`db_tagged` true·false) · **필터 켬 = `db_tagged=true` 45 만**(합의 태그 13 은 적용 0 이라 필터 켠 검색에 나올 수 없음 — 06 적용 흉내 안 함, 알고 남김)
- **평균 = 유형별 값의 평균(macro, 146 과 같음), SCATTER_GATHER 는 빼고 4유형**(FAN_IN·FAN_OUT·CYCLE·GATHER_SCATTER). SG 는 정답 2청크뿐(한계 ②)이라 판단·평균 모두에서 빼고 표에만
- 비교는 **소수 3자리 반올림 뒤**
- 정답 없는 질의(FX_RELAY 2 · 무관 2): 필터 켬 = **0건 유지 여부**(0건이 아니면 판정하지 않고 멈춤 — 코드 성질), 필터 끔 = top-3 cosine 분포만 기록(필터 끄면 늘 뭔가 나옴 — 컷오프는 308)
- 지연(판정에 안 씀, 308 리랭커 비교 기준선): 조건별 **검색 시간** p50·최대, 임베딩 시간은 질의별 따로

### 켜는 규칙 (이 순서로 — ①② 와 ③ 은 따로)

1. **검색어 조합(키워드 끔에서)**: 필터 끔 · 키워드 끔에서 조합 X ∈ {{a,c}, {a,b,c}} 를 {a} 대신 고르려면
   - 4유형 평균 recall@10(X) − 평균 recall@10({a}) **≥ 0.10** 그리고
   - 4유형 어느 것도 hit@3({a}) − hit@3(X) **> 0.05** 가 아님
   - 둘 다 넘으면 오른 폭이 큰 쪽, 두 오른 폭 차이가 **0.02 이하**면 검색어가 적은 쪽({a,c}). 하나도 못 넘으면 {a}
2. **키워드(①에서 고른 조합에서만)**: 그 조합의 키워드 켬 − 끔 4유형 평균 recall@10 **≥ 0.05** 일 때만 켬, 아니면 끔(의존성·지연 줄이기). 다른 조합의 키워드 결과는 표에만
3. **필터 켬(①② 와 따로)**: {a,c}·{a,b,c} 중 4유형 어느 것이라도 hit@3 이 지금({a})보다 낮으면 그 조합은 필터 켬 경로에 안 씀. 넘어도 초안 경로 기본값은 안 바꿈(기록만 — 위 "바꾸는 범위")

- 유형마다 질의 6개라 hit@3 은 1/6(0.167) 단위 — ① 의 하락 > 0.05 · ③ 의 "낮으면" 모두 **그 유형에서 질의 하나라도 hit 를 잃으면 탈락**(숫자 기준은 위 그대로)

결론은 "① 조합 · ② 키워드 켬/끔 · ③ 필터 켬에 쓸 수 있는 조합" 한 줄로 09 에 적는다.

### 실행 (하네스 — 손 실행, pytest 수집 X)

- `tests/str/rag_eval_v3_hybrid_live.py` + 순수 계산 `tests/str/rag_eval_v3_hybrid_support.py`. ES 때문에 **AI 컨테이너 안**(275 명령 모양 — tests 읽기 전용 + 결과 폴더 `tests/str/rag_eval_v3` 만 쓰기). 실제 임베딩은 진희 터미널
- **쪽 안 순번**: 이미지에 PDF·pymupdf 가 없고, 305 초벌 파일에는 새 297청크의 `pos` 가 없음 → 실행 전에 **호스트에서** `corpus/pdf/` 재분할(`tools/corpus_chunks.chunk_pdf_pages`, 146 기준선과 같은 방법)로 위치표 `tests/str/rag_eval_v3/positions_722.json`(chunk_id · doc_id · page · pos 만, 본문 0)을 만들고, 컨테이너 실행은 그 표를 읽음. 표가 DB 722 `chunk_id` 와 다르면 거절
- **실행 전 거절**: ① 이 절의 기준 커밋이 HEAD 조상에 없음 ② v3 정답 미확인(`consensus_pending` · 등급 빈 칸 · 확인자·날짜) ③ ES 문서 수 ≠ DB 행 수 ④ `ELASTIC_INDEX` ≠ `ai_reference_chunks_v2` ⑤ 결과 파일이 이미 있음(덮어쓰기 금지 — 다시 돌릴 땐 진희가 지우고 사유를 기록) ⑥ 위치표 ≠ DB
- `--dry`: 가짜 벡터(146 `prepare` 와 같은 sha256 벡터) · ES 끔 — 경로 점검만, 결과 파일 이름 다르게
- 결과 `tests/str/rag_eval_v3/result_307.json`: 조건마다 질의별 top-10(순위 · chunk_id · doc_id · page · pos · cosine) · 유형별·평균 지표 · 규칙 ①②③ 결과 · 설정값(`RAG_CANDIDATES`·`RAG_TOP_K`·`MIN_SIMILARITY`·`RAG_RRF_K`·`RAG_MAX_QUERIES`) · 임베딩 모델 · `ELASTIC_INDEX` · `retrieval_version` · manifest 해시 · 기준 커밋 해시 · 키워드 문장 sha256 · 지연. **원문·검색어 문장·지문 0**
- 예상 호출: 임베딩 배치 34 · ES `_search` 62(5유형 30 × en·ko + FX_RELAY 2 × ko) · `_count` 1 · PG 읽기 전용

### 한계

- 개발용 34개만 — 이 결과로 검색어·키워드를 고르고 같은 세트로 잰다(보류용 없음). 큰 차이만 잡힘
- 필터 끈 경로 수치는 **하한**(10_rag 306 한계 ① — 안 본 청크 577 중 관련 청크가 나오면 오답으로 셈)
- SG 정답 2청크(한계 ②) — 표에만
- 정답은 유형 단위(같은 유형 질의 6개는 정답이 같음) — 질의별 차이는 facts 로 달라지는 검색어 문장에서만 생김
- 필터 켬은 지금 DB 태그 기준 — 06 합의 태그를 적용하면 다시 재야 함

## 하이브리드·다중 질의 판정 결과 (SCRUM-307, 2026-11-21 — 개발용 결정)

위 기준 절은 그대로 두고 결과만 여기(기준 절 글자가 바뀌면 하네스 거절 ① 이 막음). 진희 터미널 — 기준 커밋 `48b76ad`(하네스 고정) = 실행 HEAD · 임베딩 배치 34 · ES `_search` 62(부분 응답 0) · `ai_reference_chunks_v2`(722) · `retrieval_version` `text-embedding-3-small@36b5a2d5`. 결과 `tests/str/rag_eval_v3/result_307.json`(chunk_id·위치·cosine·지표, 원문·검색어 문장 0) · 위치표 `positions_722.json`.

- **다시 돌림(추가 검토 1)**: 1회차(13:27Z) 결과는 키워드 ES 200 부분 응답(`timed_out`·샤드 실패)을 성공으로 셌을 수 있고 RRF 앞 10 에서 점수 없는 청크를 빼고 11위 이하로 채웠을 수 있어 저장값만으로 top10 을 검증할 수 없음 → `result_307.json` 지우고 고친 하네스로 2회차(14:00Z). 평균 산식도 고침(유형별 반올림 전 값으로 macro). 1회차 정답 순위는 `tests/str/fixtures/rag307_run1_answer_ranks.json`(산식 회귀 테스트용)
- **추가 검토 2 반영(결과 다시 안 돌림)**: ES `_search`·`_count` 는 HTTP 200 · 샤드 실패 0(`_search` 는 시간 초과 아님)만 · top-10 cosine 이 유한하지 않으면 중단 · 정답 후보 chunk_id 가 DB 에 다 있어야 함 · 외부 호출 뒤 읽기 전용 REPEATABLE READ 트랜잭션 하나에서 위치·태그 재확인 + 9조건 PG 검색. 2회차 결과는 cosine 2,776개 모두 유한(최소 0.197)이고, 새 거절 검사는 읽기 전용 확인 도구 `tests/str/rag_eval_v3_hybrid_check.py`(결과 파일·임베딩 0)로 지금 DB·ES 에 대 봐서 통과하면 결과 파일 그대로 둠
- **1회차 대비 바뀐 곳은 CY03 하나**: 필터 끔 {a} 정답 5위 → 4위 · {a} 키워드 정답 없음 → 10위(CYCLE recall@10 0.095 → 0.119, 규칙 ② 이득 +0.010 → +0.016). 키워드 없는 조건에서도 바뀌었고, 검색어·키워드 문장 해시는 같고, 2회차에 음수 cosine·점수 없는 청크 0 · ES 부분 응답 0 → **M4·H3 때문이 아니라 임베딩 값이 실행마다 조금씩 다름**(키워드 없는 NR01 top-3 최소 cosine 0.435152 → 0.435094). 결정은 같음

**결론: 미리 적은 규칙 ①② 를 못 넘음 → 필터 끈 경로 기본값 = {a} · 키워드 끔 유지(지금 그대로). ③ 필터 켬에는 {a,c}·{a,b,c} 를 써도 hit@3 이 안 떨어짐 — 기록만, 초안 경로 안 바꿈.** src·상수·`RAG_GAP_FILL_ENABLED`·`retrieval_version` 변경 0 — 바꿀 기본값이 없어서. 채우는 쪽 `QUERY_KINDS` 도 그대로(바꿀 결론 아님).

| 조건 | FAN_IN | FAN_OUT | CYCLE | GS | 4유형 평균 | SG(표에만) |
|---|---|---|---|---|---|---|
| 필터 끔 · {a} · 키워드 끔 | 0.000 / 0.068 | 0.000 / 0.000 | 0.333 / 0.143 | 0.000 / 0.000 | 0.083 / 0.053 | 0.000 / 0.083 |
| 필터 끔 · {a} · 키워드 켬 | 0.000 / 0.012 | 0.000 / 0.143 | 0.000 / 0.119 | 0.000 / 0.000 | 0.000 / 0.069 | 0.000 / 0.000 |
| 필터 끔 · {a,c} · 키워드 끔 | 1.000 / 0.160 | 0.000 / 0.071 | 0.500 / 0.214 | 0.000 / 0.000 | 0.375 / 0.112 | 0.000 / 0.000 |
| 필터 끔 · {a,c} · 키워드 켬 | 1.000 / 0.130 | 0.500 / 0.071 | 0.500 / 0.143 | 0.000 / 0.000 | 0.500 / 0.086 | 0.000 / 0.000 |
| 필터 끔 · {a,b,c} · 키워드 끔 | 1.000 / 0.148 | 0.000 / 0.071 | 0.500 / 0.214 | 0.000 / 0.000 | 0.375 / 0.108 | 0.000 / 0.000 |
| 필터 끔 · {a,b,c} · 키워드 켬 | 1.000 / 0.173 | 0.500 / 0.143 | 0.500 / 0.214 | 0.000 / 0.000 | 0.500 / 0.132 | 0.000 / 0.000 |
| 필터 켬 · {a} (지금 초안 경로) | 1.000 / 0.625 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 0.467 | 1.000 / 0.773 | 1.000 / 1.000 |
| 필터 켬 · {a,c} | 1.000 / 0.625 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 0.589 | 1.000 / 0.803 | 1.000 / 1.000 |
| 필터 켬 · {a,b,c} | 1.000 / 0.625 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 0.589 | 1.000 / 0.803 | 1.000 / 1.000 |

칸 = hit@3 / recall@10. 필터 끔 정답 58 · 필터 켬 정답 `db_tagged=true` 45. 유형마다 질의 6. 평균 = 유형별 반올림 전 값의 macro.

- **규칙 ①(키워드 끔, {a} 대비)**: {a,c} 0.112 − 0.053 = **+0.059** · {a,b,c} 0.108 − 0.053 = **+0.055** — 둘 다 +0.10 미달 → **{a}**. hit@3 은 두 조합 모두 어느 유형도 안 떨어짐(FAN_IN 0 → 1.000, CYCLE 0.333 → 0.500 오름) — 하락 조건은 통과, recall 조건에서 탈락
- **규칙 ②({a} 에서만)**: 키워드 켬 0.069 − 끔 0.053 = **+0.016** < +0.05 → **끔**. 표에만: {a} 키워드 켬은 CYCLE hit@3 0.333 → 0.000 · {a,b,c} 키워드 켬은 평균 recall@10 0.132(규칙상 {a,b,c} 를 안 골라 판단 대상 아님)
- **규칙 ③(필터 켬, 따로)**: {a,c}·{a,b,c} 모두 4유형 hit@3 1.000 = {a} → **둘 다 필터 켬에 써도 됨**(GS recall@10 0.467 → 0.589, 나머지 같음). 초안 경로 기본값은 안 바꿈(범위)
- **필터 켬 · {a} 질의별 결과 건수**: FAN_IN·CYCLE·GS 질의 18개 모두 10건 · FAN_OUT·SG 12개 모두 6건(그 유형 태그 청크 수 = 6) · FX_RELAY·무관 4개 0건. dry(가짜 벡터)에서 본 10건 미만·0건은 실제에선 없음
- **정답 없는 질의**: 필터 켬 = 세 조합 모두 4개 0건 ✓. 필터 끔 top-3 cosine — {a}: FX01 0.414~0.435 · FX02 0.423~0.452 · NR01 0.435~0.443 · NR02 결과 없음((a) 문장 빔 — 유형·신호·업종 없음) / {a,c}·{a,b,c} 키워드 끔: 0.443~0.609(FX01 0.537~0.595 · FX02 0.452~0.595 · NR01 0.443~0.609 · NR02 0.526~0.609). 정답 쪽과 같은 대역 — 컷오프는 308
- **지연**(판정 안 씀, 308 기준선): 검색 p50 / 최대 ms(키워드 켬 = PG 조회·합치기 + 그 질의 ES 시간) — 필터 끔 {a} 2.8 / 7.6 · {a} 키워드 34.4 / 44.2 · {a,c} 4.8 / 5.1 · {a,c} 키워드 36.1 / 45.8 · {a,b,c} 7.0 / 13.7 · {a,b,c} 키워드 38.5 / 47.9 · 필터 켬 {a} 1.4 / 2.0 · {a,c} 2.6 / 3.0 · {a,b,c} 3.6 / 7.2. 키워드 켬의 PG 조회·합치기만은 3.8~7.9 p50 · ES 62회 합 988 ms(질의당 약 29). 임베딩(질의당 배치 1) p50 202 · 최대 2,111
- **읽는 법(판정 아님)**: 필터 끈 경로 recall@10 은 0.05~0.13 으로 낮음 — 한계 ①(안 본 577청크 → 하한) 과 GS 정답 15청크가 필터 끔 top-10 에 한 번도 안 나온 것이 큼. 필터 켬은 태그 덕분에 높음(11/18 기준선과 같은 그림). 검색어를 늘리면 hit@3 은 오르지만 recall@10 오름은 미리 정한 폭에 못 미침. 같은 질의를 다시 돌려도 임베딩 차이로 순위가 한 칸쯤 움직임(CY03) — 규칙 폭(0.10 · 0.05)보다 훨씬 작음
- 알고 남김: 실행 중 추적 전송 실패 경고(`langfuse-web` 이름 못 찾음) — 추적만, 결과 무관

## 청크 맥락·리랭커·컷오프 판정 (SCRUM-308, 2026-11-21 — 결과 보기 전, 09 같은 날 줄)

세 가지(유사도 컷오프 · 리랭커 · 청크 맥락)의 판정 기준을 **실행 전에 한 커밋**으로 고정한다. 결과를 본 뒤 기준을 고칠 일이 생기면 고치지 않고 멈춘다. **진희 결정(11/21)**: 11/18 "시연 경로 검색 결과는 바꾸지 않는다" 대신 **"미리 적은 기준 통과 + 아래 '켤 때 갖출 것' 전부 → 초안 경로 기본값 켬"**. 못 넘으면 지금처럼 끔 · 숫자만 기록. PR 은 셋으로 나눔(308-1 컷오프 → 308-2 리랭커 → 308-3 청크 맥락, 앞이 안 끝나면 뒤를 안 함).

- **이름은 "개발용 결정"** — 평가 세트 v3(질의 34 · 정답 58)는 개발용뿐. 결과 문구는 "미리 적은 규칙을 넘었다/못 넘었다". 275 보류용·holdout_v2 재사용 0

### 공통 지표 (셋 다)

- **초안 경로** = 유형 필터 켬 · 한 번 찾기 {a} · 후보 `RAG_CANDIDATES`(10) → 앞 `RAG_TOP_K`(3). 정답 = 확인 등급 ≥ 1 이고 **`db_tagged=true`**(45 — 필터 켠 검색에 나올 수 있는 것만)
- **precision@3** = |top-3 ∩ 정답| / 3 (결과가 3건보다 적어도 분모 3). **hit@3** = top-3 에 정답 1개 이상이면 1. **recall@10** = |top-10 ∩ 정답| / |정답|. 유형별 = 그 유형 질의 6개 평균, 정답 있는 질의만 분모
- **평균 = 4유형(FAN_IN·FAN_OUT·CYCLE·GATHER_SCATTER) macro**, 유형별 값은 반올림 전으로 평균하고 비교·표시 때만 소수 3자리. SCATTER_GATHER 는 표에만(정답 2청크)
- **hit@3 하락 없음** = 4유형 각각 새 값 ≥ 기준 값. 유형마다 질의 6개라 1/6(0.167) 단위 — 그 유형에서 질의 하나라도 hit 를 잃으면 탈락
- **정답 없는 질의**(FX_RELAY 2 · 무관 2)는 초안 경로에서 0건 유지(지금 0건)
- 넘을 수 있는 최대 폭(후보 10 을 완벽히 다시 줄 세울 때, 307 결과 초안 경로): precision@3 0.819 → 1.000(+0.181) · recall@3 0.299 → 0.354(+0.055) · recall@10 0.773 → 0.823(+0.050, GS 완벽일 때만) — 그래서 지표는 precision@3

### ① 유사도 컷오프 (308-1)

- 데이터: `tests/str/rag_eval_v3/result_307.json` 에 저장된 cosine 만(외부 호출 0). 하네스 `tests/str/rag_eval_v3_cutoff.py`(순수) + 테스트
- **규칙**: 초안 경로(`on_a_kw0`) top-3 에서 **정답 칸을 하나도 잃지 않는 가장 큰 값** t(= 정답 칸 cosine 최소)를 구한다. t 가 **정답 없는 질의의 결과를 하나 이상 없앨 때만** `MIN_SIMILARITY = t` 로 넣고, 아니면 0.0 유지. 정답 없는 질의의 결과 = 초안 경로 결과 + 필터 끔 6조건 top-3(빈칸 채우기 채우는 쪽 cosine 은 307 에 따로 없어서 필터 끈 조건들로 대신)
- 넣으면 `MIN_SIMILARITY` 하나가 초안 경로·채우는 쪽 둘 다에 걸림(지금 상수 하나)
- 예상(★A 계산 — 결과 보기 전 분포): 정답 칸 최소 0.316 · 초안 경로 정답 없는 질의는 이미 0건 · 필터 끔 정답 없는 질의 top-3 는 0.344 이상 → **0.0 유지**가 예상값

### ② 리랭커 (308-2)

- **방식**: 같은 공급자 LLM 목록형 재정렬 — 후보(최대 10)의 `chunk_id`·`Reference.text`(600자, 화면에 나가는 것과 같음) → **`chunk_id` 순서만** 받음(점수·본문 반환 0). 새 프롬프트 `prompts/rerank_v1.md`(기동 해시 검사 대상) · 새 의존성 0. 모델 env `RAG_RERANK_MODEL`(빈 값이면 `LLM_MODEL_JUDGE`) · 시간 한도 `RAG_RERANK_TIMEOUT_S=8` · 스위치 `RAG_RERANK_ENABLED`(기본 false). 응답이 후보 집합과 다르거나(빠짐·중복·없는 id) 형식이 틀리거나 시간 초과·공급자 오류면 **원래 순서**(fail-open). `Reference.score` 는 그대로 cosine
- **판정**: 질의마다 초안 경로 후보를 **한 번 고정**(임베딩 1회)하고 같은 후보에 리랭커를 **2회**. 기준선 = 같은 실행의 원래 순서(307 숫자 아님). 각 회차에서
  - 4유형 평균 precision@3(리랭커) − (원래 순서) **≥ +0.10**
  - hit@3 하락 없음(4유형, 1/6 단위)
  - 리랭커 호출 시간 **p95 ≤ 5초**(정답 있는 질의의 호출, 회차별)
  - 형식 실패율(원래 순서로 돌아간 호출 / 호출 수) **≤ 10%** — 실패한 질의는 원래 순서로 셈
  - **두 회차 모두** 넘어야 통과. 온도는 `LLM_TEMPERATURE_SUPPORTED` 가 false 면 걸지 않고 `reasoning_effort` low 고정
- 예상 호출: 임베딩 34 · LLM 정답 있는 30 질의 × 2 = 60(정답 없는 4 질의는 후보 0 → 호출 0)

### ③ 청크 맥락 (308-3)

- **방식**: 청크 앞에 `{title} — {publisher}, {year}, p.{page}`(manifest 값) 한 줄을 붙인 문장으로 **다시 임베딩**(LLM 0). 새 표 `ai.reference_chunks_ctx`(지금 표와 같은 칸·`chunk_id`·태그, Alembic 새 버전) — 본문 `text` 는 머리말 없이 원래대로, 임베딩만 바뀜. **지금 표·ES v2 는 그대로**, ES 새 색인은 안 만듦(초안 경로는 ES 를 안 씀). 전환 env `RAG_CHUNK_CONTEXT_ENABLED`(기본 false — 끄면 원래 표). 질의 문장·질의 임베딩 변경 0
- **판정**: **같은 실행 안에서 같은 질의 벡터로 지금 표와 새 표를 함께** 초안 경로로 검색해 비교(307 결과 숫자와 비교 안 함 — 임베딩 값이 실행마다 조금씩 다름)
  - 4유형 평균 precision@3(새 표) − (지금 표) **≥ +0.10**
  - hit@3 하락 없음 · recall@10 하락 없음(4유형 각각)
  - 정답 없는 질의(필터 켬) 0건 유지
  - 필터 끔 경로는 표에만(하한)
- 11/23(월) 밤까지 판정이 안 나오면 **하지 않고 결과만**(동결 11/24) — 새 표를 만들었어도 전환 0

### 같이 켤 때

- 리랭커·청크 맥락이 **둘 다 통과**하면 조합(새 표 후보 → 리랭커 2회)을 한 번 더 잰다. 조합이 같은 기준(지금 표·원래 순서 대비 precision@3 ≥ +0.10 · hit@3 하락 없음 · 두 회차 모두)을 넘으면 둘 다 켬, 못 넘으면 **리랭커만**

### 켤 때 갖출 것 (통과해도 다 있어야 켬 — 275 와 같은 모양)

스위치 env(앱 재시작으로 끔) · fail-open 테스트(리랭커 시간 초과·형식 오류·공급자 오류 → 원래 순서) · 초안 80초 예산 안 실측 · `Reference.score` 는 cosine 그대로(리랭커 순서는 안에서만 — 규약·`references` 모양 그대로) · `retrieval_version` 꼬리 · 오류 주입 13·14 통과 · 외부 호출 중 DB 연결 안 듦 · 로그에 본문·프롬프트 전문 0 · v4 에만(v2·v3 는 그대로)

### `retrieval_version` 꼬리

켜진 것만, 순서 고정 `+ctx:v1` → `+rr:rerank_v1` → (275) `+fill:…+kw:…` — 예 `text-embedding-3-small@36b5a2d5+ctx:v1+rr:rerank_v1`(128자 안). 끄면 지금 그대로. 백엔드는 health 로그에만 찍음(변경 0)

### 시연에 미치는 것

붙이면 화면 참고 사례 3건의 순서·구성이 바뀔 수 있음(v4 초안 본문은 참고 사례를 안 써서 그대로) → 11/24 리허설 캡처·대본 다시

### 한계

- 개발용 34개만 — 큰 차이만 잡힘
- **precision@3 정답은 확인 정답(`db_tagged=true` 45)만 — 하한**: 태그는 붙었지만 등급 확인이 0 이거나 안 본 청크가 top-3 에 오르면 오답으로 셈
- SG 정답 2청크(표에만) · 정답은 유형 단위(같은 유형 질의 6개는 정답이 같음)
- LLM 흔들림은 2회로만 봄 · 컷오프의 "채우는 쪽" cosine 은 필터 끈 조건들로 대신(근사)

## 청크 맥락·리랭커·컷오프 판정 결과 (SCRUM-308 — 개발용 결정)

위 기준 절은 그대로 두고 결과만 여기(기준 절 글자가 바뀌면 하네스 거절이 막음). 기준 커밋 `87aef09`(결과 보기 전).

### ① 유사도 컷오프 (308-1, 2026-11-22) — 안 넣음, `MIN_SIMILARITY` 0.0 유지

`tests/str/rag_eval_v3_cutoff.py`(외부 호출 0 · 307 `result_307.json` 저장 cosine 과 v3 정답 후보만) · 결과 `tests/str/rag_eval_v3/result_308_cutoff.json`(값·개수·입력 해시만, 원문 0).

- **다시 돌림(추가 검토 1)**: 첫 실행(기준 커밋 `87aef09` = HEAD)은 기준 검사가 HEAD·작업 트리만 비교했고, 입력 파일을 고쳐도(질의 표식 하나만 빠져도 채택이 뒤집힘) 걸러지지 않았고, 저장 cosine 6자리 반올림을 안 봤음 → 하네스를 고친 뒤 결과 파일을 지우고 다시 돌림. 고친 것: 기준 커밋을 하네스 상수로 고정(HEAD 조상 · 그 커밋 기준 절 = HEAD = 작업 트리) · 307 결과·정답 후보·질의를 기준 커밋 안 파일과 바이트가 같을 때만 계산 + 구조 검사(초안 조건 1 · 필터 끔 6 · 질의 id·`uses`) · 반올림 오차 ±5e-7 — 적용값 t = 정답 칸 최소 − 5e-7, 정답 없는 칸은 확실히 t 아래일 때만 "없앰", 판별 못 하면 경계 칸 → 채택 보류

| 항목 | 값 |
|---|---|
| 초안 경로 top-3 정답 칸 | 66 — 최소 cosine **0.315951** → 적용값 t = 0.3159505(반올림 오차만큼 아래) |
| t 에서 잃는 정답 칸 | 0 |
| 정답 없는 질의 칸(초안 경로 + 필터 끔 6조건 top-3) | 66 — 최소 cosine **0.344247** |
| t 에서 확실히 없어지는 정답 없는 질의 칸 · 경계 칸 | **0** · 0 → 규칙 미달 |
| (참고) 확인 정답 밖 칸 | 24칸 중 2칸 제거 — 두 칸(SG05 0.298 · SG02 0.302)은 같은 SG 청크, 실제 오답 여부 미확인 |

- **결론: 미리 적은 규칙을 못 넘음 → `MIN_SIMILARITY` 0.0 유지**(src·상수·`retrieval_version` 변경 0). 초안 경로에서 정답 없는 질의는 이미 0건(태그 0 유형 · 빈칸 채우기 규칙 3)이고, 필터 끈 쪽 정답 없는 질의 cosine(0.344~)이 정답 칸 최소(0.316)보다 높아 정답을 지키면서 없앨 것이 없음 — ★A 분포에서 본 예상대로
- 확인 정답 밖 2칸(같은 청크)을 없애는 것은 참고 사례 칸을 비우기만 함(규칙 밖, 판정에 안 씀)

### ② 리랭커 (308-2, 2026-11-22) — 미채택, `RAG_RERANK_ENABLED=false` 유지

`tests/str/rag_eval_v3_rerank_live.py`(손 실행, 호스트) · 결과 `tests/str/rag_eval_v3/result_308_rerank.json`(위치·순서·값만, 원문 0). 기준 커밋 `87aef09` 그대로 판정(`judged=true`) — 다시 돌리지 않음.

- **실측은 커밋 전 작업 폴더에서 실행**했고, 결과 파일의 `head`(`662b86e`)는 실행 시점 HEAD. 실행한 코드는 이 절과 같은 커밋으로 들어감
- 실행 확인: 임베딩 `text-embedding-3-small` · 리랭커 응답 모델 1종 · LLM 호출 60(회차당 30 = 정답 있는 질의 5유형 × 6, FX_RELAY 2·무관 2 는 후보 0 → 호출 0) · 형식 실패 0 · 코퍼스 재임베딩 대조 65청크 전부 cos ≥ 0.99(최소 0.999957)
- **결정: 미채택.** 두 회차 모두 4유형 precision@3 개선 **+0.014 < +0.10**. 나머지 세 조건(hit@3 하락 없음 · p95 3.27초 / 3.38초 · 형식 실패율 0)은 통과. 코드·프롬프트(`rerank_v1.md`)·fail-open 은 남김(기본 끔)
- 한 유형은 만점이 됐고 한 유형은 떨어져서 켜지 않았다:

| 유형 | 원래 순서 | 1회 | 2회 | 후보 안 정답을 완벽히 올렸을 때 |
|---|---|---|---|---|
| FAN_IN | 1.000 | 1.000 | 1.000 | 1.000 |
| FAN_OUT | 1.000 | 0.667 | 0.667 | 1.000 |
| CYCLE | 0.667 | 0.667 | 0.667 | 1.000 |
| GATHER_SCATTER | 0.611 | 1.000 | 1.000 | 1.000 |
| **4유형 평균** | **0.819** | **0.833** | **0.833** | 1.000 |
| SCATTER_GATHER(평균 제외) | 0.389 | 0.556 | 0.500 | 0.667 |

  - 마지막 열 = 같은 정답 기준(등급 ≥ 1 · `db_tagged=true`)으로 질의마다 min(3, 후보 안 정답 수)/3
  - GATHER_SCATTER: 6 질의 모두 두 회차 모두 만점
  - FAN_OUT: `ffiec-redflags` 4쪽 pos 2(확인자 등급 0, 태그 있음)를 12번(6 질의 × 2회) 모두 상위 3에 올림(원래 순위 4~6)
  - CYCLE: `apg-typologies-2025` 53쪽 pos 3 을 12번 모두 상위 3에 올림(원래 순위 5·7) — 305 확인자 등급 0(정답 후보 파일엔 등급 ≥ 1 행만 옮겨서 이 유형 행이 없음) → 오답으로 셈
  - FAN_IN 은 후보 10건이 전부 정답, FAN_OUT 은 후보 6건 중 5건이 정답이라 원래 만점 — 리랭커가 올릴 여지 0
  - 두 회차 gain 이 같은 것은 정상: 호출된 30 질의 중 18개는 회차 간 전체 순서가 달랐고(따로 호출됨), 평균에 드는 4유형에서 상위 3 집합만 같았음
- **한계**
  - 유형 안 6 질의가 똑같이 움직여서 실질 표본은 유형 수(4)에 가깝다
  - 판정이 청크 두 개의 등급에 달려 있다 — 위 FAN_OUT 청크·CYCLE 청크가 둘 다 정답이었다면 개선 폭 약 +0.18, 하나만이면 +0.097(가정 계산 — 이번 판정은 안 바꿈)
  - 평균에 들지 않는 SCATTER_GATHER 는 6 질의 중 4개에서 상위 3 이 회차마다 달랐다 — 리랭커 결과가 호출마다 흔들릴 수 있다
  - 초안 경로는 유형 필터 뒤 후보가 6~10개라 리랭커가 올릴 여지가 작다
- **다음에 볼 것**(이번 범위 아님)
  - 태그됐지만 등급 0 인 후보 청크(이번 후보에 나온 CYCLE 3 · SG 4 · GS 3 — 305 확인 등급 0)와 FAN 등급 0 청크를 외부 확인자가 다시 확인 — 어느 청크가 문제였는지 알리지 않고 전부 맡김. 등급이 바뀌면 새 정답 버전 · 새 기준 커밋 · 새 실험, 이번 판정은 안 고침
  - 리랭커를 사례 검색 경로(후보가 많고 질의를 조사역이 직접 쓰는 곳)에서 따로 판정 — 효과는 아직 재지 않은 추정

### ③ 청크 맥락 (308-3, 2026-11-22) — 미채택, `RAG_CHUNK_CONTEXT_ENABLED=false` 유지

- 머리말 형식은 기준 그대로(`{title} — {publisher}, {year}, p.{page}`), 연도 없는 `ffiec-redflags` 15청크만 연도 칸 생략(`{title} — {publisher}, p.{page}`) — manifest 는 안 고침
- `tests/str/rag_eval_v3_ctx_live.py`(손 실행, 호스트) · 결과 `tests/str/rag_eval_v3/result_308_ctx.json`(위치·`chunk_id`·값만, 원문 0). 기준 커밋 `87aef09` 그대로 판정(`judged=true`) — 다시 돌리지 않음
- **실측은 커밋 전 작업 폴더에서 실행**했고, 결과 파일의 `head`(`f0d2ea7`)는 실행 시점 HEAD. 실행한 코드는 이 절과 같은 커밋으로 들어감
- 실행 확인: 임베딩 `text-embedding-3-small` · 질의 임베딩 32(무관 2 는 0) · 두 표 722 재임베딩 대조 below 0 · 가까운 쪽 위반 0 · indistinct 0(최소 cos 지금 0.997264 / 새 0.99981) · 기대 태그·머리말·본문 해시 대조 통과 · LLM 0
- **결정: 미채택.** 4유형 precision@3 **0.819 → 0.833(+0.014 < +0.10)** · recall@10 하락 FAN_IN·CYCLE·GATHER_SCATTER. hit@3 하락 없음 · 정답 없는 질의 0건은 통과. 새 표·적재 도구·기동 검사·스위치는 남김(기본 끔)

| 유형 | p@3 지금 | p@3 새 | hit@3 지금 | hit@3 새 | recall@10 지금 | recall@10 새 |
|---|---|---|---|---|---|---|
| FAN_IN | 1.000 | 0.944 | 1.000 | 1.000 | 0.625 | 0.573 |
| FAN_OUT | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| CYCLE | 0.667 | 0.667 | 1.000 | 1.000 | 1.000 | 0.976 |
| GATHER_SCATTER | 0.611 | 0.722 | 1.000 | 1.000 | 0.467 | 0.422 |
| **4유형 평균** | **0.819** | **0.833** | — | — | 0.773 | 0.743 |
| SCATTER_GATHER(평균 제외) | 0.389 | 0.444 | 1.000 | 1.000 | 1.000 | 1.000 |

  - 지금 표 숫자 = 308-2 원래 순서(질의별 후보 순서까지 같음) · 필터 끔({a}, 표에만): 4유형 p@3 0.028 → 0.083 · recall@10 0.053 → 0.032
  - +0.014 = 1/72(4유형 × 질의 6 × 칸 3): 상위 3 정답 칸 FAN_IN 18 → 17 · GATHER_SCATTER 11 → 13 → 순 +1칸. 308-2 와 같은 값이지만 바뀐 유형·칸은 다름(308-2 는 FAN_OUT −6 · GS +7)
  - recall@10 하락은 문서 단위 이동: FAN_IN 은 `fincen-funnel-2014` 정답(p6 pos1 등)이 상위 10 에서 빠지고 `fatf-pml-2018` 청크(p44 pos2 등급 0 · p43 pos2 정답)가 들어옴 · GATHER_SCATTER 는 `fintrac-underground-banking-2023` 정답(p3 pos3 · p7 pos1 등)이 빠지고 `apg-typologies-2025` 청크(p39 pos2·p31 pos1 정답, p81 pos3·p39 pos3 은 305 등급 0)가 들어옴 · CYCLE 은 `ffiec-redflags` p6 pos2 하나가 빠지고 `apg-typologies-2025` p53 pos1(305 등급 0)이 들어옴
- **한계**
  - 개발용 34 질의 · 유형 안 6 질의가 같은 정답을 써서 실질 표본은 유형 수에 가깝다
  - 정답은 확인 정답(`db_tagged=true`)만 — 새로 들어온 등급 0 청크(305 확인 0 포함)는 오답으로 셈(하한)
  - 머리말 형식 하나(v1)만 쟀다 — 문서 제목이 같은 청크끼리 임베딩을 끌어당기는 모양(위 문서 단위 이동)
- **다음에 볼 것**(이번 범위 아님)
  - 머리말에 쪽 안 위치·절 제목 등 다른 맥락을 넣는 형식은 새 기준 커밋·새 실험으로
  - 등급 0 청크 재확인은 ② 의 "다음에 볼 것" 과 같이(새 정답 버전 · 새 기준 커밋)

## 리랭커 (SCRUM-308-2, 2026-11-22 — 붙이되 기본 끔, 판정 통과해야 켬 → 판정 미채택, 위 결과 절 ②)

판정 기준은 위 "청크 맥락·리랭커·컷오프 판정" ②(`87aef09`)를 그대로 쓴다 — 이 절은 **어떻게 붙이는지**만. **기본 끔**(`RAG_RERANK_ENABLED=false`) — 끄면 검색 결과·호출 수·`retrieval_version` 이 지금과 같다.

```
facts → (a) build_query 임베딩 1회 → PG(필터 켬, 지금 SQL) 후보 RAG_CANDIDATES(10)
   리랭커 꺼짐 또는 v2·v3       → 앞 RAG_TOP_K(3) — 지금 그대로(후보 limit 3)
   리랭커 켬 + v4, 후보 ≥ 2     → release()(DB 연결 반납, SCRUM-122) → LLM 1회(rerank_v1) → 순서 검사 → 앞 3
   후보 0~1                    → LLM 호출 0
   → (빈칸 채우기 켰으면 그 뒤 그대로 — 275 규칙)
```

- **v4 에서만**: `rag_rerank_active = RAG_RERANK_ENABLED and NARRATIVE_PROMPT == narrative_v4`(빈칸 채우기와 같은 모양). v2·v3(참고 사례를 프롬프트에 넣음)는 지금 검색 그대로
- **보내는 것**: 질의 = 검색어 (a) `build_query(facts)`(유형·패턴·신호·업종 — 숫자·계좌·금액 0) 한 줄 + 후보마다 표지 `C1`~`Cn`(지금 순서)와 `Reference.text`(600자 — 화면에 나가는 것과 같음). `chunk_id`·문서 id·점수는 안 보냄. 이용 조건은 임베딩과 같은 공급자 → 같은 처리(⑨)
- **받는 것**: 표지 순서 목록만(Structured Output `RerankOut{order: [표지…]}`) → 코드가 `chunk_id` 로 되돌림. **순서 검사**(`str/domain/rag_rerank.py`, 순수): 응답이 후보 표지의 **순열**이어야 함 — 빠짐·중복·없는 표지·다른 형식은 형식 실패
- **fail-open**(각각 테스트): 시간 초과·공급자 오류(`LlmUnavailable`) · 형식 오류(`LlmInvalidOutput`·JSON) · 순서 검사 실패 → **원래 순서**, 경고 1줄 `rerank_failed reason=…`(이유 낱말만 — 본문·질의·응답 0). 초안은 계속
- **`Reference.score`** 는 그대로 cosine(리랭커는 순서만, 점수를 밖에 안 냄 — 규약·`references` 모양 그대로)
- **설정**: `RAG_RERANK_ENABLED`(false) · `RAG_RERANK_MODEL`(빈 값이면 `LLM_MODEL_JUDGE`) · `RAG_RERANK_TIMEOUT_S`(8 — 호출별 한도, 남은 예산으로 줄이지 않음: v4 초안은 LLM 0 이고 검색이 맨 앞) · 상수 `RAG_RERANK_MAX_TOKENS = 1000`(추론 토큰 포함 상한, `constants_rag_query.py`). 비밀값 0
- **예산**: v4 초안은 코드 조립이라 리랭커 1회(≤ 8초)가 유일한 LLM 호출 — `DRAFT_BUDGET_S=80` 안. 켤 때 실측(켤 때 갖출 것)
- **녹화**: `rerank_v1` 녹화는 안 만듦 — 녹화 재생(`AI_LLM_MOCK=true`)에서 켜면 녹화가 없어 원래 순서(fail-open). 켤 결론이 나면 시연용 녹화를 그때
- **`retrieval_version`**: 켜졌을 때만 `+rr:rerank_v1`(빈칸 채우기 꼬리 앞)
- **파일**: `str/prompts/rerank_v1.md`(새, `FROZEN_PROMPTS` 해시) · `shared/schemas/str/rerank_llm.py`(출력 모양) · `str/domain/rag_rerank.py`(순서 검사·적용, 순수) · `str/infrastructure/retriever_rerank.py`(LLM 호출·fail-open — 275 `retriever_fill` 과 같은 자리) · `Retriever(..., reranker=)` · `draft_service._retriever` 연결
- **질의 신호·업종은 등록 목록(버전 V1)만**(추가 검토 2 — 1회차 모양 검사 대체): `str/domain/constants_rerank_registry.RAG_RERANK_REGISTRY_V1` — 신호 = 점수 모델 reason 이름 `aml_ml.FEATURE_NAMES`(0.1.0rc2, 31개) ∪ v3 평가 세트·base 픽스처 신호 6개 · 업종 = 고객 업종 표시 라벨 9개 ∪ 평가 세트 업종(RESTAURANT). 출처와 같은지 테스트가 대조. 신호·업종 중 하나라도 목록 밖이면 호출 0·원래 순서(`rerank_failed reason=unregistered_signal`). **새 신호가 생기면 목록부터 고치고(V2) — 목록 밖은 원래 순서**. 모의 점수의 `mock_feature` 는 목록에 없음(리랭커 원래 순서)
- **프롬프트**: 바이트를 한 번 읽어 `FROZEN_PROMPTS` 와 대조한 템플릿을 캐시(`rerank_prompt`) — 실행·결과 해시가 같은 바이트. **만들기 실패**(템플릿·해시 등)도 fail-open: 리랭커 없이 기본 검색(`init_…`). 초안 서비스는 이미 만든 LLM 클라이언트를 같이 씀
- **`retrieval_version` 길이 기동 검사**: 켜진 꼬리까지 붙인 길이가 128(`generations.retrieval_version`)을 넘으면 기동 실패 — 초안 저장 실패를 요청 전에 막음
- **응답 모델·마감**(추가 검토 4): 응답 해석 경계(`openai_responses.read_output`)가 모델명을 **맨 먼저** 읽고(strip, 빈 값은 None), 그 뒤 output·content·usage 해석의 어떤 오류든 모델명을 실은 `LlmInvalidOutput`(`response_received=True`)으로. 리랭커는 진입 때 단조 시계로 마감(진입 + `RAG_RERANK_TIMEOUT_S`)을 잡고 순열을 돌려주기 직전에 다시 봐서, 지났으면 `deadline` 실패 → 원래 순서(운영·평가 공통)
- **임베딩 응답 모델**(추가 검토 4 — 기본 경로에도 적용): 공통 `HttpEmbeddingClient.embed()` 가 배치마다 응답 본문 `model`(strip) = 요청 모델(strip)일 때만 벡터를 돌려줌. 다르거나 없으면 `EmbeddingModelMismatch`(`RetrievalUnavailable` 하위) — 운영 검색은 기존 임베딩 실패처럼 RAG 없이 진행, 적재 도구는 INSERT 전 중단. 요청·DB `embedding_model` 기록도 정규화 값
- **켜기 전 확인 — 운영 타임아웃 상한 8초(기동 검사), 남은 요청 예산은 안 봄**(추가 검토 3): `RAG_RERANK_ENABLED=true` 면 `RAG_RERANK_TIMEOUT_S` 가 0 초과·8 이하여야 기동(`rerank_timeout_problem`). 8 이하는 허용(짧으면 폴백만 늘어남). v4 는 검색이 초안 맨 앞이라 남은 예산 검사는 이번 범위 밖
- **응답 수신·허용 응답 모델**(추가 검토 5): HTTP 200 본문을 받은 뒤의 모든 해석 실패(JSON 디코딩·최상위가 객체 아님 포함)도 `LlmInvalidOutput(response_received=True, response_model=None)` — 판정 하네스는 "모델명 없는 응답"으로 세어 판정 안 함. **운영 `order()` 는 응답 모델이 `RAG_RERANK_RESPONSE_MODEL`(strip, 실제 응답 모델 ID)과 같을 때만 순열 적용**, 없거나 다르거나 빈 값이면 `response_model_mismatch` → 원래 순서. 하네스(`order_with_model`)는 이 값을 쓰지 않고 응답 모델을 모아 기록
- **검색 SQL 의 임베딩 모델 조건·응답 index**(추가 검토 5 — 기본 경로, 리랭커와 무관): 운영 후보 검색(`_candidates`, 유형 필터 켬·끔 둘 다)과 빈칸 채우기 cosine 조회(`_cosines`)는 `embedding_model = 질의 모델(정규화)` 행만 — 차원이 같은 다른 모델 벡터와 순위를 섞지 않음. ES 키워드 경로는 벡터를 안 써서 그대로(키워드 후보도 cosine 은 같은 모델 행에서만 받음). 임베딩 응답은 `index` 로 입력 순서 복원 — 0..n-1 순열이 아니면(누락·중복·범위 밖) `EmbeddingIndexInvalid`(`RetrievalUnavailable` 하위: 운영 RAG 없이·적재 INSERT 전 중단), 단일 입력은 index 없으면 0
- **수신 경계·동점 기준**(추가 검토 6): LLM 응답은 상태 먼저 받고 본문을 따로 읽음(`llm_receive`) — 200 뒤 본문 압축 해제 실패도 `LlmInvalidOutput(response_received=True, response_model=None)`, 200 이 아니면 지금 분류 그대로, 연결·읽기 끊김·시간 초과는 그대로 `LlmUnavailable`. 후보 SQL 바깥 정렬은 `ORDER BY 거리, chunk_id` — 기본 LIMIT 3 결과 = 리랭커 후보 LIMIT 10 의 앞 셋이라 리랭커 폴백(모델 불일치·마감·형식 오류) = 리랭커 끔. **기본 경로 동작 변경**: 거리가 같을 때만 순서가 chunk_id 로 고정(develop 은 동점 순서 미정)
- **한계 — 임베딩 응답 index 타입**(추가 검토 6 M4, 알고 남김): `index` 는 정수만 온다고 봄(OpenAI 임베딩 응답 규격). 공급자가 불리언(`true`/`false`)을 보내면 Pydantic 이 1/0 으로 바꿔 순열 검사를 통과할 수 있음 — 규격 밖 응답이라 엄격 정수 검사는 넣지 않음
- **켜는 절차**(추가 검토 5): ② 통과 결과의 `response_models` 한 값을 `RAG_RERANK_RESPONSE_MODEL` 에 넣고 `RAG_RERANK_ENABLED=true` — 켰는데 비면 기동 실패(`rerank_response_model_problem`)
- **판정 하네스**(손 실행, 호스트 — ES 안 씀): `tests/str/rag_eval_v3_rerank_live.py` + 순수·거절 모듈 — 307·308-1 과 같은 모양(기준 커밋 `87aef09` 고정 · v3 입력·위치표 바이트 = 기준 커밋 · DB 722·태그 대조 · 결과 `result_308_rerank.json` 배타 생성 · 원문·프롬프트·검색어 문장 0). 실측은 첫 외부 호출 전에 녹화 재생(`AI_LLM_MOCK=true`)·빈 모델명(`RAG_RERANK_MODEL`·`LLM_MODEL_JUDGE` 각각 strip 뒤 폴백)·`LLM_REASONING_EFFORT` ≠ low·**`RAG_RERANK_TIMEOUT_S` ≠ 8** 거절 · DB `embedding_model` 이 정확히 하나이고 질의 모델과 같아야(사전 검사·후보 스냅샷 둘 다), 질의가 쓰는 base 픽스처도 기준 커밋과 바이트 대조 · 결과 경로 잠금 → **잠금 직후 결과 파일 다시 검사**(있으면 외부 호출 0 으로 끝). 질의 문장은 **검증한 픽스처 객체의 복사본만으로**(파일 재읽기 0) 한 번 만들어 (a) 임베딩(유형 있는 질의 32)·두 회차에 재사용 → 읽기 전용 REPEATABLE READ 스냅샷 하나에서 후보 10 → **정답 없는 질의에 결과가 하나라도 있으면 판정 중단** → 스냅샷 닫고 **코퍼스 재임베딩 대조**(추가 검토 4·5 — 적재 당시 응답 모델을 확인 못 한 기존 코퍼스: 평가 질의들의 유형 필터를 통과하는 **모든** 같은 모델 청크(순위와 무관 — 검토 5)의 저장 본문을 검증 경로로 다시 임베딩해 저장 벡터와 cos ≥ 0.99(정규화 후 내적, 유한값만 — 검토 5)일 때만 진행, 한 청크라도 아니거나 대상 0 이면 리랭커 호출 전 중단 · 결과에 `corpus_recheck{chunks, min_cos, below}` · 전체 재적재 대신) → 리랭커 2회(정답 있는 30 질의 × 2 = LLM 60, 타이머는 `order()` 만) → 회차별 precision@3·hit@3·호출 p95(정답 있는 질의 호출)·형식 실패율(**회차 전체 리랭커 대상 중 폴백** — 범주 밖 질의 포함) → ② 규칙 → 임시 파일 → 원자적 게시(기존 결과 안 덮음). 결과에 요청 모델·회차별 **응답 모델**(응답 본문 `model` — 본문 파싱 **전에** 읽어 거절·형식 실패 응답에도 실음, 없으면 요청 모델로 안 채우고 None)·추론 설정 기록 — 한 실측에서 응답 모델이 2종 이상이거나 모델명 없는 응답이 하나라도 있으면 `judged=false`(추가 검토 3). 임베딩 모델명은 한 번 정규화(strip)한 값 하나를 사전 검사·임베딩 요청·스냅샷 대조·결과에 공통으로 쓰고, 실측 임베딩은 응답 본문 `model` 이 그 값과 같아야(없거나 다르면 후보 검색 전 중단). `--dry` = 가짜 벡터 + 가짜 리랭커, 회차 지표만 남기고 **최종 판정 `judged=false`·`adopt=false` 고정**(결과·출력에 `dry=true`)
- **다시 돌리기**: 결과 파일을 지우고 다시 돌리는 건 **하네스 결함을 고쳤을 때만**, 사유를 report·이 절에 기록 — LLM 결과가 마음에 안 들어서는 다시 돌리지 않음

## 청크 맥락 (SCRUM-308-3, 2026-11-22 — 새 표에 붙이되 기본 끔, 판정 통과해야 켬 → 판정 미채택, 위 결과 절 ③)

판정 기준은 위 "청크 맥락·리랭커·컷오프 판정" ③(`87aef09`)을 그대로 쓴다 — 이 절은 **어떻게 붙이는지**만. **기본 끔**(`RAG_CHUNK_CONTEXT_ENABLED=false`) — 끄면 검색 표·결과·`retrieval_version` 이 지금과 같다. 리랭커가 미채택(308-2)이라 **조합은 재지 않음**("같이 켤 때" 조건 미충족).

```
적재(한 번, 진희 터미널) : ai.reference_chunks(읽기만) 722행 → 머리말 + 본문 임베딩 → ai.reference_chunks_ctx
검색(켬 + v4)           : 질의 임베딩 그대로 → 같은 SQL 모양으로 ai.reference_chunks_ctx 조회
검색(끔 또는 v2·v3)     : 지금 그대로 ai.reference_chunks
```

- **새 표 `ai.reference_chunks_ctx`**(Alembic `0007_reference_chunks_ctx`): `reference_chunks` 와 **같은 칸**(14) · PK `chunk_id` · `content_hash` UNIQUE · HNSW(`vector_cosine_ops`) on `embedding` · GIN on `typologies`. `vector(1536)` 고정(0004 와 같은 이유). `text` 는 머리말 없이 원래 본문 — **임베딩만** 머리말 붙인 문장
- **머리말**(순수 함수, `str/domain`): `{title} — {publisher}, {year}, p.{page}` 한 줄 + 줄바꿈 + 본문. 값은 manifest(`title`·`publisher`·`year`) + 청크 `page`. `year` 가 없으면 `, {year}` 칸만 생략(지금 `ffiec-redflags` 15청크). 버전 상수 `CHUNK_CONTEXT_VERSION = "v1"`
- **적재 도구**(새 표에만 씀): 지금 표에서 `chunk_id`·`doc_id`·`doc_title`·`publisher`·`year`·`page`·`section`·`lang`·`typologies`·`text`·`content_hash` 를 **읽기만** 해 그대로 복사(같은 `chunk_id`·태그·본문 보장), 임베딩은 공통 클라이언트(응답 `model`·`index` 검사)로 머리말 문장만. 거절: 새 표가 비어 있지 않음 · 지금 표 DB 메타(`doc_title`·`publisher`·`year`) ≠ manifest · 지금 표 `embedding_model` 2종 이상 또는 설정과 다름. 전부 한 트랜잭션 — 실패면 INSERT 0. 지금 표·ES v2·manifest 변경 0
- **켜는 경로 — v4 에서만**: `rag_chunk_context_active = RAG_ENABLED and RAG_CHUNK_CONTEXT_ENABLED and NARRATIVE_PROMPT == narrative_v4`(RAG 전체 끔이면 기동 대조도 안 함 — 추가 검토 2)(리랭커·빈칸 채우기와 같은 모양). 켜면 Retriever 의 **벡터 조회 전부**(한 번 찾기 · 빈칸 채우기 필터 끔 후보 · 키워드 후보 cosine)가 같은 표 — 섞으면 두 임베딩의 cosine 이 섞임. SQL 은 표 이름만 다르고 같은 모양(`embedding_model = 질의 모델` · 바깥 정렬 `거리, chunk_id`). 질의 문장·질의 임베딩 변경 0. ES 키워드 경로는 그대로(키워드 후보도 cosine 은 새 표에서)
- **기동 검사**(켬 + v4 일 때만): 기동 때 읽기 전용으로 새 표 = 지금 표 대조 — 행 수 · `chunk_id` 집합 · 청크별 태그 · `embedding_model` 1종이고 같음 · 벡터 차원 · 비유한 성분 0. **다르면 기동 실패**. **DB 접속 실패는 기동을 막지 않고 지금 표로**(경고 1줄 `chunk_context_unverified`) — 그 프로세스는 끝까지 지금 표 · `+ctx` 꼬리 없음(확인 못 한 표를 쓰지 않음). **DB 접속 실패로 지금 표가 된 프로세스는 DB 가 살아나도 재시작 전까지 지금 표**. 기동 대조 칸에 머리말 메타(제목·발행처·연도)·section·lang 도(추가 검토 1). **한계(추가 검토 1 H3)**: compose 기동은 컨테이너가 마이그레이션을 먼저 돌려서(`alembic upgrade head && uvicorn …`) DB 가 내려가 있으면 컨테이너가 앱 전에 멈춤 — 지금 표 폴백은 앱이 뜬 뒤 기동 검사 시점에만 DB 접속이 안 될 때(uvicorn 직접 실행 등). Dockerfile·compose 는 안 바꿈, 배포 단계 분리는 발표 뒤 후보 끄면 대조 안 함. 비유한 성분은 pgvector 가 넣을 때 거절해서(NaN·inf 입력 오류) 표에 있을 수 없음 — 테스트로 확인
- **`Reference.score`** 는 새 표 cosine(머리말 붙인 임베딩 기준) — 규약·`references` 모양 그대로
- **`retrieval_version`**: 이번 프로세스가 새 표를 쓸 때만 `+ctx:v1`(`+rr:` 앞 — 순서 `+ctx:v1` → `+rr:rerank_v1` → `+fill:…+kw:…`). 128자 기동 검사에 포함
- **되돌리기**: 스위치 끔(앱 재시작). 표 드롭은 하지 않음
- **기대값 대조**(추가 검토 1): 기대 태그·머리말 = 기준 커밋 `87aef09` 의 manifest(바이트 대조 · 위치표 `manifest_sha256` 과 같음) + 위치표의 문서·쪽(`tests/str/rag_eval_v3_ctx_expect.py`, 적재와 같은 태그 규칙·머리말 함수). 사전 검사·스냅샷에서 **두 표의 청크별 태그·문서·쪽·머리말 메타가 기대와 정확히 같고, 722행 모두 본문 해시 `compute_content_hash(doc_id, page, text)` = 위치표 chunk_id = 저장 `content_hash` 일 때만** 진행(개수가 같아도 내용이 다르면 거절, 본문 교체도 거절 — 추가 검토 2). 재임베딩 대조는 **두 표 722 전부**(지금 표 = 본문, 새 표 = 기대 머리말 + 본문 — 추가 검토 2, 순위·태그와 무관). **두 벌로 가까운 쪽까지**(추가 검토 3 — 새 호출 0): 다시 만든 본문 벡터 B′·기대 머리말 벡터 H′ 로 지금 표 C 는 cos(C,B′) ≥ 0.99 이고 cos(C,B′) > cos(C,H′), 새 표 N 은 cos(N,H′) ≥ 0.99 이고 cos(N,H′) > cos(N,B′)(유한값만) — 머리말 없이 임베딩한 새 표 행을 0.99 를 넘어도 가름. B′·H′ cos ≥ 0.999(본문이 거의 없는 청크)는 비교 대신 수만(`indistinct`). 두 표 같은 chunk_id 저장 벡터가 완전히 같은 행은 거절(사전 검사·스냅샷). 결과에 표별 `below`·`closer_violations`·`min_cos` · 벡터 집합 sha256(chunk_id 순). **한계**: 본문 대조는 정규화 해시(NFKC·앞뒤 공백 제거) — 두 표를 같은 모양으로 손으로 고쳐 앞뒤 공백만 바뀐 본문은 못 잡음(적재는 지금 표 본문을 바이트 그대로 복사하고 기동 검사가 `text IS DISTINCT FROM` 으로 대조 · PDF 복원 대조는 발표 뒤 후보, 추가 검토 3 H2 알고 남김). 판정 뒤 표를 손으로 고쳐 벡터가 바뀌는 건 범위 밖 — 기동 검사는 벡터 값을 안 봄(기동 때 벡터 해시 대조는 발표 뒤 후보). 적재 도구는 빈 표 검사 전에 새 표 잠금(`LOCK … EXCLUSIVE NOWAIT`), 못 잡으면 임베딩 전에 거절
- **판정 하네스**(손 실행, 호스트 — ES 안 씀): `tests/str/rag_eval_v3_ctx_live.py` + 308-2 모듈 재사용(결과 파일 잠금·원자 게시·덮어쓰기 금지 · 실측 거절: 녹화 재생·빈/공백 모델명·기준 커밋 · dry 는 판정 false). 기준 커밋 `87aef09` 고정 · v3 입력·위치표 바이트 = 기준 커밋 · 질의 34 임베딩 **1회** → 같은 읽기 전용 스냅샷에서 두 표 대조(위 기동 검사와 같은 항목) + 지금 표·새 표 초안 경로 후보 10 각각 → 스냅샷 닫고 **재임베딩 대조 두 표**(722 전부 — 추가 검토 2, 처음 계획은 평가 유형 필터 65청크 · 지금 표는 본문, 새 표는 기대 머리말 문장, cos ≥ 0.99 · 비유한 거절, 하나라도 아니면 결과 파일 0) → 지표. 결과 `tests/str/rag_eval_v3/result_308_ctx.json`(위치·`chunk_id`·값만 — 원문·검색어 문장 0)
  - 지표: 4유형 precision@3(새 − 지금) ≥ +0.10 · 4유형 각각 hit@3·recall@10 하락 없음 · 정답 없는 질의(필터 켬) 0건 · SG 와 필터 끔({a} 1조건, 두 표)은 표에만
  - 외부 호출: 적재 722(머리말 문장) · 질의 32(유형 있는 질의 — 무관 2 는 임베딩 0, 308-2 와 같음) · 대조 **722 + 722**(추가 검토 2 — 두 표 전부, 약 56만 토큰) — LLM 0
  - 다시 돌리기: 하네스 결함을 고쳤을 때만, 사유를 report·이 절에 기록
- **켤 때 갖출 것**(판정 통과 뒤, 위 기준 절 목록 중 청크 맥락에 해당하는 것): 스위치 env · 기동 검사(위) · 초안 80초 예산 안 실측 · `Reference.score` cosine · `retrieval_version` 꼬리 · 오류 주입 13·14 통과 · 외부 호출 중 DB 연결 안 듦(새 표는 질의 임베딩 뒤 조회라 지금과 같음) · 로그에 본문 0 · v4 에만. 리랭커 fail-open 항목은 해당 없음

## 참고 사례 검색 (SCRUM-309, 2026-11-22 — 조사역이 유형으로 더 찾아보기, 기본 끔)

정본 노션 「참고 사례 검색 · 승인 STR 색인 설계 문서 (RAG 2차)」 A. 계약 `shared/01` "참고 사례 검색", 처리 순서 `str/03`. 초안 경로(`Retriever`)는 **고치지 않음** — 초안에 붙는 참고 사례 3건·`retrieval_version`·기본값 그대로. 308 판정을 따름: `MIN_SIMILARITY` 0.0 · 리랭커·청크 맥락 안 씀 · 지금 표 `ai.reference_chunks`.

```
요청(유형 1~3 · 검색어 0~1 · top_k) → 스위치·입력 검사 → mask_question(검색어)
  → 질의 한 줄 = 유형 영문 패턴(정해진 순서) + 가린 검색어 → 임베딩 1회(유형만이면 캐시)
  → PG: 같은 모델 · 유형 OR 필터 · 후보 30 → chunk_id 중복 제거 → 한 문서 최대 3 → 앞 top_k
```

- **질의**: 고른 유형의 `TYPOLOGY_PATTERN_EN` 을 `FAN_IN`·`FAN_OUT`·`CYCLE`·`SCATTER_GATHER`·`GATHER_SCATTER` 순서로 공백으로 이어 붙이고, 검색어가 있으면 가린 뒤 뒤에 붙임(`str/domain/reference_search.py`, 순수). 유형마다 따로 임베딩하지 않음(호출 1~3배)
- **가리기**: 질문 답변과 같은 `mask_question`(NFKC 뒤 은행 번호 붙은 계좌 키 → `10_****BD30`, 맨 계좌 → `****BD30`) 뒤에 **검색용으로 한 번 더**(추가 검토 1 — 질문 답변 쪽은 그대로): 숫자 사이에 `-`·공백(탭·줄바꿈 포함)·`.` 만 낀 숫자열을 이어 세어 숫자 8개 이상이면 뒤 4자리만(`****6789`). 구분자는 연속 허용(`1234 - 5678`), 한 자리 사이 묶음은 최대 3글자 — 그보다 멀리 떨어진 숫자는 따로 셈(추가 검토 2). 쉼표 낀 금액(`15,000,000`)은 그대로, 쉼표 없는 8자리 이상 숫자는 금액·날짜(`2022-09-07` → `****0907`)여도 가림(검색 의미 손실이 작아 실패 쪽으로 닫음). 외부 임베딩 API 로 가는 문장에 계좌 원문 0. 가린 뒤 남는 글자(공백 빼고)가 없으면 유형 질의만. 추가 검토 3 — 검색용 가리기를 **`mask_question` 보다 먼저** 이 순서로: ① NFKC 뒤 하이픈 변형(`‐ ‑ ‒ – — ―`·`−`·`﹘ ﹣ －`)을 `-` 로 ② 은행 번호 + 나뉜 계좌를 한 덩어리로(`10_123456-78` → `10_****5678`, 구분자 뒤 조각은 숫자가 있어야 이어 붙임) ③ 16진 글자(`0-9A-F`) 묶음이 구분자(최대 3글자)로 이어지고 구분자 뺀 길이 8 이상·숫자 4개 이상이면 `****끝4`(`8000-EBD-30` → `****BD30`, 숫자 4개 미만인 `ADD-BEEF` 같은 단어는 그대로) ④ 위 숫자열 규칙 → `mask_question`. **한계**(알고 남김): 조각 사이 구분자가 4글자 이상이면 따로 셈 · 16진 아닌 영문이 섞여 구분자로 나뉜 계좌(`8000-XYZ-30`)는 조각마다 따로 봄(붙어 있으면 `mask_question` 이 가림) · `CAFE 2023` 처럼 16진 단어와 숫자가 붙으면 계좌가 아니어도 가림(실패 쪽으로 닫음)
- **캐시**: 검색어 없음(또는 가린 뒤 빈 값)만 프로세스 안 캐시 — 키 = (정렬한 유형, 임베딩 모델, 질의 버전 `REFERENCE_QUERY_VERSION = "v1"`), 최대 `REFERENCE_CACHE_MAX = 25`(유형 1~3개 조합 수). 기동 때 미리 계산 안 함(기동에 외부 호출이 생김). 적중이면 외부 호출 0
- **검색 SQL**: `retriever_sql` 에 OR 필터 변형(`typologies && CAST(:tys AS text[])`) — 나머지는 초안 SQL 과 같은 모양(`embedding_model = 질의 모델` · HNSW `relaxed_order` · 바깥 정렬 `거리, chunk_id`). 후보 `REFERENCE_SEARCH_CANDIDATES = 30`(`top_k` 최대 10 × 한 문서 3건). 고를 칸은 `doc_id`·`doc_title`·`publisher`·`year`·`page`·`typologies`·`chunk_id`·cosine — **본문은 안 읽음**
- **정리**: `score < MIN_SIMILARITY`(0.0) 제외(0.0 은 포함 — 추가 검토 1) → `chunk_id` 중복 제거 → 한 문서 최대 `REFERENCE_PER_DOC_MAX = 3` → 앞 `top_k`(점수 내림차순 · 동점 `chunk_id`). 모자라면 있는 만큼(다른 유형으로 안 채움). 0건이면 `EMPTY`
- **ES 키워드**: 이번엔 안 씀 — `search_meta.degraded` 는 늘 false(켜는 건 범위 밖, 붙이면 실패 시 `degraded: true`)
- **예산**: `REFERENCE_SEARCH_BUDGET_S=5` · 임베딩 `REFERENCE_SEARCH_EMBED_TIMEOUT_S=3` · `X-Budget-Ms` 가 더 짧으면 그 값. ★L 실측(11/22): 첫 호출 약 2.2초, 그 뒤 0.2~0.6초(7회 모두 200 · 예산 5초 안). 추가 검토 1: 임베딩은 **전송·본문 읽기 전체를 한 마감**(min(3초, 남은 시간))으로 — 검색 전용 `str/infrastructure/reference_embedding.embed_within`(LLM 전체 마감 SCRUM-322 와 같은 비동기 + 취소, 응답 검사는 공통 클라이언트와 같음 · 공통 클라이언트·초안 경로는 그대로) · DB 진입 전(캐시 적중 포함)·응답 직전에 남은 시간 확인 — 0 이하면 502 `LLM_UNAVAILABLE` · SQL 은 `statement_timeout` = 남은 ms, 넘으면 503 `DB_UNAVAILABLE`. 추가 검토 2: 마감은 **요청이 들어온 시각부터**(순수 ASGI 미들웨어 `ReceivedAtMiddleware` 가 단조 시계로 기록 — 의존성·작업 스레드 대기도 셈, `latency_ms` 도 같은 기준) · 서비스 진입 때 이미 만료면 임베딩·DB 전 502 · 응답 조립·검증 뒤 성공 반환 직전 다시 확인(넘으면 502, 로그 `reference_search_failed`) · `retrieval_version` 은 기동 때 읽은 값 재사용(요청마다 manifest 안 읽음) · 임베딩은 앱 수명 루프 하나(`reference_search_runtime`, lifespan 시작·종료)에서 돌리고 요청 스레드는 남은 시간만 기다렸다 취소(DNS 지연에도 바로 502) · 저장소는 **연결을 얻은 뒤** 남은 시간을 셈 — 0 이하면 검색 SQL 없이 502. **한계**: 연결 풀 대기 자체는 요청마다 한도를 못 줌(엔진 공통 `pool_timeout`) — 대신 대기 뒤 만료면 검색을 시작하지 않고, 예산을 넘긴 응답은 200 으로 안 나감. 추가 검토 3: **응답 경계에서 한 번 더** — 검색 입구에만 걸린 순수 ASGI 래퍼(`shared/received_at.ResponseDeadlineGuard`, 경로 `/v1/references/search` 만)가 라우터가 적어 둔 절대 마감을 들고 있다가 `http.response.start` 를 보내기 직전에 만료면 200 을 규약 502 `LLM_UNAVAILABLE` 본문으로 바꿈(성공 로그·응답 검증 대기 포함, 다른 경로는 안 걸림) · 임베딩은 **절대 마감**(min(지금+3초, 요청 마감))을 받아 루프 쪽에서 클라이언트 만들기 전·전송 직전에 확인(지났으면 전송 0), 호출자 대기는 제출 뒤 다시 계산 · 저장소는 `statement_timeout` 설정 왕복 뒤 마감을 다시 확인(지났으면 검색 SQL 없이 502)
- **DB 연결**: 임베딩(외부 호출) 뒤에 처음 씀 — 외부 호출 중 연결 안 듦(SCRUM-122 원칙)
- **기록**: `ai.generations` 0 · 로그 `reference_search_done`(유형·검색어 길이·결과 수·후보 수·지연·캐시 적중) — 검색어·청크 본문 0(NFR-COM-04). 검색 전용 임베딩 경로는 Langfuse 래퍼를 거치지 않음(기록 자체 0 — 검토 1 뒤)
- **스위치**: `RAG_REFERENCE_SEARCH_ENABLED`(false) — 끄거나 `RAG_ENABLED=false` 면 400(설계 13-4, 404 아님). 켜면 기동 때 `EMBEDDING_MODEL` 과 읽을 수 있는 manifest 가 있어야(`reference_search_problem`, 없으면 기동 실패 — 응답 `retrieval_version` 은 늘 `모델@해시`, 모델명만 보내지 않음 · 추가 검토 1). 11/24 저녁까지 실제 한 바퀴가 안 돌면 끈 채로 머지(설계 11절)
- **하지 않음**: 승인 STR(`APPROVED_STR` — SCRUM-310 은 색인만, 검색에 붙이는 건 발표 뒤 — 아래 "승인 STR 색인") · LLM 으로 고르기·요약 · 본문 발췌 · 유형 없이 검색어만 · 리랭커(LLM 재정렬) — 2차 고도화 후보(아래 "2차로 넘기는 것" 9번)

## 승인 STR 색인 (SCRUM-310, 2026-11-23 — 승인된 STR 을 다음 초안 참고 사례 후보로 쌓기, 기본 끔)

정본 노션 「참고 사례 검색 · 승인 STR 색인 설계 문서 (RAG 2차)」 B(3절 R-B1~B3 · 4.2 · 5.2 · 8절 · 9절 #21·#22·#24·#25 · 13절 6~8). 계약 `shared/01` "승인 STR 색인", 처리 순서 `str/03`, 표 `shared/03`. **이번 범위는 색인만**(★A 0 — (a)): 검색(`/v1/references/search`)은 지금처럼 `source_types` 의 `APPROVED_STR` 을 400 으로 받고, 초안 경로·309 검색 모두 새 표를 읽지 않음. 새 표를 검색에 붙이는 건 발표 뒤 한 이슈(13절 9번 — 남의 승인 STR 을 결과에 어디까지·`report_no` 를 보일지 — 를 그때 같이 정함).

```
요청(문서번호 · 초안 id · 승인 시각 · 유형 · 섹션별 본문) → 스위치 → 입력 검사 → 명시적 계좌 키 → 짧음 → 초안 facts 케이스 계좌·원천 표 대조
  → (같은 번호 행 있으면: 본문 해시 같음 = 기존 응답 / 다름 = 400) → 섹션마다 청크로 나눔(≤1200, SCRUM-361) → 임베딩 1회(청크 n개)
  → 한 트랜잭션: 문서번호 잠금 → 다시 확인 → 청크마다 한 행 → INDEXED
```

- **새 표 `ai.str_reference_docs`(부모, 문서번호 PK) + `ai.str_reference_chunks`(섹션, 부모 FK)**(`shared/03`): 공개 자료 표(`ai.reference_chunks`)와 따로 — 같은 표에 넣으면 초안 경로 검색이 바로 바뀌고 305 판정과 섞임(설계 8절). 칸은 공개 자료 표와 같은 벡터·유형 칸 + 문서번호·섹션·섹션 세트·본문 해시·승인 시각. HNSW cosine · GIN(typologies) 는 지금 읽는 곳이 없지만 검색을 붙일 때를 위해 같이 만듦
- **스위치**: `STR_INDEX_ENABLED`(false) — `RAG_ENABLED` 와 둘 다 켜야 색인. 꺼지면 **200 `SKIPPED`·`DISABLED`**(설계 5.2 표 — 검색 309 의 400 과 다름, 백엔드는 꺼짐 설정이면 아예 안 부름) · 임베딩 0 · 행 0
- **섹션**: 새 초안 7항목(`SectionV2`)·옛 6섹션(`SectionV1`) 둘 다 받음 — 한 요청은 한 세트만(섞이면 400), 한 세트 안에서 1개 이상(전부 필수 아님), 같은 섹션 두 번 400, 섹션 글 1~`STR_INDEX_TEXT_MAX`(**5000** — 백엔드 단락 상한과 같음, SCRUM-361. 초안 본문 `NARRATIVE_TEXT_MAX` 1200 과 따로). 공백만인 섹션은 청크에서 뺌
- **계좌 원문 검사 — 실제 계좌 대조**(`str/domain/raw_account.py` 순수 + 저장소 조회, 추가 검토 2 에서 "모양 찾기" → "실제 계좌 대조" 로 바꿈 · 허용 모양 예외 없음 · 참고 사례 검색(309) 가리기는 그대로). 검사 대상 = 임베딩에 보내는 섹션 글 전체(섹션 경계 포함). 지키는 것은 "**데이터에 있는 실제 계좌 번호가 임베딩으로 나가지 않는 것**":
  1. **명시적 계좌 키** — 은행 번호(원천 키는 최대 6자리 — 1~8자리로 넓게) + `_` + 영숫자(짧아도), `****` 로 가린 것 제외. 섹션 안 + 앞 섹션 끝·다음 섹션 시작을 이은 것
  2. **케이스 계좌 정밀 대조** — 요청 `draft_id` 의 초안 facts(`ai.generations` kind=DRAFT·SUCCEEDED)에서 대상 계좌 `subject.account_key` + facts 의 거래 ID 로 `ops.transactions` 를 한 번 읽어 나온 보낸·받은 계좌(**facts 거래가 하나라도 빠지거나 송·수신 계좌가 비면 임베딩 전 503** — 대조를 끝낸 것으로 치지 않음, 추가 검토 3). 정규화한 글(가린 표기 `****XXXX` 먼저 뺌 → 공백·줄바꿈·`-`·`.`·`_` 지움 → 대문자, 섹션은 그대로 이어 붙임) 안에 그 계좌의 **계좌 부분(은행 번호 뺀 것) 6자 이상 연속 조각**이 어디든 있으면 원문. 은행 번호는 가린 표기에서도 보이는 값이라 조각에서 뺌(★ R02 실측 — 빼기 전 1,850건 중 594건이 은행 번호 6자리로 오탐). 대신 **`은행번호` 바로 뒤에 그 계좌 앞 4자 이상이 이어 나오면 원문**(다른 곳의 `****뒤4` 와 합치면 복원, 섹션 경계 이음 — 추가 검토 3). 가린 표기는 `****` 뒤가 **정확히 4자에서 끝날 때만** 빼고, 더 이어지면 원래대로 대조(추가 검토 3). 검사본은 NFKC 뒤 **서식 문자(Cf — 폭 없는 공백·소프트 하이픈·단어 결합자·BOM 등)를 지움** — 원문은 그대로(추가 검토 3)
  3. **원천 계좌 표 정확 일치** — 짧은 구분자(최대 3글자 — **섹션 경계는 0자로 셈**, 원래 있던 공백만 셈)로 이어진 조각 묶음의 연속 부분을 붙인 문자열(숫자 포함·6~24자 — 토큰 수가 아니라 이어 붙인 길이로 자름, 추가 검토 3)이 `ops.accounts` 의 계좌 키(구분자 뺀 전체 또는 계좌 부분)와 **정확히 같으면** 원문 — 쿼리 한 번(로컬 51만 행 · 약 250ms, 승인 뒤 백그라운드 호출이라 받아들임)
  4. facts 를 못 찾으면(목업 모드 초안 등 `ai.generations` 행 없음) **200 `SKIPPED`·`NO_FACTS`** — 케이스 대조를 못 하므로 색인 안 함
  5. 대조 조회(DB) 실패 → 색인 안 하고 503 `DB_UNAVAILABLE`(실패 쪽으로 닫음)
  - 확인(모양만): v4 조립 본문 픽스처 · 예시 요청 · **실제 R02 경보 1,850건의 v4 본문 — 케이스 계좌·원천 표 대조까지 0건**(DB 읽기 전용, LLM 0) · v4 비율 관측값(`0.333…`) 통과
  - **한계(기록)**: 데이터에 없는 번호(지어낸 번호)는 통과 — 실제 정보가 아니라 유출 아님 · 그 케이스 밖 계좌의 **일부 조각**은 정확 일치만 봐서 못 잡음 · `draft_id` 와 `report_no` 가 서로 다른 초안을 가리키는 요청은 내부 호출 변조로만 생김(알고 남김) · 참고 사례 검색과 색인이 기동 때 manifest 를 따로 읽어, 같은 기동 안 두 읽기 사이에 manifest 가 바뀌면 버전이 달라질 수 있음 — 운영 중 manifest 교체는 재적재 절차(재기동)로만 함(알고 남김, 추가 검토 3) · 승인 STR 을 외부로 아예 안 보내는 로컬 임베딩은 발표 뒤 2차 후보
- **짧음**: 공백 뺀 섹션 글 합 < `STR_INDEX_MIN_CHARS = 100` → `SKIPPED`·`TOO_SHORT`(v4 조립 본문 785·899자, 옛 예시 496자, 가장 짧은 섹션 50자)
- **같은 문서번호**: `request_hash` = sha256(정규 JSON — 문서번호·승인 시각·유형(정렬)·섹션 순서대로 이름과 글). 임베딩 **전에**, **계좌 검사보다 먼저**(facts 를 못 읽게 돼도 이미 색인된 번호는 저장된 결과 · 다른 본문은 400, 추가 검토 3) 읽기만으로 확인(대조 조회까지 다 읽은 뒤 연결 반납 — 실패면 503) — 부모 행(`str_reference_docs`)이 있고 해시가 같으면 기존 행 그대로 같은 응답(임베딩 0), 다르면 400. 넣을 때는 트랜잭션 첫 문장으로 `READ COMMITTED` 를 정한 뒤 `pg_advisory_xact_lock(문서번호)` → 한 번 더 확인(동시 두 요청 → 한 벌만, 늦은 쪽은 기존 응답). **부모 표 PK(문서번호)** 가 같은 번호 두 벌을 막음 — DB 기본이 REPEATABLE READ 여도(추가 검토 2). 해시에 `draft_id` 포함. `SKIPPED` 는 행을 남기지 않음(같은 요청은 같은 판정이라 응답이 같음)
- **청크 나누기(SCRUM-361, `str/domain/str_index.split_text` 순수)**: 섹션 글을 **청크 ≤ `STR_INDEX_CHUNK_MAX`(1200, 코드 포인트)** 로 — 문장(`.`·`?`·`!` + 공백, 또는 줄바꿈 + 그 뒤 공백까지, 끝 공백은 그 문장에 붙음 — 추가 검토 1 M1) 단위로 앞에서부터 채우고, 다음 문장이 남은 자리에 안 들어가면 지금 청크를 닫음. 1200 넘는 한 문장은 지금 청크를 닫고 그 문장만 1200 에서 자르며, **남은 꼬리는 따로 닫지 않고 다음 문장과 이어 채움**(아래 상한 식을 지키는 조건 — 꼬리를 닫으면 2자·1201자·2자가 4청크). 글을 바꾸거나 겹치게 넣지 않음 — 이어 붙이면 원문 그대로. **공백만인 청크는 만들지 않음** — 공백만 남은 조각(글 맨 앞 공백·1200 에서 잘린 꼬리가 공백뿐 등)은 **앞 청크 남은 자리에 붙이고, 그래도 남으면 보관했다가 다음 청크(공백 아닌 글) 앞에 자리만큼 붙임 — 1200 에서 잘린 공백만 조각도 같음. 앞 청크·다음 청크 둘 다 꽉 차서 못 붙인 공백만 버림**(버리는 글자는 늘 공백, 순서는 그대로 — 추가 검토 1 M1 · 2 M, 진희). 청크 키 `{report_no}:{section}:{순번}`(1부터, 0009). `RAW_ACCOUNT`·`TOO_SHORT` 는 **나누기 전** 요청 전체로 판정(그대로). 응답 `chunk_count` = 청크 수 합 — 나누기가 결정적이라 같은 번호·같은 본문은 같은 응답(멱등 그대로)
- **`chunk_count` 상한 식(백엔드 #174 와 같은 식)**: 공백만이 아닌 단락마다 `⌊글자 수(코드 포인트, 원문 그대로) ÷ 600⌋ + 1` 의 합. 근거 — 청크를 닫는 건 "다음 문장이 안 들어갈 때"와 "1200 조각"뿐이라 **이웃 두 청크 길이 합 > 1200** → 청크 n개면 글자 수 > 600(n−1) → n ≤ ⌊L/600⌋+1. 공백을 이웃 청크에 붙이면 길이만 늘고, 못 붙여 버려도 수만 줄어 그대로. 성질 테스트(시드 고정 무작위 — 청크 1~1200 · 공백만 청크 없음 · 상한 · `join == 원문`, 다르면 빠진 글자가 공백뿐)로 고정
- **0009 는 처음 켜기 전에(추가 검토 3 H, 진희)**: AI `STR_INDEX_ENABLED`·백엔드 `AML_AI_STR_INDEX_ENABLED` 둘 다 기본 꺼짐 · 개발 DB `ai.str_reference_chunks` 0행(2026-11-23 진희 확인) · 운영 서버 없음 → 지금까지 켜진 적 없음. **0009 를 올린 뒤에 처음 켬** — 그러면 아래 순서가 필요 없음
- **이미 켜진 뒤 배포라면 — 배포 동안 승인을 잠시 멈춤**: 백엔드 스위치를 끈 사이 승인된 STR 은 색인에서 빠지고 **다시 보내는 길이 없음**(추가 검토 3 H). 승인 멈춤 → 아래 순서 → 다시 켠 뒤 승인 재개
- **배포 순서(0009, 추가 검토 1 M2 · 2 H)**: ① 백엔드의 승인 STR 색인 호출을 멈춤(백엔드 `AML_AI_STR_INDEX_ENABLED=false` 로 재기동) → ② 처리 중인 색인 요청이 끝나고 **구버전 AI 서버가 모두 내려갔는지 확인**(설정은 프로세스마다 기동 때 읽고, 요청은 들어올 때만 스위치를 봄 — 스위치만 끄면 이미 임베딩을 기다리던 구버전 요청이 0009 뒤에 순번 없는 키로 저장할 수 있음) → ③ `alembic upgrade head`(0009) → ④ 새 코드를 `STR_INDEX_ENABLED=true` 로 기동 → ⑤ 백엔드 스위치 켬(`AML_AI_STR_INDEX_ENABLED=true`). 구버전이 0009 뒤에 색인하면 키가 `{report_no}:{section}`(순번 없음)으로 남고, 같은 요청 재시도는 해시가 같아 저장된 응답만 돌려줘 고쳐지지 않음(트리거로 고치지 않음, 09)
- **임베딩·저장**: 공통 임베딩 클라이언트(`HttpEmbeddingClient`, 공개 자료 적재와 같은 모델·수·차원 검사)로 청크 n개를 한 번에(최대 7항목 × 9 = 63 ≤ `EMBED_BATCH` 64 → HTTP 한 번) — 한 호출이라 "일부 실패" = 전체 실패 → 502 `LLM_UNAVAILABLE`, 행 0. **임베딩 뒤에 DB**(외부 호출 중 연결 안 듦, SCRUM-122) · 넣기는 한 트랜잭션(실패 → 503 `DB_UNAVAILABLE`, 행 0). 절대 마감은 쓰지 않음 — 백엔드가 승인 커밋 뒤 백그라운드로 부르고 기다리는 사람이 없음(호출 한도는 공통 클라이언트 `LLM_TIMEOUT_S`, `X-Budget-Ms` 는 받기만)
- **응답 `retrieval_version`**: 검색(309)과 같은 `{EMBEDDING_MODEL}@{manifest 8자}` — 같은 모델 벡터임을 맞춤. **부모 행에 저장**하고 같은 번호 재요청(사전 확인·잠금 안 확인 두 경로)은 저장된 값을 돌려줌(모델이 바뀐 뒤에도 그 벡터를 만든 모델, 추가 검토 1). **기동 때 한 번 읽어 고정**(`str_index_runtime` — 309 검색과 같은 값, 요청마다 manifest 안 읽음, 추가 검토 2). `DISABLED` 면 `null`. `chunk_count` = 넣은(또는 이미 있는) 행 수, SKIPPED 는 0
- **기동 검사**(`str_index_problem`, 두 스위치가 켜졌을 때만): `EMBEDDING_MODEL` 있음 · manifest 읽힘 · `EMBEDDING_DIM == 1536`(표가 `vector(1536)` 고정 — 다르면 매번 넣기 실패, 추가 검토 1)
- **기록**: `ai.generations` 0 · 로그 `str_index_done`·`str_index_skipped`·`str_index_failed` — 문서번호·섹션 세트·섹션 수·청크 수·상태·건너뛴 이유·지연만(본문·섹션 글 0, NFR-COM-04)
- **평가 방법(결과 보기 전 고정, ★A 7)**: ① 공개 자료 기준선 그대로 — 초안 경로 검색 SQL·308 dry 후보·309 검색 결과가 색인 전후로 같음(새 표를 읽지 않음, 테스트로 고정) ② 승인 STR 은 시연용 몇 건뿐이라 검색 품질은 판정하지 않음 — ★L 에서는 색인된 건의 섹션 수·청크 수·임베딩 모델만 봄. "같은 유형이 위에 오는지" 는 검색을 붙이는 발표 뒤 이슈에서 같은 유형 질의 n 건 중 같은 유형이 1위인 수를 셈(유의성 주장 안 함)
- **하지 않음**: 검색에 붙이기((b), 13절 9번) · 본문 가려서 넣기 · 판 교체·삭제 API(승인 초안은 `LOCKED`, 13절 8) · 재색인 배치 · 백엔드 호출·트리거(채영 님·shared 이슈)

## 버전

`retrieval_version = f"{EMBEDDING_MODEL}@{manifest_sha256[:8]}"` → `generation_meta`, `generations.retrieval_version`.

- **SCRUM-305**: manifest 에 새 3줄이 들어가면 manifest 해시가 바뀌어 `retrieval_version` 도 바뀐다. 복원하면 manifest 를 develop 으로 되돌려 304 때 값으로 돌아간다(위 "305 실행 기록").

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

1. **평가 세트 확장** (진행 — SCRUM-306, 개발용 34) — 질의 10개 → 30~50개, 정답 없는 질의 포함, **질의마다 facts 를 달리**(146 기준선에서 (c) 문장이 10개 모두 같았음), 유형 필터 켬/끔 둘 다(주 비교는 끔), 지표에 recall@10 · 정답 없는 질의 오탐. 정답 위치는 `chunk_id` 가 아니라 doc_id·page·쪽 안 순번. 개발용/보류용 나눔. 11/18 기준선 파일(`tests/str/rag_baseline_20261118{,_ac,_a}.json`)로 재채점 가능.
2. **태그 검수** (진행 — SCRUM-306, 표본 70 두 사람 블라인드 · 적용 0) — 용어 대응표(공개 자료 용어 → FAN_IN·FAN_OUT·CYCLE·SG·GS)부터. 태그 없는 398청크 검토 목록은 SCRUM-281. 두 사람 표본 일치율 → LLM 후보 비교(태그별 놓친 비율) → 사람 승인 뒤에만 적용.
3. **자료 확장** — 2 뒤에도 SG·GS 근거가 비면. 1순위 후보 **APG Yearly Typologies Report**(Annual Report 와 다른 문서). 넣기 전 이용 조건 확인 → 쪽수·해시 검증 → 문단별 역할·태그 검수.
4. **하이브리드 + 다중 질의** (개발용 결정 — SCRUM-307 11/21: 규칙 ①② 미달 → 필터 끈 경로 {a} · 키워드 끔 유지, ③ 필터 켬은 {a,c}·{a,b,c} 써도 hit@3 안 떨어짐 — 기록만. 위 "하이브리드·다중 질의 판정 결과". 보류용 판정은 발표 뒤 새 세트로) — 합치기 층은 SCRUM-146 에서 기본 끔으로 이미 있음, 키워드(Elasticsearch)는 SCRUM-275 로 같은 층. 켤 기준은 09 2026-11-19 "SCRUM-275 판정 기준" 줄로 대체(빈칸만 채우기).
5. **리랭커 · 유사도 임계값** (끝 — SCRUM-308, 청크 맥락 포함 · 기준은 위 "청크 맥락·리랭커·컷오프 판정" · ① 컷오프 11/22 안 넣음(0.0 유지) · ② 리랭커 11/22 미채택 · ③ 청크 맥락 11/22 미채택 — 셋 다 기본값 그대로) — 후보가 넓어진 뒤. cosine 절댓값 컷오프는 정답 없는 질의와 정답 쪽 점수가 겹쳐 안 됨(11/12 · 11/18 실측).
6. **사례 검색 화면** — 사람 평가(참고 사례가 도움 되는지) 기준을 넘은 뒤. 규약 변경 요청 먼저.
7. **청크 자동 태깅(LLM)** — 자료를 여러 권 넣게 될 때. 사람 일치율 기준 뒤.
8. **승인 STR 재사용** — 재사용 승인·철회 흐름과 자체 임베딩이 준비된 뒤(맨 뒤).
9. **사례 검색 경로 리랭커** — 후보 30·자유 검색어라 초안 경로(308-2 미채택)와 조건이 다름. 할 때는 조사역 검색어로 새 질의 세트 + 결과 전 기준 커밋, 308-2 리랭커 코드(스위치·fail-open·응답 모델 검사) 재사용, 자유 검색어를 LLM 에 넣는 입력 방어 새로 설계, 예산 5초 안인지 실측. 설계 문서 1절 "LLM 0" 과 규약 5.5 를 바꾸는 팀 결정 필요(SCRUM-309 에서 남김).

- 목표는 청크 수가 아니라 유형별 커버리지(유형마다 출처 2곳 이상, 관련 청크 N개 — N 은 팀이 정함).
- SCATTER_GATHER·GATHER_SCATTER 는 규제기관 용어가 아니라 합성 데이터(IBM·AMLSim) 이름이라, 공개 자료에서는 funnel account·pass-through·경유 계좌 같은 말로 찾는다 — 태그 기준에 용어 대응표가 필요.
- **2차 준비 자료(SCRUM-281, 11/19 — 적용 0)**: `docs/str/rag2/00_tagging_criteria.md`(두 사람 태깅용 공통 기준 사본 — 위치·후보 없음) · `01_term_map.md`(용어 대응표 초안) · `02_untagged_review.csv`(태그 없는 398청크 검토 목록, 키 `chunk_id`=`content_hash`) · `03_sampling.md`(표본 60~80개 뽑는 법·Cohen's κ). 청크는 DB 가 아니라 `corpus/pdf/` + `tools/corpus_chunks.chunk_pdf_pages` 로 다시 나눠 만듦(425 · 빈 398, DB `chunk_id` 425/425 일치). **원문 문장은 옮기지 않고 위치만**(`doc_id · page · 쪽 안 문장 순번`, 문장 순번 = 그 쪽 `get_text()` NFKC 후 문장 끝 `.`·`?`·`!`·`다.` + 공백 / 빈 줄로 나눈 1부터). 목록의 "후보 유형"은 2차 사람 태깅의 출발점일 뿐 **태그가 아님** — manifest·DB 에 안 들어감. 검색·적재 경로는 `docs/` 를 읽지 않음.
- **SCRUM-306 (완료, 11/21 — 적용 0)**: `rag2/03` 방법 그대로 표본 70(`rag2/05_sample.csv`, 시드 281) + 새 3문서 무태그 층 10(시드 306, ★B-4) = 80 → 두 사람 블라인드 태깅 → 확인자(김종민) 불일치 결정 → 합의 태그 → `02` AI 보조 후보와 비교(유형별 놓친 수·잘못 붙인 수). 합의 태그는 "적용 제안" 파일까지 — manifest·DB·ES 안 바꿈. 나머지 328 청크는 알고 남김(κ ≥ 0.6 유형만 다음 이슈). 개발용 평가 세트 34(유형 5 × 6 + 정답 없는 4 — FX_RELAY 2 · 무관 2, `build_query` 시드 306 기계 추출, 기존 질의와 문자열 겹침 0), 정답 = 청크 × 유형(합의 태그 + 확인 등급 ≥ 1, 확인자 김종민).
  - **결과(11/20 받은 시트, 확인자 김종민)**: 두 사람 κ — 전체 80 FAN_IN **0.671** · 후보 유무 **0.701**(기존 70: 0.665 · 0.696), FAN_OUT·GS 는 붙임 < 5 라 비움, CYCLE·SG 는 두 사람 다 0, 새 3문서 10행은 계산 불가(한계 ③). 불일치 6행 → 결정(이유분류 기준 모호 4 · 단순 실수 2) → 합의 태그 12청크(FAN_IN 11 · FAN_OUT 2, 전부 기존 70행). AI(`02`) 대 합의(기존 70행): FAN_IN 맞음 9 · 잘못 붙임 3 · 놓침 2(놓친 비율 2/11) κ 0.740 · 후보 유무 11·5·1(1/12) κ 0.734 · FAN_OUT 1·1·1 · CYCLE 0·2·0 · GS 0·1·0. 새 3문서 대 305: 합의 없음 10 = 305 초벌 0 10. 적용 제안 `rag2/06_apply_proposal.csv` 12행(적용 안 함). 반영 시 태그 수(지금 FAN_IN 19 · FAN_OUT 6 · 무태그 657): **청크 단위**로 12청크만 붙이면 FAN_IN 30 · FAN_OUT 8 · 무태그 645 / **지금 manifest 쪽 단위(`typology_pages`)로 적용하면 FAN_IN 38 · FAN_OUT 10 · 무태그 636**(같은 쪽 이웃 청크 포함 — 사람이 확인한 범위보다 넓음, 06 `이웃청크` 칸). 평가 세트 v3 정답(등급 ≥ 1) 58 = `db_tagged=true` 45(FAN_IN 16 · FAN_OUT 5 · CYCLE 7 · SG 2 · GS 15) + `false` 13(FAN_IN 11 · FAN_OUT 2). 기준 모호 4행의 기준 문구 고침과 κ 없는 유형의 다음 단계는 사람이 정함
  - **평가 세트 v3(개발용, `tests/str/rag_eval_v3/`)** — 질의 `queries_dev.json`(split `dev_v3`): 304 와 같은 방식으로 `build_query` 결과를 **시드 `306`** 한 난수열로 기계 추출(신호 6개 중 1~2개 순열 × 업종 5, 설계자가 질의 안 씀), 기존 275 dev·275 보류용·holdout_v2 질의와 **문자열이 같으면 건너뜀**. 계획(이 순서로 난수열을 이어 씀): FAN_IN 6(base `facts_fan_in`·`facts_fan_in_b`·`facts_multi_currency` 번갈아) · FAN_OUT 6(`facts_fan_out`·`facts_multi_currency`) · CYCLE 6(`facts_cycle_nopaths`·`facts_multi_currency`) · SCATTER_GATHER 6 · GATHER_SCATTER 6(`facts_scatter_gather`) — `uses=[hit]` · FX_RELAY 2(`facts_multi_currency`, `uses=[empty]` — 태그 0 유형) · 무관한 질의 2(`facts_fan_in_b`, 유형 없음·신호 없음, 업종만 섞음, `uses=[reference]`) = 34. 정답 후보 `answer_candidates.json`(청크 × 유형, 위치 = doc_id·page·쪽 안 청크 순번, 본문 0): CYCLE·SG·GS = 305 확인 등급 ≥ 1(김종민 11/20, 등급 그대로) · FAN_IN·FAN_OUT = 지금 FAN 태그 청크 전부(등급 칸 빔 — 김종민 확인 대상) · 표본 합의 태그 행은 태깅 끝난 뒤 같은 파일에 더함(등급 빔). 위치는 DB 가 아니라 `corpus/pdf/` 재분할로 계산(해시 = chunk_id). 칸 `db_tagged` = 지금 DB 태그로 그 유형 필터 검색에 걸리는가(FAN 태그·305 후보 true, 합의 태그 새 행 false). **필터 켠 경로는 `db_tagged=true` 정답만으로도 따로 계산**(합의 태그는 적용 0 이라 켠 경로에서는 나올 수 없음). 정답 = 확인 등급 ≥ 1(304·305 와 같음 — FAN 태그 청크라도 0 이면 뺌). 확인 시트는 두 번(진희 ★ 11/20): ① FAN 25행(태깅과 무관, 11/20 반영) ② 불일치 결정(`disagree.csv`, `본문` 칸 포함) + 합의 태그 새 행 등급(`consensus_grade_sheet.csv` — 두 사람이 같은 태그를 붙였고 지금 후보에 없는 (유형, 청크), 행ID `C-FI-001` 모양·등급 칸 `ID=`) — 11/23 밤 대신 11/20 한 번에(진희 ★C-3), 입구 `tests/str/rag_eval_v3_round2.py export`(①②③ 내보내기 공통: 출력 폴더는 Git 작업 트리 밖 · 경로 어느 상위든 `blind_*` 거절 · 확인자 단계 파일 말고 다른 파일이 있으면 본문 쓰기 전 거절 · 목적지는 CSV 전에 모두 검사, 안내 파일은 배타 생성 또는 같은 내용일 때만 재사용, README 는 단계별 절 보존). 불일치 행 중 결정태그가 붙는 행의 등급은 결정 시트가 돌아온 뒤 작은 시트로 따로(`decided_grade_sheet.csv` — 결정태그의 (유형, 청크) 중 지금 후보에 없는 것, 행ID `D-FI-001` 모양, 입구 `tests/str/rag_eval_v3_decided.py export`). 돌아온 두 시트(합의 새 행 · 결정 행)는 `tests/str/rag_eval_v3_apply_new.py apply` 로 **한 번에** 반영 — 두 시트 모두 행·칸·DB 본문·등급 칸 ID 대조를 통과해야 하고(하나라도 틀리면 반영 0), 등급 ≥ 1 만 `source` `합의_태그`·`결정_태그` · `db_tagged=false` 로 후보에 더함(0 은 안 넣음), `consensus_checked_by`·`consensus_checked_at` 기록 · `consensus_pending=false`, 이미 반영됐으면 거절. 0·1·2 기록은 전부 `consensus_grades` 에 남김(적용 제안 입력). `db_tagged` 는 같은 DB 조회의 `typologies` 로 계산 — 최종 반영(②③) 때 한 번의 DB 조회로 **표본 80 전체**가 있고 무태그인지, **기존 후보(305·FAN) 유형별 태그 = `db_tagged`** 인지 대조하고, 하나라도 어긋나면 반영 전체 중단. ②③ 진입 전 ① 확인자·날짜와 FAN 출처 행 전체 등급 0·1·2 검증. 반영 둘(`apply-fan`·`apply`)은 같은 잠금 · 순서 ① → ②③ 검사 · 임시 파일 원자 교체, ① 은 `FAN_태그` 출처 행만. 후보 생성기(`rag_eval_v3_candidates`)는 파일이 없을 때만 쓰고, 재현 검사는 메모리에서 — 305 확인 시트와 같은 방식(칸·행ID 미리 채움·등급 칸 `ID=`·DB 본문 해시 대조, 본문은 리포 밖 시트에만, 등급 0/1/2 는 `rag2/04_checker_guide.md`) — 입구는 `tests/str/rag_eval_v3_sheet.py` 하위 명령(`export-fan` · 돌아온 시트는 `apply-fan --sheet <리포 밖> --checker --checked-at` — 행·칸·DB 본문·등급 칸 ID 를 대조하고 하나라도 틀리면 반영 0, FAN 행 `grade` 와 `fan_checked_by`·`fan_checked_at` 만 씀, 이미 반영됐으면 거절; 305 입구 파일이 줄 수 한도에 닿아 따로)
  - **한계 ①** 정답 후보는 합의 태그(표본 80) + 확인 등급 ≥ 1 뿐 — **아직 안 본 청크: 기존 표본 밖 328 + 새 3문서 표본 밖 249** 중 관련 청크가 필터 끈 검색에 나오면 오답으로 셈 → **필터 끈 경로 수치는 하한**
  - **한계 ②** SG 는 정답 후보가 2청크뿐(305 확인 등급 ≥ 1) — **SG 6질의의 정답이 거의 같아** 질의별 차이를 못 가림
  - **한계 ③** 새 3문서 10행은 두 사람 모두 전부 `없음`(11/20 받은 시트) — 붙임이 0이라 p_e = 1, **새 3문서 κ 는 계산 불가**(유형별·후보 유무 모두). 새 문서 쪽 두 사람 기준 일치는 이 표본으로 말할 수 없음 — 10행 모두 일치(p_o = 1)만 적음
  - **알고 남김(추가 검토 1회차)**: 이번 두 사람 시트·결정 시트의 태그 칸에는 행 ID 가 없어(이미 회수) 태그·근거를 다른 행으로 옮긴 시트는 `근거위치` 의 쪽·문장 범위 검사와 결정 시트 본문 해시로만 막음 — 다음 회차 묶음은 태그 칸에도 `ID=` 를 미리 채움
  - **알고 남김(추가 검토 2회차)**: 반영 잠금은 임시 폴더(`TMPDIR`) 기준 — `TMPDIR` 가 다른 두 프로세스가 같은 후보 파일을 동시에 반영하는 경우는 막지 않음(한 사람이 한 기계에서 차례로 돌리는 손 도구라 범위 밖). 00 기준서 근거 예시 `p쪽·s문장` 과 묶음 안내 `p15 s19` 는 다음 배포본에서 한 가지로 통일(이번 판독은 둘 다 받음)
- **이용 조건 원칙**(진희 11/18 — 법률 판단 아님, 허가가 필요할 수 있는 건 하지 않는 쪽, 09 같은 날 줄):
  ① 원문 PDF·추출 텍스트는 리포·이미지에 넣지 않음(리포 공개 · .gitignore corpus/pdf·corpus/text · Dockerfile PDF 제외 — SCRUM-256)
  ② 화면·응답은 문서명·발행기관·연도·쪽·공식 링크만. 문단 발췌는 허가가 확인됐거나 공공 정보인 자료만 — 2차 → 2026-11-19 ⑨로 바뀜(발췌 사용 가능)
  ③ FATF·APG·Egmont 자료는 번역본 만들지 않음 → 2026-11-19 ⑨로 바뀜(번역 사용 가능)
  ④ 초안 본문에 원문 문장 반입 금지(v4 는 안 씀 · 규칙 8)
  ⑤ 임베딩 외부 API 전송은 처리용으로 보고 유지, 승인 STR 은 자체 임베딩(2차)
  ⑥ 새 자료는 이용 조건 확인 뒤 적재(manifest 이용 조건·확인일 칸은 2차 자료 확장 때 → SCRUM-305 에서 새 3줄에 `terms`·`terms_checked`)
  ⑦ 발표 자료 출처는 '문서명 · 발행기관 · 연도'
  ⑧ 상업화·외부 서비스 땐 원 기관 허가부터 다시 봄
  ⑨ 2026-11-19 멘토 확인 — 비상업 포트폴리오·공개 자료라 임베딩·외부 임베딩 API·화면 발췌·번역에 써도 된다는 의견 → 팀 결정으로 사용(법률 판단 아님, 09 같은 날 줄). 원문 PDF 는 리포에 안 올림, 출처 표기(문서명·발행기관·연도) 유지

`retrieve()` 시그니처는 그대로라 `narrative_generator.py`는 안 바뀐다.

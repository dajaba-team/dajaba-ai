# corpus/

RAG 원문 (docs/str/10). `manifest.json` 만 커밋. PDF 는 `pdf/` 에 브라우저로 받아 둔다(.gitignore). 받은 뒤 `tools/ingest_corpus.py --verify` 가 sha256·쪽수를 manifest 에 채운다.
KoFIU 참고유형 사례집은 비공개라 없다 — 국문 적색신호는 FFIEC 부록 F 번역 + FinCEN 한국어 지침.
SCRUM-305 로 넣는 자료 3개(`fincen-cmln-2025`·`fintrac-underground-banking-2023`·`apg-typologies-2025`)는 manifest 줄에 이용 조건 `terms`·확인일 `terms_checked` 칸이 있다(docs/str/10 이용 조건 ⑥·⑨). 새 3문서에는 FAN_IN·FAN_OUT 태그를 붙이지 않는다.

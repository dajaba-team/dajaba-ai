"""부작용이 있는 것 전부 — DB, LLM, 임베딩, 파일. 얇게. 로직은 domain 에.

orm.py                     ai 스키마 SQLAlchemy 모델 (str 쪽 4테이블)
transaction_reader.py      ops.transactions/accounts/entities/customer_attributes SELECT (Repository, 읽기)
generation_repository.py   ai.generations
verification_repository.py ai.verification_runs
fewshot_store.py           fewshot/*.json → Example (DB fewshot_examples 는 사본)
narrative_generator.py     프롬프트 조립 → LLM → 스키마 검증 (1회 재생성)
judge.py                   평가자 LLM
retriever.py               RAG — 임베딩 → pgvector top-3
prompt_index.py            기동 시 prompts/*.md 해시 → ai.prompt_versions
"""

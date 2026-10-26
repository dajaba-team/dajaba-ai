# LLM 녹화 응답

`AI_LLM_MOCK=true` 면 `shared/infrastructure/llm_client.RecordedLlmClient` 가 호출 대신 여기를 읽는다.
경로: `{prompt_version}/{sha256(system+user)[:16]}.json`, 내용 `{"text": "<LLM 이 돌려준 JSON 문자열>", "model": "<모델 ID>"}`.
없으면 LLM_UNAVAILABLE — 조용히 지어내지 않는다. 녹화는 W2 에 `tools/record.py`(실제 호출 1회 → 저장)로. 커밋한다.

# LLM 녹화 응답

`AI_LLM_MOCK=true` 면 `shared/infrastructure/llm_client.RecordedLlmClient` 가 호출 대신 여기를 읽는다.
경로: `{prompt_version}/{recording_key(system, user)}.json`, 내용 `{"text": "<LLM 이 돌려준 JSON 문자열>", "model": "<모델 ID>"}`.
녹화 키 = `sha256(stable_json({"s":system,"u":user}))[:16]` — `shared/infrastructure/llm_client.recording_key(...)` 하나(`record.py`도 같은 함수).
없으면 LLM_UNAVAILABLE — 조용히 지어내지 않는다. 녹화는 `uv run python -m tools.record --case fan_in`(실제 호출 1회 → 저장)로. 커밋 = 템플릿 동결 시점.

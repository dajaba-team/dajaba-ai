# LLM 녹화 응답

`AI_LLM_MOCK=true` 면 `shared/infrastructure/llm_client.RecordedLlmClient` 가 호출 대신 여기를 읽는다.
경로: `{prompt_version}/{recording_key(system, user)}.json`, 내용 `{"text": "<LLM 이 돌려준 JSON 문자열>", "model": "<모델 ID>"}`.
녹화 키 = `sha256(stable_json({"s":system,"u":user}))[:16]` — `shared/infrastructure/llm_client.recording_key(...)` 하나(`record.py` 도 같은 함수).
없으면 LLM_UNAVAILABLE — 조용히 지어내지 않는다.

**버전별 폴더** (SCRUM-47·20): `narrative_v1/`·`narrative_v2/`. 활성 버전은 `shared/config.narrative_prompt`(env `NARRATIVE_PROMPT`).

## 재녹화 조건

다음이 바뀌면 녹화 키가 깨지므로 **같은 커밋에서 재녹화** 필요:
- `src/aml_ai/str/prompts/narrative_v{N}.md` (system/user 템플릿)
- `tests/str/fixtures/facts_{case}.json` (입력 facts)
- `src/aml_ai/str/fewshot/narrative_v{N}/*.json` (few-shot 예시)
- 코드가 조립 결과(system·user 문자열)를 바꾸는 변경(`render_user`·`masking.mask_for_llm`·`fact_keys` 등)

재녹화 명령 (`AI_LLM_MOCK=false` 접두사로 `.env` 안 건드림):
```
AI_LLM_MOCK=false NARRATIVE_PROMPT=narrative_v1 uv run --frozen --extra dev python -m tools.record --case fan_in
AI_LLM_MOCK=false NARRATIVE_PROMPT=narrative_v2 uv run --frozen --extra dev python -m tools.record --case fan_in
```
✓ 줄에 `latency_ms`·`tokens_in`·`tokens_out` 가 뜸 — 실측값은 PR ★C 에.

**녹화 커밋 = 템플릿 동결 시점** (`FROZEN_PROMPTS` 에 그 버전의 파일 sha256). 동결 뒤 템플릿을 바꾸려면 새 버전 파일(`narrative_vN+1.md`).

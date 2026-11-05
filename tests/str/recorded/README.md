# LLM 녹화 응답

`AI_LLM_MOCK=true` 면 `shared/infrastructure/llm_client.RecordedLlmClient` 가 호출 대신 여기를 읽는다.
경로: `{prompt_version}/{recording_key(system, user)}.json`, 내용 `{"text": "<LLM 이 돌려준 JSON 문자열>", "model": "<모델 ID>"}`.
녹화 키 = `sha256(stable_json({"s":system,"u":user}))[:16]` — `shared/infrastructure/llm_client.recording_key(...)` 하나(`record.py` 도 같은 함수).
없으면 LLM_UNAVAILABLE — 조용히 지어내지 않는다.

**버전별 폴더** (SCRUM-47·20): `narrative_v1/`·`narrative_v2/`. 활성 버전은 `shared/config.narrative_prompt`(env `NARRATIVE_PROMPT`).

**평가자 녹화** (SCRUM-61): `judge_v2/`. 녹화 키는 같은 함수(`recording_key(system, user)`), user 조립은 `render_judge_user(template, facts_masked, narrative, fact_keys)` 순수 함수를 Judge 와 녹화 도구가 공용(`judge_v1` 은 녹화 없음 — 기록용 보존).

## 재녹화 조건

다음이 바뀌면 녹화 키가 깨지므로 **같은 커밋에서 재녹화** 필요:
- `src/aml_ai/str/prompts/narrative_v{N}.md` (system/user 템플릿)
- `tests/str/fixtures/facts_{case}.json` (입력 facts)
- `src/aml_ai/str/fewshot/narrative_v{N}/*.json` (few-shot 예시)
- 코드가 조립 결과(system·user 문자열)를 바꾸는 변경(`render_user`·`masking.mask_for_llm`·`fact_keys` 등)

재녹화 명령 (`AI_LLM_MOCK=false` 접두사로 `.env` 안 건드림):

```sh
AI_LLM_MOCK=false NARRATIVE_PROMPT=narrative_v1 uv run --frozen --extra dev python -m tools.record --case fan_in
AI_LLM_MOCK=false NARRATIVE_PROMPT=narrative_v2 uv run --frozen --extra dev python -m tools.record --case fan_in
```

**평가자(judge_v2)** 재녹화는 narrative 녹화 파일을 입력으로 받는다 — facts·본문이 녹화 안에 있으므로 fixture 추가 필요 없음:

```sh
AI_LLM_MOCK=false uv run --frozen --extra dev python -m tools.record --judge --from-recorded narrative_v1/<key>.json
AI_LLM_MOCK=false uv run --frozen --extra dev python -m tools.record --judge --from-recorded narrative_v2/<key>.json
```

재녹화 조건(평가자): `src/aml_ai/str/prompts/judge_v2.md` · `render_judge_user` · `masking.mask_for_llm` · `fact_keys` 가 바뀌면 녹화 키가 깨짐.

✓ 줄에 `latency_ms`·`tokens_in`·`tokens_out` 가 뜸 — 실측값은 PR ★C 에.

**녹화 커밋 = 템플릿 동결 시점** (`FROZEN_PROMPTS` 에 그 버전의 파일 sha256). 동결 뒤 템플릿을 바꾸려면 새 버전 파일(`narrative_vN+1.md`·`judge_vN+1.md`).

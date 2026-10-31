# few-shot 예시 (정본)

파일 하나 = 예시 하나. `example_id` 는 고정, 내용을 바꾸면 **새 id** 로 새 파일(`generations.few_shot_ids` 추적 때문). DB `ai.fewshot_examples` 는 서빙용 사본.

**버전별 폴더** (SCRUM-47): `fewshot/{prompt_name}/*.json`. `fewshot_store` 는 활성 버전(`shared/config.narrative_prompt`) 폴더만 읽는다 — v1 과 v2 가 섞이지 않도록.

- `narrative_v1/` — 기존 6섹션(SUMMARY·WHO·WHAT_WHEN_WHERE·HOW·WHY_SUSPICIOUS·CONCLUSION). `001_fan_in.json` 샘플 1개.
- `narrative_v2/` — 별지 제1호 7항목(SUBJECT·DATE·PLACE·INSTRUMENT·METHOD·GROUNDS·OPINION). `002~006_*.json` 5개 — FAN_IN·FAN_OUT·PASS_THROUGH·CYCLE + 근거 약한 예시(`typology: null`).

형식: `{"example_id": N, "typology": "FAN_IN"|null, "facts": {...Facts...}, "narrative": [{...섹션...}]}`

작성 기준: 실제 STR 을 본 적이 없으므로 FinCEN SAR 서술 지침(2003) 부록의 "충분한 서술" 구조를 따라 우리가 쓴다. 숫자·이름은 전부 가짜(IBM 합성, Example Bank). 유형별 1개 이상, cites ⊆ `fact_keys(facts)`. 노션 Jira 2절에 없는 STRUCTURING 유형은 **쓰지 않는다**.

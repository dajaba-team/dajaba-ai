# few-shot 예시 (정본)

파일 하나 = 예시 하나. `example_id` 는 고정, 내용을 바꾸면 **새 id** 로 새 파일(`generations.few_shot_ids` 추적 때문). DB `ai.fewshot_examples` 는 서빙용 사본.

형식: `{"example_id": 1, "typology": "FAN_IN", "facts": {...Facts...}, "narrative": [ {...6섹션...} ]}`

작성 기준: 실제 STR 을 본 적이 없으므로 FinCEN SAR 서술 지침(2003) 부록의 "충분한 서술" 구조를 따라 우리가 쓴다. 숫자·이름은 전부 가짜(IBM 합성). 유형별 1개 이상, W2 목표 5개(FAN_IN·FAN_OUT·PASS_THROUGH·CYCLE·STRUCTURING).

`001_fan_in.json` 은 형식 확인용 샘플 — 본문은 W2 에 다시 쓴다.

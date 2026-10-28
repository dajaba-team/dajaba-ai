# 규약 JSON 예시 — 백엔드와 같은 파일

규약 문서의 예시 JSON 을 파일로 둔다. **백엔드 리포 `dajaba` 와 같은 내용** — 한 쪽에서 바꾸면 다른 쪽에 복사 (docs/shared/01 절차).
`tests/contract/` 가 이 파일들이 `shared/schemas/` 로 파싱되는지 본다. 백엔드는 같은 파일로 DTO 테스트.

| 파일 | 스키마 |
|---|---|
| `score_request.json` | `alerts.ScoreRequest` |
| `score_response.json` | `scores.ScoreResponse` |
| `draft_request.json` | `str.DraftRequest` |
| `draft_response.json` | `str.DraftResponse` |
| `verify_request.json` | `str.VerifyRequest` |
| `verify_response.json` | `str.VerifyResponse` |
| `error.json` | `errors.ErrorBody` |

규약 v0.2 (10/27·10/28) 반영 — SCRUM-12. 바꿀 때는 여기와 schemas 를 같은 PR 에서.

- `verify_response.json` 의 `narrative_sha256` 은 자리값(`0`×64). 실제 값은 SCRUM-16 `narrative_hash.json` 테스트 벡터에서 나온다.
- facts 금액은 문자열, 통화는 ISO 코드(`USD`) — 노션 규약 5.2 예시의 `US Dollar` 는 옛 표기라 맞춰야 함(docs/str/04 가 정본).
- `score_response.json` 에 FAILED 항목 하나를 일부러 넣었다(실패 항목 모양 확인용).

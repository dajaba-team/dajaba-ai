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

10/27 회의 뒤 규약 v0.2 로 바뀌면 여기와 schemas 를 같은 PR 에서.

"""shared — str/ 과 scoring/ 이 같이 쓰는 것만. 공유 코드 추가는 상대에게 먼저 말한다 (docs/shared/00).

config.py       .env → Settings (pydantic-settings)
errors.py       예외 클래스 + 예외→HTTP 매핑 (규약 6절)
logging.py      JSON 로그, request_id 미들웨어
auth.py         X-Internal-Key
versioning.py   응답에 붙는 버전 (docs/shared/04)
db.py           SQLAlchemy 엔진·세션 (app_ai)
schemas/        규약 Pydantic 한 벌 (docs/shared/01)
infrastructure/ LLM·임베딩 클라이언트
"""

"""통합 테스트 공용 상수 (SCRUM-60) — `conftest.py` 가 아니라 모듈로 분리.

conftest.py 에서 import 하면 pytest 가 fixture 파일을 모듈로 쓰게 돼 경고가 뜨거나 자동 참조가
헷갈린다. 테스트 파일이 import 할 수 있게 별도 모듈로.
"""

from __future__ import annotations

INTEGRATION_INTERNAL_KEY = "test-internal-key"

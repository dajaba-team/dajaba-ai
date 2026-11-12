"""narrative_v3 REFERENCES 렌더링 상수 (docs/str/05 narrative_v3, SCRUM-225).

`constants.py` 가 200줄 한도에 닿아 따로 둠 — 쓰는 곳은 이 모듈에서 이름별로 직접 import.
"""

from __future__ import annotations

REFERENCE_SNIPPET_PROMPTS: frozenset[str] = frozenset({"narrative_v3"})  # 새 렌더링을 쓰는 프롬프트
REFERENCES_PROMPT_MAX = 2  # 프롬프트·generation_meta 에 넣는 참고 사례 수 (검색은 RAG_TOP_K 그대로)
REFERENCE_SNIPPET_SENTENCES = 2  # 청크에서 고르는 유형 패턴 문장 수
REFERENCE_SNIPPET_FALLBACK_CHARS = 300  # 겹침 0·패턴 없음 → 앞부분
REFERENCE_SNIPPET_MIN_WORD = 4  # 겹침 셈에 쓰는 영단어 최소 길이 (to·of·the 등 제외)
REFERENCE_SNIPPET_STEM_CHARS = 5  # 단어 앞 5자로 비교 — deposit/deposits, account/accounts

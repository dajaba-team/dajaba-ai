"""질문 답변 상수 (SCRUM-290, 정본 docs/str/03·04·05). constants.py 200줄 한도 때문에 분리."""

from __future__ import annotations

import re

ASK_PLAN_PROMPT = "ask_plan_v1"  # 05 ask_plan_v1 — 녹화 커밋 때 FROZEN_PROMPTS
ASK_PLAN_MAX_TOKENS = 1000  # 출력은 JSON 한 줄이지만 추론 토큰 몫을 남김(summary 1500 보다 짧게)

# 04 "질문 속 계좌" (SCRUM-290 추가 검토 1) — NFKC 뒤에 적용, 영문 대소문자 무관. 앞뒤 기호(`*`·`` ` ``·`.`)는 경계로만
_ALNUM = "0-9A-Za-z"
# 은행 번호 붙은 계좌 키 — 영숫자 4자로 끝나야 함(뒤에 붙은 `**` 를 계좌로 먹지 않게). 이미 가린 `10_****BD30` 도 걸려 같은 값
RE_ASK_ACCOUNT_FULL = re.compile(rf"(?<![{_ALNUM}])\d{{1,4}}_[{_ALNUM}*]*[{_ALNUM}]{{4}}(?![{_ALNUM}])")
# 은행 번호 없는 맨 계좌 — 8자 이상, 숫자·영문자 둘 다 포함. 가린 꼬리 `****BD30` 은 4자라 안 걸림
RE_ASK_ACCOUNT_BARE = re.compile(
    rf"(?<![{_ALNUM}])(?=[{_ALNUM}]*[0-9])(?=[{_ALNUM}]*[A-Za-z])[{_ALNUM}]{{8,}}(?![{_ALNUM}])"
)
ACCOUNT_MASK = "****"

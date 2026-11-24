"""질문 한정어 정규식 (docs/str/06 "질문 한정어 ↔ 자리표 집계 범위"). constants_ask.py 200줄 한도 때문에 분리(SCRUM-412).

facts 는 기간 전체 집계(일별·방향별 최대 없음) — 질문에 한정어가 있으면 기간 전체 자리표를 막는다.
"""

from __future__ import annotations

import re

_BASE = r"\d+\s*(?:월|일|년)|\d+\s*시(?!간)|오전|오후|하루|당일|그날|주말|어제|오늘|지난달|이번\s*달"  # 추가 검토 3 H2
# 아래는 SCRUM-412(9/7 점검 · 추가 검토 1~3) — 덧붙이기만(막는 쪽으로만) · 원칙 (A) 애매하면 막는다
_SEP = r"\s*[-./‐‑‒–—−]\s*"  # 구분자 앞뒤 공백 · 유니코드 하이픈
_YMD = rf"(?<!\d)(?:\d{{4}}|\d{{2}}){_SEP}\d{{1,2}}{_SEP}\d{{1,2}}(?!\d)"  # `22.09.07` 도 · 앞뒤 숫자면 아님
_M, _D = r"(?:1[0-2]|0?[1-9])", r"(?:3[01]|[12]\d|0?[1-9])"
# 월 1–12 / 일 1–31 은 앞뒤가 숫자·소수점이 아니면 모두 날짜 — 분수도 막힘(알고 남김) · `M.D(요일)`
_MD = rf"(?<!\d)(?<!\d\.){_M}\s*/\s*{_D}(?!\d|\.\d)|(?<![\d.,]){_M}\.{_D}\s*\(\s*[월화수목금토일]\s*\)"
_ID = r"(?<![A-Za-z0-9_\-])"  # 케이스 번호·계좌 끝 숫자는 수로 안 봄
_KO = r"(?<![가-힣])(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)"
_NUM = rf"(?:{_ID}\d+|{_KO})"
_PRE = r"(?:지난|최근|직전|이전|이번)"
_WEEK = r"주(?!요|거래|체|식|제)"  # 수·`최근`·`이전` 뒤 — `주요`·`주거래`·`주체`·`주식`·`주제` 는 아님
_UNIT = rf"(?:분|시간|일|{_WEEK}|달|개월|해(?!외)|년)"  # `이번 해외송금` 의 `해` 는 아님
_RANGE = (
    rf"{_ID}\d+\s*[-~‐‑‒–—−]\s*\d+\s*(?:분|시간|일|주|달|개월|년)"  # `1-2시간` — 뒤 숫자는 식별자 제외 안 함
)
_RELATIVE = (  # `달러` 의 `달` 은 아님
    rf"최근|일주일|(?:지난|이번|직전)\s*주|{_PRE}\s*{_WEEK}|지난\s*달|{_RANGE}"
    rf"|{_NUM}\s*{_WEEK}|{_NUM}\s*시간|{_ID}\d+\s*분"
    rf"|{_PRE}\s*{_NUM}?\s*{_UNIT}"
    r"|주간|\d+\s*(?:개월|달(?!러))|며칠|한\s*달(?!러)"
)
_YEAR = r"작년|올해|지난해|금년|전년"
_EN = r"(?i:\b(?:yesterday|today|recent(?:ly)?|(?:last|this|past)\s+(?:week|month|\d+\s+days?))\b)"
# 질문 쪽(`ask_checks.qualifier_mismatch`)과 절 쪽(`ask_qualifier.period_mismatch`)이 같은 목록
RE_DATE_QUALIFIER = re.compile("|".join((_BASE, _YMD, _MD, _RELATIVE, _YEAR, _EN)))
# 기간과 무관한 키 허용 목록 — 그 밖(목록에 없는 새 키 포함)은 모두 기간 전체 집계(추가 검토 2, 목록 뒤집기)
ASK_PERIOD_FREE_KEYS: tuple[str, ...] = ("period", "subject", "typology", "model_signals")
ASK_PERIOD_FREE_PREFIXES: tuple[str, ...] = ("subject.", "customer.")
# 거래 기간에서 계산하지 않은 집계 — 같은 문장 `period` 예외 없음(추가 검토 3)
ASK_NOT_PERIOD_DERIVED: tuple[str, ...] = ("prior_alert_count", "observations.")
RE_EXTREME_QUALIFIER = re.compile(r"최대|최소|최고|최저|(?:가장|제일)\s*(?:큰|작은)")

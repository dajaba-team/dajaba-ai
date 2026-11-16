"""카탈로그 문장 린트 도우미 (docs/str/08 narrative_v4 4번) — 1차 때의 자유 문장 정규식 검사를 옮겨 온 것.

v4 에는 자유 문장이 없으므로 본 코드에서는 안 돈다. 우리가 쓴 카탈로그 문장·변형·짧은 꼴·연결어가
숫자·수 낱말·플래그 주제 낱말·금지 어간·인과/대립 연결어에 걸리지 않는지 테스트로만 확인한다.
닫힌 목록이며 반례마다 늘리지 않는다(09 추가 검토 1차).
"""

from __future__ import annotations

import re

ALLOWED = r"[가-힣\s.,·'\"()\-]"  # 한글 음절·공백·기본 문장부호
_SINO = "[일이삼사오육칠팔구십백천만억조]"
_NATIVE = (
    r"(?:두|세|네|다섯|여섯|일곱|여덟|아홉|열|스물|서른|마흔|쉰|예순|일흔|여든|아흔)"
    r"(?:하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉|한|두|세|네|댓)?"
)
_UNITS = "차례|계좌|달러|유로|곳|개|건|명|회|번|원|엔|억|만|천|백"
_UNITS_NO_ACCOUNT = "차례|달러|유로|곳|개|건|명|회|번|원|엔|억|만|천|백"  # `한 계좌로` 관용만 허용
FLAG_TOPIC = (
    *("자행", "타행", "은행"),
    *("당일", "하루", r"같은\s*날", r"동일한\s*날", "날짜", "일자", "시각", "오전", "오후", "새벽"),
    *("입금만", "출금만", "입금뿐", "출금뿐", r"입금(?:이|은)?\s*없", r"출금(?:이|은)?\s*없"),
)
FORBIDDEN = (
    *("급격", "급증", "증가", "감소", "폭증", "과도", "과다", "고액", "소액", "이례", "비정상"),
    *("평소", "통상", "일반적으로", "다수", "집중적으로"),
    r"(?<!거래 )(?<!계좌 )목적",  # `거래 목적`·`계좌 목적`만 허용
    *("의도", "숨[기긴길겨]", "감[추춘출춰]", "은닉", "은폐", "위장", "차명", r"범죄\s*수익", "불법"),
)
# "제공되지 않았" — UNVERIFIED 는 자료가 왔는데 확인이 안 된 것이라 거짓(경로 문구는 "확인되지 않" 꼴만)
NOT_PROVIDED = r"제공되지\s*않았"
CAUSAL_OR_CONTRAST = (
    "따라서",
    "그러므로",
    "반면",
    "그러나",
    r"[가-힣](?:이|으)나[\s,]",
    r"[가-힣](?:인|는|은)데[\s,]",
)  # ~이나·~으나·~인데·~는데

_RE_DISALLOWED = re.compile(f"(?!{ALLOWED}).")
_RE_NUMBER_WORD = re.compile(rf"(?<![가-힣])(?:(?!이(?!{_SINO})){_SINO}+|{_NATIVE})\s*(?:{_UNITS})")
_RE_HAN = re.compile(rf"(?<![가-힣])한\s*(?:{_UNITS_NO_ACCOUNT})")
_RE_FLAG = re.compile("|".join(FLAG_TOPIC))
_RE_FORBIDDEN = re.compile("|".join(FORBIDDEN))
_RE_CONNECTIVE = re.compile("|".join(CAUSAL_OR_CONTRAST))
_RE_NOT_PROVIDED = re.compile(NOT_PROVIDED)


def lint(text: str) -> list[str]:
    problems: list[str] = []
    if any(ch.isnumeric() for ch in text):
        problems.append("digit")
    elif _RE_DISALLOWED.search(text):
        problems.append("disallowed_char")
    if _RE_NUMBER_WORD.search(text) or _RE_HAN.search(text):
        problems.append("korean_numeral")
    if _RE_FLAG.search(text):
        problems.append("flag_topic")
    if _RE_FORBIDDEN.search(text):
        problems.append("forbidden_word")
    if _RE_CONNECTIVE.search(text):
        problems.append("causal_or_contrast")
    if _RE_NOT_PROVIDED.search(text):
        problems.append("not_provided")
    return problems

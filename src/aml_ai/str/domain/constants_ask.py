"""질문 답변 상수 (SCRUM-290, 정본 docs/str/03·04·05). constants.py 200줄 한도 때문에 분리."""

from __future__ import annotations

import re

from aml_ai.str.domain.constants import DIRECTION_IN_WORDS, DIRECTION_INTERNAL_WORDS, DIRECTION_OUT_WORDS

ASK_PLAN_PROMPT = "ask_plan_v1"  # 05 ask_plan_v1 — 녹화 커밋 때 FROZEN_PROMPTS
ASK_PLAN_MAX_TOKENS = 1000  # 출력은 JSON 한 줄이지만 추론 토큰 몫을 남김(summary 1500 보다 짧게)
ASK_ANSWER_PROMPT = "ask_answer_v2"  # 05 ask_answer_v2(SCRUM-358·359) — 녹화 커밋 때 FROZEN_PROMPTS
ASK_ANSWER_MAX_TOKENS = 1500  # 답 ≤400자 + cites + 추론 몫(요약과 같음)

# 04 "질문 속 계좌" (SCRUM-290 추가 검토 1) — NFKC 뒤에 적용, 영문 대소문자 무관. 앞뒤 기호(`*`·`` ` ``·`.`)는 경계로만
_ALNUM = "0-9A-Za-z"
# 은행 번호 붙은 계좌 키 — 영숫자 4자로 끝나야 함(뒤에 붙은 `**` 를 계좌로 먹지 않게). 이미 가린 `10_****BD30` 도 걸려 같은 값
RE_ASK_ACCOUNT_FULL = re.compile(rf"(?<![{_ALNUM}])\d{{1,4}}_[{_ALNUM}*]*[{_ALNUM}]{{4}}(?![{_ALNUM}])")
# 은행 번호 없는 맨 계좌 — 8자 이상, 숫자·영문자 둘 다 포함. 가린 꼬리 `****BD30` 은 4자라 안 걸림
RE_ASK_ACCOUNT_BARE = re.compile(
    rf"(?<![{_ALNUM}])(?=[{_ALNUM}]*[0-9])(?=[{_ALNUM}]*[A-Za-z])[{_ALNUM}]{{8,}}(?![{_ALNUM}])"
)
ACCOUNT_MASK = "****"

# 06 "질문 답변" 2번 — 응답 EVIDENCE_IN_SCOPE.draft_value 고정 표시(cites 는 모델 자유 문자열이라 반사 안 함, 추가 검토 1)
EVIDENCE_OUT_OF_SCOPE_MARK = "인용 키 범위 밖 {n}개"
# 추가 검토 4 H6 — 이 케이스 밖 케이스 번호(질문이면 계획 전에 범위 밖, 답이면 UNVERIFIED)
RE_CASE_NO = re.compile(r"CASE-\d{4}-\d{6}")
OTHER_CASE_MARK = "다른 케이스 번호 {n}개"
# 06 "질문 답변" 10번(추가 검토 2) — 상대 수·자행·타행 숫자를 바로 꾸미는 말의 방향. 공용 COUNT 낱말은 그대로
COUNTERPARTY_OUT_WORD, COUNTERPARTY_IN_WORD = "수취인", "송금인"
ASK_CP_IN_WORDS: tuple[str, ...] = ("입금", "들어온", "받은", COUNTERPARTY_IN_WORD, "유입")
ASK_CP_OUT_WORDS: tuple[str, ...] = ("출금", "보낸", "나간", COUNTERPARTY_OUT_WORD, "유출")
ASK_CP_BOTH_WORDS: tuple[str, ...] = (
    "입출금",
    "입·출금",
    "입금과 출금",
    "입금·출금",
    "입금 및 출금",
    "양방향",
    "전체",
    "모든",
)
# 06 "질문 답변" 8번(추가 검토 3) — 금액 앞 가장 가까운 표시가 종류. single(개별 대상)·표시 없음은 UNPARSED
ASK_AMOUNT_KIND_WORDS: dict[str, tuple[str, ...]] = {
    "total": ("합계", "총", "모두", "전체"),
    "max": ("최대", "가장 큰", "제일 큰"),
    "min": ("최소", "가장 작은", "제일 작은"),
    "observation": ("관측값", "지표"),
    "single": ("한 상대", "한 건", "한 번에", "한 계좌", "각 상대", "상대마다", "거래마다", "건당"),
}
ASK_BOTH_EXTREMES_WORD = "모두"  # `최대와 최소는 모두 X` — 검토 3 멈춤 답 ①
OBS_AMOUNT_UNIT = (
    "amount"  # 06 8번(추가 검토 1 M2) — 금액 관측값, 통화는 basis 끝(`sum_inbound_amount_eur` → EUR)
)

# 04 "계획 보강" (SCRUM-358 ④) — 질문(LLM 복사본)에 이 낱말이 있으면 코드가 flows 묶음을 붙임.
# 검사 방향 낱말(constants.DIRECTION_*_WORDS)은 그대로 두고 질문 쪽만 넓힘 — '받' 한 글자는 넓어서 `받았` 만
ASK_DIRECTION_WORDS: tuple[str, ...] = (
    *DIRECTION_IN_WORDS,
    *DIRECTION_OUT_WORDS,
    *DIRECTION_INTERNAL_WORDS,
    *("들어온", "들어오", "나간", "나가", "보내", "받았", "유입", "유출", "송금"),
)

# 04 "이어지는 질문" (SCRUM-359 · 추가 검토 1 M3) — 20자 이하일 때 계획 전에 범위 밖:
# 앞 답 집합을 가리키는 머리 낱말이면 늘, 접속어(`그럼`·`그러면`)면 주제 낱말이 없을 때만
ASK_FOLLOW_UP_SET_HEADS: tuple[str, ...] = ("그 중", "그중", "그 다음", "그다음", "거기서")
ASK_FOLLOW_UP_JOIN_HEADS: tuple[str, ...] = ("그럼", "그러면")
ASK_FOLLOW_UP_MAX_CHARS = 20
# `건` 단독은 주제 아님("그 중에 제일 큰 건?") — 건수는 `건수`·`몇 건`·`몇건` 또는 숫자+건
ASK_TOPIC_WORDS: tuple[str, ...] = (
    *ASK_DIRECTION_WORDS,
    *("건수", "몇 건", "몇건", "거래", "금액", "돈", "상대", "계좌", "결제", "방식", "기간", "날짜", "업종"),
    *(
        "위험",
        "고객",
        "경로",
        "모델",
        "룰",
        "점수",
        "통화",
        "관측",
        "경보",
        "유형",
        "이 케이스",
    ),  # 유형·이 케이스: 추가 검토 2
)
RE_ASK_COUNT_TOPIC = re.compile(r"\d+\s*건")
ASK_NO_LLM_MODEL = (
    "none"  # 코드가 끝낸 응답(계획·답 호출 0)의 generation_meta.llm_model — 백엔드는 문자열만 봄
)

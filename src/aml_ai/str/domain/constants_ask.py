"""질문 답변 상수 (SCRUM-290, 정본 docs/str/03·04·05). constants.py 200줄 한도 때문에 분리."""

from __future__ import annotations

import re

from aml_ai.str.domain.constants import DIRECTION_IN_WORDS, DIRECTION_INTERNAL_WORDS, DIRECTION_OUT_WORDS

ASK_PLAN_PROMPT = "ask_plan_v3"  # 05 ask_plan_v3(SCRUM-362 WHY 경계·복합 질문) — 녹화 커밋 때 FROZEN_PROMPTS
ASK_PLAN_MAX_TOKENS = 1000  # 출력은 JSON 한 줄이지만 추론 토큰 몫을 남김(summary 1500 보다 짧게)
ASK_ANSWER_PROMPT = (
    "ask_answer_v6"  # 05 ask_answer_v6(SCRUM-362 추가 검토 3 끝맺음 허용 목록) — 녹화 때 FROZEN_PROMPTS
)
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
# 06 "질문 답변" 3번(SCRUM-362) — 한 방향 질문 판정 낱말(양방향 낱말을 먼저 지움). 공용 COUNT 낱말은 그대로
COUNTERPARTY_OUT_WORD, COUNTERPARTY_IN_WORD = "수취인", "송금인"
ASK_CP_IN_WORDS: tuple[str, ...] = ("입금", "들어온", "받은", COUNTERPARTY_IN_WORD, "유입")
ASK_CP_OUT_WORDS: tuple[str, ...] = ("출금", "보낸", "나간", COUNTERPARTY_OUT_WORD, "유출")
# 추가 검토 1 H3 — 영어 질문 방향(소문자 비교). 18개 O3 `How many incoming transactions are there?`
ASK_EN_IN_WORDS: tuple[str, ...] = ("incoming", "inbound", "received", "deposit")
ASK_EN_OUT_WORDS: tuple[str, ...] = ("outgoing", "outbound", "sent", "withdraw")
# 추가 검토 2 H4 — 질문이 입출금을 함께 묻는 낱말(양방향 검사) · 배제한 방향(`출금 말고`)
ASK_BOTH_DIRECTION_WORDS: tuple[str, ...] = (
    "입출금",
    "입·출금",
    "입금과 출금",
    "입금·출금",
    "입금 및 출금",
    "양방향",
)
RE_EXCLUDED_DIRECTION = re.compile(
    r"(?:입금|출금|들어온|나간|받은|보낸|송금인|수취인|유입|유출)\s*(?:은|는|을|를)?\s*(?:말고|제외하고|빼고|외에)"
)
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
# 06 "질문 답변"(SCRUM-362) — EVIDENCE_IN_SCOPE 고정 표시(위 두 개 + 아래). 응답 허용 모양은 ask_public
SLOT_ERROR_MARK = "자리표 오류 {n}개"
OUTSIDE_NUMBER_MARK = "자리표 밖 숫자 {n}개"
OPPOSITE_DIRECTION_MARK = "반대 방향 키만 {n}개"
NO_SLOT_MARK = "자리표 없음"
TOO_LONG_MARK = "답 길이 넘침"
# 04 "답 자리표" 조사 — (받침 있을 때, 없을 때). 쌍의 어느 쪽을 써도 같은 쌍
ASK_PARTICLES: tuple[tuple[str, str], ...] = (
    ("은", "는"),
    ("이", "가"),
    ("을", "를"),
    ("과", "와"),
    ("으로", "로"),
    ("이에요", "예요"),
    ("이며", "며"),  # 연결 조사 — 사실 주장 없음(★B7-3, v6 규칙 13 끝맺음과 맞춤)
    ("이고", "고"),
)
# 06 "질문 답변" 2번 — 자리표 밖 숫자(추가 검토 1 H2): 아라비아 · 고유어 수사(단일·복합) + 단위 · 한자어 수량(십·백·천·만·억)
# + 단위 · 어림수. 수와 단위 사이 공백은 몇 칸이든. 앞이 한글이면 낱말 안(`입금만`·`대한 건`)이라 안 셈
_NATIVE = r"(?:(?:열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)\s*(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉)?|한|두|세|네|다섯|여섯|일곱|여덟|아홉)"
# `조` 는 뺌 — `조건`·`조회` 가 조 + 건/회 로 읽힘(W1 v4 녹화 재생에서 발견). 조 단위 수는 아라비아 숫자로 걸림
_SINO = r"(?:[일이삼사오육칠팔구]?\s*(?:십|백|천|만|억))+(?:\s*[일이삼사오육칠팔구])?"
_COUNT_UNIT = r"(?:건|개|곳|명|번|회|차례|가지|계좌|단계|군데)"
_MONEY_UNIT = r"(?:원|달러|유로|위안|엔)"
_RANGE = r"(?:한두|두세|서너|너덧|네다섯|대여섯|예닐곱|일고여덟)"  # 범위 수사(추가 검토 2 H2)
_EN = (  # 영어 수사 — 소문자 비교(re.I)
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|"
    r"million|billion"
)
RE_OUTSIDE_NUMBER = re.compile(
    r"[0-9]+"
    rf"|(?<![가-힣]){_NATIVE}\s*{_COUNT_UNIT}"
    rf"|(?<![가-힣]){_SINO}\s*(?:{_COUNT_UNIT}|{_MONEY_UNIT})"
    rf"|(?<![가-힣])(?:수십|수백|수천|수만|수억|몇십|몇백|몇천|몇만)\s*(?:{_COUNT_UNIT}|{_MONEY_UNIT})"  # 단위가 올 때만
    rf"|(?<![가-힣])(?:첫|{_NATIVE})\s*번째|(?<![가-힣])(?:첫|둘|셋|넷)째"  # 서수
    rf"|(?<![가-힣]){_RANGE}"
    r"|(?<![가-힣])[일이삼사오육칠팔구십백]+\s*분의|(?<![가-힣])절반"  # 분수
    r"|(?<![가-힣])[일이삼사오육칠팔구십백천만]+\s*(?:퍼센트|프로)"  # 퍼센트
    rf"|\b(?:{_EN})\b",
    re.IGNORECASE,
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

# 06 "질문 답변" (B) — 자리표 밖 비교 꼴(SCRUM-362 B1). `보다 자세히`·`…것 같아요` 는 안 막음
_ADJ = r"(?:많|적|높|낮|크|커|작)"
RE_OUTSIDE_COMPARE = re.compile(
    rf"(?:보다|에 비해|대비)\s*(?:더\s*|덜\s*)?{_ADJ}"
    rf"|(?:더|덜)\s+{_ADJ}"
    rf"|(?<![가-힣])(?:많아|적어|높아|낮아|커|작아)요|(?<![가-힣])(?:많|적|높|낮|크|작)습니다"
    r"|(?<!것 )(?:같아요|같습니다)|비슷|차이가|차이는"
)
COMPARE_MARK = "자리표 밖 비교 {n}개"

# 06 "질문 답변" 방향 전환(추가 검토 3) — 자리표 밖 절의 끝맺음 허용 목록(v5 녹화 42 가 실제로 쓴 것에서 뽑음, 2026-11-23)
ASK_ALLOWED_ENDINGS: frozenset[str] = frozenset(
    (
        "확인돼요",
        "확인됩니다",
        "보여요",
        "있어요",
        "없어요",
        "나타나요",
        "있고",
        "없고",
        "확인되며",
        "확인되고",
        "이며",
        "이고",
    )
)
ASK_ALLOWED_PAIRS: frozenset[tuple[str, str]] = frozenset(  # (앞 어절, 끝 어절)
    (("확인되지", "않아요"), ("확인되지", "않습니다"), ("확인하기", "어려워요"), ("확인하기", "어렵습니다"))
)
ASK_COPULA_ENDINGS: tuple[str, ...] = ("예요", "이에요", "입니다")
SLOT_MARKER = "§"  # 자리표 자리 — 자리표로 끝난 절은 허용
RE_BLOCKED_QUANTITY = (
    re.compile(  # 수량·경계 낱말(허용 목록 밖) — 자리표 밖 `배` · 자리표 바로 뒤 경계 · 영어 비교
        r"(?<![가-힣])배(?:예요|이에요|입니다|로|나|가|를|에)?(?![가-힣])"
        r"|§\s*(?:이상|이하|초과|미만|이내|넘게|가량|남짓|정도|쯤)"
        r"|\b(?:more|less|higher|lower|greater|fewer|than|exceeds?|twice|double|half)\b",
        re.IGNORECASE,
    )
)
PREDICATE_MARK = "자리표 밖 서술어 {n}개"
# 06 질문 한정어 ↔ 자리표 집계 범위(추가 검토 3 H2) — facts 는 기간 전체 집계(일별·방향별 최대 없음)
RE_DATE_QUALIFIER = re.compile(
    r"\d+\s*(?:월|일|년)|\d+\s*시(?!간)|오전|오후|하루|당일|그날|주말|어제|오늘|지난달|이번\s*달"
)
RE_EXTREME_QUALIFIER = re.compile(r"최대|최소|최고|최저|(?:가장|제일)\s*(?:큰|작은)")
ASK_PERIOD_AGG_PREFIXES: tuple[str, ...] = (
    "inbound.",
    "outbound.",
    "internal.",
    "compare.",
    "counterparties",
    "counterparty_banks.",
    "payment_format_counts.",
    "amount_range.",
)
QUALIFIER_MARK = "질문 한정어와 다른 집계 {n}개"

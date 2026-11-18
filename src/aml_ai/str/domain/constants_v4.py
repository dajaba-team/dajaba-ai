"""narrative_v4 상수 (docs/str/05 narrative_v4, SCRUM-228).

`constants.py` 가 200줄 한도라 따로 둠 — 쓰는 곳이 이름별로 직접 import.
"""

from __future__ import annotations

NARRATIVE_V4 = "narrative_v4"
DISPLAY_LABELS_VERSION = "display-labels-v1"
# 05 "카탈로그 판" — 슬롯·판정·카탈로그·표기 사전 문장이 바뀌면 올림(응답 칸 없음, 재현은 server_version). 1 = SCRUM-228~268
V4_CATALOG_VERSION = "v4-catalog-2"  # SCRUM-269

# 사전 칸 이름 — contracts/display_labels_v1.json 최상위 키와 같음.
LABEL_FIELDS: tuple[str, ...] = (
    "entity_type",
    "industry",
    "account_purpose",
    "risk_level",
    "payment_format",
    "typology",
    "currency",
    "observation_basis",  # SCRUM-264 부터 v4 슬롯은 안 씀(228 블라인드 v2 표기 통일 하네스용)
    "observation_unit",
    "observation_name",  # 피처 이름 → 표기(SCRUM-264)
    "observation_name_unit",  # 피처 이름 → 단위, 비율은 ""
)
# 표기에 넣지 않는 검사기 종류 단어(05 표기 원칙).
LABEL_BANNED_WORDS: tuple[str, ...] = ("입금", "출금", "상대", "자행", "타행", "경보")

# 입출금 집계 범위 구절 — 결제 방식·거래 통화·금액 범위는 내부 거래를 뺀 집계(05). 쉼표 없음(COUNT 절)
FLOW_SCOPE_BARE = "내부 거래를 뺀 입금·출금"
FLOW_SCOPE = f"{FLOW_SCOPE_BARE}의"
# 미등록 통화가 있을 때 열거·합계 범위 — 바로 뒤 "{원문} 통화 거래는 대응 미확인임." 과 짝(SCRUM-265 2/2)
MAPPED_SCOPE = "대응이 확인된 통화"
SLOT_JOIN = " "  # 섹션 안 슬롯 문장·자유 문장 잇기
NO_DATA = "자료 없음"

# 플래그 문장(05) — 숫자 문장과 반복되지 않는 것만. 출금만 문장은 G-PURPOSE-OUT 이 GROUNDS 에서 씀.
FLAG_SLOT_TEXT: dict[str, str] = {"single_day": "거래는 모두 같은 날 이루어짐."}

# 카탈로그 전제 — 항목 문장이 깔고 있는 사실. 후보 = 조건 AND 전제 전부(05 "requires", 추가 검토 1차 구조 변경 뒤)
PREMISES: tuple[str, ...] = (
    *("has_inbound", "has_outbound", "has_counterparty", "path_verified", "cycle_verified"),
    *("has_purpose", "has_customer", "has_prior", "has_same_bank"),
    *(
        "typology_supported",
        "typology_unsupported",
    ),  # 유형 뒷받침 판정(SCRUM-265 2/2) — 판정 없음이면 둘 다 거짓
)

# 유형 뒷받침 판정 임계값(05 "유형 뒷받침 판정") — 새로 정하지 않고 백엔드 rules.md params 값을 이름 붙여 씀.
# 출처: 백엔드 develop cf971d6(2026-11-17) docs/06_features/rules.md params(09 SCRUM-265 1/2 사전 등록 줄 값과 같음).
# 백엔드가 임계값을 바꾸면 "탐지 기준" 판정 문장이 틀어짐 — 같이 바꿀 것(09 알려진 한계).
MIN_DISTINCT_SENDERS = 5  # R02_FAN_IN params min_distinct_senders
MIN_DISTINCT_RECEIVERS = 10  # R01_FAN_OUT params min_distinct_receivers
MIN_INTERMEDIATES = 3  # R05_SCATTER_GATHER params min_intermediates
# 뒷받침 안 됨(미확인·불충족)일 때 GROUNDS·OPINION 에 나오면 안 되는 낱말 — 낱말 단위 검사(테스트)
UNSUPPORTED_BANNED_WORDS: tuple[str, ...] = ("부합", "충족", "뒷받침됨", "전형적")

# 사유·종합의견 카탈로그 고르기(05) — 기본 경로 순서 목록의 개수
GROUNDS_ITEMS_MAX = 3
OPINION_OPTIONAL_MAX = 2
# 연결어 닫힌 목록 — id → 문장 앞에 붙는 말. 인과·대립 연결어는 없음(린트로 확인)
CONNECTIVES: dict[str, str] = {"none": "", "also": "또한", "moreover": "아울러", "meanwhile": "한편"}
DEFAULT_CONNECTIVE = "none"
# ★A-8 — 코드 조립(LLM 호출 0)일 때 generation_meta.llm_model
V4_CODE_MODEL = "code"
SALES_DEPOSIT = "SALES_DEPOSIT"

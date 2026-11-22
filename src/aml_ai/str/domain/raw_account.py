"""승인 STR 본문의 계좌 원문 검사 — 실제 계좌 대조 (SCRUM-310 추가 검토 2, docs/str/10 "승인 STR 색인"). 순수.

모양을 추측하지 않고 데이터에 있는 실제 계좌와 맞춰 본다(허용 모양 예외 없음). 검사 대상 = 임베딩에 보내는 섹션 글 전체.
① 명시적 계좌 키 — 은행 번호 + `_` + 영숫자(짧아도), `****` 로 가린 것 제외
② 케이스 계좌 — 그 초안 facts 의 대상·상대 계좌(은행 번호 뺀 계좌 부분)의 6자 이상 연속 조각이 정규화한 글(대문자·구분자 제거, 섹션 경계 이음)
   어디든 있으면 + `은행번호_` 뒤에 계좌 앞 4자 이상이 이어 나오면(다른 곳의 `****뒤4` 와 합치면 복원, 검토 3).
   가린 표기 `****XXXX` 는 정확히 뒤 4자에서 끝날 때만 먼저 뺌(뒤 4자리는 원래 보여 주는 값 — 더 이어지면 원래대로)
검사본은 NFKC · 서식 문자(폭 없는 공백·소프트 하이픈 등) 지움 · 하이픈 변형 → `-` — 원문은 그대로(검토 3).
③ 그 밖 계좌 — 조각 묶음(정규화)이 원천 계좌 표의 계좌 키와 정확히 같은지 → 후보 목록만 여기서 만들고 대조는 저장소(쿼리 한 번)
참고 사례 검색(309) 가리기는 그대로 — 이 검사는 색인 전용.
"""

from __future__ import annotations

import re
import unicodedata

_HYPHENS = re.compile("[‐-―−﹘﹣－]")
_MASKED_TAIL = re.compile(
    r"\*{4}[0-9A-Za-z]{4}(?![0-9A-Za-z])"
)  # 정확히 뒤 4자에서 끝날 때만 — 더 이어지면 원래대로 대조(검토 3)
_BREAK = "|"  # 지운 자리 — 앞뒤 조각이 이어 붙지 않게
_EXPLICIT_KEY = re.compile(
    r"(?<![0-9A-Za-z])[0-9]{1,8}_[0-9A-Za-z*]*[0-9A-Za-z]"
)  # 원천 키는 은행 번호 최대 6자리
_SEPARATORS = re.compile(r"[\s\-._]+")
_TOKEN = re.compile(r"[0-9A-Za-z]+")
_SEP_MAX = 3
FRAGMENT_MIN = 6
_CANDIDATE_MIN, _CANDIDATE_MAX = (
    6,
    24,
)  # 이어 붙인 영숫자 길이(지원 계좌번호 길이 상한) — 토큰 수로 자르지 않음(검토 3)
_BOUNDARY = "\x00"  # 섹션 경계 — 구분자 길이에 안 셈(검토 3)
PREFIX_MIN = 4  # 은행 번호 뒤에 이어 나온 케이스 계좌 앞자리(검토 3 H5)


def _base(texts: list[str]) -> list[str]:
    """NFKC · 서식 문자(Cf — 폭 없는 공백·소프트 하이픈 등) 지움 · 하이픈 변형 → `-`. 검사본만 — 원문은 그대로(검토 3)."""
    out = []
    for t in texts:
        n = unicodedata.normalize("NFKC", t)
        out.append(_HYPHENS.sub("-", "".join(ch for ch in n if unicodedata.category(ch) != "Cf")))
    return out


def explicit_key(texts: list[str]) -> bool:
    """① — 섹션 안 + 앞 섹션 끝과 다음 섹션 시작을 이은 것."""
    parts = _base(texts)
    joined = [*parts, *(a[-32:] + b[:32] for a, b in zip(parts, parts[1:], strict=False))]
    return any("*" not in m.group(0) for t in joined for m in _EXPLICIT_KEY.finditer(t))


def normalized(texts: list[str]) -> str:
    """② 대조용 — 가린 표기 빼고 → 구분자(공백·줄바꿈·`-`·`.`·`_`) 지우고 → 대문자. 섹션은 그대로 이어 붙임."""
    return "".join(_SEPARATORS.sub("", _MASKED_TAIL.sub(_BREAK, t)) for t in _base(texts)).upper()


def case_fragment_hit(texts: list[str], case_accounts: set[str]) -> bool:
    text = normalized(texts)
    for account in case_accounts:
        bank, sep, part = account.partition("_")
        prefix = re.sub(r"[^0-9A-Za-z]", "", part).upper()[:PREFIX_MIN]
        if sep and len(prefix) == PREFIX_MIN and f"{bank.upper()}{prefix}" in text:
            return True  # `은행번호_앞4자` — 다른 곳의 `****뒤4` 와 합치면 복원(검토 3 H5)
        # 은행 번호는 가린 표기(`800102_****XXXX`)에서도 보이는 값 — 계좌 부분(`_` 뒤)에서만 조각을 만듦(★ R02 실측)
        key = re.sub(r"[^0-9A-Za-z]", "", account.split("_", 1)[-1]).upper()
        if any(key[i : i + FRAGMENT_MIN] in text for i in range(len(key) - FRAGMENT_MIN + 1)):
            return True
    return False


def exact_candidates(texts: list[str]) -> list[str]:
    """③ 후보 — 조각이 짧은 구분자(최대 3글자 — 섹션 경계는 0자로 셈)로 이어진 묶음의 연속 부분을 붙여 대문자로. 숫자 포함·6~24자."""
    text = _BOUNDARY.join(_MASKED_TAIL.sub(_BREAK, t) for t in _base(texts))
    groups: list[list[str]] = []
    last_end = None
    for m in _TOKEN.finditer(text):
        if groups and last_end is not None and _joins(text[last_end : m.start()]):
            groups[-1].append(m.group(0))
        else:
            groups.append([m.group(0)])
        last_end = m.end()
    out: set[str] = set()
    for g in groups:
        for i in range(len(g)):
            c = ""
            for tok in g[i:]:
                c += tok.upper()
                if len(c) > _CANDIDATE_MAX:
                    break
                if len(c) >= _CANDIDATE_MIN and any(ch.isdigit() for ch in c):
                    out.add(c)
    return sorted(out)


def _joins(gap: str) -> bool:
    """조각 사이가 짧은 구분자(경계 표시는 0자로 셈)면 같은 묶음."""
    g = gap.replace(_BOUNDARY, "")
    return (g == "" and _BOUNDARY in gap) or (0 < len(g) <= _SEP_MAX and _SEPARATORS.fullmatch(g) is not None)

"""질문 답변 답 자리표 → 이름표 + 값 (docs/str/04 "답 자리표", SCRUM-362). 순수 함수.

답 LLM(`ask_answer_v3`·`v4`)은 숫자 대신 `{{키}}`·`{{키|조사}}` 만 쓴다. 코드가 묶음 조각(마스킹본)에서 값을 꺼내 바꾸고,
cites = 쓴 자리표 키(나온 순서·중복 제거). 판정(범위 밖·오류·자리표 밖 숫자 등)은 `ask_checks`(06).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from aml_ai.str.domain.ask_bundles import AskPiece
from aml_ai.str.domain.ask_slot_labels import count_value, slot
from aml_ai.str.domain.constants_ask import ASK_PARTICLES, SLOT_MARKER
from aml_ai.str.domain.display_format import topic, with_ro
from aml_ai.str.domain.display_labels_check import Labels

_TOKEN = re.compile(r"\{\{([^{}]*)\}\}")
_PARTICLE_OF = {p: pair for pair in ASK_PARTICLES for p in pair}  # 쌍의 어느 쪽을 써도 같은 쌍

_HANGUL_FIRST, _HANGUL_LAST = 0xAC00, 0xD7A3  # 받침 읽기 — 마지막 한글 글자(★B7-3)


@dataclass(frozen=True)
class AskSlots:
    text: str  # 렌더링한 답(오류가 있으면 그 자리표는 빈 글자 — 응답에 안 나감)
    keys: tuple[str, ...]  # 쓴 자리표 중 허용 키(나온 순서·중복 제거) = cites
    out_of_scope: int  # 허용 키(`piece.keys`) 밖 자리표 수
    errors: int  # 문법·렌더링 오류 수(닫힘 없음·빈 키·중첩·목록 밖 조사·이름표/값 없음)
    outside: str  # 자리표를 지운 원문 — 자리표 밖 숫자·케이스 번호 검사용
    zero_keys: tuple[str, ...] = ()  # 쓴 키 중 값이 0 인 건수 키 — 전제 바로잡기 판단(06 3번)
    spans: tuple[
        tuple[str, int, str], ...
    ] = ()  # (키, 원문 위치, 그 절의 LLM 글 — 자리표는 지움) — 06 3번 정정 절
    marked: str = ""  # 자리표를 `§` 로 바꾼 원문 — 끝맺음 허용 목록 검사용(06 방향 전환)
    flow_counts: tuple[int | None, int | None] = (
        None,
        None,
    )  # 조각의 (입금, 출금) 건수 — 질문 한정어 검사(06)
    sentences: tuple[
        int, ...
    ] = ()  # spans 마다 그 자리표가 든 문장의 시작 위치 — 기간 예외는 같은 문장만(06, ★B8 D-2)


def render(answer: str, piece: AskPiece, labels: Labels) -> AskSlots:
    allowed = set(piece.keys)
    keys: list[str] = []
    counts = {"out": 0, "err": 0}

    def one(m: re.Match[str]) -> str:
        key, sep, particle = m.group(1).partition("|")
        if not key or (sep and particle not in _PARTICLE_OF):
            counts["err"] += 1
            return ""
        if key not in allowed:
            counts["out"] += 1
            return ""
        pair = slot(
            key,
            piece.content,
            labels,
            exclusive_ok=_exclusive_ok(piece),
            non_external=piece.non_external,
            evidence_scoped=evidence_scoped(piece),
        )
        if pair is None:
            counts["err"] += 1
            return ""
        if key not in keys:
            keys.append(key)
        text = f"{pair[0]} {pair[1]}"
        return text + (_particle(text, _PARTICLE_OF[particle]) if sep else "")

    text = _TOKEN.sub(one, answer)
    outside = _TOKEN.sub(" ", answer)
    counts["err"] += outside.count("{{") + outside.count("}}")  # 남은 여닫이 = 닫힘 없음·중첩
    zero = tuple(k for k in keys if count_value(k, piece.content) == 0)
    marked = _TOKEN.sub(f" {SLOT_MARKER} ", answer)
    flows = tuple((piece.content.get(s) or {}).get("count") for s in ("inbound", "outbound"))
    spans = _spans(answer, allowed)
    sentences = _sentence_starts(answer, spans)
    return AskSlots(
        text, tuple(keys), counts["out"], counts["err"], outside, zero, spans, marked, flows, sentences
    )


# 정정 절(06 3번) — 문장 끝 · `…고,`·`…며,` · `…지만`·`…는데` 뒤 · `대신`·`반면`·`그리고` 앞에서 끊음(추가 검토 2 H3)
_END = re.compile(r"[.!?\n]|(?<=고|며),|(?<=지만)|(?<=는데)|(?=대신|반면|그리고)")


def _spans(answer: str, allowed: set[str]) -> tuple[tuple[str, int, str], ...]:
    """허용 키 자리표마다 (키, 위치, 같은 절의 LLM 글). 경계는 자리표를 지운 글에서만(키 안 `.` 무시)."""
    blank = _blank_keep_particle(answer)
    out = []
    for m in _TOKEN.finditer(answer):
        key = m.group(1).partition("|")[0]
        if key not in allowed:
            continue
        ends = [e.end() for e in _END.finditer(blank, 0, m.start())]
        nxt = _END.search(blank, m.end())
        out.append((key, m.start(), blank[(ends[-1] if ends else 0) : nxt.start() if nxt else len(blank)]))
    return tuple(out)


def _blank_keep_particle(answer: str) -> str:
    """자리표를 같은 길이 공백으로 — 조사는 끝에 남김(`{{…|이며}},` 의 `며,` 경계를 봄, 06 ★B8 D-2)."""

    def one(m: re.Match[str]) -> str:
        particle = m.group(1).partition("|")[2]
        return " " * (len(m.group(0)) - len(particle)) + particle

    return _TOKEN.sub(one, answer)


def _sentence_starts(answer: str, spans: tuple[tuple[str, int, str], ...]) -> tuple[int, ...]:
    blank = _TOKEN.sub(lambda m: " " * len(m.group(0)), answer)
    ends = [m.end() for m in _SENTENCE_END.finditer(blank)]
    return tuple(max([0, *(e for e in ends if e <= pos)]) for _, pos, _ in spans)


_SENTENCE_END = re.compile(r"[.!?\n]")


def evidence_scoped(piece: AskPiece) -> bool:
    """근거가 경보 전체로 확인되지 않음(일부 · 범위 모름) — 근거 거래로 센 값에 표시(04, ★B8 N-1)."""
    return piece.scope is None or not piece.scope.whole_alert


def _exclusive_ok(piece: AskPiece) -> bool:
    return piece.scope is not None and piece.scope.whole_alert and piece.scope.ownership_known


def _particle(text: str, pair: tuple[str, str]) -> str:
    """(받침 있을 때, 없을 때) 중 하나. 문장부호(닫는 괄호·마침표 …)로 끝나면 그 앞 마지막 한글 글자 기준(★B7-3) ·
    으로/로는 ㄹ 받침이면 로(display_format)."""
    base = _sound_base(text)
    if pair[0] == "으로":
        return with_ro(base)[len(base) :]
    return pair[0] if topic(base).endswith("은") else pair[1]


def _sound_base(text: str) -> str:
    """받침을 읽을 말 — 문장부호로 끝나지 않으면 그대로, 끝나면 마지막 한글 글자까지(`(FAN_IN)` 은 괄호 앞 한글)."""
    stripped = text.rstrip()
    if not stripped or stripped[-1].isalnum():
        return text
    hangul = [k for k, ch in enumerate(stripped) if _HANGUL_FIRST <= ord(ch) <= _HANGUL_LAST]
    return stripped[: hangul[-1] + 1] if hangul else text

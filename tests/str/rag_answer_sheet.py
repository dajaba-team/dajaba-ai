"""SCRUM-275-2 정답 확인 시트 — 초벌 → 시트 행 → 확인 반영 (docs/str/10 "확인 시트"). 순수(파일 읽기·쓰기만).

확인 범위 (가): CYCLE 은 425 전부(`all_chunks`), FAN_IN·FAN_OUT 은 LLM 등급 ≥ 1 행만(`llm_positive_rows`).
시트에는 본문이 있으므로 리포 밖에만 씀(호출하는 손 실행 도구가 막음). 정답 파일에는 위치·chunk_id·등급만.
점검(초벌 완전성·확인 시트 대조)은 `rag_answer_sheet_check.py`.
"""

from __future__ import annotations

import csv
from hashlib import sha256
from pathlib import Path
from typing import Any

from tests.str.rag_eval_v2_support import expand_answers

SCOPE_ALL = "all_chunks"
SCOPE_POSITIVE = "llm_positive_rows"
FULL_REVIEW = frozenset({"CYCLE"})  # 판정에 정답이 쓰이는 유형(채울 칸이 생기는 유형)
TYPOLOGY_ORDER = ("CYCLE", "FAN_IN", "FAN_OUT")
COLUMNS = (
    "row_id",
    "유형",
    "문서",
    "쪽",
    "쪽안순번",
    "LLM등급",
    "확인등급",
    "메모",
    "본문",
    "chunk_id",
    "초벌지문",
)
FINGERPRINT_CHARS = 16
GRADES = ("0", "1", "2")
ROW_ID_CHARS = 12
_FORMULA_START = ("=", "+", "-", "@")

GUIDE_MD = """# 정답 확인 안내 (SCRUM-275-2)

행마다 그 청크 **본문 안에서만** 보고 `확인등급` 칸에 0·1·2 중 하나를 적어요. LLM 등급과 같아도 그대로 적어요.
빈 칸 = 안 봄 — 빈 칸이 하나라도 있으면 반영이 거절돼요. `메모` 는 자유(정답 파일에는 안 들어감).

## 등급
- **2** — 그 유형의 계좌 사이 흐름이 청크 문장에 있음(송금·입금·이체·수표 같은 이체가 있고, FAN_IN 은 모이는 한 계좌, FAN_OUT 은 보내는 한 계좌, CYCLE 은 출발 계좌로 돌아옴)
- **1** — 그 유형에 관한 내용이지만 구조 전체는 없음(징후·지표·정의·사례 맥락 — 그 유형 보고서를 쓰는 조사역에게 쓸모 있음)
- **0** — 그 밖(단계 이름·용어만 나옴 포함)

## 그 유형이 아님(다른 부분이 맞지 않으면 0)
- 범죄 수익을 범죄자·의뢰인·소유주에게 돌려주는 통합 단계(CYCLE 아님)
- 상품-현금 치환·무역 송장 조작·카지노 칩·우편환끼리 교환·현금을 사람에게 넘김
- 여러 곳 ↔ 여러 곳 정산·상계, 돈이 실제로 안 움직이는 가치 이전
- 한 사람이 여러 지점·여러 번 나눠 넣기(출처가 하나라 FAN_IN 아님)
- 사업 모델·회사 역할 설명

## 칸
`LLM등급` 은 참고용이에요 — 따라가지 말고 본문으로 판단해 주세요. 원문 문장은 메모에 옮기지 않아요.
"""


def row_id(typology: str, chunk_id: str) -> str:
    return f"{typology}:{chunk_id[:ROW_ID_CHARS]}"


def _in_scope(typology: str, grade: int) -> bool:
    return typology in FULL_REVIEW or grade > 0


def scope_of(typology: str) -> str:
    return SCOPE_ALL if typology in FULL_REVIEW else SCOPE_POSITIVE


def expected_items(draft: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """시트에 나올 (유형, 초벌 항목) — 유형 → 문서 → 쪽 → 쪽 안 순번 → chunk_id 순."""
    graded = draft["graded_by_typology"]
    out = [(t, i) for t in TYPOLOGY_ORDER for i in graded.get(t, []) if _in_scope(t, int(i["grade"]))]
    rank = {t: n for n, t in enumerate(TYPOLOGY_ORDER)}
    pos_key = lambda i: i["pos"] if i["pos"] is not None else 10**9  # noqa: E731 — 순번 없는 문서는 쪽 끝
    return sorted(
        out, key=lambda ti: (rank[ti[0]], ti[1]["doc_id"], ti[1]["page"], pos_key(ti[1]), ti[1]["chunk_id"])
    )


def _safe(text: str) -> str:
    return "'" + text if text.startswith(_FORMULA_START) else text


def fingerprint(draft_bytes: bytes, manifest_bytes: bytes) -> str:
    """시트가 어느 초벌 파일·코퍼스 위에서 만들어졌는지 — 행마다 `초벌지문` 칸, apply 때 지금 파일과 대조."""
    return f"{sha256(draft_bytes).hexdigest()[:FINGERPRINT_CHARS]}:{sha256(manifest_bytes).hexdigest()[:FINGERPRINT_CHARS]}"


def sheet_records(draft: dict[str, Any], texts: dict[str, str], fp: str) -> list[dict[str, Any]]:
    return [
        {"row_id": row_id(t, i["chunk_id"]), "유형": t, "문서": i["doc_id"], "쪽": i["page"], "쪽안순번": i["pos"],
         "LLM등급": str(i["grade"]), "확인등급": "", "메모": "", "본문": _safe(texts[i["chunk_id"]]),
         "chunk_id": i["chunk_id"], "초벌지문": fp}
        for t, i in expected_items(draft)
    ]  # fmt: skip


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    """UTF-8 BOM · 모든 칸 따옴표 — 엑셀·구글 시트에서 한글·칸 안 줄바꿈이 안 깨짐. 이미 있으면 안 덮음."""
    with path.open("x", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(records)


class SheetFormatError(Exception):
    """머리글·칸 수가 export 와 다름 — problems = [(CSV 행 번호, 설명)]."""

    def __init__(self, problems: list[tuple[int, str]]) -> None:
        super().__init__(f"sheet format: {len(problems)}")
        self.problems = problems


def read_csv(path: Path) -> list[dict[str, str]]:
    """머리글이 `COLUMNS` 와 이름·순서까지 같고 모든 행의 칸 수가 머리글과 같을 때만 읽음(추가 검토 2 — 같은 이름
    칸이 둘이면 DictReader 가 뒤 칸만 남겨 앞 칸의 빈 등급·다른 본문을 숨김)."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        raise SheetFormatError([(1, "머리글 없음")])
    header, body = rows[0], rows[1:]
    if tuple(header) != COLUMNS:
        raise SheetFormatError(
            [(1, f"머리글이 export 칸 목록과 다름(칸 {len(header)} · 중복 {len(header) - len(set(header))})")]
        )
    bad = [(n, f"칸 수 {len(r)} ≠ {len(COLUMNS)}") for n, r in enumerate(body, 2) if len(r) != len(COLUMNS)]
    if bad:
        raise SheetFormatError(bad)
    return [dict(zip(COLUMNS, r, strict=True)) for r in body]


def build_answers(
    draft: dict[str, Any],
    records: list[dict[str, str]],
    queries: list[dict[str, Any]],
    *,
    checker: str,
    checked_at: str,
) -> dict[str, Any]:
    """확인 등급 → 질의별 정답(1·2 만 목록). `rag_answer_sheet_check.check` 가 빈 뒤에만 부름."""
    human = {r["row_id"].strip(): int(r["확인등급"].strip()) for r in records}
    by_type: dict[str, list[dict[str, Any]]] = {t: [] for t in TYPOLOGY_ORDER}
    for t, i in expected_items(draft):
        grade = human[row_id(t, i["chunk_id"])]
        if grade > 0:
            by_type[t].append({k: i[k] for k in ("chunk_id", "doc_id", "page", "pos")} | {"grade": grade})
    entries = [
        {"query_id": q["id"], "answers": [dict(a) for a in by_type.get(q["typology"], [])], "draft": "human",
         "llm_draft": f"llm:{draft['prompt_version']}", "llm_prompt_sha256": draft["prompt_sha256"],
         "check_scope": scope_of(q["typology"]), "checked_by": checker, "checked_at": checked_at}
        for q in queries if not q["expect_empty"]
    ]  # fmt: skip
    return {"_doc": "SCRUM-275-2 확인 반영 정답 — 위치·chunk_id·사람 등급만, 원문 0. check_scope 로 본 범위 표시.",
            "queries": entries}  # fmt: skip


def existing_problem(
    existing: dict[str, Any] | None, draft: dict[str, Any], queries: list[dict[str, Any]]
) -> str | None:
    """이미 있는 정답 파일 — 없으면 None, 확인 전 + 같은 초벌(`--expand` 결과)이면 None(대체), 그 밖은 거절 이유."""
    if existing is None:
        return None
    if any(e.get("checked_by") or e.get("checked_at") for e in existing.get("queries", [])):
        return "이미 확인된 정답 파일 — 다시 반영하려면 파일을 일부러 지운 뒤"
    if existing.get("queries") != expand_answers(draft, queries)["queries"]:
        return "확인 전 정답 파일이 이 초벌로 만든 것과 다름 — 초벌을 확인"
    return None

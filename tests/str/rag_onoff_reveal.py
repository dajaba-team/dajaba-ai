"""SCRUM-126 ★L-2 — 블라인드 선택 확정 뒤 키 파일로 ON/OFF 매핑 (별도 단계).

LLM 호출 **0** — JSON 매핑만. 추가 검토 1차: 생성 단계 결과 JSON 에는 `rag` 키가 없고,
키 파일은 진희 선택 확정 뒤에만 열어야 한다. 이 스크립트가 그 유일한 매핑 단계.

SCRUM-225: 검색 진단(`retrieval_status`·`references`)은 공개용 결과 JSON 에 없고 진단 파일에 있다 —
세 번째 인자로 (case_id, side) 로 붙인 뒤 매핑. **새 형식(결과에 retrieval_status 없음)은 진단 파일 필수이고
모든 case_id × side 진단이 있어야 함** — 없으면 검색 실패 초안이 RAG ON 표본으로 섞이므로 멈춘다(추가 검토 1차).
126 옛 형식(진단이 결과 안에 있음)만 두 인자 호출 허용.

사용 (진희 선택 확정 뒤):
    python -m tests.str.rag_onoff_reveal \\
        tests/str/recorded/_tmp/rag_onoff_<tag>.json \\
        tests/str/recorded/_tmp/rag_onoff_blind_key_<tag>.json \\
        tests/str/recorded/_tmp/rag_onoff_diag_<tag>.json

출력: 같은 폴더의 `rag_onoff_revealed_<tag>.json`
    {"runs_revealed": [{"case_id":..., "rag": true, "retrieval_status":..., ...}, ...],
     "excluded_failed": [...]}

집계 규칙:
- `retrieval_status == "failed"` 레코드는 `excluded_failed` 로 분리 (invalid, 집계 제외)
- `ok`·`empty`·`disabled` 는 `runs_revealed` 에 포함
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _reveal_side(record: dict, key_entry: dict) -> dict:
    """A/B 레코드 → `rag` 매핑 포함 레코드 (side 키 제거)."""
    side = record["side"]
    rag = bool(key_entry[f"{side}_rag"])
    revealed = {k: v for k, v in record.items() if k != "side"}
    revealed["rag"] = rag
    return revealed


def _diag_index(result: dict, diag: dict | None) -> dict[tuple[str, str], dict]:
    """(case_id, side) → 진단. 새 형식이면 진단 필수·전부 있어야 함 — 아니면 ValueError."""
    extra = {(d["case_id"], d["side"]): d for d in (diag or {}).get("runs", [])}
    runs = result.get("runs", [])
    if all("retrieval_status" in r for r in runs):
        return extra  # 126 옛 형식 — 진단이 결과 안에 있음
    if diag is None:
        raise ValueError("new-format result needs diag file (retrieval_status not in result)")
    missing = sorted({(r["case_id"], r["side"]) for r in runs} - set(extra))
    if missing:
        raise ValueError(f"diag missing for {missing}")
    return extra


def reveal(result: dict, key: dict, diag: dict | None = None) -> dict:
    """생성 결과 + 키 (+ 진단) → `{runs_revealed, excluded_failed}`. 셈은 하지 않음."""
    runs_revealed: list[dict] = []
    excluded: list[dict] = []
    extra = _diag_index(result, diag)
    for rec in result.get("runs", []):
        case_id = rec["case_id"]
        if case_id not in key:
            raise KeyError(f"key missing case_id={case_id}")
        d = extra.get((case_id, rec["side"]), {})
        merged = {**rec, **{k: v for k, v in d.items() if k not in ("case_id", "side")}}
        revealed = _reveal_side(merged, key[case_id])
        if revealed.get("retrieval_status") == "failed":
            excluded.append(revealed)
        else:
            runs_revealed.append(revealed)
    out = {k: v for k, v in result.items() if k != "runs"}
    out["runs_revealed"] = runs_revealed
    out["excluded_failed"] = excluded
    return out


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: rag_onoff_reveal <result.json> <key.json> [diag.json]", file=sys.stderr)
        return 2
    result_path = Path(sys.argv[1])
    key_path = Path(sys.argv[2])
    result = json.loads(result_path.read_text(encoding="utf-8"))
    key = json.loads(key_path.read_text(encoding="utf-8"))
    diag = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8")) if len(sys.argv) > 3 else None
    try:
        revealed = reveal(result, key, diag)
    except ValueError as exc:
        print(f"[fatal] {exc}", file=sys.stderr)
        return 1
    out = result_path.with_name(result_path.name.replace("rag_onoff_", "rag_onoff_revealed_", 1))
    if out == result_path:
        out = result_path.with_name("rag_onoff_revealed_" + result_path.name)
    out.write_text(json.dumps(revealed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"revealed → {out} (ok/empty/disabled={len(revealed['runs_revealed'])}, failed={len(revealed['excluded_failed'])})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

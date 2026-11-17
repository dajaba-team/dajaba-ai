"""SCRUM-265 (1/2) — 재블라인드 배포물 (docs/str/08 "재블라인드"). LLM 0.

사건은 `v4_blind2_cases.json` 만 읽음(다시 뽑지 않음). 대조쌍 사건도 파일에서. 쌍 순서·좌우는 생성 때 시드.
228 `build_blind` 와 같은 모양(공개·진단·키 분리) + 안내문 두 줄·쌍마다 ④ 문항.
"""

from __future__ import annotations

import random
from typing import Any

from aml_ai.shared.schemas.str import Facts
from tests.str.v4_blind2_cases import case_facts
from tests.str.v4_blind2_io import diag_hash
from tests.str.v4_blind_support import BlindCase, BlindOutput, CaseDrafts, _pair

SUPPORT_QUESTION = (
    "이 초안에 따르면 유형 분류가 거래 내역으로 뒷받침됩니까?(예/아니오/알 수 없음) A __ / B __"
)
BLIND2_INTRO = (
    "# 초안 비교 평가\n\n각 쌍의 A와 B를 읽고 조사에 더 쓸 만한 쪽을 선택해 주세요. "
    "차이가 없으면 차이 없음을 선택해 주세요.\n"
    "그대로 쓰려면 고칠 문장 수와 사실에 틀린 문장 원문을 각각 적고, 한 줄 이유를 남겨 주세요.\n"
    "고칠 문장 수 = 초안 전체 문장 수가 아니라 고쳐야 할 문장만 셉니다(없으면 0).\n"
    "응답 파일의 fix_a 는 A 초안, fix_b 는 B 초안의 고칠 문장 수입니다. "
    "예: A 는 2문장, B 는 고칠 것 없음 → fix_a 2, fix_b 0.\n"
    "choice 는 A, B, same(차이 없음) 셋 중 하나로 적어 주세요.\n"
    "쌍마다 A·B 둘 다 유형 문항에 답해 주세요 — 응답 파일 support_a·support_b 에 yes/no/unknown"
    "(예/아니오/알 수 없음).\n"
    "평가자: __\n"
)


def blind2_cases(doc: dict[str, Any]) -> list[BlindCase]:
    """새 사건은 묶음 표시 없음, 회귀는 228 처럼 같은 고객끼리 묶음."""
    facts = case_facts(doc)
    groups: dict[str, str] = {}
    out = []
    for c in doc["cases"]:
        f: Facts = facts[c["case_id"]]
        group = None
        if c["role"] == "regression":
            customer = f.subject.entity_id or f.subject.account_key
            group = groups.setdefault(customer, f"g{len(groups) + 1}")
        out.append(BlindCase(c["case_id"], group, f))
    return out


def build_blind2(drafts: list[CaseDrafts], doc: dict[str, Any], seed: int, run_id: str) -> BlindOutput:
    """run_id 는 공개·진단·키(+ 빈 응답 양식)에 같이 — 키에 진단 sha256."""
    by_id = {d.case.case_id: d for d in drafts}
    if len(by_id) != len(drafts) or set(by_id) != {c["case_id"] for c in doc["cases"]}:
        raise ValueError("사건 파일과 같은 사건이 필요함")
    rng = random.Random(seed)
    pairs = [(d, False) for d in drafts] + [(by_id[doc["control_case_id"]], True)]
    rng.shuffle(pairs)
    public: dict[str, Any] = {"run_id": run_id, "pairs": []}
    diag: dict[str, Any] = {"run_id": run_id, "pairs": []}
    key: dict[str, Any] = {
        "run_id": run_id,
        "seed": seed,
        "pairs": [],
        "v2_original": {},
        "replaced": {},
        "unknown": {},
    }
    blocks = [BLIND2_INTRO]
    for number, (draft, control) in enumerate(pairs, start=1):
        record, mapping, body = _pair(number, draft, control, rng)
        public["pairs"].append({"pair_no": number, "group": draft.case.group})
        diag["pairs"].append(record)
        key["pairs"].append(mapping)
        blocks.append(f"{body}{SUPPORT_QUESTION}\n")
    for d in drafts:
        name = d.case.case_id
        key["v2_original"][name] = [
            s.model_dump(mode="json", include={"section", "text"}) for s in d.v2_original
        ]
        key["replaced"][name] = [list(p) for p in d.replaced]
        key["unknown"][name] = list(d.unknown)
    key["diag_sha256"] = diag_hash(diag)
    return BlindOutput("\n".join(blocks), public, diag, key)

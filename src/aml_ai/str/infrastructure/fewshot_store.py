"""few-shot 예시. 정본은 fewshot/*.json, DB fewshot_examples 는 서빙용 사본 (docs/str/05).

MVP: 같은 유형 1 + 다른 유형 2, 고정 순서. 시그니처는 facts 를 받을 수 있게 둬서 임베딩 유사도로 바꿔도 generate 는 안 바뀐다.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts, NarrativeSection
from aml_ai.str.domain.constants import FEWSHOT_OTHER_TYPOLOGY, FEWSHOT_SAME_TYPOLOGY
from aml_ai.str.domain.models import Example

FEWSHOT_DIR = Path(__file__).resolve().parent.parent / "fewshot"


class FewshotStore:
    def __init__(self, session: Session | None = None, directory: Path = FEWSHOT_DIR) -> None:
        self._s = session
        self._dir = directory
        self._cache: list[Example] | None = None

    def all(self) -> list[Example]:
        if self._cache is None:
            self._cache = sorted(
                (self._load(p) for p in self._dir.glob("*.json")), key=lambda e: e.example_id
            )
        return self._cache

    def pick_examples(self, typology: Typology) -> list[Example]:
        same = [e for e in self.all() if e.typology == typology][:FEWSHOT_SAME_TYPOLOGY]
        other = [e for e in self.all() if e.typology != typology][:FEWSHOT_OTHER_TYPOLOGY]
        return same + other

    @staticmethod
    def _load(path: Path) -> Example:
        d = json.loads(path.read_text(encoding="utf-8"))
        return Example(
            example_id=int(d["example_id"]),
            typology=d["typology"],
            facts=Facts.model_validate(d["facts"]),
            narrative=[NarrativeSection.model_validate(s) for s in d["narrative"]],
        )

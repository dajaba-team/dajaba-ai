"""PDF → 청크 → 임베딩 → ai.reference_chunks (docs/str/10 적재 절차). W4.

사용: uv run python -m tools.ingest_corpus --verify     # sha256·쪽수만 manifest 에 채움
      uv run python -m tools.ingest_corpus              # 적재 (멱등, content_hash 로 중복 방지)
      uv run python -m tools.ingest_corpus --truncate   # 임베딩 모델 바꿨을 때 비우고 전부 다시
"""

from __future__ import annotations

import argparse


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--verify", action="store_true")
    p.add_argument("--truncate", action="store_true")
    p.parse_args()
    raise NotImplementedError(
        "W4 — docs/str/10 적재 절차 (pymupdf → 500토큰 청크 → 태깅 → embed 배치 64 → insert on conflict)"
    )


if __name__ == "__main__":
    main()

"""도메인 층 — 순수. 이 폴더는 aml_ai.shared.schemas 와 표준 라이브러리만 import 한다.

DB·LLM·시계·설정·파일 금지. 입력 → 출력. 그래서 픽스처만으로 테스트가 끝난다 (docs/str/01).

models.py        도메인 dataclass — Transaction, Subject, Example, GenerationResult
constants.py     이름 붙인 상수 전부
facts.py         build_facts()        정본 docs/str/04
masking.py       mask_for_llm()       정본 docs/str/04
verification.py  run_code_checks()    정본 docs/str/06
"""

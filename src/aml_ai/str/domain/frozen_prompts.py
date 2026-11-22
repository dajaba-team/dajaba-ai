"""FROZEN_PROMPTS — 녹화 커밋 시점 프롬프트 파일 sha256 (docs/str/05, SCRUM-15).

기동 때 `check_frozen_prompts()` 가 파일 해시와 대조하고, 다르면 FrozenPromptMismatch 로 기동 실패.
녹화를 커밋할 때 같은 커밋에 해시를 박는다.
"""

from __future__ import annotations

FROZEN_PROMPTS: dict[str, str] = {
    "narrative_v1": "d2cbb854386dd3c01dc0d71556878e1e1287cab540839c56ae7dc51281155424",
    "narrative_v2": "66210c3d25e59b136f4ec2359ad2f09c43501435322874f0048192795653aa9f",
    "judge_v2": "9879f7d2eb7f7a82cffe6bdddacb880362c06ad682d0aca318da03b1af62862d",
    "judge_v3": "f57cb7bf38e51b181cb155e037ac507ef2f25996e28746aec9650054d1d5a278",  # SCRUM-127
    "summary_v1": "110d73729036723f6587721ae5e39ebbd4a5d925142ab683522126e13eac5d65",  # SCRUM-129
    "rewrite_v1": "006a3880474364e6aefb20980e8aa2b795e0003469441138fe6d01c8d341c8ed",  # SCRUM-147
    "narrative_v3": "851ba7937c4cafa5d9bed1cfc85293aa23f978220410f0c79a3c4e699959b518",  # SCRUM-225
    "judge_v4": "e4214d8a6dec15d2eafadc7602265d6b040eb6b47c945b13053df666966f7067",  # SCRUM-268
    "ask_plan_v1": "a9b831d22f799c3c0028a6e018fb4c45ae751fd27c08219859e477f537df8a87",  # SCRUM-290
    "ask_answer_v1": "54573315ae0532ec3a38a99acc4cd25a95b733075dd297e080c352615cb64666",  # SCRUM-290
    "ask_answer_v2": "56bc4d87c48e5b5e3058554786b8a181f89e462b96127b5b440e7206ec3f848d",  # SCRUM-358·359
    "rerank_v1": "fb0caf66661cc1668a2b55fce0dc8e9b56bd291b21614fd0f49329c3c73f7336",  # SCRUM-308-2
    "summary_v2": "d5d7eb5759ebbd7a6d7a56a39d2cb0c254934bb9a2052e8b8b5dea5c3dc3c7ba",  # SCRUM-340
}

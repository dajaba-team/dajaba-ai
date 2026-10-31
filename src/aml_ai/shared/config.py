"""설정. 전부 .env 에서. 코드에 모델 이름·키·주소가 보이면 틀린 것 (docs/shared/05 변수 표)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # DB — 백엔드 compose 의 PostgreSQL. 계정 app_ai (ops 읽기, ai 쓰기)
    database_url: str = Field(default="postgresql+psycopg://app_ai@localhost:5432/aml", alias="DATABASE_URL")
    app_ai_password: str = Field(default="", alias="APP_AI_PASSWORD")

    # 백엔드 ↔ AI 내부 인증
    ai_internal_key: str = Field(default="", alias="AI_INTERNAL_KEY")

    # LLM
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_api_base: str = Field(default="https://api.openai.com/v1", alias="LLM_API_BASE")
    llm_model_generate: str = Field(default="", alias="LLM_MODEL_GENERATE")
    llm_model_judge: str = Field(default="", alias="LLM_MODEL_JUDGE")
    llm_timeout_s: float = Field(default=35.0, alias="LLM_TIMEOUT_S")  # docs/shared/05 가정값 (str/03)
    # 결정성 — 설정 하나로 고정, 호출마다 폴백하지 않음(SCRUM-15 10/29)
    llm_temperature_supported: bool = Field(default=False, alias="LLM_TEMPERATURE_SUPPORTED")
    llm_reasoning_effort: str = Field(default="low", alias="LLM_REASONING_EFFORT")
    # 초안 요청 시간 예산 (SCRUM-45) — draft_service 가 요청 수신 즉시 deadline = clock() + draft_budget_s 결정,
    # 생성기는 첫 LLM 호출 전과 재생성 전 두 지점에서만 남은 예산을 본다 (str/03 "구현 위치")
    draft_budget_s: float = Field(default=80.0, gt=0, alias="DRAFT_BUDGET_S")
    regen_min_remaining_s: float = Field(default=40.0, gt=0, alias="REGEN_MIN_REMAINING_S")
    stale_processing_s: float = Field(default=110, gt=0, alias="STALE_PROCESSING_S")
    llm_daily_token_budget: int = Field(default=2_000_000, alias="LLM_DAILY_TOKEN_BUDGET")

    # 임베딩 (RAG, W4)
    embedding_provider: str = Field(default="openai", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field(default="", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=1536, alias="EMBEDDING_DIM")
    rag_enabled: bool = Field(default=False, alias="RAG_ENABLED")
    corpus_dir: Path = Field(default=Path("corpus"), alias="CORPUS_DIR")

    # 목업 스위치
    ai_scoring_mock: bool = Field(default=True, alias="AI_SCORING_MOCK")  # aml-ml 없을 때 고정 점수
    ai_llm_mock: bool = Field(default=False, alias="AI_LLM_MOCK")  # 녹화 응답 재생
    recorded_dir: Path = Field(default=Path("tests/str/recorded"), alias="RECORDED_DIR")

    # 기동
    index_prompts_on_startup: bool = Field(default=True, alias="INDEX_PROMPTS_ON_STARTUP")
    server_version: str = Field(default="dev", alias="SERVER_VERSION")  # 빌드 시 git 짧은 해시 주입
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @model_validator(mode="after")
    def _check_time_budget(self) -> Settings:
        """시간 예산 불변식(SCRUM-45) — 한 번은 LLM 을 부를 수 있어야 하고,
        재생성 경계는 선체크 임계값 아래로 내려가면 안 된다. 어기면 기동 실패."""
        if self.draft_budget_s < self.llm_timeout_s:
            raise ValueError(
                f"draft_budget_s({self.draft_budget_s}) must be >= llm_timeout_s({self.llm_timeout_s})"
            )
        if self.regen_min_remaining_s < self.llm_timeout_s:
            raise ValueError(
                f"regen_min_remaining_s({self.regen_min_remaining_s}) must be >= "
                f"llm_timeout_s({self.llm_timeout_s})"
            )
        return self

    @property
    def sqlalchemy_url(self) -> str:
        """DATABASE_URL 에 비밀번호가 없으면 APP_AI_PASSWORD 를 끼운다 (백엔드 .env 와 변수 공유)."""
        if (
            self.app_ai_password
            and "@" in self.database_url
            and ":" not in self.database_url.split("//", 1)[1].split("@", 1)[0]
        ):
            scheme, rest = self.database_url.split("//", 1)
            user, host = rest.split("@", 1)
            return f"{scheme}//{user}:{self.app_ai_password}@{host}"
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()

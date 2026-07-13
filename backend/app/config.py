"""환경변수에서 로드하는 애플리케이션 설정.

API key와 런타임 설정을 소스 코드 밖에 두기 위한 모듈이다. 덕분에 MVP의 mock
모드에서 실제 LLM 또는 내부 시스템 연동으로 확장할 때도 비즈니스 로직 모듈을
크게 바꾸지 않고 설정만 교체할 수 있다.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """FastAPI 애플리케이션에서 사용하는 타입 지정 런타임 설정."""

    # 프론트엔드 개발 서버 주소를 쉼표로 여러 개 지정할 수 있다.
    backend_cors_origins: str = "http://localhost:5173"
    # mock이면 외부 API를 호출하지 않고, auto이면 선택 모델/provider 설정을 따른다.
    llm_provider: str = "mock"
    # 모델 선택기와 provider 라우팅에 사용하는 세미콜론 구분 모델 레지스트리.
    llm_models: str = ""
    # 설정된 기본 모델 id. 모델 목록에 없으면 llm_settings에서 안전하게 보정한다.
    default_llm_model: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    openai_api_key: str = ""
    # Langfuse key가 모두 설정된 경우에만 observability tracing을 활성화한다.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_tracing_environment: str = "development"
    data_dir: Path = Path(__file__).resolve().parents[1] / "data"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def cors_origin_list(self) -> list[str]:
        """FastAPI CORS middleware가 사용할 수 있도록 origin 문자열을 목록으로 변환한다."""
        # CORS 설정 문자열을 FastAPI가 사용할 수 있는 origin 리스트로 변환한다.

        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """설정 객체를 한 번 생성한 뒤 요청 전반에서 재사용한다."""
    # 환경 설정 객체를 캐시해 요청마다 동일한 설정을 재사용한다.

    return Settings()

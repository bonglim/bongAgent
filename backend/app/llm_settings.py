"""런타임에서 설정 가능한 LLM 모델 레지스트리.

이 모듈은 백엔드 라우팅과 프론트엔드 모델 선택기가 함께 사용하는 모델
목록을 한곳에서 관리한다. 모델 정의는 주로 설정값에서 읽어오므로, 배포
환경마다 소스 코드를 수정하지 않고 provider, 표시 이름, API key 환경변수
이름을 바꿀 수 있다.

런타임 설정이 없거나 형식이 올바르지 않으면 아래의 내장 기본값을 사용한다.
API key 값은 public selector 응답에 절대 포함하지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

from .config import Settings


DEFAULT_LLM_MODELS = (
    "gemini-2.5-flash|gemini-2.5-flash|gemini|GEMINI_API_KEY;"
    "gemini-3.5-flash|gemini-3.5-flash|gemini|GEMINI_API_KEY;"
    "gpt5.5|gpt5.5|openai|OPENAI_API_KEY;"
    "gpt-4o-mini|GPT4o-mini|openai|GPT4O_MINI_API_KEY"
)
DEFAULT_LLM_MODEL = "gemini-3.5-flash"
GPT4O_MINI_MODEL_ID = "gpt-4o-mini"
GPT4O_MINI_API_KEY_ENV = "GPT4O_MINI_API_KEY"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


@dataclass(frozen=True)
class LLMModelConfig:
    """요청 라우팅에 사용하는 선택 가능한 LLM 모델 메타데이터.

    Attributes:
        id: 프론트엔드가 보내고 앱 데이터에 저장하는 안정적인 모델 식별자.
        label: 프론트엔드 모델 선택기에 표시할 사람이 읽기 쉬운 이름.
        provider: ``gemini`` 또는 ``openai`` 같은 백엔드 provider 이름.
        key_env: 해당 모델의 API key가 들어 있는 환경변수 이름.
    """

    id: str
    label: str
    provider: str
    key_env: str


def parse_llm_models(raw_models: str) -> list[LLMModelConfig]:
    """세미콜론으로 구분된 모델 설정 문자열을 파싱한다.

    각 행의 형식은 ``model_id|label|provider|api_key_env_name`` 이다. 형식이
    틀렸거나 값이 비어 있는 행은 건너뛰어, 잘못된 항목 하나 때문에 전체
    모델 레지스트리가 깨지지 않게 한다.

    Args:
        raw_models: 설정값 또는 기본값에서 가져온 원본 모델 레지스트리 문자열.

    Returns:
        설정된 순서를 유지한 유효한 ``LLMModelConfig`` 목록.

    Example:
        ``parse_llm_models("demo|Demo|openai|DEMO_API_KEY")``는 id가
        ``demo``인 설정 하나를 반환한다.
    """
    # 형식: model_id|label|provider|api_key_env_name

    configs: list[LLMModelConfig] = []
    for row in raw_models.split(";"):
        parts = [part.strip() for part in row.split("|")]
        if len(parts) != 4 or not all(parts):
            continue
        configs.append(LLMModelConfig(id=parts[0], label=parts[1], provider=parts[2].lower(), key_env=parts[3]))
    return configs


def get_llm_model_configs(settings: Settings) -> list[LLMModelConfig]:
    """현재 활성화된 모델 레지스트리를 반환한다.

    런타임 설정값을 우선 사용한다. ``settings.llm_models``가 비어 있거나 모든
    설정 행이 유효하지 않으면 내장된 ``DEFAULT_LLM_MODELS`` 목록을 대신
    사용한다.

    Args:
        settings: 환경변수와 ``.env``에서 로드한 애플리케이션 설정.

    Returns:
        애플리케이션에서 사용할 수 있는 파싱된 모델 설정 목록.
    """
    # .env 설정이 비어 있거나 형식이 틀리면 기본 모델 목록을 사용한다.

    return parse_llm_models(settings.llm_models) or parse_llm_models(DEFAULT_LLM_MODELS)


def get_default_llm_model(settings: Settings) -> str:
    """활성 모델 레지스트리에 존재하는 기본 모델 id를 반환한다.

    설정된 기본 모델은 파싱된 모델 목록에 실제로 존재할 때만 사용한다.
    그렇지 않으면 모듈 수준의 ``DEFAULT_LLM_MODEL``을 우선 사용하고, 그다음
    첫 번째 설정 모델을 사용한다. 모든 fallback이 실패하면 마지막으로 모듈
    기본 문자열을 반환한다.

    Args:
        settings: 모델 레지스트리 옵션을 포함한 애플리케이션 설정.

    Returns:
        새 요청에 안전하게 사용할 수 있는 모델 id.
    """
    # 기본 모델이 목록에 없으면 첫 번째 모델을 안전한 기본값으로 사용한다.

    configs = get_llm_model_configs(settings)
    ids = {config.id for config in configs}
    if settings.default_llm_model in ids:
        return settings.default_llm_model
    if DEFAULT_LLM_MODEL in ids:
        return DEFAULT_LLM_MODEL
    return configs[0].id if configs else DEFAULT_LLM_MODEL


def get_llm_model_config(settings: Settings, model_id: str | None) -> LLMModelConfig:
    """요청된 모델 id를 알려진 모델 설정으로 해석한다.

    알 수 없거나 비어 있거나 오래된 모델 id는 현재 기본 모델로 보정한다.
    호출하는 쪽에서 fallback 로직을 중복 구현하지 않고도 요청을 라우팅할 수
    있게 한다.

    Args:
        settings: 모델 레지스트리 옵션을 포함한 애플리케이션 설정.
        model_id: 프론트엔드나 저장 데이터에서 넘어온 선택적 모델 id.

    Returns:
        일치하는 ``LLMModelConfig`` 또는 기본 fallback 설정.
    """
    # 프론트에서 알 수 없는 model id가 들어와도 설정된 기본 모델로 보정한다.

    configs = get_llm_model_configs(settings)
    default_model = get_default_llm_model(settings)
    target_id = model_id or default_model
    for config in configs:
        if config.id == target_id:
            return config
    for config in configs:
        if config.id == default_model:
            return config
    return parse_llm_models(DEFAULT_LLM_MODELS)[0]


def public_llm_models(settings: Settings) -> dict:
    """프론트엔드에 전달해도 안전한 모델 선택기 payload를 만든다.

    반환하는 dictionary에는 모델 id, 표시 이름, provider, 선택된 기본 id만
    포함한다. API key 환경변수 이름과 실제 key 값은 의도적으로 제외한다.

    Args:
        settings: 모델 레지스트리 옵션을 포함한 애플리케이션 설정.

    Returns:
        프론트엔드 모델 선택기에서 사용할 JSON 직렬화 가능한 dictionary.

    Example:
        응답은 ``{"default_model": "...", "models": [...]}`` 형태이며
        ``key_env``와 실제 API key는 포함하지 않는다.
    """
    # key_env와 실제 key 값은 브라우저로 내려보내지 않는다.

    configs = get_llm_model_configs(settings)
    return {
        "default_model": get_default_llm_model(settings),
        "models": [{"id": config.id, "label": config.label, "provider": config.provider} for config in configs],
    }


@lru_cache
def _dotenv_cache() -> dict[str, str | None]:
    """동적 key 환경변수 이름을 해석하기 위해 ``.env``를 한 번만 읽는다.

    ``Settings``는 미리 정의된 필드만 노출하지만, 모델 항목은 임의의 API key
    변수 이름을 가리킬 수 있다. 이 캐시는 매 요청마다 파일을 다시 파싱하지
    않고도 ``.env``의 사용자 정의 key 이름을 읽을 수 있게 한다.

    Returns:
        프로젝트 ``.env``에서 읽은 변수 이름과 값의 mapping.
    """
    # pydantic Settings에 필드로 없는 사용자 정의 key 변수도 읽을 수 있게 한다.

    return dotenv_values(ENV_FILE)


def _read_key_from_env(key_env: str) -> str:
    """환경변수 또는 ``.env``에서 지정한 이름의 API key를 읽는다.

    Args:
        key_env: API key 값이 들어 있는 환경변수 이름.

    Returns:
        환경변수나 ``.env``에서 찾은 key 문자열. 없으면 빈 문자열.
    """
    # 프로세스 환경변수를 우선하고, 없으면 프로젝트 .env 값을 사용한다.

    return str(os.environ.get(key_env) or _dotenv_cache().get(key_env) or "")


def _resolve_gpt4o_mini_api_key(config: LLMModelConfig) -> str:
    """``gpt-4o-mini`` 모델에 사용할 전용 API key를 해석한다.

    ``LLM_MODELS`` 설정에서 key_env를 잘못 지정했거나 공통 OpenAI key로 둔
    경우에도 ``GPT4O_MINI_API_KEY``를 먼저 사용할 수 있게 한다.

    Args:
        config: key를 해석할 모델 설정.

    Returns:
        ``gpt-4o-mini`` 전용 key 문자열. 대상 모델이 아니거나 key가 없으면
        빈 문자열.
    """
    # gpt-4o-mini는 별도 key를 둘 수 있으므로 모델별 전용 변수명을 우선한다.

    if config.id != GPT4O_MINI_MODEL_ID:
        return ""
    return _read_key_from_env(GPT4O_MINI_API_KEY_ENV)


def resolve_model_api_key(settings: Settings, config: LLMModelConfig) -> str:
    """모델 설정에 사용할 API key를 해석한다.

    ``gpt-4o-mini``는 먼저 ``GPT4O_MINI_API_KEY``를 확인한다. 그 외에는
    ``config.key_env``를 사용해 프로세스 환경변수와 프로젝트 ``.env``에서
    모델별 key를 찾는다. 모델별 key가 없으면 기존 동작과의 호환을 위해 provider
    수준 설정값을 fallback으로 사용한다.

    Args:
        settings: provider 수준 fallback key를 포함한 애플리케이션 설정.
        config: API key를 해석할 모델 설정.

    Returns:
        해석된 API key 문자열. key를 찾지 못하면 빈 문자열.
    """
    # 모델별 key_env가 우선이며, 기존 provider별 키는 호환용 fallback이다.

    key = _resolve_gpt4o_mini_api_key(config) or _read_key_from_env(config.key_env)
    if key:
        return key
    if config.provider in {"gemini", "google"}:
        return settings.gemini_api_key
    if config.provider == "openai":
        return settings.openai_api_key
    return ""

"""LLM provider abstraction for GPT chat fallback.

MVP command handling is rule-based, but this boundary keeps the app ready for
OpenAI, LangChain, or LangGraph-backed implementations without coupling routes
to a specific vendor SDK.
"""

from .config import Settings

try:
    from openai import OpenAI, OpenAIError
except ImportError:  # Keeps mock mode usable before dependencies are installed.
    OpenAI = None
    OpenAIError = Exception


class LLMProvider:
    """Small interface for natural-language chat responses."""

    def chat(self, message: str) -> str:
        """Return an assistant response for non-ToDo chat messages."""

        raise NotImplementedError


class MockLLMProvider(LLMProvider):
    """Deterministic provider used when no real API key is configured."""

    def chat(self, message: str) -> str:
        """Return a helpful mock response for general workplace prompts."""

        return (
            "현재는 mock GPT 모드입니다. 요청하신 내용을 업무 문구로 정리하면: "
            f"'{message}'에 대해 고객에게 명확하고 정중하게 안내해 주세요. "
            "필요하면 이 답변을 바탕으로 ToDo를 추가할 수 있습니다."
        )


class OpenAIReadyProvider(LLMProvider):
    """OpenAI-backed provider for general chat fallback responses."""

    def __init__(self, api_key: str, model: str):
        """Create a reusable OpenAI client for chat requests."""

        self.model = model
        self.client = OpenAI(api_key=api_key) if OpenAI else None

    def chat(self, message: str) -> str:
        """Call the OpenAI Responses API and return the generated text."""

        if not self.client:
            return "OpenAI SDK가 설치되어 있지 않습니다. backend에서 requirements.txt 의존성을 설치해 주세요."

        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=(
                    "당신은 한국어로 답하는 개인 업무 비서입니다. "
                    "은행 업무 맥락의 문구 작성, 일정 정리, 고객 응대 초안을 간결하고 정중하게 도와주세요. "
                    "제공되지 않은 고객 개인정보나 내부 정보는 추측하지 마세요."
                ),
                input=message,
            )
        except OpenAIError as exc:
            code = getattr(exc, "code", None)
            status_code = getattr(exc, "status_code", None)
            if code == "insufficient_quota" or status_code == 429:
                return "OpenAI API 할당량 또는 결제 설정 문제로 응답을 생성하지 못했습니다. OpenAI 프로젝트의 billing/usage 상태를 확인해 주세요."
            if status_code == 401:
                return "OpenAI API 키가 유효하지 않습니다. .env의 OPENAI_API_KEY를 확인해 주세요."
            return f"OpenAI 호출 중 오류가 발생했습니다: {exc}"

        return response.output_text.strip() or "OpenAI 응답이 비어 있습니다."


def build_llm_provider(settings: Settings) -> LLMProvider:
    """Select the configured LLM provider for dependency injection."""

    provider = settings.llm_provider.lower()
    if provider in {"gpt", "openai"} and settings.openai_api_key:
        return OpenAIReadyProvider(settings.openai_api_key, settings.openai_model)
    return MockLLMProvider()

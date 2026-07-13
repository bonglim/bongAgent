"""모델 선택이 가능한 채팅 fallback용 LLM provider 추상화.

MVP의 ToDo 명령 처리는 규칙 기반으로 동작하지만, 일반 채팅 응답은 이 경계를
통해 실제 LLM provider로 위임한다. 라우터가 특정 vendor SDK에 직접 묶이지
않도록 하여 Gemini, OpenAI, LangChain, LangGraph 기반 구현으로 확장하기 쉽게
만든다.
"""

from __future__ import annotations

import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import certifi
from langfuse import Langfuse

from .config import Settings
from .llm_settings import get_default_llm_model, get_llm_model_config, resolve_model_api_key
from .models import LLMModel


class LLMProvider:
    """자연어 채팅 응답을 생성하는 provider의 최소 인터페이스."""

    def chat(self, message: str, model: LLMModel | None = None) -> str:
        """ToDo 명령이 아닌 일반 채팅 메시지에 대한 assistant 응답을 반환한다."""
        # 구현 클래스에서 실제 채팅 응답 생성 방식을 정의하도록 강제한다.

        raise NotImplementedError


class MockLLMProvider(LLMProvider):
    """실제 API key가 없을 때 사용하는 결정적 mock provider."""

    def chat(self, message: str, model: LLMModel | None = None) -> str:
        """일반 업무 프롬프트에 대해 화면 검증용 mock 응답을 반환한다."""
        # API 키 없이도 화면 흐름을 검증할 수 있는 결정적 mock 답변을 만든다.

        return (
            f"현재는 mock LLM 모드입니다. 선택된 모델은 {model or 'default'}입니다. 요청하신 내용을 업무 문구로 정리하면: "
            f"{message}에 대해 고객에게 명확하고 정중하게 안내해 주세요. "
            "필요하면 이 답변을 바탕으로 ToDo를 추가할 수 있습니다."
        )


class GeminiProvider(LLMProvider):
    """일반 채팅 fallback 응답을 Gemini로 생성하는 provider."""

    def __init__(self, api_key: str, model: str, langfuse: Langfuse | None = None) -> None:
        """Gemini 채팅 요청에 필요한 설정을 보관한다."""
        # Gemini API 호출에 필요한 API 키와 모델명을 보관한다.

        self.api_key = api_key
        self.model = model
        self.langfuse = langfuse

    def chat(self, message: str, model: LLMModel | None = None) -> str:
        """Gemini generateContent REST API를 호출하고 생성된 텍스트를 반환한다."""
        # 일반 채팅 요청을 Gemini REST API로 보내고 사용자 친화적인 결과를 반환한다.

        active_model = model or self.model
        if self.langfuse is None:
            return self._chat(message, active_model)
        with self.langfuse.start_as_current_observation(
            as_type="generation",
            name="gemini-generate-content",
            model=str(active_model),
            input=message,
            metadata={"provider": "gemini"},
        ) as generation:
            output = self._chat(message, active_model)
            generation.update(output=output)
            return output

    def _chat(self, message: str, active_model: LLMModel) -> str:
        """Gemini REST 호출을 수행해 tracing 여부와 무관한 응답 문자열을 만든다."""

        payload = {
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "당신은 한국어로 답하는 개인 업무 비서입니다. "
                            "은행 업무 맥락의 문구 작성, 일정 정리, 고객 응대 초안을 간결하고 정중하게 도와주세요. "
                            "제공되지 않은 고객 개인정보나 내부 정보는 추측하지 마세요."
                        )
                    }
                ]
            },
            "contents": [{"parts": [{"text": message}]}],
        }
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(active_model, safe='')}:generateContent?key={quote(self.api_key, safe='')}"
        )
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            context = ssl.create_default_context(cafile=certifi.where())
            with urlopen(request, timeout=45, context=context) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return self._format_http_error(exc)
        except URLError as exc:
            return f"Gemini API에 연결하지 못했습니다: {exc.reason}"

        return self._extract_text(body)

    def _format_http_error(self, exc: HTTPError) -> str:
        """Gemini HTTP 오류를 한국어 사용자 안내 메시지로 변환한다."""
        # Gemini REST API 오류 본문을 읽어 상황별 안내 문구로 변환한다.

        detail = exc.read().decode("utf-8", errors="ignore")
        if exc.code == 429:
            return "Gemini API 할당량 또는 결제 설정 문제로 응답을 생성하지 못했습니다. Google AI Studio의 billing/usage 상태를 확인해 주세요."
        if exc.code in {400, 401, 403}:
            return "Gemini API 키가 유효하지 않거나 권한이 없습니다. .env의 GEMINI_API_KEY를 확인해 주세요."
        return f"Gemini 호출 중 오류가 발생했습니다: HTTP {exc.code} {detail}"

    def _extract_text(self, body: dict) -> str:
        """Gemini generateContent 응답에서 첫 번째 텍스트 part를 추출한다."""
        # candidates 배열에서 화면에 표시할 최종 텍스트를 안전하게 꺼낸다.

        for candidate in body.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                text = part.get("text", "").strip()
                if text:
                    return text
        return "Gemini 응답이 비어 있습니다."


class OpenAIProvider(LLMProvider):
    """일반 채팅 fallback 응답을 OpenAI Responses API로 생성하는 provider."""

    def __init__(self, api_key: str, langfuse: Langfuse | None = None) -> None:
        """OpenAI 채팅 요청에 필요한 API key를 보관한다."""
        # OpenAI API 호출에 필요한 API 키를 보관한다.

        self.api_key = api_key
        self.langfuse = langfuse

    def chat(self, message: str, model: LLMModel | None = None) -> str:
        """OpenAI Responses API를 호출하고 생성된 텍스트를 반환한다."""
        # 선택된 OpenAI 모델로 일반 채팅 요청을 보내고 사용자 친화적인 결과를 반환한다.

        if self.langfuse is None:
            return self._chat(message, model)
        with self.langfuse.start_as_current_observation(
            as_type="generation",
            name="openai-responses",
            model=str(model or "default"),
            input=message,
            metadata={"provider": "openai"},
        ) as generation:
            output = self._chat(message, model)
            generation.update(output=output)
            return output

    def _chat(self, message: str, model: LLMModel | None) -> str:
        """OpenAI REST 호출을 수행해 tracing 여부와 무관한 응답 문자열을 만든다."""

        payload = {
            "model": model,
            "instructions": (
                "당신은 한국어로 답하는 개인 업무 비서입니다. "
                "은행 업무 맥락의 문구 작성, 일정 정리, 고객 응대 초안을 간결하고 정중하게 도와주세요. "
                "제공되지 않은 고객 개인정보나 내부 정보는 추측하지 마세요."
            ),
            "input": message,
        }
        request = Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )

        try:
            context = ssl.create_default_context(cafile=certifi.where())
            with urlopen(request, timeout=45, context=context) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return self._format_http_error(exc)
        except URLError as exc:
            return f"OpenAI API에 연결하지 못했습니다: {exc.reason}"

        return self._extract_text(body)

    def _format_http_error(self, exc: HTTPError) -> str:
        """OpenAI HTTP 오류를 한국어 사용자 안내 메시지로 변환한다."""
        # OpenAI REST API 오류 본문을 읽어 상황별 안내 문구로 변환한다.

        detail = exc.read().decode("utf-8", errors="ignore")
        if exc.code == 429:
            return "OpenAI API 할당량 또는 결제 설정 문제로 응답을 생성하지 못했습니다. usage/billing 상태를 확인해 주세요."
        if exc.code in {400, 401, 403}:
            return "OpenAI API 키가 유효하지 않거나 선택한 모델 권한이 없습니다. .env의 OPENAI_API_KEY와 모델 접근 권한을 확인해 주세요."
        return f"OpenAI 호출 중 오류가 발생했습니다: HTTP {exc.code} {detail}"

    def _extract_text(self, body: dict) -> str:
        """OpenAI Responses API 응답에서 표시 가능한 텍스트를 추출한다."""
        # output_text 단축 필드가 없을 때도 output 배열을 순회해 텍스트를 안전하게 꺼낸다.

        direct_text = body.get("output_text", "").strip()
        if direct_text:
            return direct_text
        for item in body.get("output", []):
            for content in item.get("content", []):
                text = content.get("text", "").strip()
                if text:
                    return text
        return "OpenAI 응답이 비어 있습니다."


class RoutedLLMProvider(LLMProvider):
    """선택된 모델에 맞는 provider로 각 채팅 요청을 라우팅한다."""

    def __init__(self, settings: Settings, langfuse: Langfuse | None = None) -> None:
        """런타임 설정을 사용해 provider 라우팅에 필요한 상태를 준비한다."""
        # 선택 모델별로 사용할 수 있는 실제 provider와 mock fallback을 준비한다.

        self.settings = settings
        self.langfuse = langfuse
        self.mock_provider = MockLLMProvider()

    def chat(self, message: str, model: LLMModel | None = None) -> str:
        """선택 모델이 의미하는 provider를 통해 채팅 메시지를 전송한다."""
        # 설정 모듈에서 model id별 provider/key를 해석하고, 키가 없으면 mock으로 응답한다.

        model_config = get_llm_model_config(self.settings, model)
        provider_setting = self.settings.llm_provider.lower()
        if provider_setting == "mock":
            return self.mock_provider.chat(message, model_config.id)

        api_key = resolve_model_api_key(self.settings, model_config)
        if not api_key:
            return self.mock_provider.chat(message, model_config.id)
        if model_config.provider in {"gemini", "google"}:
            return GeminiProvider(api_key, get_default_llm_model(self.settings), self.langfuse).chat(
                message, model_config.id
            )
        if model_config.provider == "openai":
            return OpenAIProvider(api_key, self.langfuse).chat(message, model_config.id)
        return self.mock_provider.chat(message, model_config.id)


def build_llm_provider(settings: Settings, langfuse: Langfuse | None = None) -> LLMProvider:
    """의존성 주입에 사용할 LLM provider를 설정값에 맞춰 생성한다."""
    # 환경 설정과 요청 모델에 따라 실제 provider 또는 mock provider를 선택한다.

    return RoutedLLMProvider(settings, langfuse)

"""일반 LLM 질문 답변 fallback sub-agent."""

from __future__ import annotations

from ..llm_provider import LLMProvider
from ..models import AssistantCommandResponse
from .shared import AgentContext


class LLMQuestionAnswerAgent:
    """업무 명령이 아닌 일반 질문을 LLM provider로 전달한다."""

    def __init__(self, llm_provider: LLMProvider) -> None:
        """일반 질문 답변을 위임할 LLM provider를 보관한다."""

        self.llm_provider = llm_provider

    def can_handle(self, context: AgentContext) -> bool:
        """fallback agent이므로 모든 요청을 처리할 수 있다."""

        return True

    def handle(self, context: AgentContext) -> AssistantCommandResponse:
        """일반 질문에 대한 LLM 응답을 반환한다."""

        return AssistantCommandResponse(intent="chat", reply=self.llm_provider.chat(context.message, context.model))

"""도메인별 채팅 agent가 공유하는 context와 helper."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from ..models import AftercareCustomer, AssistantCommandResponse, InternalMessage, LLMModel


def contains_any(message: str, keywords: list[str]) -> bool:
    """문장 안에 지정된 키워드가 하나라도 있는지 확인한다."""

    return any(keyword in message for keyword in keywords)


def compact_title(message: str, remove_words: list[str], fallback: str) -> str:
    """명령어 키워드를 제거해 저장용 제목을 만든다."""

    title = message
    for word in remove_words:
        title = re.sub(re.escape(word), "", title, flags=re.IGNORECASE)
    title = re.sub(r"^(오늘|내일)\s*", "", title).strip(" .,:;/-")
    return title[:40] or fallback


@dataclass(frozen=True)
class AgentContext:
    """각 agent가 공유하는 요청 context."""

    message: str
    model: LLMModel | None = None
    messages: tuple[InternalMessage, ...] = ()
    customers: tuple[AftercareCustomer, ...] = ()


class DomainAgent(Protocol):
    """orchestrator가 호출할 수 있는 도메인 agent 인터페이스."""

    def can_handle(self, context: AgentContext) -> bool:
        """현재 요청을 처리할 수 있으면 ``True``를 반환한다."""

    def handle(self, context: AgentContext) -> AssistantCommandResponse:
        """현재 요청을 처리하고 API 응답 모델을 반환한다."""

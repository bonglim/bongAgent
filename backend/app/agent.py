"""채팅 orchestration agent의 이전 import 경로를 보존한다.

Example:
    기존 코드의 ``from app.agent import RuleBasedAssistantAgent``는 실제 구현이
    ``app.agents.orchestrator``로 이동한 뒤에도 그대로 동작한다.
"""

from .agents.orchestrator import RuleBasedAssistantAgent

__all__ = ["RuleBasedAssistantAgent"]

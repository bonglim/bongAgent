"""LangGraph 형식으로 도메인별 sub-agent를 라우팅하는 orchestration agent."""

from __future__ import annotations

from typing import Literal, Protocol, TypedDict

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover - langgraph 설치 전 로컬 실행을 위한 fallback
    END = "__end__"
    START = "__start__"
    StateGraph = None

from ..llm_provider import LLMProvider
from ..models import AssistantCommandResponse, LLMModel
from ..repository import JsonRepository
from .customer_agent import AftercareCustomerManagementAgent
from .llm_agent import LLMQuestionAnswerAgent
from .message_agent import InternalMessageManagementAgent
from .shared import AgentContext
from .todo_agent import TodoManagementAgent


RouteName = Literal["message", "customer", "todo", "llm"]


class OrchestratorState(TypedDict):
    """LangGraph node 사이에서 공유하는 orchestration 상태."""

    message: str
    model: LLMModel | None
    response: AssistantCommandResponse | None


class InvokableGraph(Protocol):
    """orchestrator가 의존하는 graph 실행 인터페이스."""

    def invoke(self, state: OrchestratorState) -> OrchestratorState:
        """state를 받아 node 실행 후 갱신된 state를 반환한다."""


class _FallbackCompiledGraph:
    """langgraph 미설치 환경에서 같은 ``invoke`` 계약으로 동작하는 최소 graph."""

    def __init__(self, orchestrator: RuleBasedAssistantAgent) -> None:
        """fallback graph가 호출할 orchestrator instance를 보관한다."""

        self.orchestrator = orchestrator

    def invoke(self, state: OrchestratorState) -> OrchestratorState:
        """route node를 실행한 뒤 선택된 sub-agent node를 호출한다."""

        route = self.orchestrator._route(state)
        if route == "message":
            return self.orchestrator._run_message_agent(state)
        if route == "customer":
            return self.orchestrator._run_customer_agent(state)
        if route == "todo":
            return self.orchestrator._run_todo_agent(state)
        return self.orchestrator._run_llm_agent(state)


class RuleBasedAssistantAgent:
    """LangGraph state graph로 sub-agent 라우팅을 수행하는 채팅 orchestrator."""

    def __init__(self, repository: JsonRepository, llm_provider: LLMProvider) -> None:
        """API 계층에서 저장소와 LLM provider 의존성을 주입받는다."""

        self.message_agent = InternalMessageManagementAgent(repository, llm_provider)
        self.customer_agent = AftercareCustomerManagementAgent(repository)
        self.todo_agent = TodoManagementAgent(repository)
        self.llm_agent = LLMQuestionAnswerAgent(llm_provider)
        self.graph = self._build_graph()

    def handle(self, message: str, model: LLMModel | None = None) -> AssistantCommandResponse:
        """사용자 메시지를 graph에 전달하고 최종 agent 응답을 반환한다."""

        state: OrchestratorState = {
            "message": message.strip(),
            "model": model,
            "response": None,
        }
        result = self.graph.invoke(state)
        return result["response"] or AssistantCommandResponse(intent="chat", reply="")

    def _build_graph(self) -> InvokableGraph:
        """LangGraph ``StateGraph``를 만들고, 미설치 시 fallback graph를 반환한다."""

        if StateGraph is None:
            return _FallbackCompiledGraph(self)

        graph = StateGraph(OrchestratorState)
        graph.add_node("message", self._run_message_agent)
        graph.add_node("customer", self._run_customer_agent)
        graph.add_node("todo", self._run_todo_agent)
        graph.add_node("llm", self._run_llm_agent)
        graph.add_conditional_edges(
            START,
            self._route,
            {
                "message": "message",
                "customer": "customer",
                "todo": "todo",
                "llm": "llm",
            },
        )
        graph.add_edge("message", END)
        graph.add_edge("customer", END)
        graph.add_edge("todo", END)
        graph.add_edge("llm", END)
        return graph.compile()

    def _route(self, state: OrchestratorState) -> RouteName:
        """입력 문장을 처리할 sub-agent node 이름으로 라우팅한다."""

        context = self._context(state)
        if self.message_agent.can_handle(context):
            return "message"
        if self.customer_agent.can_handle(context):
            return "customer"
        if self.todo_agent.can_handle(context):
            return "todo"
        return "llm"

    def _run_message_agent(self, state: OrchestratorState) -> OrchestratorState:
        """사내쪽지 agent node를 실행한다."""

        return {**state, "response": self.message_agent.handle(self._context(state))}

    def _run_customer_agent(self, state: OrchestratorState) -> OrchestratorState:
        """사후고객관리 agent node를 실행한다."""

        return {**state, "response": self.customer_agent.handle(self._context(state))}

    def _run_todo_agent(self, state: OrchestratorState) -> OrchestratorState:
        """ToDo agent node를 실행한다."""

        return {**state, "response": self.todo_agent.handle(self._context(state))}

    def _run_llm_agent(self, state: OrchestratorState) -> OrchestratorState:
        """일반 LLM fallback agent node를 실행한다."""

        return {**state, "response": self.llm_agent.handle(self._context(state))}

    def _context(self, state: OrchestratorState) -> AgentContext:
        """LangGraph state를 기존 sub-agent가 쓰는 ``AgentContext``로 변환한다."""

        return AgentContext(message=state["message"], model=state["model"])

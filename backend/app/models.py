"""Bong에이전트 API endpoint들이 공유하는 Pydantic 모델.

요청 body, 응답 body, JSON 저장소에 기록되는 업무 데이터의 schema를 한곳에
정의한다. FastAPI는 이 모델들을 사용해 입력값을 검증하고 OpenAPI 문서를 만든다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TodoStatus = Literal["todo", "doing", "done"]
Priority = Literal["high", "medium", "low"]
TodoSource = Literal["manual", "message", "customer", "assistant"]
MessageStatus = Literal["unread", "todo_linked", "done"]
LLMModel = str


class TodoBase(BaseModel):
    """ToDo 항목에서 생성과 수정 화면이 공유하는 기본 필드."""

    # title은 카드의 핵심 식별 텍스트이므로 빈 문자열을 허용하지 않는다.
    title: str = Field(..., min_length=1)
    description: str = ""
    status: TodoStatus = "todo"
    priority: Priority = "medium"
    due_date: str = ""
    source: TodoSource = "manual"
    linked_type: str | None = None
    linked_id: str | None = None


class TodoCreate(TodoBase):
    """사용자나 agent가 ToDo를 생성할 때 전달하는 payload."""


class TodoUpdate(BaseModel):
    """ToDo 일부 필드만 수정할 때 사용하는 부분 update payload."""

    title: str | None = None
    description: str | None = None
    status: TodoStatus | None = None
    priority: Priority | None = None
    due_date: str | None = None


class Todo(TodoBase):
    """저장소에 기록되고 프론트엔드로 반환되는 ToDo 항목."""

    id: str
    created_at: datetime
    updated_at: datetime


class InternalMessage(BaseModel):
    """ToDo로 전환할 수 있는 사내쪽지 레코드.

    ``priority``는 high/medium/low 등급이고 ``priority_rank``는 재조정된
    전체 목록의 정확한 1~N 순서다. 예를 들어 high 등급 항목이 여러 개여도
    ``priority_rank=1``인 쪽지가 먼저 표시된다.
    """

    id: str
    title: str
    sender: str
    received_at: str
    priority: Priority
    status: MessageStatus
    body: str
    linked_todo_id: str | None = None
    priority_rank: int | None = Field(default=None, ge=1)
    priority_reason: str = ""


class InternalMessageCreate(BaseModel):
    """사용자가 화면에서 사내쪽지를 직접 등록할 때 전달하는 payload."""

    title: str = Field(..., min_length=1)
    sender: str = Field(..., min_length=1)
    received_at: str = ""
    priority: Priority = "medium"
    body: str = ""


class InternalMessageUpdate(BaseModel):
    """사내쪽지 일부 필드만 수정할 때 사용하는 부분 update payload."""

    priority: Priority | None = None
    priority_rank: int | None = Field(default=None, ge=1)
    priority_reason: str | None = None


class AftercareCustomer(BaseModel):
    """ToDo로 전환할 수 있는 사후관리 고객 레코드.

    Example:
        최근 예정일 순 재조정 결과는 ``priority="high"``,
        ``priority_rank=1``, ``priority_reason="최근 관리예정일 기준..."``처럼
        등급·전체 순위·근거를 함께 저장한다.
    """

    id: str
    name: str
    reason: str
    recommended_action: str
    scheduled_date: str
    priority: Priority
    detail: str
    linked_todo_id: str | None = None
    priority_rank: int | None = Field(default=None, ge=1)
    priority_reason: str = ""


class AftercareCustomerCreate(BaseModel):
    """사용자가 화면에서 사후관리 고객을 직접 등록할 때 전달하는 payload."""

    name: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    recommended_action: str = ""
    scheduled_date: str = ""
    priority: Priority = "medium"
    detail: str = ""


class AftercareCustomerUpdate(BaseModel):
    """사후관리 고객 일부 필드만 수정할 때 사용하는 부분 update payload."""

    priority: Priority | None = None
    priority_rank: int | None = Field(default=None, ge=1)
    priority_reason: str | None = None


class CustomerPriorityRecommendationRequest(BaseModel):
    """사후관리 고객 AI 우선순위 추천에 사용할 선택 모델."""

    model: LLMModel | None = None


class AssistantCommandRequest(BaseModel):
    """채팅 패널에서 전송되는 자연어 명령 요청."""

    message: str = Field(..., min_length=1)
    model: LLMModel | None = None


class AgentInvokeRequest(BaseModel):
    """개별 agent API를 직접 호출할 때 사용하는 요청 payload."""

    message: str = Field(..., min_length=1)
    model: LLMModel | None = None


class AssistantCommandResponse(BaseModel):
    """명령 분류와 처리 후 반환되는 구조화된 assistant 응답."""

    intent: str
    reply: str
    result: dict | None = None
    todos: list[Todo] | None = None

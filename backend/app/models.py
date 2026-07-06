"""Pydantic models shared by Bong에이전트 API endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TodoStatus = Literal["todo", "doing", "done"]
Priority = Literal["high", "medium", "low"]
TodoSource = Literal["manual", "message", "customer", "assistant"]
MessageStatus = Literal["unread", "todo_linked", "done"]


class TodoBase(BaseModel):
    """Common editable fields for a ToDo item."""

    title: str = Field(..., min_length=1)
    description: str = ""
    status: TodoStatus = "todo"
    priority: Priority = "medium"
    due_date: str = ""
    source: TodoSource = "manual"
    linked_type: str | None = None
    linked_id: str | None = None


class TodoCreate(TodoBase):
    """Payload used when a user or agent creates a ToDo."""


class TodoUpdate(BaseModel):
    """Partial update payload for a ToDo."""

    title: str | None = None
    description: str | None = None
    status: TodoStatus | None = None
    priority: Priority | None = None
    due_date: str | None = None


class Todo(TodoBase):
    """Persisted ToDo item returned to the frontend."""

    id: str
    created_at: datetime
    updated_at: datetime


class InternalMessage(BaseModel):
    """Mock internal message that can be converted into a ToDo."""

    id: str
    title: str
    sender: str
    received_at: str
    priority: Priority
    status: MessageStatus
    body: str
    linked_todo_id: str | None = None


class AftercareCustomer(BaseModel):
    """Mock aftercare customer record that can be converted into a ToDo."""

    id: str
    name: str
    reason: str
    recommended_action: str
    scheduled_date: str
    priority: Priority
    detail: str
    linked_todo_id: str | None = None


class AssistantCommandRequest(BaseModel):
    """Natural-language command sent from the chat panel."""

    message: str = Field(..., min_length=1)


class AssistantCommandResponse(BaseModel):
    """Structured response returned after command classification and handling."""

    intent: str
    reply: str
    result: dict | None = None
    todos: list[Todo] | None = None

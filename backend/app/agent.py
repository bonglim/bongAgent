"""Rule-based assistant agent for MVP natural-language ToDo commands."""

from __future__ import annotations

import re

from .llm_provider import LLMProvider
from .models import AssistantCommandResponse, TodoCreate, TodoUpdate
from .repository import JsonRepository


class RuleBasedAssistantAgent:
    """Classify Korean natural-language input and execute simple ToDo actions."""

    def __init__(self, repository: JsonRepository, llm_provider: LLMProvider):
        """Receive storage and LLM dependencies from the API layer."""

        self.repository = repository
        self.llm_provider = llm_provider

    def handle(self, message: str) -> AssistantCommandResponse:
        """Route a user message to create, update, delete, or chat handling."""

        normalized = message.strip()
        if self._is_delete(normalized):
            return self._delete_todo(normalized)
        if self._is_update(normalized):
            return self._update_todo(normalized)
        if self._is_create(normalized):
            return self._create_todo(normalized)
        return self._chat(normalized)

    def _is_create(self, message: str) -> bool:
        """Detect ToDo creation requests by common Korean command keywords."""

        return any(keyword in message for keyword in ["추가", "등록", "할일", "todo", "ToDo"])

    def _is_update(self, message: str) -> bool:
        """Detect ToDo status update requests."""

        return any(keyword in message for keyword in ["진행중", "진행 중", "완료", "할일로", "변경", "바꿔"])

    def _is_delete(self, message: str) -> bool:
        """Detect ToDo deletion requests."""

        return any(keyword in message for keyword in ["삭제", "지워", "제거"])

    def _create_todo(self, message: str) -> AssistantCommandResponse:
        """Extract a ToDo draft from text and create it immediately for the MVP."""

        title = self._extract_title(message)
        due_date = self._extract_due_text(message)
        priority = "high" if any(word in message for word in ["중요", "긴급", "오늘"]) else "medium"
        todo = self.repository.create_todo(
            TodoCreate(
                title=title,
                description=f"자연어 명령에서 생성됨: {message}",
                priority=priority,
                due_date=due_date,
                source="assistant",
            )
        )
        return AssistantCommandResponse(
            intent="create_todo",
            reply=f"'{todo.title}' ToDo를 생성했습니다.",
            result=todo.model_dump(mode="json"),
            todos=self.repository.list_todos(),
        )

    def _update_todo(self, message: str) -> AssistantCommandResponse:
        """Find the closest ToDo and update its status from natural language."""

        target = self._find_matching_todo(message)
        if not target:
            return AssistantCommandResponse(intent="needs_confirmation", reply="수정할 ToDo를 찾지 못했습니다.")
        status = self._extract_status(message)
        updated = self.repository.update_todo(target.id, TodoUpdate(status=status))
        return AssistantCommandResponse(
            intent="update_todo",
            reply=f"'{target.title}' 상태를 변경했습니다.",
            result=updated.model_dump(mode="json") if updated else None,
            todos=self.repository.list_todos(),
        )

    def _delete_todo(self, message: str) -> AssistantCommandResponse:
        """Find the closest ToDo and delete it from the dashboard."""

        target = self._find_matching_todo(message)
        if not target:
            return AssistantCommandResponse(intent="needs_confirmation", reply="삭제할 ToDo를 찾지 못했습니다.")
        self.repository.delete_todo(target.id)
        return AssistantCommandResponse(
            intent="delete_todo",
            reply=f"'{target.title}' ToDo를 삭제했습니다.",
            result={"deleted_id": target.id},
            todos=self.repository.list_todos(),
        )

    def _chat(self, message: str) -> AssistantCommandResponse:
        """Send non-ToDo requests to the configured LLM provider."""

        return AssistantCommandResponse(intent="chat", reply=self.llm_provider.chat(message))

    def _extract_title(self, message: str) -> str:
        """Clean common command words to derive a concise ToDo title."""

        title = re.sub(r"(추가해줘|추가|등록해줘|등록|할일로|ToDo로|todo로)", "", message, flags=re.IGNORECASE)
        title = re.sub(r"^(오늘|내일)\s*", "", title).strip()
        return title[:40] or "새 업무"

    def _extract_due_text(self, message: str) -> str:
        """Extract simple Korean date/time phrases for display."""

        match = re.search(r"(오늘|내일)?\s*(오전|오후)?\s*\d{1,2}시", message)
        if match:
            return match.group(0).strip()
        if "오늘" in message:
            return "오늘"
        if "내일" in message:
            return "내일"
        return ""

    def _extract_status(self, message: str) -> str:
        """Map Korean status words to the API status enum."""

        if "완료" in message:
            return "done"
        if "진행중" in message or "진행 중" in message:
            return "doing"
        return "todo"

    def _find_matching_todo(self, message: str):
        """Choose the first ToDo whose title shares a token with the message."""

        command_words = {"삭제", "지워", "제거", "진행중", "진행", "완료", "변경", "바꿔", "업무를", "업무"}
        tokens = [token for token in re.split(r"\s+", message) if token and token not in command_words]
        todos = self.repository.list_todos()
        for todo in todos:
            if any(token in todo.title or token in todo.description for token in tokens):
                return todo
        return todos[0] if todos else None

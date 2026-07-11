"""MVP 자연어 ToDo 명령을 처리하는 규칙 기반 assistant agent.

이 agent는 한국어 사용자의 간단한 업무 명령을 생성, 수정, 삭제, 일반 채팅으로
분류한다. 명확한 ToDo 명령은 저장소에 즉시 반영하고, 그 외 문장 작성이나 일반
질문은 설정된 LLM provider로 넘긴다.
"""

from __future__ import annotations

import re

from .llm_provider import LLMProvider
from .models import AssistantCommandResponse, LLMModel, TodoCreate, TodoUpdate
from .repository import JsonRepository


class RuleBasedAssistantAgent:
    """한국어 자연어 입력을 분류하고 단순 ToDo 작업을 실행한다."""

    def __init__(self, repository: JsonRepository, llm_provider: LLMProvider):
        """API 계층에서 저장소와 LLM provider 의존성을 주입받는다."""
        # 저장소와 LLM provider를 주입받아 agent 동작을 외부 의존성에서 분리한다.

        self.repository = repository
        self.llm_provider = llm_provider

    def handle(self, message: str, model: LLMModel | None = None) -> AssistantCommandResponse:
        """사용자 메시지를 생성, 수정, 삭제, 일반 채팅 처리로 라우팅한다."""
        # 자연어 메시지를 삭제, 수정, 생성, 일반 채팅 순서로 분류한다.

        normalized = message.strip()
        if self._is_delete(normalized):
            return self._delete_todo(normalized)
        if self._is_update(normalized):
            return self._update_todo(normalized)
        if self._is_create(normalized):
            return self._create_todo(normalized)
        return self._chat(normalized, model)

    def _is_create(self, message: str) -> bool:
        """자주 쓰는 한국어 명령 키워드로 ToDo 생성 요청을 감지한다."""
        # 한국어 생성 명령 키워드가 포함됐는지 확인한다.

        return any(keyword in message for keyword in ["추가", "등록", "할일", "todo", "ToDo"])

    def _is_update(self, message: str) -> bool:
        """한국어 상태 변경 표현으로 ToDo 수정 요청을 감지한다."""
        # 한국어 상태 변경 명령 키워드가 포함됐는지 확인한다.

        return any(keyword in message for keyword in ["진행중", "진행 중", "완료", "할일로", "변경", "바꿔"])

    def _is_delete(self, message: str) -> bool:
        """한국어 삭제 표현으로 ToDo 삭제 요청을 감지한다."""
        # 한국어 삭제 명령 키워드가 포함됐는지 확인한다.

        return any(keyword in message for keyword in ["삭제", "지워", "제거"])

    def _create_todo(self, message: str) -> AssistantCommandResponse:
        """자연어 문장에서 ToDo 초안을 추출하고 MVP에서는 즉시 생성한다."""
        # 자연어 문장에서 제목, 마감일, 우선순위를 추출해 ToDo를 생성한다.

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
        """가장 가까운 ToDo를 찾아 자연어에서 추출한 상태로 변경한다."""
        # 메시지와 가장 가까운 ToDo를 찾아 상태를 변경한다.

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
        """가장 가까운 ToDo를 찾아 대시보드에서 삭제한다."""
        # 메시지와 가장 가까운 ToDo를 찾아 삭제한다.

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

    def _chat(self, message: str, model: LLMModel | None) -> AssistantCommandResponse:
        """ToDo 명령이 아닌 요청을 설정된 LLM provider로 전달한다."""
        # ToDo 명령이 아닌 일반 요청을 LLM provider로 전달한다.

        return AssistantCommandResponse(intent="chat", reply=self.llm_provider.chat(message, model))

    def _extract_title(self, message: str) -> str:
        """흔한 명령어 표현을 제거해 간결한 ToDo 제목을 만든다."""
        # 명령어 표현을 제거해 카드 제목으로 쓸 짧은 문장을 만든다.

        title = re.sub(r"(추가해줘|추가|등록해줘|등록|할일로|ToDo로|todo로)", "", message, flags=re.IGNORECASE)
        title = re.sub(r"^(오늘|내일)\s*", "", title).strip()
        return title[:40] or "새 업무"

    def _extract_due_text(self, message: str) -> str:
        """표시에 사용할 간단한 한국어 날짜/시간 표현을 추출한다."""
        # 간단한 한국어 날짜와 시간 표현을 마감일 텍스트로 뽑아낸다.

        match = re.search(r"(오늘|내일)?\s*(오전|오후)?\s*\d{1,2}시", message)
        if match:
            return match.group(0).strip()
        if "오늘" in message:
            return "오늘"
        if "내일" in message:
            return "내일"
        return ""

    def _extract_status(self, message: str) -> str:
        """한국어 상태 단어를 API status enum 값으로 매핑한다."""
        # 한국어 상태 표현을 API enum 값으로 변환한다.

        if "완료" in message:
            return "done"
        if "진행중" in message or "진행 중" in message:
            return "doing"
        return "todo"

    def _find_matching_todo(self, message: str):
        """메시지와 토큰을 공유하는 첫 번째 ToDo를 선택한다."""
        # 명령어 토큰을 제외한 단어로 기존 ToDo 중 가장 가까운 항목을 찾는다.

        command_words = {"삭제", "지워", "제거", "진행중", "진행", "완료", "변경", "바꿔", "업무를", "업무"}
        tokens = [token for token in re.split(r"\s+", message) if token and token not in command_words]
        todos = self.repository.list_todos()
        for todo in todos:
            if any(token in todo.title or token in todo.description for token in tokens):
                return todo
        return todos[0] if todos else None

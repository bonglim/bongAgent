"""자연어 ToDo 생성, 수정, 삭제 sub-agent."""

from __future__ import annotations

import re

from ..models import AssistantCommandResponse, Todo, TodoCreate, TodoUpdate
from ..repository import JsonRepository
from .shared import AgentContext, compact_title, contains_any


class TodoManagementAgent:
    """자연어 ToDo 생성, 수정, 삭제 명령을 처리한다."""

    DOMAIN_WORDS = ["todo", "ToDo", "할일", "업무", "일정", "작업"]
    QUERY_WORDS = ["목록", "조회", "보여", "확인", "찾아", "검색", "내용", "상세", "뭐", "무엇", "어떤", "어때", "있어", "있나", "있니", "알려", "해야", "할까"]
    PRIORITY_FILTERS = {
        "high": ["high", "높음", "높은", "중요", "긴급"],
        "medium": ["medium", "보통", "중간"],
        "low": ["low", "낮음", "낮은"],
    }
    STATUS_FILTERS = {
        "done": ["완료", "끝난"],
        "doing": ["진행중", "진행 중", "하는중"],
        "todo": ["할일", "해야", "todo", "ToDo"],
    }

    def __init__(self, repository: JsonRepository) -> None:
        """ToDo 생성/수정/삭제에 사용할 repository를 보관한다."""

        self.repository = repository

    def can_handle(self, context: AgentContext) -> bool:
        """ToDo 관련 조회, 생성, 수정, 삭제 키워드가 있는지 확인한다."""

        message = context.message
        return self._is_delete(message) or self._is_update(message) or self._is_query(message) or self._is_create(message)

    def handle(self, context: AgentContext) -> AssistantCommandResponse:
        """삭제, 수정, 조회, 생성 순서로 ToDo 명령을 실행한다."""

        message = context.message
        if self._is_delete(message):
            return self._delete_todo(message)
        if self._is_update(message):
            return self._update_todo(message)
        if self._is_query(message):
            return self._query_todos(message)
        return self._create_todo(message)

    def _is_create(self, message: str) -> bool:
        """자주 쓰는 한국어 명령 키워드로 ToDo 생성 요청을 감지한다."""

        return contains_any(message, ["추가", "등록"]) or (
            contains_any(message, ["할일", "todo", "ToDo"]) and not self._is_query(message)
        )

    def _is_query(self, message: str) -> bool:
        """ToDo 데이터를 참고해 답해야 하는 질문인지 확인한다."""

        return contains_any(message, self.DOMAIN_WORDS) and contains_any(message, self.QUERY_WORDS)

    def _is_update(self, message: str) -> bool:
        """한국어 상태 변경 표현으로 ToDo 수정 요청을 감지한다."""

        if self._is_query(message) and not contains_any(message, ["변경", "바꿔"]):
            return False
        return contains_any(message, ["진행중", "진행 중", "완료", "할일로", "변경", "바꿔"])

    def _is_delete(self, message: str) -> bool:
        """한국어 삭제 표현으로 ToDo 삭제 요청을 감지한다."""

        return contains_any(message, ["삭제", "지워", "제거"])

    def _create_todo(self, message: str) -> AssistantCommandResponse:
        """자연어 문장에서 ToDo 초안을 추출하고 즉시 생성한다."""

        title = self._extract_title(message)
        due_date = self._extract_due_text(message)
        priority = "high" if contains_any(message, ["중요", "긴급", "오늘"]) else "medium"
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
        """가장 가까운 ToDo를 찾아 삭제한다."""

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

    def _query_todos(self, command: str) -> AssistantCommandResponse:
        """내부 tool 함수처럼 ToDo 데이터를 조건별로 조회하고 요약한다."""

        todos = self._filter_todos(command, self.repository.list_todos())
        if not todos:
            return AssistantCommandResponse(
                intent="query_todos",
                reply="조건에 맞는 ToDo를 찾지 못했습니다.",
                result={"todos": []},
                todos=self.repository.list_todos(),
            )
        detail_mode = contains_any(command, ["내용", "상세", "자세히"]) or len(todos) == 1
        reply = self._format_todo_detail_reply(todos) if detail_mode else self._format_todo_list_reply(todos)
        return AssistantCommandResponse(
            intent="query_todos",
            reply=reply,
            result={"todos": [todo.model_dump(mode="json") for todo in todos]},
            todos=self.repository.list_todos(),
        )

    def _extract_title(self, message: str) -> str:
        """흔한 명령어 표현을 제거해 간결한 ToDo 제목을 만든다."""

        return compact_title(message, ["추가해줘", "추가", "등록해줘", "등록", "할일로", "ToDo로", "todo로"], "새 업무")

    def _extract_due_text(self, message: str) -> str:
        """표시에 사용할 간단한 한국어 날짜/시간 표현을 추출한다."""

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

        if "완료" in message:
            return "done"
        if "진행중" in message or "진행 중" in message:
            return "doing"
        return "todo"

    def _find_matching_todo(self, message: str) -> Todo | None:
        """메시지와 토큰을 공유하는 첫 번째 ToDo를 선택한다."""

        command_words = {"삭제", "지워", "제거", "진행중", "진행", "완료", "변경", "바꿔", "업무를", "업무"} | set(self.QUERY_WORDS)
        tokens = [token for token in re.split(r"\s+", message) if token and token not in command_words]
        todos = self.repository.list_todos()
        for todo in todos:
            if any(token in todo.title or token in todo.description for token in tokens):
                return todo
        return todos[0] if todos else None

    def _filter_todos(self, command: str, todos: list[Todo]) -> list[Todo]:
        """명령문에서 상태, 우선순위, 검색어를 추출해 ToDo 목록을 좁힌다."""

        priority = self._extract_priority_filter(command)
        status = self._extract_status_filter(command)
        tokens = self._extract_search_tokens(command)
        filtered = [
            todo
            for todo in todos
            if (not priority or todo.priority == priority) and (not status or todo.status == status)
        ]
        if not tokens:
            return filtered
        return [
            todo
            for todo in filtered
            if any(token in f"{todo.title} {todo.description} {todo.due_date} {todo.source}" for token in tokens)
        ]

    def _extract_priority_filter(self, command: str) -> str | None:
        """채팅 문장에 포함된 우선순위 표현을 priority 값으로 변환한다."""

        for priority, words in self.PRIORITY_FILTERS.items():
            if contains_any(command, words):
                return priority
        return None

    def _extract_status_filter(self, command: str) -> str | None:
        """채팅 문장에 포함된 상태 표현을 status 값으로 변환한다."""

        for status, words in self.STATUS_FILTERS.items():
            if contains_any(command, words):
                return status
        return None

    def _extract_search_tokens(self, command: str) -> list[str]:
        """ToDo 조회 명령에서 도메인/동작 키워드를 제외한 검색어를 뽑는다."""

        command_words = set(self.DOMAIN_WORDS + self.QUERY_WORDS + ["해줘", "줘", "중", "관련", "대한", "있는", "오늘", "내일"])
        priority_words = {word for words in self.PRIORITY_FILTERS.values() for word in words}
        status_words = {word for words in self.STATUS_FILTERS.values() for word in words}
        raw_tokens = re.split(r"[\s,./:;!?()]+", command)
        return [
            token
            for token in raw_tokens
            if len(token) >= 2
            and not any(word in token for word in command_words)
            and not any(word in token for word in priority_words)
            and not any(word in token for word in status_words)
        ]

    def _format_todo_list_reply(self, todos: list[Todo]) -> str:
        """여러 ToDo를 채팅창에서 읽기 쉬운 목록 형태로 만든다."""

        rows = [
            f"{index}. [{todo.status}/{todo.priority}] {todo.title} - 마감: {todo.due_date or '미정'}"
            for index, todo in enumerate(todos[:6], start=1)
        ]
        suffix = f"\n외 {len(todos) - 6}건이 더 있습니다." if len(todos) > 6 else ""
        return f"조건에 맞는 ToDo {len(todos)}건입니다.\n" + "\n".join(rows) + suffix

    def _format_todo_detail_reply(self, todos: list[Todo]) -> str:
        """ToDo 제목, 상태, 우선순위, 설명을 포함한 상세 응답을 만든다."""

        rows = [
            (
                f"{index}. [{todo.status}/{todo.priority}] {todo.title}\n"
                f"   마감: {todo.due_date or '미정'} / 출처: {todo.source}\n"
                f"   설명: {todo.description or '설명 없음'}"
            )
            for index, todo in enumerate(todos[:4], start=1)
        ]
        suffix = f"\n외 {len(todos) - 4}건은 목록에서 확인해 주세요." if len(todos) > 4 else ""
        return f"ToDo 상세 {min(len(todos), 4)}건입니다.\n" + "\n".join(rows) + suffix

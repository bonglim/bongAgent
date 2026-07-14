"""Bong에이전트 MVP에서 사용하는 JSON 파일 기반 저장소.

이 모듈은 API 라우터와 assistant agent가 로컬 파일 저장 방식에 직접 의존하지
않도록 저장소 책임을 한곳에 모은다. 이후 데이터베이스 기반 구현으로 바꾸더라도
라우터와 agent의 호출 방식은 최대한 유지할 수 있게 하는 경계 역할을 한다.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import AftercareCustomer, AftercareCustomerCreate, AftercareCustomerUpdate, InternalMessage, InternalMessageCreate, InternalMessageUpdate, Todo, TodoCreate, TodoUpdate


class JsonRepository:
    """로컬 JSON 파일에서 MVP 데이터를 읽고 쓰는 저장소 클래스.

    ToDo, 사내쪽지, 사후관리 고객, undo/redo 히스토리를 모두 같은 데이터
    디렉터리 아래의 JSON 배열 파일로 관리한다. 쓰기 작업은 재진입 가능한 lock으로
    감싸, 한 요청 안에서 다른 저장소 메서드를 다시 호출해도 안전하게 동작한다.

    Example:
        ``JsonRepository(Path("backend/data")).list_customers()``는 저장된
        ``priority_rank``가 있으면 1~N 순서로, 없으면 high/medium/low 순서로 반환한다.
    """

    HISTORY_LIMIT = 30

    def __init__(self, data_dir: Path) -> None:
        """데이터 디렉터리와 쓰기 작업용 lock을 초기화한다.

        Args:
            data_dir: JSON 데이터 파일들이 위치한 디렉터리 경로.
        """
        # 데이터 디렉터리와 쓰기 잠금을 저장소 인스턴스에 보관한다.

        self.data_dir = data_dir
        self._lock = threading.RLock()

    def list_todos(self) -> list[Todo]:
        """전체 ToDo를 우선순위와 생성일 기준으로 정렬해 반환한다.

        Returns:
            우선순위가 높은 항목이 먼저 오고, 같은 우선순위에서는 먼저 생성된
            항목이 먼저 오는 ``Todo`` 목록.
        """
        # JSON에서 ToDo를 읽어 우선순위와 생성일 기준으로 정렬한다.

        todos = [Todo(**item) for item in self._read_json("todos.json")]
        return sorted(todos, key=lambda item: (self._priority_order(item.priority), item.created_at))

    def get_todo(self, todo_id: str) -> Todo | None:
        """id가 일치하는 단일 ToDo를 찾는다.

        Args:
            todo_id: 조회할 ToDo의 고유 id.

        Returns:
            일치하는 ``Todo``. 없으면 ``None``.
        """
        # 전체 ToDo 목록에서 id가 일치하는 항목 하나를 찾는다.

        return next((todo for todo in self.list_todos() if todo.id == todo_id), None)

    def create_todo(self, payload: TodoCreate, record_history: bool = True) -> Todo:
        """새 ToDo를 생성하고 JSON 저장소에 저장한다.

        Args:
            payload: 화면, agent, 원천 데이터에서 넘어온 생성 payload.
            record_history: ``True``이면 생성 전 상태를 undo 히스토리에 저장한다.

        Returns:
            id와 생성/수정 시각이 채워진 저장 완료 ``Todo``.
        """
        # 새 id와 타임스탬프를 붙인 뒤 JSON 파일에 ToDo를 추가한다.

        now = datetime.now()
        todo = Todo(id=f"todo_{uuid4().hex[:8]}", created_at=now, updated_at=now, **payload.model_dump())
        with self._lock:
            if record_history:
                self._save_history("create_todo", f"'{todo.title}' ToDo 생성 전")
            rows = self._read_json("todos.json")
            rows.append(todo.model_dump(mode="json"))
            self._write_json("todos.json", rows)
        return todo

    def update_todo(self, todo_id: str, payload: TodoUpdate) -> Todo | None:
        """ToDo 일부 필드만 수정하고 수정된 레코드를 반환한다.

        Args:
            todo_id: 수정할 ToDo id.
            payload: 설정된 필드만 반영할 부분 수정 payload.

        Returns:
            수정된 ``Todo``. 대상 id가 없으면 ``None``.
        """
        # 전달된 필드만 기존 ToDo에 반영하고 수정 시각을 갱신한다.

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return self.get_todo(todo_id)
        with self._lock:
            rows = self._read_json("todos.json")
            for row in rows:
                if row["id"] == todo_id:
                    self._save_history("update_todo", f"'{row['title']}' ToDo 수정 전")
                    row.update(updates)
                    row["updated_at"] = datetime.now().isoformat()
                    self._write_json("todos.json", rows)
                    return Todo(**row)
        return None

    def delete_todo(self, todo_id: str) -> bool:
        """ToDo를 삭제하고 참조 중이던 mock 원천 레코드의 연결을 해제한다.

        Args:
            todo_id: 삭제할 ToDo id.

        Returns:
            삭제 대상이 존재해 실제 삭제가 수행되면 ``True``.
        """
        # ToDo를 제거하고 연결된 mock 원천 데이터의 링크를 해제한다.

        with self._lock:
            rows = self._read_json("todos.json")
            deleted = next((row for row in rows if row["id"] == todo_id), None)
            if not deleted:
                return False
            self._save_history("delete_todo", f"'{deleted['title']}' ToDo 삭제 전")
            kept = [row for row in rows if row["id"] != todo_id]
            self._write_json("todos.json", kept)
            self._unlink_source("messages.json", todo_id)
            self._unlink_source("customers.json", todo_id)
            return True

    def list_history(self) -> dict:
        """전체 스냅샷을 제외한 undo/redo 히스토리 메타데이터를 반환한다.

        Returns:
            UI 표시용 ``undo``와 ``redo`` 목록을 담은 dictionary.
        """
        # 브라우저에는 화면 표시용 요약만 내려주고 전체 스냅샷은 숨긴다.

        with self._lock:
            return {
                "undo": self._public_history("history.json"),
                "redo": self._public_history("redo.json"),
            }

    def undo(self) -> tuple[str, list[Todo]]:
        """가장 최근 저장된 스냅샷으로 복구하고 현재 상태는 redo에 보관한다.

        Returns:
            사용자 안내 메시지와 복구 후 ToDo 목록.
        """
        # 마지막 변경 전 상태로 되돌리고 현재 상태는 redo 스택에 저장한다.

        with self._lock:
            history = self._read_json("history.json")
            if not history:
                return "되돌릴 변경이 없습니다.", self.list_todos()
            record = history.pop()
            self._write_json("history.json", history)
            self._push_history_record(
                "redo.json",
                "redo",
                f"{record['summary']} 되돌리기 전",
                self._capture_state(),
            )
            self._restore_state(record["state"])
            return f"{record['summary']} 상태로 되돌렸습니다.", self.list_todos()

    def redo(self) -> tuple[str, list[Todo]]:
        """가장 최근 redo 스냅샷을 복구하고 현재 상태는 undo에 보관한다.

        Returns:
            사용자 안내 메시지와 복구 후 ToDo 목록.
        """
        # 방금 되돌린 변경을 다시 적용할 수 있도록 undo 스택과 redo 스택을 맞바꾼다.

        with self._lock:
            redo = self._read_json("redo.json")
            if not redo:
                return "다시 실행할 변경이 없습니다.", self.list_todos()
            record = redo.pop()
            self._write_json("redo.json", redo)
            self._push_history_record(
                "history.json",
                "undo",
                f"{record['summary']} 다시 실행 전",
                self._capture_state(),
            )
            self._restore_state(record["state"])
            return "최근 변경을 다시 실행했습니다.", self.list_todos()

    def restore_history(self, history_id: str) -> tuple[bool, str, list[Todo]]:
        """지정한 히스토리 id의 스냅샷으로 업무판을 복구한다.

        Args:
            history_id: 복구할 히스토리 레코드 id.

        Returns:
            성공 여부, 사용자 안내 메시지, 복구 후 ToDo 목록.
        """
        # 히스토리 모달에서 선택한 시점으로 이동한다.

        with self._lock:
            history = self._read_json("history.json")
            record = next((row for row in history if row["id"] == history_id), None)
            if not record:
                return False, "선택한 히스토리를 찾을 수 없습니다.", self.list_todos()
            self._push_history_record(
                "history.json",
                "restore",
                f"{record['summary']} 이동 전",
                self._capture_state(),
            )
            self._write_json("redo.json", [])
            self._restore_state(record["state"])
            return True, f"{record['summary']} 시점으로 이동했습니다.", self.list_todos()

    def list_messages(self) -> list[InternalMessage]:
        """mock 사내쪽지를 저장된 상세 순위와 우선순위 순서로 반환한다."""
        # mock 사내쪽지를 읽어 우선순위 순서로 반환한다.

        messages = [InternalMessage(**item) for item in self._read_json("messages.json")]
        return sorted(
            messages,
            key=lambda item: (
                item.priority_rank if item.priority_rank is not None else 10_000 + self._priority_order(item.priority),
                self._priority_order(item.priority),
            ),
        )

    def create_message(self, payload: InternalMessageCreate) -> InternalMessage:
        """화면에서 입력한 사내쪽지를 JSON 저장소에 추가한다.

        Args:
            payload: 사내쪽지 등록 모달에서 전달된 생성 payload.

        Returns:
            id와 기본 상태가 채워진 저장 완료 ``InternalMessage``.
        """
        # 직접 등록한 사내쪽지는 아직 ToDo에 연결되지 않은 unread 상태로 저장한다.

        message = InternalMessage(id=f"message_{uuid4().hex[:8]}", status="unread", linked_todo_id=None, **payload.model_dump())
        with self._lock:
            self._save_history("create_message", f"'{message.title}' 사내쪽지 등록 전")
            rows = self._read_json("messages.json")
            rows.append(message.model_dump(mode="json"))
            self._write_json("messages.json", rows)
        return message

    def delete_message(self, message_id: str) -> bool:
        """사내쪽지를 삭제하고 연결된 ToDo의 원천 링크를 정리한다.

        Args:
            message_id: 삭제할 사내쪽지 id.

        Returns:
            삭제 대상이 존재해 실제 삭제가 수행되면 ``True``.
        """
        # 사내쪽지만 제거하고, 이미 만들어진 ToDo는 남기되 원천 연결 표시는 해제한다.

        with self._lock:
            messages = self._read_json("messages.json")
            deleted = next((row for row in messages if row["id"] == message_id), None)
            if not deleted:
                return False
            self._save_history("delete_message", f"'{deleted['title']}' 사내쪽지 삭제 전")
            self._write_json("messages.json", [row for row in messages if row["id"] != message_id])
            if deleted.get("linked_todo_id"):
                self._unlink_todo_source("message", message_id)
            return True

    def update_message(self, message_id: str, payload: InternalMessageUpdate) -> InternalMessage | None:
        """사내쪽지 일부 필드만 수정하고 수정된 레코드를 반환한다.

        Args:
            message_id: 수정할 사내쪽지 id.
            payload: 설정된 필드만 반영할 부분 수정 payload.

        Returns:
            수정된 ``InternalMessage``. 대상 id가 없으면 ``None``.
        """
        # 현재는 LLM 추천/사용자 클릭으로 바뀌는 priority만 부분 수정 대상으로 둔다.

        updates = payload.model_dump(exclude_none=True, exclude_unset=True)
        if not updates:
            return next((message for message in self.list_messages() if message.id == message_id), None)
        if "priority" in updates and "priority_rank" not in updates:
            updates.update({"priority_rank": None, "priority_reason": ""})
        with self._lock:
            rows = self._read_json("messages.json")
            for row in rows:
                if row["id"] == message_id:
                    row.update(updates)
                    self._write_json("messages.json", rows)
                    return InternalMessage(**row)
        return None

    def update_message_priorities(self, priorities: dict[str, str]) -> list[InternalMessage]:
        """여러 사내쪽지 우선순위를 한 번에 저장하고 변경된 목록을 반환한다.

        Args:
            priorities: 사내쪽지 id를 key, priority 값을 value로 갖는 mapping.

        Returns:
            우선순위가 변경된 ``InternalMessage`` 목록.
        """
        # LLM 추천 결과를 적용할 때 히스토리는 한 번만 저장해 undo 단위를 유지한다.

        allowed = {"high", "medium", "low"}
        clean_priorities = {message_id: priority for message_id, priority in priorities.items() if priority in allowed}
        if not clean_priorities:
            return []
        with self._lock:
            rows = self._read_json("messages.json")
            changed = False
            for row in rows:
                next_priority = clean_priorities.get(row["id"])
                if next_priority and row.get("priority") != next_priority:
                    if not changed:
                        self._save_history("update_message_priorities", "사내쪽지 우선순위 일괄 설정 전")
                    row["priority"] = next_priority
                    changed = True
            if changed:
                self._write_json("messages.json", rows)
        return self.list_messages()

    def update_message_priority_recommendations(self, recommendations: dict[str, dict]) -> list[InternalMessage]:
        """쪽지별 등급, 전체 순위, 조정 사유를 한 번에 저장한다."""

        return self._update_source_priority_recommendations(
            "messages.json", recommendations, "사내쪽지 우선순위 재조정 전"
        )

    def list_customers(self) -> list[AftercareCustomer]:
        """mock 사후관리 고객을 저장된 상세 순위와 우선순위 순서로 반환한다."""
        # mock 사후관리 고객을 읽어 우선순위 순서로 반환한다.

        customers = [AftercareCustomer(**item) for item in self._read_json("customers.json")]
        return sorted(
            customers,
            key=lambda item: (
                item.priority_rank if item.priority_rank is not None else 10_000 + self._priority_order(item.priority),
                self._priority_order(item.priority),
            ),
        )

    def create_customer(self, payload: AftercareCustomerCreate) -> AftercareCustomer:
        """화면에서 입력한 사후관리 고객을 JSON 저장소에 추가한다.

        Args:
            payload: 고객관리 등록 모달에서 전달된 생성 payload.

        Returns:
            id와 연결 초기값이 채워진 저장 완료 ``AftercareCustomer``.
        """
        # 직접 등록한 고객은 아직 ToDo에 연결되지 않은 상태로 저장한다.

        customer = AftercareCustomer(id=f"customer_{uuid4().hex[:8]}", linked_todo_id=None, **payload.model_dump())
        with self._lock:
            self._save_history("create_customer", f"'{customer.name}' 고객 등록 전")
            rows = self._read_json("customers.json")
            rows.append(customer.model_dump(mode="json"))
            self._write_json("customers.json", rows)
        return customer

    def delete_customer(self, customer_id: str) -> bool:
        """사후관리 고객을 삭제하고 연결된 ToDo의 원천 링크를 정리한다.

        Args:
            customer_id: 삭제할 고객 id.

        Returns:
            삭제 대상이 존재해 실제 삭제가 수행되면 ``True``.
        """
        # 고객 데이터만 제거하고, 이미 만들어진 ToDo는 남기되 원천 연결 표시는 해제한다.

        with self._lock:
            customers = self._read_json("customers.json")
            deleted = next((row for row in customers if row["id"] == customer_id), None)
            if not deleted:
                return False
            self._save_history("delete_customer", f"'{deleted['name']}' 고객 삭제 전")
            self._write_json("customers.json", [row for row in customers if row["id"] != customer_id])
            if deleted.get("linked_todo_id"):
                self._unlink_todo_source("customer", customer_id)
            return True

    def update_customer(self, customer_id: str, payload: AftercareCustomerUpdate) -> AftercareCustomer | None:
        """사후관리 고객 일부 필드만 수정하고 수정된 레코드를 반환한다.

        Args:
            customer_id: 수정할 사후관리 고객 id.
            payload: 설정된 필드만 반영할 부분 수정 payload.

        Returns:
            수정된 ``AftercareCustomer``. 대상 id가 없으면 ``None``.
        """
        # 사후관리 고객 패널의 별 아이콘 클릭으로 바뀌는 priority를 저장한다.

        updates = payload.model_dump(exclude_none=True, exclude_unset=True)
        if not updates:
            return next((customer for customer in self.list_customers() if customer.id == customer_id), None)
        if "priority" in updates and "priority_rank" not in updates:
            updates.update({"priority_rank": None, "priority_reason": ""})
        with self._lock:
            rows = self._read_json("customers.json")
            for row in rows:
                if row["id"] == customer_id:
                    row.update(updates)
                    self._write_json("customers.json", rows)
                    return AftercareCustomer(**row)
        return None

    def update_customer_priorities(self, priorities: dict[str, str]) -> list[AftercareCustomer]:
        """AI 추천으로 받은 여러 고객의 우선순위를 하나의 히스토리 단위로 저장한다.

        Args:
            priorities: 고객 id를 key, high/medium/low를 value로 갖는 mapping.

        Returns:
            추천 우선순위가 반영되어 높은 순서로 정렬된 전체 고객 목록.
        """

        allowed = {"high", "medium", "low"}
        clean_priorities = {customer_id: priority for customer_id, priority in priorities.items() if priority in allowed}
        if not clean_priorities:
            return self.list_customers()
        with self._lock:
            rows = self._read_json("customers.json")
            changed = False
            for row in rows:
                next_priority = clean_priorities.get(row["id"])
                if next_priority and row.get("priority") != next_priority:
                    if not changed:
                        self._save_history("update_customer_priorities", "사후관리 고객 AI 우선순위 추천 전")
                    row["priority"] = next_priority
                    changed = True
            if changed:
                self._write_json("customers.json", rows)
                linked_priorities = {
                    row["linked_todo_id"]: row["priority"]
                    for row in rows
                    if row.get("linked_todo_id") and row["id"] in clean_priorities
                }
                if linked_priorities:
                    todos = self._read_json("todos.json")
                    for todo in todos:
                        if todo["id"] in linked_priorities:
                            todo["priority"] = linked_priorities[todo["id"]]
                            todo["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._write_json("todos.json", todos)
        return self.list_customers()

    def update_customer_priority_recommendations(self, recommendations: dict[str, dict]) -> list[AftercareCustomer]:
        """고객별 등급, 전체 순위, 조정 사유를 한 번에 저장한다."""

        return self._update_source_priority_recommendations(
            "customers.json", recommendations, "사후관리 고객 우선순위 재조정 전"
        )

    def create_todo_from_message(self, message_id: str) -> tuple[Todo | None, str]:
        """사내쪽지를 ToDo로 전환하되 중복 연결을 방지한다.

        Args:
            message_id: ToDo로 전환할 사내쪽지 id.

        Returns:
            생성되었거나 이미 연결된 ``Todo``와 사용자 안내 메시지.
        """
        # 사내쪽지 내용을 ToDo payload로 변환하고 원천 레코드에 링크를 남긴다.

        with self._lock:
            messages = self._read_json("messages.json")
            message = next((row for row in messages if row["id"] == message_id), None)
            if not message:
                return None, "사내쪽지를 찾을 수 없습니다."
            if message.get("linked_todo_id"):
                existing = self.get_todo(message["linked_todo_id"])
                return existing, "이미 등록된 ToDo가 있습니다."
            self._save_history("create_from_message", f"'{message['title']}' 사내쪽지 ToDo 전환 전")
            todo = self.create_todo(
                TodoCreate(
                    title=message["title"],
                    description=message["body"],
                    priority=message["priority"],
                    due_date=message["received_at"],
                    source="message",
                    linked_type="message",
                    linked_id=message_id,
                ),
                record_history=False,
            )
            message["status"] = "todo_linked"
            message["linked_todo_id"] = todo.id
            self._write_json("messages.json", messages)
            return todo, "사내쪽지 기반 ToDo가 생성되었습니다."

    def create_todo_from_customer(self, customer_id: str) -> tuple[Todo | None, str]:
        """사후관리 고객 정보를 ToDo로 전환하되 중복 연결을 방지한다.

        Args:
            customer_id: ToDo로 전환할 고객 레코드 id.

        Returns:
            생성되었거나 이미 연결된 ``Todo``와 사용자 안내 메시지.
        """
        # 고객 사후관리 정보를 ToDo payload로 변환하고 고객 레코드에 링크를 남긴다.

        with self._lock:
            customers = self._read_json("customers.json")
            customer = next((row for row in customers if row["id"] == customer_id), None)
            if not customer:
                return None, "고객 정보를 찾을 수 없습니다."
            if customer.get("linked_todo_id"):
                existing = self.get_todo(customer["linked_todo_id"])
                return existing, "이미 등록된 ToDo가 있습니다."
            self._save_history("create_from_customer", f"'{customer['name']}' 고객 ToDo 전환 전")
            todo = self.create_todo(
                TodoCreate(
                    title=f"{customer['name']} 고객 {customer['recommended_action']}",
                    description=f"{customer['reason']} - {customer['detail']}",
                    priority=customer["priority"],
                    due_date=customer["scheduled_date"],
                    source="customer",
                    linked_type="customer",
                    linked_id=customer_id,
                ),
                record_history=False,
            )
            customer["linked_todo_id"] = todo.id
            self._write_json("customers.json", customers)
            return todo, "사후관리 고객 기반 ToDo가 생성되었습니다."

    def _update_source_priority_recommendations(
        self, filename: str, recommendations: dict[str, dict], history_summary: str
    ) -> list[InternalMessage] | list[AftercareCustomer]:
        """원천 레코드의 우선순위 등급·순번·사유를 원자적으로 갱신한다.

        추천 하나는 ``{"priority": "high", "rank": 1, "reason": "..."}``
        형태다. 첫 실제 변경 전에 스냅샷을 한 번만 저장해 전체 재정렬이 단일
        undo 작업으로 복원되며, 연결된 ToDo의 등급도 함께 동기화된다.
        """

        allowed = {"high", "medium", "low"}
        clean = {
            item_id: {
                "priority": item.get("priority"),
                "rank": item.get("rank"),
                "reason": str(item.get("reason", "")).strip(),
            }
            for item_id, item in recommendations.items()
            if item.get("priority") in allowed
            and isinstance(item.get("rank"), int)
            and item["rank"] >= 1
            and str(item.get("reason", "")).strip()
        }
        if not clean:
            return self.list_messages() if filename == "messages.json" else self.list_customers()

        with self._lock:
            rows = self._read_json(filename)
            changed = False
            for row in rows:
                item = clean.get(row["id"])
                if not item:
                    continue
                updates = {
                    "priority": item["priority"],
                    "priority_rank": item["rank"],
                    "priority_reason": item["reason"],
                }
                if any(row.get(key) != value for key, value in updates.items()):
                    if not changed:
                        self._save_history("update_source_priorities", history_summary)
                    row.update(updates)
                    changed = True
            if changed:
                self._write_json(filename, rows)
                linked_priorities = {
                    row["linked_todo_id"]: row["priority"]
                    for row in rows
                    if row.get("linked_todo_id") and row["id"] in clean
                }
                if linked_priorities:
                    todos = self._read_json("todos.json")
                    for todo in todos:
                        if todo["id"] in linked_priorities:
                            todo["priority"] = linked_priorities[todo["id"]]
                            todo["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._write_json("todos.json", todos)
        return self.list_messages() if filename == "messages.json" else self.list_customers()

    def _read_json(self, filename: str) -> list[dict]:
        """설정된 데이터 디렉터리에서 JSON 배열 파일을 읽는다."""
        # 파일이 없으면 빈 목록을 반환해 초기 실행을 안전하게 처리한다.

        path = self.data_dir / filename
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, filename: str, rows: list[dict]) -> None:
        """JSON 배열을 UTF-8과 안정적인 들여쓰기 형식으로 저장한다."""
        # UTF-8과 들여쓰기를 유지해 사람이 읽기 쉬운 JSON으로 저장한다.

        path = self.data_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def _capture_state(self) -> dict:
        """복구 가능한 단기 기억으로 대시보드 JSON 파일 상태를 캡처한다."""
        # 업무판, 쪽지, 고객 연결 상태를 함께 저장해야 되돌리기가 일관된다.

        return {
            "todos": self._read_json("todos.json"),
            "messages": self._read_json("messages.json"),
            "customers": self._read_json("customers.json"),
        }

    def _restore_state(self, state: dict) -> None:
        """저장된 스냅샷에서 대시보드 JSON 파일들을 복구한다."""
        # 스냅샷에 없는 파일은 빈 목록으로 복구해 JSON 구조를 유지한다.

        self._write_json("todos.json", state.get("todos", []))
        self._write_json("messages.json", state.get("messages", []))
        self._write_json("customers.json", state.get("customers", []))

    def _save_history(self, action: str, summary: str) -> None:
        """사용자에게 보이는 새 변경을 수행하기 전 현재 상태를 저장한다."""
        # 새 변경이 생기면 기존 redo는 더 이상 같은 미래가 아니므로 비운다.

        self._push_history_record("history.json", action, summary, self._capture_state())
        self._write_json("redo.json", [])

    def _push_history_record(self, filename: str, action: str, summary: str, state: dict) -> None:
        """히스토리 스택 파일에 개수 제한이 있는 기록을 추가한다."""
        # 최근 기록만 유지해 로컬 JSON 저장소가 계속 작게 유지되게 한다.

        rows = self._read_json(filename)
        rows.append(
            {
                "id": f"history_{uuid4().hex[:10]}",
                "created_at": datetime.now().isoformat(),
                "action": action,
                "summary": summary,
                "state": state,
            }
        )
        self._write_json(filename, rows[-self.HISTORY_LIMIT :])

    def _public_history(self, filename: str) -> list[dict]:
        """UI로 보내기 전에 히스토리 기록에서 실제 스냅샷을 제거한다."""
        # 최신 기록이 먼저 보이도록 역순으로 반환한다.

        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "action": row["action"],
                "summary": row["summary"],
            }
            for row in reversed(self._read_json(filename))
        ]

    def _unlink_source(self, filename: str, todo_id: str) -> None:
        """삭제된 ToDo id를 연결 중이던 mock 원천 레코드에서 제거한다."""
        # 삭제된 ToDo id를 참조하던 쪽지/고객 연결 상태를 초기화한다.

        rows = self._read_json(filename)
        changed = False
        for row in rows:
            if row.get("linked_todo_id") == todo_id:
                row["linked_todo_id"] = None
                if filename == "messages.json":
                    row["status"] = "unread"
                changed = True
        if changed:
            self._write_json(filename, rows)

    def _unlink_todo_source(self, linked_type: str, linked_id: str) -> None:
        """삭제된 원천 레코드를 참조하던 ToDo의 연결 정보를 제거한다."""
        # 원천 데이터가 사라졌을 때 업무 카드는 유지하되 더 이상 연결됨으로 보지 않는다.

        rows = self._read_json("todos.json")
        changed = False
        for row in rows:
            if row.get("linked_type") == linked_type and row.get("linked_id") == linked_id:
                row["linked_type"] = None
                row["linked_id"] = None
                row["updated_at"] = datetime.now().isoformat()
                changed = True
        if changed:
            self._write_json("todos.json", rows)

    def _priority_order(self, priority: str) -> int:
        """우선순위 문자열을 안정적으로 정렬 가능한 숫자로 변환한다."""
        # 문자열 우선순위를 정렬 가능한 숫자 값으로 바꾼다.

        return {"high": 0, "medium": 1, "low": 2}.get(priority, 9)

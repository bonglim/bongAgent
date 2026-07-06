"""JSON-backed repository for the Bong에이전트 MVP.

The repository isolates storage details from the API and agent layers. Later,
this module can be replaced by a database-backed implementation while keeping
route handlers mostly unchanged.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .models import AftercareCustomer, InternalMessage, Todo, TodoCreate, TodoUpdate


class JsonRepository:
    """Read and write MVP data from local JSON files."""

    def __init__(self, data_dir: Path):
        """Store the data directory and create a lock for write operations."""

        self.data_dir = data_dir
        self._lock = threading.RLock()

    def list_todos(self) -> list[Todo]:
        """Return all ToDos sorted by priority and creation date."""

        todos = [Todo(**item) for item in self._read_json("todos.json")]
        return sorted(todos, key=lambda item: (self._priority_order(item.priority), item.created_at))

    def get_todo(self, todo_id: str) -> Todo | None:
        """Find a single ToDo by id."""

        return next((todo for todo in self.list_todos() if todo.id == todo_id), None)

    def create_todo(self, payload: TodoCreate) -> Todo:
        """Create a ToDo and persist it to JSON storage."""

        now = datetime.now()
        todo = Todo(id=f"todo_{uuid4().hex[:8]}", created_at=now, updated_at=now, **payload.model_dump())
        with self._lock:
            rows = self._read_json("todos.json")
            rows.append(todo.model_dump(mode="json"))
            self._write_json("todos.json", rows)
        return todo

    def update_todo(self, todo_id: str, payload: TodoUpdate) -> Todo | None:
        """Patch a ToDo and return the updated record."""

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return self.get_todo(todo_id)
        with self._lock:
            rows = self._read_json("todos.json")
            for row in rows:
                if row["id"] == todo_id:
                    row.update(updates)
                    row["updated_at"] = datetime.now().isoformat()
                    self._write_json("todos.json", rows)
                    return Todo(**row)
        return None

    def delete_todo(self, todo_id: str) -> bool:
        """Delete a ToDo and unlink any mock source records that referenced it."""

        with self._lock:
            rows = self._read_json("todos.json")
            kept = [row for row in rows if row["id"] != todo_id]
            if len(kept) == len(rows):
                return False
            self._write_json("todos.json", kept)
            self._unlink_source("messages.json", todo_id)
            self._unlink_source("customers.json", todo_id)
            return True

    def list_messages(self) -> list[InternalMessage]:
        """Return mock internal messages sorted by priority."""

        messages = [InternalMessage(**item) for item in self._read_json("messages.json")]
        return sorted(messages, key=lambda item: self._priority_order(item.priority))

    def list_customers(self) -> list[AftercareCustomer]:
        """Return mock aftercare customers sorted by priority."""

        customers = [AftercareCustomer(**item) for item in self._read_json("customers.json")]
        return sorted(customers, key=lambda item: self._priority_order(item.priority))

    def create_todo_from_message(self, message_id: str) -> tuple[Todo | None, str]:
        """Create a ToDo from a message while preventing duplicate links."""

        with self._lock:
            messages = self._read_json("messages.json")
            message = next((row for row in messages if row["id"] == message_id), None)
            if not message:
                return None, "사내쪽지를 찾을 수 없습니다."
            if message.get("linked_todo_id"):
                existing = self.get_todo(message["linked_todo_id"])
                return existing, "이미 등록된 ToDo가 있습니다."
            todo = self.create_todo(
                TodoCreate(
                    title=message["title"],
                    description=message["body"],
                    priority=message["priority"],
                    due_date=message["received_at"],
                    source="message",
                    linked_type="message",
                    linked_id=message_id,
                )
            )
            message["status"] = "todo_linked"
            message["linked_todo_id"] = todo.id
            self._write_json("messages.json", messages)
            return todo, "사내쪽지 기반 ToDo가 생성되었습니다."

    def create_todo_from_customer(self, customer_id: str) -> tuple[Todo | None, str]:
        """Create a ToDo from an aftercare customer while preventing duplicates."""

        with self._lock:
            customers = self._read_json("customers.json")
            customer = next((row for row in customers if row["id"] == customer_id), None)
            if not customer:
                return None, "고객 정보를 찾을 수 없습니다."
            if customer.get("linked_todo_id"):
                existing = self.get_todo(customer["linked_todo_id"])
                return existing, "이미 등록된 ToDo가 있습니다."
            todo = self.create_todo(
                TodoCreate(
                    title=f"{customer['name']} 고객 {customer['recommended_action']}",
                    description=f"{customer['reason']} - {customer['detail']}",
                    priority=customer["priority"],
                    due_date=customer["scheduled_date"],
                    source="customer",
                    linked_type="customer",
                    linked_id=customer_id,
                )
            )
            customer["linked_todo_id"] = todo.id
            self._write_json("customers.json", customers)
            return todo, "사후관리 고객 기반 ToDo가 생성되었습니다."

    def _read_json(self, filename: str) -> list[dict]:
        """Read a JSON array from the configured data directory."""

        path = self.data_dir / filename
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, filename: str, rows: list[dict]) -> None:
        """Write a JSON array using stable UTF-8 formatting."""

        path = self.data_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def _unlink_source(self, filename: str, todo_id: str) -> None:
        """Remove a deleted ToDo id from linked mock source records."""

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

    def _priority_order(self, priority: str) -> int:
        """Convert a priority label into a stable sort order."""

        return {"high": 0, "medium": 1, "low": 2}.get(priority, 9)

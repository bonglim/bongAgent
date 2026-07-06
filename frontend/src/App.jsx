// Main React application for the Bong에이전트 MVP dashboard.
import React, { useEffect, useMemo, useState } from "react";
import { DndContext, PointerSensor, useDroppable, useSensor, useSensors } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { Check, Loader2, MessageSquareText, PanelRightClose, PanelRightOpen, Plus, RefreshCw, Send, Settings, Trash2, UserRound } from "lucide-react";
import {
  createTodo,
  createTodoFromCustomer,
  createTodoFromMessage,
  deleteTodo,
  fetchCustomers,
  fetchMessages,
  fetchTodos,
  sendAssistantCommand,
  updateTodo,
} from "./api.js";

const STATUS_COLUMNS = [
  { id: "todo", label: "할일" },
  { id: "doing", label: "진행중" },
  { id: "done", label: "완료" },
];

const PRIORITY_LABELS = {
  high: "높음",
  medium: "보통",
  low: "낮음",
};

const SOURCE_LABELS = {
  manual: "직접 입력",
  message: "사내쪽지",
  customer: "사후관리",
  assistant: "AI 명령",
};

// Format the header date in a compact Korean workplace style.
function formatToday() {
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "full" }).format(new Date());
}

// Group ToDos by Kanban status for rendering columns.
function groupTodos(todos) {
  return STATUS_COLUMNS.reduce((groups, column) => {
    groups[column.id] = todos.filter((todo) => todo.status === column.id);
    return groups;
  }, {});
}

// Build the default modal state for creating a new manual ToDo.
function emptyDraft() {
  return {
    title: "",
    description: "",
    status: "todo",
    priority: "medium",
    due_date: "오늘",
    source: "manual",
  };
}

// Root component orchestrates dashboard state, API calls, and user feedback.
export default function App() {
  const [todos, setTodos] = useState([]);
  const [messages, setMessages] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [selectedTodo, setSelectedTodo] = useState(null);
  const [draft, setDraft] = useState(emptyDraft());
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isChatVisible, setIsChatVisible] = useState(true);
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState([
    { role: "assistant", text: "오늘 처리할 업무를 자연어로 입력해 주세요." },
  ]);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));
  const groupedTodos = useMemo(() => groupTodos(todos), [todos]);

  // Load dashboard data once when the app starts.
  useEffect(() => {
    refreshDashboard();
  }, []);

  // Fetch all dashboard data in parallel and show one user-facing error if needed.
  async function refreshDashboard() {
    setLoading(true);
    try {
      const [todoRows, messageRows, customerRows] = await Promise.all([fetchTodos(), fetchMessages(), fetchCustomers()]);
      setTodos(todoRows);
      setMessages(messageRows);
      setCustomers(customerRows);
      setNotice("대시보드를 새로고침했습니다.");
    } catch (error) {
      setNotice(error.message);
    } finally {
      setLoading(false);
    }
  }

  // Persist a dragged ToDo status and optimistically update the board.
  async function handleDragEnd(event) {
    const todoId = event.active?.id;
    const overId = event.over?.id;
    const overTodo = todos.find((todo) => todo.id === overId);
    const nextStatus = overTodo?.status || overId;
    const dragged = todos.find((todo) => todo.id === todoId);
    if (!dragged || !STATUS_COLUMNS.some((column) => column.id === nextStatus) || dragged.status === nextStatus) return;
    const previous = todos;
    setTodos((current) => current.map((todo) => (todo.id === todoId ? { ...todo, status: nextStatus } : todo)));
    try {
      await updateTodo(todoId, { status: nextStatus });
      setNotice("ToDo 상태를 변경했습니다.");
    } catch (error) {
      setTodos(previous);
      setNotice(error.message);
    }
  }

  // Open the modal for a new manual ToDo.
  function openCreateModal() {
    setSelectedTodo(null);
    setDraft(emptyDraft());
    setIsModalOpen(true);
  }

  // Open the modal with a copy of the selected ToDo.
  function openEditModal(todo) {
    setSelectedTodo(todo);
    setDraft({ ...todo });
    setIsModalOpen(true);
  }

  // Save either a new ToDo or edits to an existing ToDo.
  async function saveTodo() {
    try {
      if (selectedTodo) {
        const updated = await updateTodo(selectedTodo.id, draft);
        setTodos((current) => current.map((todo) => (todo.id === updated.id ? updated : todo)));
        setNotice("ToDo를 수정했습니다.");
      } else {
        const created = await createTodo(draft);
        setTodos((current) => [created, ...current]);
        setNotice("ToDo를 생성했습니다.");
      }
      setIsModalOpen(false);
    } catch (error) {
      setNotice(error.message);
    }
  }

  // Delete the currently selected ToDo after browser confirmation.
  async function removeSelectedTodo() {
    if (!selectedTodo || !window.confirm("이 ToDo를 삭제하시겠습니까?")) return;
    try {
      await deleteTodo(selectedTodo.id);
      setTodos((current) => current.filter((todo) => todo.id !== selectedTodo.id));
      setIsModalOpen(false);
      await refreshDashboard();
      setNotice("ToDo를 삭제했습니다.");
    } catch (error) {
      setNotice(error.message);
    }
  }

  // Convert a priority message into a ToDo and refresh linked states.
  async function addMessageTodo(id) {
    try {
      const todo = await createTodoFromMessage(id);
      setTodos((current) => [todo, ...current.filter((item) => item.id !== todo.id)]);
      await refreshDashboard();
      setNotice("사내쪽지를 ToDo로 전환했습니다.");
    } catch (error) {
      setNotice(error.message);
    }
  }

  // Convert an aftercare customer into a ToDo and refresh linked states.
  async function addCustomerTodo(id) {
    try {
      const todo = await createTodoFromCustomer(id);
      setTodos((current) => [todo, ...current.filter((item) => item.id !== todo.id)]);
      await refreshDashboard();
      setNotice("사후관리 고객을 ToDo로 전환했습니다.");
    } catch (error) {
      setNotice(error.message);
    }
  }

  // Submit the chat input to the assistant and merge command results into UI state.
  async function submitChat(event) {
    event.preventDefault();
    const message = chatInput.trim();
    if (!message) return;
    setChatInput("");
    setChatMessages((current) => [...current, { role: "user", text: message }]);
    try {
      const response = await sendAssistantCommand(message);
      setChatMessages((current) => [...current, { role: "assistant", text: response.reply }]);
      if (response.todos) setTodos(response.todos);
      setNotice(response.reply);
    } catch (error) {
      setChatMessages((current) => [...current, { role: "assistant", text: error.message }]);
      setNotice(error.message);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <strong className="brand">Bong에이전트</strong>
          <span className="page-title">오늘의 업무 대시보드</span>
        </div>
        <div className="header-meta">
          <span>{formatToday()}</span>
          <span>김보람 · WM영업부</span>
          <button className="icon-button" onClick={refreshDashboard} title="새로고침">
            {loading ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
          </button>
          <button className="icon-button" title="설정">
            <Settings size={18} />
          </button>
        </div>
      </header>

      <main className={isChatVisible ? "dashboard-layout" : "dashboard-layout chat-hidden"}>
        <section className="work-area">
          <div className="section-heading">
            <div>
              <h1>ToDo Kanban</h1>
              <p>오늘의 업무를 상태별로 정리합니다.</p>
            </div>
            <div className="section-actions">
              <button className="icon-button" onClick={() => setIsChatVisible((visible) => !visible)} title={isChatVisible ? "채팅 숨김" : "채팅 보기"} aria-label={isChatVisible ? "채팅 숨김" : "채팅 보기"}>
                {isChatVisible ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
              </button>
              <button className="primary-button" onClick={openCreateModal}>
                <Plus size={17} /> ToDo
              </button>
            </div>
          </div>

          <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
            <div className="kanban-grid">
              {STATUS_COLUMNS.map((column) => (
                <KanbanColumn key={column.id} column={column} todos={groupedTodos[column.id] || []} onCardClick={openEditModal} />
              ))}
            </div>
          </DndContext>

          <div className="priority-grid">
            <PriorityPanel
              title="우선순위 사내쪽지"
              icon={<MessageSquareText size={18} />}
              items={messages}
              emptyText="처리할 사내쪽지가 없습니다."
              renderItem={(item) => (
                <SourceItem
                  key={item.id}
                  title={item.title}
                  meta={`${item.sender} · ${item.received_at}`}
                  description={item.body}
                  priority={item.priority}
                  linked={Boolean(item.linked_todo_id)}
                  onAdd={() => addMessageTodo(item.id)}
                />
              )}
            />
            <PriorityPanel
              title="우선순위 사후관리 고객"
              icon={<UserRound size={18} />}
              items={customers}
              emptyText="오늘 관리할 고객이 없습니다."
              renderItem={(item) => (
                <SourceItem
                  key={item.id}
                  title={`${item.name} 고객`}
                  meta={`${item.reason} · ${item.scheduled_date}`}
                  description={item.recommended_action}
                  priority={item.priority}
                  linked={Boolean(item.linked_todo_id)}
                  onAdd={() => addCustomerTodo(item.id)}
                />
              )}
            />
          </div>
        </section>

        {isChatVisible && <aside className="chat-panel">
          <div className="chat-header">
            <h2>GPT 채팅 / 자연어 명령</h2>
            <span>규칙 기반 MVP</span>
          </div>
          <div className="chat-messages">
            {chatMessages.map((message, index) => (
              <div className={`chat-bubble ${message.role}`} key={`${message.role}-${index}`}>
                {message.text}
              </div>
            ))}
          </div>
          <div className="suggestions">
            <button onClick={() => setChatInput("오늘 오후 3시에 김민수 고객 전화 추가해줘")}>전화 추가</button>
            <button onClick={() => setChatInput("김민수 고객 업무를 진행중으로 바꿔줘")}>상태 변경</button>
            <button onClick={() => setChatInput("고객에게 보낼 만기 안내 문구 작성해줘")}>문구 작성</button>
          </div>
          <form className="chat-form" onSubmit={submitChat}>
            <input value={chatInput} onChange={(event) => setChatInput(event.target.value)} placeholder="업무 추가, 상태 변경, 문구 작성..." />
            <button className="send-button" type="submit" title="전송">
              <Send size={18} />
            </button>
          </form>
        </aside>}
      </main>

      {notice && <div className="toast">{notice}</div>}
      {isModalOpen && (
        <TodoModal
          draft={draft}
          setDraft={setDraft}
          selectedTodo={selectedTodo}
          onClose={() => setIsModalOpen(false)}
          onSave={saveTodo}
          onDelete={removeSelectedTodo}
        />
      )}
    </div>
  );
}

// Render one droppable Kanban column with a sortable context.
function KanbanColumn({ column, todos, onCardClick }) {
  const { setNodeRef, isOver } = useDroppable({ id: column.id });
  return (
    <section className={`kanban-column ${isOver ? "is-over" : ""}`} ref={setNodeRef}>
      <div className="column-title">
        <h2>{column.label}</h2>
        <span>{todos.length}</span>
      </div>
      <SortableContext items={todos.map((todo) => todo.id)} strategy={verticalListSortingStrategy}>
        <div className="card-list">
          {todos.length === 0 && <div className="empty-state">오늘 등록된 업무가 없습니다.</div>}
          {todos.map((todo) => (
            <TodoCard key={todo.id} todo={todo} onClick={() => onCardClick(todo)} />
          ))}
        </div>
      </SortableContext>
    </section>
  );
}

// Render a draggable ToDo card with priority and source badges.
function TodoCard({ todo, onClick }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: todo.id });
  const style = { transform: CSS.Transform.toString(transform), transition };
  return (
    <article className={`todo-card priority-${todo.priority} ${isDragging ? "dragging" : ""}`} ref={setNodeRef} style={style} {...attributes} {...listeners} onClick={onClick}>
      <div className="card-topline">
        <span className={`priority-dot ${todo.priority}`}>{PRIORITY_LABELS[todo.priority]}</span>
        <span>{SOURCE_LABELS[todo.source]}</span>
      </div>
      <h3>{todo.title}</h3>
      <p>{todo.description}</p>
      <footer>
        <span>{todo.due_date || "마감일 없음"}</span>
        {todo.linked_type && <span>연결됨</span>}
      </footer>
    </article>
  );
}

// Render a reusable panel for priority source lists.
function PriorityPanel({ title, icon, items, emptyText, renderItem }) {
  return (
    <section className="priority-panel">
      <div className="panel-title">
        {icon}
        <h2>{title}</h2>
      </div>
      <div className="source-list">{items.length ? items.map(renderItem) : <div className="empty-state">{emptyText}</div>}</div>
    </section>
  );
}

// Render a single internal-message or customer source item.
function SourceItem({ title, meta, description, priority, linked, onAdd }) {
  return (
    <article className="source-item">
      <div>
        <div className="source-title-row">
          <strong>{title}</strong>
          <span className={`priority-pill ${priority}`}>{PRIORITY_LABELS[priority]}</span>
        </div>
        <span className="source-meta">{meta}</span>
        <p>{description}</p>
      </div>
      <button className={linked ? "ghost-button linked" : "ghost-button"} onClick={onAdd} disabled={linked}>
        {linked ? <Check size={15} /> : <Plus size={15} />}
        {linked ? "등록됨" : "ToDo"}
      </button>
    </article>
  );
}

// Render a modal for creating, editing, and deleting ToDos.
function TodoModal({ draft, setDraft, selectedTodo, onClose, onSave, onDelete }) {
  return (
    <div className="modal-backdrop">
      <section className="modal">
        <div className="modal-title">
          <h2>{selectedTodo ? "ToDo 상세" : "ToDo 생성"}</h2>
          <button className="text-button" onClick={onClose}>닫기</button>
        </div>
        <label>
          업무 제목
          <input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
        </label>
        <label>
          업무 설명
          <textarea value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
        </label>
        <div className="modal-row">
          <label>
            상태
            <select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>
              {STATUS_COLUMNS.map((column) => (
                <option key={column.id} value={column.id}>{column.label}</option>
              ))}
            </select>
          </label>
          <label>
            우선순위
            <select value={draft.priority} onChange={(event) => setDraft({ ...draft, priority: event.target.value })}>
              <option value="high">높음</option>
              <option value="medium">보통</option>
              <option value="low">낮음</option>
            </select>
          </label>
        </div>
        <label>
          마감일
          <input value={draft.due_date || ""} onChange={(event) => setDraft({ ...draft, due_date: event.target.value })} />
        </label>
        <div className="modal-actions">
          {selectedTodo && (
            <button className="danger-button" onClick={onDelete}>
              <Trash2 size={16} /> 삭제
            </button>
          )}
          <button className="primary-button" onClick={onSave}>저장</button>
        </div>
      </section>
    </div>
  );
}

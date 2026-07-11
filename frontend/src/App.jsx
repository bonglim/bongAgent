/**
 * Bong에이전트 MVP 대시보드의 최상위 React 애플리케이션.
 *
 * 이 파일은 업무 Kanban 보드, 우선순위 원천 패널, 자연어 채팅 패널, ToDo 상세
 * 모달, 히스토리 모달을 한 화면에서 조율한다. 서버 상태는 ``api.js`` 함수로
 * 읽고 쓰며, 사용자가 보는 즉각적인 반응을 위해 일부 작업은 optimistic update로
 * 먼저 화면에 반영한다.
 */
import React, { useEffect, useMemo, useState } from "react";
import { DndContext, PointerSensor, useDroppable, useSensor, useSensors } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import { SortableContext, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { BarChart3, CalendarDays, Check, CheckCircle2, ClipboardList, Copy, History, LayoutDashboard, Loader2, MessageSquareText, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Plus, Redo2, RefreshCw, Send, Settings, Star, Timer, Trash2, Undo2, UserRound } from "lucide-react";
import {
  API_BASE_URL,
  createCustomer,
  createMessage,
  createTodo,
  createTodoFromCustomer,
  createTodoFromMessage,
  deleteCustomer,
  deleteTodo,
  deleteMessage,
  fetchAgentApis,
  fetchCustomers,
  fetchHistory,
  fetchLlmModels,
  fetchMessages,
  fetchTodos,
  invokeAgent,
  redoHistory,
  restoreHistory,
  sendAssistantCommand,
  undoHistory,
  updateCustomer,
  updateMessage,
  updateTodo,
} from "./api.js";
import kbLogo from "./assets/kb-logo-mark.png";
import profileAvatar from "./assets/profile-avatar.png";
import { createLlmModelChangeHandler, DEFAULT_LLM_MODEL, FALLBACK_LLM_MODELS, normalizeLlmModels } from "./llmSettings.js";

/**
 * @typedef {object} TodoItem
 * @property {string} id
 * @property {string} title
 * @property {string} description
 * @property {"todo" | "doing" | "done"} status
 * @property {"high" | "medium" | "low"} priority
 * @property {string} due_date
 * @property {string | null} [linked_type]
 * @property {string | null} [linked_id]
 */

/**
 * @typedef {object} SourceRecord
 * @property {string} id
 * @property {"high" | "medium" | "low"} priority
 * @property {string | null} [linked_todo_id]
 */

/**
 * @typedef {object} AgentApiSpec
 * @property {string} id
 * @property {string} name
 * @property {string} method
 * @property {string} endpoint
 * @property {string} description
 * @property {string} sample_message
 * @property {Array<{ method: string, endpoint: string, description: string }>} related_apis
 */

const STATUS_COLUMNS = [
  { id: "todo", label: "할일", summaryTitle: "오늘의 업무", Icon: ClipboardList },
  { id: "doing", label: "진행중", summaryTitle: "진행중", Icon: Timer },
  { id: "done", label: "완료", summaryTitle: "완료", Icon: CheckCircle2 },
];

const PRIORITY_LABELS = {
  high: "높음",
  medium: "보통",
  low: "낮음",
};

const NEXT_PRIORITY = {
  low: "medium",
  medium: "high",
  high: "low",
};

const SOURCE_LABELS = {
  manual: "직접 입력",
  message: "사내쪽지",
  customer: "사후관리",
  assistant: "AI 명령",
};

const EMPTY_HISTORY = { undo: [], redo: [] };
const WEEKDAY_LABELS = ["일", "월", "화", "수", "목", "금", "토"];

/** 헤더에 표시할 오늘 날짜를 한국어 전체 날짜 형식으로 변환한다. */
function formatToday() {
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "full" }).format(new Date());
}

/**
 * ToDo 목록을 Kanban column id별로 묶는다.
 *
 * @param {Array<TodoItem>} todos - 백엔드에서 받은 ToDo 목록.
 * @returns {Record<string, Array<TodoItem>>} status id를 key로 갖는 ToDo group.
 */
function groupTodos(todos) {
  return STATUS_COLUMNS.reduce((groups, column) => {
    groups[column.id] = todos.filter((todo) => todo.status === column.id);
    return groups;
  }, {});
}

/** 새 수동 ToDo를 만들 때 사용할 모달 draft 기본값을 만든다. */
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

/** 사내쪽지를 직접 등록할 때 사용할 모달 draft 기본값을 만든다. */
function emptyMessageDraft() {
  return {
    title: "",
    sender: "",
    received_at: toDateKey(new Date()),
    priority: "medium",
    body: "",
  };
}

/** 사후관리 고객을 직접 등록할 때 사용할 모달 draft 기본값을 만든다. */
function emptyCustomerDraft() {
  return {
    name: "",
    reason: "",
    recommended_action: "",
    scheduled_date: toDateKey(new Date()),
    priority: "medium",
    detail: "",
  };
}

/** 날짜를 캘린더 집계 key로 통일한다. */
function toDateKey(value) {
  if (!value) return "";
  if (value instanceof Date) {
    const year = value.getFullYear();
    const month = String(value.getMonth() + 1).padStart(2, "0");
    const day = String(value.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }
  return String(value).slice(0, 10);
}

/** 현재 월 캘린더에 표시할 빈칸과 날짜 cell을 만든다. */
function buildCalendarDays(monthDate) {
  const year = monthDate.getFullYear();
  const month = monthDate.getMonth();
  const firstDay = new Date(year, month, 1);
  const lastDate = new Date(year, month + 1, 0).getDate();
  const leadingEmptyDays = firstDay.getDay();
  return [
    ...Array.from({ length: leadingEmptyDays }, () => null),
    ...Array.from({ length: lastDate }, (_, index) => new Date(year, month, index + 1)),
  ];
}

/**
 * 대시보드 상태, API 호출, 사용자 피드백을 조율하는 root component.
 *
 * 서버에서 가져온 ToDo/쪽지/고객/히스토리 상태를 보관하고, 드래그 앤 드롭,
 * 모달 저장, 자연어 명령, undo/redo 같은 사용자 이벤트를 각각의 handler로
 * 연결한다.
 */
export default function App() {
  const [todos, setTodos] = useState([]);
  const [messages, setMessages] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [selectedTodo, setSelectedTodo] = useState(null);
  const [draft, setDraft] = useState(emptyDraft());
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isMenuCollapsed, setIsMenuCollapsed] = useState(false);
  const [isCalendarOpen, setIsCalendarOpen] = useState(false);
  const [isMessageDetailOpen, setIsMessageDetailOpen] = useState(false);
  const [isMessageCreateOpen, setIsMessageCreateOpen] = useState(false);
  const [messageDraft, setMessageDraft] = useState(emptyMessageDraft());
  const [isCustomerDetailOpen, setIsCustomerDetailOpen] = useState(false);
  const [isCustomerCreateOpen, setIsCustomerCreateOpen] = useState(false);
  const [customerDraft, setCustomerDraft] = useState(emptyCustomerDraft());
  const [isChatVisible, setIsChatVisible] = useState(true);
  const [chatInput, setChatInput] = useState("");
  const [selectedModel, setSelectedModel] = useState(DEFAULT_LLM_MODEL);
  const [llmModels, setLlmModels] = useState(FALLBACK_LLM_MODELS);
  const [chatMessages, setChatMessages] = useState([
    { role: "assistant", text: "오늘 처리할 업무를 자연어로 입력해 주세요." },
  ]);
  const [historyState, setHistoryState] = useState(EMPTY_HISTORY);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isAgentApiOpen, setIsAgentApiOpen] = useState(false);
  const [agentApiItems, setAgentApiItems] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState("orchestrator");
  const [agentApiInput, setAgentApiInput] = useState("쪽지 우선순위 설정해줘");
  const [agentApiResult, setAgentApiResult] = useState(null);
  const [agentApiLoading, setAgentApiLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));
  const groupedTodos = useMemo(() => groupTodos(todos), [todos]);
  const handleModelChange = useMemo(() => createLlmModelChangeHandler(setSelectedModel, llmModels), [llmModels]);
  const canUndo = historyState.undo.length > 0;
  const canRedo = historyState.redo.length > 0;

  // 앱이 처음 mount될 때 대시보드 데이터와 LLM 모델 목록을 한 번 불러온다.
  useEffect(() => {
    refreshDashboard();
    loadLlmModels();
  }, []);

  /** 백엔드 설정에서 모델 선택기 옵션을 불러오고 실패하면 프론트 fallback을 사용한다. */
  async function loadLlmModels() {
    try {
      const settings = normalizeLlmModels(await fetchLlmModels());
      setLlmModels(settings.models);
      setSelectedModel(settings.defaultModel);
    } catch (error) {
      const fallback = normalizeLlmModels();
      setLlmModels(fallback.models);
      setSelectedModel(fallback.defaultModel);
    }
  }

  /** 대시보드에 필요한 모든 서버 데이터를 병렬로 가져오고 사용자 알림을 갱신한다. */
  async function refreshDashboard() {
    setLoading(true);
    try {
      const [todoRows, messageRows, customerRows, historyRows] = await Promise.all([fetchTodos(), fetchMessages(), fetchCustomers(), fetchHistory()]);
      setTodos(todoRows);
      setMessages(messageRows);
      setCustomers(customerRows);
      setHistoryState(historyRows);
      setNotice("대시보드를 새로고침했습니다.");
    } catch (error) {
      setNotice(error.message);
    } finally {
      setLoading(false);
    }
  }

  /** 헤더 새로고침 버튼에서 대시보드 데이터와 모델 설정을 함께 다시 읽는다. */
  async function handleHeaderRefresh() {
    await Promise.all([refreshDashboard(), loadLlmModels()]);
  }

  /** 설정 메뉴에서 agent API 정보 팝업을 열고 목록을 준비한다. */
  async function openAgentApiModal() {
    setIsAgentApiOpen(true);
    setAgentApiResult(null);
    try {
      const response = await fetchAgentApis();
      const items = response.agents || [];
      setAgentApiItems(items);
      if (items.length && !items.some((item) => item.id === selectedAgentId)) {
        setSelectedAgentId(items[0].id);
        setAgentApiInput(items[0].sample_message || "");
      }
    } catch (error) {
      setNotice(error.message);
    }
  }

  /** 선택한 agent API를 직접 호출하고 결과를 표시한다. */
  async function runAgentApi() {
    if (!selectedAgentId || !agentApiInput.trim()) return;
    setAgentApiLoading(true);
    try {
      const response = await invokeAgent(selectedAgentId, { message: agentApiInput.trim(), model: selectedModel });
      setAgentApiResult(response);
      if (["create_message", "delete_message", "set_message_priorities", "create_customer", "delete_customer", "create_todo", "update_todo", "delete_todo"].includes(response.intent)) {
        await refreshDashboard();
      }
      await refreshHistoryState();
      setNotice(response.reply);
    } catch (error) {
      setAgentApiResult({ intent: "error", reply: error.message });
      setNotice(error.message);
    } finally {
      setAgentApiLoading(false);
    }
  }

  /** 로컬 mutation 후 보드는 이미 갱신된 상태에서 히스토리 스택만 다시 읽는다. */
  async function refreshHistoryState() {
    try {
      setHistoryState(await fetchHistory());
    } catch (error) {
      setNotice(error.message);
    }
  }

  /** undo/redo/restore 응답을 화면에 반영하고 연결 원천 패널 상태까지 동기화한다. */
  async function applyHistoryResponse(response) {
    setTodos(response.todos || []);
    if (response.history) setHistoryState(response.history);
    setNotice(response.message);
    await refreshDashboard();
    setNotice(response.message);
  }

  /** 가장 최근 변경 이전 상태로 되돌린다. */
  async function handleUndo() {
    try {
      await applyHistoryResponse(await undoHistory());
    } catch (error) {
      setNotice(error.message);
    }
  }

  /** 가장 최근 되돌린 변경을 다시 실행한다. */
  async function handleRedo() {
    try {
      await applyHistoryResponse(await redoHistory());
    } catch (error) {
      setNotice(error.message);
    }
  }

  /** 히스토리 모달에서 선택한 시점으로 업무판을 이동한다. */
  async function handleRestoreHistory(historyId) {
    try {
      await applyHistoryResponse(await restoreHistory(historyId));
      setIsHistoryOpen(false);
    } catch (error) {
      setNotice(error.message);
    }
  }

  /** 드래그한 ToDo의 status를 optimistic update로 반영한 뒤 서버에 저장한다. */
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
      await refreshHistoryState();
      setNotice("ToDo 상태를 변경했습니다.");
    } catch (error) {
      setTodos(previous);
      setNotice(error.message);
    }
  }

  /** 새 수동 ToDo를 만들기 위한 빈 모달을 연다. */
  function openCreateModal() {
    setSelectedTodo(null);
    setDraft(emptyDraft());
    setIsModalOpen(true);
  }

  /** 사내쪽지 직접 등록 모달을 새 draft 상태로 연다. */
  function openMessageCreateModal() {
    setMessageDraft(emptyMessageDraft());
    setIsMessageCreateOpen(true);
  }

  /** 사후관리 고객 직접 등록 모달을 새 draft 상태로 연다. */
  function openCustomerCreateModal() {
    setCustomerDraft(emptyCustomerDraft());
    setIsCustomerCreateOpen(true);
  }

  /** 선택한 ToDo의 현재 값을 draft로 복사해 상세 모달을 연다. */
  function openEditModal(todo) {
    setSelectedTodo(todo);
    setDraft({ ...todo });
    setIsModalOpen(true);
  }

  /** 선택 상태에 따라 새 ToDo 생성 또는 기존 ToDo 수정을 저장한다. */
  async function saveTodo() {
    try {
      if (selectedTodo) {
        const updated = await updateTodo(selectedTodo.id, draft);
        setTodos((current) => current.map((todo) => (todo.id === updated.id ? updated : todo)));
        await refreshHistoryState();
        setNotice("ToDo를 수정했습니다.");
      } else {
        const created = await createTodo(draft);
        setTodos((current) => [created, ...current]);
        await refreshHistoryState();
        setNotice("ToDo를 생성했습니다.");
      }
      setIsModalOpen(false);
    } catch (error) {
      setNotice(error.message);
    }
  }

  /** 브라우저 확인 후 ToDo를 삭제하고 연결 원천 상태를 다시 동기화한다. */
  async function removeTodo(todo, { closeModal = false } = {}) {
    if (!todo || !window.confirm(`'${todo.title}' ToDo를 삭제하시겠습니까?`)) return;
    try {
      await deleteTodo(todo.id);
      setTodos((current) => current.filter((item) => item.id !== todo.id));
      if (selectedTodo?.id === todo.id) setSelectedTodo(null);
      if (closeModal) setIsModalOpen(false);
      await refreshDashboard();
      await refreshHistoryState();
      setNotice("ToDo를 삭제했습니다.");
    } catch (error) {
      setNotice(error.message);
    }
  }

  /** 상세 모달에서 현재 선택된 ToDo를 삭제한다. */
  async function removeSelectedTodo() {
    await removeTodo(selectedTodo, { closeModal: true });
  }

  /** 우선순위 사내쪽지를 ToDo로 전환하고 연결 상태를 새로고침한다. */
  async function addMessageTodo(id) {
    try {
      const todo = await createTodoFromMessage(id);
      setTodos((current) => [todo, ...current.filter((item) => item.id !== todo.id)]);
      await refreshDashboard();
      await refreshHistoryState();
      setNotice("사내쪽지를 ToDo로 전환했습니다.");
    } catch (error) {
      setNotice(error.message);
    }
  }

  /** 입력한 사내쪽지를 저장하고 우선순위 패널을 갱신한다. */
  async function saveMessage() {
    try {
      const created = await createMessage(messageDraft);
      setMessages((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      await refreshDashboard();
      await refreshHistoryState();
      setIsMessageCreateOpen(false);
      setNotice("사내쪽지를 등록했습니다.");
    } catch (error) {
      setNotice(error.message);
    }
  }

  /** 사내쪽지를 삭제하고 연결된 ToDo/히스토리 상태를 새로고침한다. */
  async function removeMessage(message) {
    if (!message || !window.confirm(`'${message.title}' 사내쪽지를 삭제하시겠습니까?`)) return;
    try {
      await deleteMessage(message.id);
      setMessages((current) => current.filter((item) => item.id !== message.id));
      await refreshDashboard();
      await refreshHistoryState();
      setNotice("사내쪽지를 삭제했습니다.");
    } catch (error) {
      setNotice(error.message);
    }
  }

  /** 사내쪽지 별 아이콘 클릭 시 priority를 순환시키고 서버에 저장한다. */
  async function cycleMessagePriority(message) {
    const nextPriority = NEXT_PRIORITY[message.priority] || "low";
    const previousMessages = messages;
    const previousTodos = todos;
    setMessages((current) => current.map((item) => (item.id === message.id ? { ...item, priority: nextPriority } : item)));
    if (message.linked_todo_id) {
      setTodos((current) => current.map((todo) => (todo.id === message.linked_todo_id ? { ...todo, priority: nextPriority } : todo)));
    }
    try {
      const [updated] = await Promise.all([
        updateMessage(message.id, { priority: nextPriority }),
        message.linked_todo_id ? updateTodo(message.linked_todo_id, { priority: nextPriority }) : Promise.resolve(null),
      ]);
      setMessages((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      await refreshHistoryState();
      setNotice(`'${updated.title}' 우선순위를 ${PRIORITY_LABELS[updated.priority]}으로 변경했습니다.`);
    } catch (error) {
      setMessages(previousMessages);
      setTodos(previousTodos);
      setNotice(error.message);
    }
  }

  /** 사후관리 고객을 ToDo로 전환하고 연결 상태를 새로고침한다. */
  async function addCustomerTodo(id) {
    try {
      const todo = await createTodoFromCustomer(id);
      setTodos((current) => [todo, ...current.filter((item) => item.id !== todo.id)]);
      await refreshDashboard();
      await refreshHistoryState();
      setNotice("사후관리 고객을 ToDo로 전환했습니다.");
    } catch (error) {
      setNotice(error.message);
    }
  }

  /** 입력한 사후관리 고객을 저장하고 고객 목록을 갱신한다. */
  async function saveCustomer() {
    try {
      const created = await createCustomer(customerDraft);
      setCustomers((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      await refreshDashboard();
      await refreshHistoryState();
      setIsCustomerCreateOpen(false);
      setNotice("사후관리 고객을 등록했습니다.");
    } catch (error) {
      setNotice(error.message);
    }
  }

  /** 사후관리 고객을 삭제하고 연결된 ToDo/히스토리 상태를 새로고침한다. */
  async function removeCustomer(customer) {
    if (!customer || !window.confirm(`'${customer.name}' 고객을 삭제하시겠습니까?`)) return;
    try {
      await deleteCustomer(customer.id);
      setCustomers((current) => current.filter((item) => item.id !== customer.id));
      await refreshDashboard();
      await refreshHistoryState();
      setNotice("사후관리 고객을 삭제했습니다.");
    } catch (error) {
      setNotice(error.message);
    }
  }

  /** 사후관리 고객 별 아이콘 클릭 시 priority를 순환시키고 서버에 저장한다. */
  async function cycleCustomerPriority(customer) {
    const nextPriority = NEXT_PRIORITY[customer.priority] || "low";
    const previousCustomers = customers;
    const previousTodos = todos;
    setCustomers((current) => current.map((item) => (item.id === customer.id ? { ...item, priority: nextPriority } : item)));
    if (customer.linked_todo_id) {
      setTodos((current) => current.map((todo) => (todo.id === customer.linked_todo_id ? { ...todo, priority: nextPriority } : todo)));
    }
    try {
      const [updated] = await Promise.all([
        updateCustomer(customer.id, { priority: nextPriority }),
        customer.linked_todo_id ? updateTodo(customer.linked_todo_id, { priority: nextPriority }) : Promise.resolve(null),
      ]);
      setCustomers((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      await refreshHistoryState();
      setNotice(`'${updated.name}' 고객 우선순위를 ${PRIORITY_LABELS[updated.priority]}으로 변경했습니다.`);
    } catch (error) {
      setCustomers(previousCustomers);
      setTodos(previousTodos);
      setNotice(error.message);
    }
  }

  /** ToDo 카드 별 아이콘 클릭 시 priority를 순환시키고 연결된 원천 데이터와 함께 저장한다. */
  async function cycleTodoPriority(todo) {
    const nextPriority = NEXT_PRIORITY[todo.priority] || "low";
    const previousTodos = todos;
    const previousMessages = messages;
    const previousCustomers = customers;
    setTodos((current) => current.map((item) => (item.id === todo.id ? { ...item, priority: nextPriority } : item)));
    if (todo.linked_type === "message" && todo.linked_id) {
      setMessages((current) => current.map((item) => (item.id === todo.linked_id ? { ...item, priority: nextPriority } : item)));
    }
    if (todo.linked_type === "customer" && todo.linked_id) {
      setCustomers((current) => current.map((item) => (item.id === todo.linked_id ? { ...item, priority: nextPriority } : item)));
    }
    try {
      const [updated] = await Promise.all([
        updateTodo(todo.id, { priority: nextPriority }),
        todo.linked_type === "message" && todo.linked_id ? updateMessage(todo.linked_id, { priority: nextPriority }) : Promise.resolve(null),
        todo.linked_type === "customer" && todo.linked_id ? updateCustomer(todo.linked_id, { priority: nextPriority }) : Promise.resolve(null),
      ]);
      setTodos((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      await refreshHistoryState();
      setNotice(`'${updated.title}' 우선순위를 ${PRIORITY_LABELS[updated.priority]}으로 변경했습니다.`);
    } catch (error) {
      setTodos(previousTodos);
      setMessages(previousMessages);
      setCustomers(previousCustomers);
      setNotice(error.message);
    }
  }

  /** 채팅 입력을 assistant에 보내고 명령 결과를 현재 UI 상태에 병합한다. */
  async function submitChat(event) {
    event.preventDefault();
    const message = chatInput.trim();
    if (!message) return;
    setChatInput("");
    setChatMessages((current) => [...current, { role: "user", text: message }]);
    try {
      const response = await sendAssistantCommand(message, selectedModel);
      setChatMessages((current) => [...current, { role: "assistant", text: response.reply }]);
      if (response.todos) setTodos(response.todos);
      if (["create_message", "delete_message", "set_message_priorities", "create_customer", "delete_customer"].includes(response.intent)) {
        await refreshDashboard();
      }
      await refreshHistoryState();
      setNotice(response.reply);
    } catch (error) {
      setChatMessages((current) => [...current, { role: "assistant", text: error.message }]);
      setNotice(error.message);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-group">
          <img className="kb-logo" src={kbLogo} alt="KB국민은행" />
          <strong className="brand">KB Comrade</strong>
          <div className="header-greeting">
            <div>
              <strong>안녕하세요, 이봉림 수석님 <span className="greeting-applause" aria-hidden="true">👏</span></strong>
              <span className="header-greeting-subtitle">KB Comrade가 당신의 업무를 더 스마트하게 도와 드립니다.</span>
            </div>
          </div>
        </div>
        <div className="header-meta">
          <span>{formatToday()}</span>
          <span className="user-profile">
            <img className="profile-avatar" src={profileAvatar} alt="이봉림 프로필" />
            <span>이봉림 · 금융AI1센터</span>
          </span>
          <button className="icon-button" type="button" onClick={handleHeaderRefresh} title="새로고침" aria-label="새로고침" disabled={loading}>
            {loading ? <Loader2 className="spin" size={18} /> : <RefreshCw size={18} />}
          </button>
          <button className="icon-button" type="button" onClick={openAgentApiModal} title="설정" aria-label="설정">
            <Settings size={18} />
          </button>
        </div>
      </header>

      <main className={`dashboard-layout ${isChatVisible ? "" : "chat-hidden"} ${isMenuCollapsed ? "menu-collapsed" : ""}`}>
        <DashboardMenu
          collapsed={isMenuCollapsed}
          onToggle={() => setIsMenuCollapsed((collapsed) => !collapsed)}
          onCalendarOpen={() => setIsCalendarOpen(true)}
          onMessageDetailOpen={() => setIsMessageDetailOpen(true)}
          onCustomerDetailOpen={() => setIsCustomerDetailOpen(true)}
          onSettingsOpen={openAgentApiModal}
          todos={todos}
          messages={messages}
          customers={customers}
        />

        <section className="work-area" id="today-work">
          <div className="section-heading">
            <div className="section-title-row">
              <h1>오늘의 할일</h1>
              <p className="section-helper">오늘의 업무를 상태별로 정리합니다.</p>
            </div>
            <div className="section-actions">
              <button className="icon-button" onClick={handleUndo} disabled={!canUndo} title="되돌리기" aria-label="되돌리기">
                <Undo2 size={18} />
              </button>
              <button className="icon-button" onClick={handleRedo} disabled={!canRedo} title="다시 실행" aria-label="다시 실행">
                <Redo2 size={18} />
              </button>
              <button className="icon-button" onClick={() => setIsHistoryOpen(true)} title="히스토리" aria-label="히스토리">
                <History size={18} />
              </button>
              <button className="primary-button compact-todo-button" onClick={openCreateModal}>
                <Plus size={17} /> ToDo
              </button>
              <button className="icon-button" onClick={() => setIsChatVisible((visible) => !visible)} title={isChatVisible ? "채팅 숨김" : "채팅 보기"} aria-label={isChatVisible ? "채팅 숨김" : "채팅 보기"}>
                {isChatVisible ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
              </button>
            </div>
          </div>

          <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
            <div className="kanban-grid">
              {STATUS_COLUMNS.map((column) => (
                <KanbanColumn key={column.id} column={column} todos={groupedTodos[column.id] || []} onCardClick={openEditModal} onCardDelete={removeTodo} onPriorityClick={cycleTodoPriority} />
              ))}
            </div>
          </DndContext>

          <div className="priority-grid" id="priority-sources">
            <PriorityPanel
              title="사내쪽지"
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
                  onPriorityClick={() => cycleMessagePriority(item)}
                />
              )}
            />
            <PriorityPanel
              title="사후관리 고객 목록"
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
                  onPriorityClick={() => cycleCustomerPriority(item)}
                />
              )}
            />
          </div>
          <footer className="work-tip-bar">
            <img className="work-tip-logo" src={kbLogo} alt="KB국민은행" />
            <strong>KB Comrade Tip</strong>
            <span>중요한 업무는 북마크로 저장해 보세요. 나중에 빠르게 확인할 수 있습니다.</span>
          </footer>
        </section>

        {isChatVisible && <aside className="chat-panel" id="assistant-chat">
          <div className="chat-header">
            <h2>LLM 채팅 / 자연어 명령</h2>
            <label className="model-picker">
              <select value={selectedModel} onChange={handleModelChange} aria-label="LLM 모델 선택">
                {llmModels.map((model) => (
                  <option key={model.id} value={model.id}>{model.label}</option>
                ))}
              </select>
            </label>
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

      {isHistoryOpen && (
        <HistoryModal
          historyState={historyState}
          onClose={() => setIsHistoryOpen(false)}
          onRestore={handleRestoreHistory}
          onUndo={handleUndo}
          onRedo={handleRedo}
          canUndo={canUndo}
          canRedo={canRedo}
        />
      )}
      {isAgentApiOpen && (
        <AgentApiModal
          agents={agentApiItems}
          selectedAgentId={selectedAgentId}
          setSelectedAgentId={setSelectedAgentId}
          input={agentApiInput}
          setInput={setAgentApiInput}
          result={agentApiResult}
          loading={agentApiLoading}
          onRun={runAgentApi}
          onClose={() => setIsAgentApiOpen(false)}
        />
      )}
      {isCalendarOpen && (
        <CalendarModal
          todos={todos}
          onClose={() => setIsCalendarOpen(false)}
        />
      )}
      {isMessageDetailOpen && (
        <MessageDetailModal
          messages={messages}
          onCreate={openMessageCreateModal}
          onDelete={removeMessage}
          onClose={() => setIsMessageDetailOpen(false)}
        />
      )}
      {isMessageCreateOpen && (
        <MessageCreateModal
          draft={messageDraft}
          setDraft={setMessageDraft}
          onClose={() => setIsMessageCreateOpen(false)}
          onSave={saveMessage}
        />
      )}
      {isCustomerDetailOpen && (
        <CustomerDetailModal
          customers={customers}
          onCreate={openCustomerCreateModal}
          onDelete={removeCustomer}
          onClose={() => setIsCustomerDetailOpen(false)}
        />
      )}
      {isCustomerCreateOpen && (
        <CustomerCreateModal
          draft={customerDraft}
          setDraft={setCustomerDraft}
          onClose={() => setIsCustomerCreateOpen(false)}
          onSave={saveCustomer}
        />
      )}
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

/**
 * 좌측 메뉴는 앱의 주요 업무 화면으로 이동하는 내비게이션을 제공한다.
 *
 * @param {object} props
 * @param {boolean} props.collapsed - 좌측 메뉴 접힘 여부.
 * @param {() => void} props.onToggle - 메뉴 접기/펼치기 handler.
 * @param {() => void} props.onCalendarOpen - 캘린더 팝업 열기 handler.
 * @param {() => void} props.onMessageDetailOpen - 사내쪽지 상세 팝업 열기 handler.
 * @param {() => void} props.onCustomerDetailOpen - 고객관리 상세 팝업 열기 handler.
 * @param {() => void} props.onSettingsOpen - 에이전트 API 설정 팝업 열기 handler.
 * @param {Array<TodoItem>} props.todos - 캘린더 badge 계산에 사용할 ToDo 목록.
 * @param {Array<SourceRecord>} props.messages - 사내쪽지 badge 계산에 사용할 목록.
 * @param {Array<SourceRecord>} props.customers - 고객관리 badge 계산에 사용할 목록.
 */
function DashboardMenu({ collapsed, onToggle, onCalendarOpen, onMessageDetailOpen, onCustomerDetailOpen, onSettingsOpen, todos, messages = [], customers = [] }) {
  const [isCalendarTipOpen, setIsCalendarTipOpen] = useState(false);
  const monthPrefix = toDateKey(new Date()).slice(0, 7);
  const calendarTodos = todos
    .filter((todo) => toDateKey(todo.due_date).startsWith(monthPrefix))
    .sort((first, second) => toDateKey(first.due_date).localeCompare(toDateKey(second.due_date)));
  const menuItems = [
    { href: "#today-work", label: "대시보드", icon: <LayoutDashboard size={24} /> },
    { label: "캘린더", icon: <CalendarDays size={24} />, onClick: onCalendarOpen, badgeCount: calendarTodos.length, badgeAction: () => setIsCalendarTipOpen((open) => !open) },
    { label: "사내쪽지", icon: <MessageSquareText size={24} />, onClick: onMessageDetailOpen, badgeCount: messages.length, badgeAction: onMessageDetailOpen },
    { label: "고객관리", icon: <UserRound size={24} />, onClick: onCustomerDetailOpen, badgeCount: customers.length, badgeAction: onCustomerDetailOpen },
    { href: "#priority-sources", label: "보고서", icon: <BarChart3 size={24} /> },
    { label: "설정", icon: <Settings size={24} />, onClick: onSettingsOpen },
  ];

  return (
    <nav className={`dashboard-menu ${collapsed ? "collapsed" : ""}`} aria-label="대시보드 메뉴">
      <button className="menu-toggle" type="button" onClick={onToggle} title={collapsed ? "메뉴 펼치기" : "메뉴 숨기기"} aria-label={collapsed ? "메뉴 펼치기" : "메뉴 숨기기"}>
        <img className="menu-profile-avatar" src={profileAvatar} alt="" />
        <span className="menu-profile-text">
          <strong>이봉림</strong>
          <span>금융AI1센터</span>
        </span>
        {collapsed ? <PanelLeftOpen size={22} /> : <PanelLeftClose size={22} />}
      </button>
      <div className="menu-list">
        {menuItems.map((item) => (
          item.onClick ? (
            <div className="menu-calendar-wrap" key={item.label}>
              <div className="menu-item menu-calendar-item">
                <button className="menu-calendar-main" type="button" onClick={item.onClick} title={item.label}>
                  <span className="menu-item-label">
                    {item.icon}
                    <span>{item.label}</span>
                  </span>
                </button>
                {item.badgeCount > 0 && (
                  <button
                    className="menu-calendar-count"
                    type="button"
                    onClick={item.badgeAction}
                    title={`${item.label} 상세`}
                    aria-label={`${item.label} ${item.badgeCount}건 상세 보기`}
                  >
                    <span />
                    {item.badgeCount}
                  </button>
                )}
              </div>
              {item.label === "캘린더" && isCalendarTipOpen && calendarTodos.length > 0 && (
                <div className="menu-calendar-tooltip">
                  {calendarTodos.slice(0, 5).map((todo) => (
                    <div className="menu-calendar-tooltip-item" key={todo.id}>
                      <strong>{toDateKey(todo.due_date)}</strong>
                      <span>{todo.title}</span>
                    </div>
                  ))}
                  {calendarTodos.length > 5 && <div className="menu-calendar-more">외 {calendarTodos.length - 5}건</div>}
                </div>
              )}
            </div>
          ) : (
          <a className="menu-item" href={item.href} key={item.label} title={item.label}>
            <span className="menu-item-label">
              {item.icon}
              <span>{item.label}</span>
            </span>
          </a>
          )
        ))}
      </div>
    </nav>
  );
}

/**
 * 설정 메뉴에서 agent API 목록과 sub-agent 직접 호출 UI를 보여준다.
 *
 * @param {object} props
 * @param {Array<AgentApiSpec>} props.agents - 백엔드에서 받은 agent API metadata.
 * @param {string} props.selectedAgentId - 현재 선택된 agent id.
 * @param {(id: string) => void} props.setSelectedAgentId - 선택 agent setter.
 * @param {string} props.input - 직접 호출할 자연어 메시지.
 * @param {(value: string) => void} props.setInput - 자연어 메시지 setter.
 * @param {object | null} props.result - agent 직접 호출 응답.
 * @param {boolean} props.loading - 호출 진행 상태.
 * @param {() => void} props.onRun - 선택 agent 호출 handler.
 * @param {() => void} props.onClose - 팝업 닫기 handler.
 */
function AgentApiModal({ agents, selectedAgentId, setSelectedAgentId, input, setInput, result, loading, onRun, onClose }) {
  const selectedAgent = agents.find((agent) => agent.id === selectedAgentId) || agents[0];
  const [copiedUrl, setCopiedUrl] = useState("");

  function handleAgentChange(event) {
    const nextId = event.target.value;
    const nextAgent = agents.find((agent) => agent.id === nextId);
    setSelectedAgentId(nextId);
    setInput(nextAgent?.sample_message || "");
  }

  function fullApiUrl(endpoint) {
    if (!endpoint) return API_BASE_URL;
    if (/^https?:\/\//.test(endpoint)) return endpoint;
    return `${API_BASE_URL}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;
  }

  async function copyApiUrl(url) {
    await navigator.clipboard.writeText(url);
    setCopiedUrl(url);
    window.setTimeout(() => setCopiedUrl((current) => (current === url ? "" : current)), 1300);
  }

  return (
    <div className="modal-backdrop">
      <section className="modal agent-api-modal" aria-label="에이전트 API 정보">
        <div className="modal-title">
          <div className="modal-title-copy">
            <h2>에이전트 API</h2>
            <span>Agent API와 메뉴별 연동 API의 전체 호출 URL을 확인합니다.</span>
          </div>
          <button className="text-button" type="button" onClick={onClose}>닫기</button>
        </div>

        <div className="agent-api-layout">
          <div className="agent-api-list">
            {agents.map((agent) => (
              <button
                className={agent.id === selectedAgentId ? "agent-api-item active" : "agent-api-item"}
                type="button"
                key={agent.id}
                onClick={() => {
                  setSelectedAgentId(agent.id);
                  setInput(agent.sample_message || "");
                }}
              >
                <strong>{agent.name}</strong>
                <span><b>{agent.method}</b> {agent.endpoint}</span>
              </button>
            ))}
          </div>

          <div className="agent-api-detail">
            {selectedAgent ? (
              <>
                <div className="agent-api-summary">
                  <div className="agent-api-endpoint">
                    <span className={`method-pill ${String(selectedAgent.method || "GET").toLowerCase()}`}>{selectedAgent.method}</span>
                    <div className="api-url-row">
                      <code>{fullApiUrl(selectedAgent.endpoint)}</code>
                      <button
                        className="copy-url-button"
                        type="button"
                        onClick={() => copyApiUrl(fullApiUrl(selectedAgent.endpoint))}
                        title={copiedUrl === fullApiUrl(selectedAgent.endpoint) ? "복사됨" : "API URL 복사"}
                        aria-label={copiedUrl === fullApiUrl(selectedAgent.endpoint) ? "API URL 복사됨" : "API URL 복사"}
                      >
                        <Copy size={14} />
                      </button>
                    </div>
                  </div>
                  <strong>{selectedAgent.name}</strong>
                  <p>{selectedAgent.description}</p>
                  <pre>{JSON.stringify(selectedAgent.request_body || {}, null, 2)}</pre>
                  <div className="agent-related-api-list">
                    <strong>관련 메뉴 API</strong>
                    {(selectedAgent.related_apis || []).map((api) => (
                      <div className="agent-related-api-item" key={`${api.method}-${api.endpoint}`}>
                        <span className={`method-pill ${String(api.method || "GET").toLowerCase()}`}>{api.method}</span>
                        <div>
                          <div className="api-url-row">
                            <code>{fullApiUrl(api.endpoint)}</code>
                            <button
                              className="copy-url-button"
                              type="button"
                              onClick={() => copyApiUrl(fullApiUrl(api.endpoint))}
                              title={copiedUrl === fullApiUrl(api.endpoint) ? "복사됨" : "API URL 복사"}
                              aria-label={copiedUrl === fullApiUrl(api.endpoint) ? "API URL 복사됨" : "API URL 복사"}
                            >
                              <Copy size={14} />
                            </button>
                          </div>
                          <p>{api.description}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <label>
                  호출 대상
                  <select value={selectedAgentId} onChange={handleAgentChange}>
                    {agents.map((agent) => (
                      <option key={agent.id} value={agent.id}>{agent.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  요청 메시지
                  <textarea value={input} onChange={(event) => setInput(event.target.value)} />
                </label>
                <div className="modal-actions">
                  <button className="primary-button" type="button" onClick={onRun} disabled={loading || !input.trim()}>
                    {loading ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
                    호출
                  </button>
                </div>
                <div className="agent-api-result">
                  <strong>응답</strong>
                  <pre>{result ? JSON.stringify(result, null, 2) : "아직 호출 결과가 없습니다."}</pre>
                </div>
              </>
            ) : (
              <div className="empty-state">에이전트 API 목록을 불러오고 있습니다.</div>
            )}
          </div>

        </div>
      </section>
    </div>
  );
}

/**
 * ToDo 마감일 기준으로 현재 월 일정 건수를 표시하는 캘린더 팝업.
 *
 * @param {object} props
 * @param {Array<TodoItem>} props.todos - 캘린더에 표시할 ToDo 목록.
 * @param {() => void} props.onClose - 팝업 닫기 handler.
 */
function CalendarModal({ todos, onClose }) {
  const today = new Date();
  const monthLabel = new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "long" }).format(today);
  const monthPrefix = toDateKey(today).slice(0, 7);
  const todayKey = toDateKey(today);
  const schedulesByDate = todos.reduce((groups, todo) => {
    const key = toDateKey(todo.due_date);
    if (!key || !key.startsWith(monthPrefix)) return groups;
    groups[key] = [...(groups[key] || []), todo];
    return groups;
  }, {});
  const calendarDays = buildCalendarDays(today);
  const scheduledTodos = Object.values(schedulesByDate).flat();

  return (
    <div className="modal-backdrop">
      <section className="modal calendar-modal" aria-label="업무 캘린더">
        <div className="modal-title">
          <div>
            <h2>캘린더</h2>
            <span>{monthLabel}</span>
          </div>
          <button className="text-button" type="button" onClick={onClose}>닫기</button>
        </div>
        <div className="calendar-weekdays">
          {WEEKDAY_LABELS.map((label) => <span key={label}>{label}</span>)}
        </div>
        <div className="calendar-grid">
          {calendarDays.map((day, index) => {
            if (!day) return <div className="calendar-day empty" key={`empty-${index}`} />;
            const key = toDateKey(day);
            const daySchedules = schedulesByDate[key] || [];
            return (
              <div className={`calendar-day ${key === todayKey ? "today" : ""}`} key={key} tabIndex={daySchedules.length > 0 ? 0 : undefined}>
                <span className="calendar-date">{day.getDate()}</span>
                {daySchedules.length > 0 && (
                  <>
                    <span className="calendar-count" aria-label={`${day.getDate()}일 일정 ${daySchedules.length}건`}>
                      <span />
                      {daySchedules.length}
                    </span>
                    <div className="calendar-day-tooltip">
                      {daySchedules.map((todo) => (
                        <div className="calendar-day-tooltip-item" key={todo.id}>
                          <strong>{todo.title}</strong>
                          <span>{PRIORITY_LABELS[todo.priority]} · {todo.status}</span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
        <div className="calendar-summary">
          <strong>{scheduledTodos.length}</strong>
          <span>이번 달 날짜가 지정된 업무</span>
        </div>
      </section>
    </div>
  );
}

/**
 * 좌측 메뉴 사내쪽지 클릭 시 쪽지 목록 상세를 보여준다.
 *
 * @param {object} props
 * @param {Array<object>} props.messages - 상세 팝업에 렌더링할 사내쪽지 목록.
 * @param {() => void} props.onCreate - 사내쪽지 등록 팝업 열기 handler.
 * @param {(message: object) => void} props.onDelete - 사내쪽지 삭제 handler.
 * @param {() => void} props.onClose - 팝업 닫기 handler.
 */
function MessageDetailModal({ messages, onCreate, onDelete, onClose }) {
  return (
    <div className="modal-backdrop">
      <section className="modal message-detail-modal" aria-label="사내쪽지 상세">
        <div className="modal-title">
          <div className="modal-title-copy">
            <h2>사내쪽지 상세</h2>
            <span>{messages.length}건의 사내쪽지가 있습니다.</span>
          </div>
          <div className="modal-title-actions">
            <button className="primary-button source-register-button" type="button" onClick={onCreate}>
              <Plus size={15} /> 등록
            </button>
            <button className="text-button" type="button" onClick={onClose}>닫기</button>
          </div>
        </div>
        <div className="message-detail-list">
          {messages.length === 0 && <div className="empty-state">확인할 사내쪽지가 없습니다.</div>}
          {messages.map((message) => (
            <article className="message-detail-item" key={message.id}>
              <div className="message-detail-item-head">
                <strong>{message.title}</strong>
                <div className="detail-item-actions">
                  <span className={`priority-pill ${message.priority}`}>{PRIORITY_LABELS[message.priority]}</span>
                  <button
                    className="source-delete-button"
                    type="button"
                    onClick={() => onDelete(message)}
                    title="사내쪽지 삭제"
                    aria-label={`${message.title} 사내쪽지 삭제`}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              <span className="message-detail-meta">{message.sender} · {message.received_at}</span>
              <p>{message.body}</p>
              <footer>
                <span>{message.status}</span>
                <span>{message.linked_todo_id ? "ToDo 등록됨" : "ToDo 미등록"}</span>
              </footer>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

/**
 * 좌측 메뉴 고객관리 클릭 시 사후관리 고객 목록 상세를 보여준다.
 *
 * @param {object} props
 * @param {Array<object>} props.customers - 상세 팝업에 렌더링할 사후관리 고객 목록.
 * @param {() => void} props.onCreate - 고객 등록 팝업 열기 handler.
 * @param {(customer: object) => void} props.onDelete - 고객 삭제 handler.
 * @param {() => void} props.onClose - 팝업 닫기 handler.
 */
function CustomerDetailModal({ customers, onCreate, onDelete, onClose }) {
  return (
    <div className="modal-backdrop">
      <section className="modal customer-detail-modal" aria-label="사후관리 고객 목록 상세">
        <div className="modal-title">
          <div className="modal-title-copy">
            <h2>사후관리 고객 목록</h2>
            <span>{customers.length}명의 고객이 있습니다.</span>
          </div>
          <div className="modal-title-actions">
            <button className="primary-button source-register-button" type="button" onClick={onCreate}>
              <Plus size={15} /> 등록
            </button>
            <button className="text-button" type="button" onClick={onClose}>닫기</button>
          </div>
        </div>
        <div className="customer-detail-list">
          {customers.length === 0 && <div className="empty-state">확인할 사후관리 고객이 없습니다.</div>}
          {customers.map((customer) => (
            <article className="customer-detail-item" key={customer.id}>
              <div className="customer-detail-item-head">
                <strong>{customer.name} 고객</strong>
                <div className="detail-item-actions">
                  <span className={`priority-pill ${customer.priority}`}>{PRIORITY_LABELS[customer.priority]}</span>
                  <button
                    className="source-delete-button"
                    type="button"
                    onClick={() => onDelete(customer)}
                    title="사후관리 고객 삭제"
                    aria-label={`${customer.name} 고객 삭제`}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              <span className="customer-detail-meta">{customer.reason} · {customer.scheduled_date}</span>
              <p>{customer.recommended_action}</p>
              <footer>
                <span>{customer.detail}</span>
                <span>{customer.linked_todo_id ? "ToDo 등록됨" : "ToDo 미등록"}</span>
              </footer>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

/**
 * 드롭 가능한 Kanban column 하나를 sortable context와 함께 렌더링한다.
 *
 * @param {object} props
 * @param {{id: string, label: string}} props.column - column 식별자와 표시 이름.
 * @param {Array<TodoItem>} props.todos - 이 column에 속한 ToDo 목록.
 * @param {(todo: TodoItem) => void} props.onCardClick - 카드 클릭 시 상세 모달을 여는 handler.
 * @param {(todo: TodoItem) => void} props.onCardDelete - 카드 삭제 버튼 handler.
 * @param {(todo: TodoItem) => void} props.onPriorityClick - 카드 별 아이콘 클릭 handler.
 */
function KanbanColumn({ column, todos, onCardClick, onCardDelete, onPriorityClick }) {
  const { setNodeRef, isOver } = useDroppable({ id: column.id });
  const SummaryIcon = column.Icon;
  return (
    <section className={`kanban-column ${isOver ? "is-over" : ""}`} id={`status-${column.id}`} ref={setNodeRef}>
      <div className="column-summary">
        <div className="column-summary-icon" aria-hidden="true">
          <SummaryIcon size={34} />
        </div>
        <div className="column-summary-body">
          <div className="column-summary-title">
            <h2>{column.summaryTitle}</h2>
          </div>
          <div className="column-summary-count" aria-label={`${column.summaryTitle} 총 ${todos.length}건`}>
            <strong>{todos.length}</strong>
            <span>총 건수</span>
          </div>
        </div>
      </div>
      <SortableContext items={todos.map((todo) => todo.id)} strategy={verticalListSortingStrategy}>
        <div className="card-list">
          {todos.length === 0 && <div className="empty-state">오늘 등록된 업무가 없습니다.</div>}
          {todos.map((todo) => (
            <TodoCard key={todo.id} todo={todo} onClick={() => onCardClick(todo)} onDelete={onCardDelete} onPriorityClick={onPriorityClick} />
          ))}
        </div>
      </SortableContext>
    </section>
  );
}

/**
 * 드래그 가능한 ToDo 카드를 우선순위와 원천 badge와 함께 렌더링한다.
 *
 * @param {object} props
 * @param {TodoItem} props.todo - 카드에 표시할 ToDo 데이터.
 * @param {() => void} props.onClick - 카드 본문 클릭 handler.
 * @param {(todo: TodoItem) => void} props.onDelete - 카드 삭제 handler.
 * @param {(todo: TodoItem) => void} props.onPriorityClick - 별 아이콘 클릭 handler.
 */
function TodoCard({ todo, onClick, onDelete, onPriorityClick }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: todo.id });
  const style = { transform: CSS.Transform.toString(transform), transition };
  return (
    <article className={`todo-card priority-${todo.priority} ${isDragging ? "dragging" : ""}`} ref={setNodeRef} style={style} {...attributes} {...listeners} onClick={onClick}>
      <div className="card-topline">
        <div className="card-meta">
          <span className={`priority-dot ${todo.priority}`}>{PRIORITY_LABELS[todo.priority]}</span>
          <span>{SOURCE_LABELS[todo.source]}</span>
        </div>
        <button
          className="card-delete-button"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onDelete(todo);
          }}
          onPointerDown={(event) => event.stopPropagation()}
          title="ToDo 삭제"
          aria-label={`${todo.title} ToDo 삭제`}
        >
          <Trash2 size={15} />
        </button>
      </div>
      <div className="todo-title-row">
        <button
          className={`priority-star ${todo.priority}`}
          type="button"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onPriorityClick(todo);
          }}
          onPointerDown={(event) => event.stopPropagation()}
          title={`우선순위: ${PRIORITY_LABELS[todo.priority]}`}
          aria-label={`${todo.title} 우선순위 변경`}
        >
          <Star size={16} fill="currentColor" />
        </button>
        <h3>{todo.title}</h3>
      </div>
      <p className="todo-description" title={todo.description}>{todo.description}</p>
      <footer>
        <span>{todo.due_date || "마감일 없음"}</span>
        {todo.linked_type && <span>연결됨</span>}
      </footer>
    </article>
  );
}

/**
 * 우선순위 원천 목록을 표시하는 재사용 패널을 렌더링한다.
 *
 * 사내쪽지와 사후관리 고객 패널이 같은 레이아웃을 공유하되, 항목 렌더링 방식은
 * 호출하는 쪽에서 ``renderItem``으로 주입한다.
 *
 * @param {object} props
 * @param {string} props.title - 패널 제목.
 * @param {React.ReactNode} props.icon - 제목 옆 아이콘.
 * @param {Array<object>} props.items - 패널에 표시할 원천 데이터 목록.
 * @param {string} props.emptyText - 항목이 없을 때 표시할 문구.
 * @param {(item: object) => React.ReactNode} props.renderItem - 항목 렌더링 함수.
 * @param {React.ReactNode | null} [props.action] - 제목 우측에 표시할 선택 액션.
 */
function PriorityPanel({ title, icon, items, emptyText, renderItem, action = null }) {
  return (
    <section className="priority-panel">
      <div className="panel-title">
        <div className="panel-title-main">
          {icon}
          <h2>{title}</h2>
        </div>
        {action}
      </div>
      <div className="source-list">{items.length ? items.map(renderItem) : <div className="empty-state">{emptyText}</div>}</div>
    </section>
  );
}

/**
 * 사내쪽지 또는 고객 원천 데이터 항목 하나를 렌더링한다.
 *
 * @param {object} props
 * @param {string} props.title - 항목 제목.
 * @param {string} props.meta - 발신자/날짜 등 보조 정보.
 * @param {string} props.description - 항목 설명.
 * @param {"high" | "medium" | "low"} props.priority - 현재 우선순위.
 * @param {boolean} props.linked - ToDo 연결 여부.
 * @param {() => void} props.onAdd - ToDo 전환 handler.
 * @param {() => void} [props.onPriorityClick] - 우선순위 순환 handler.
 */
function SourceItem({ title, meta, description, priority, linked, onAdd, onPriorityClick }) {
  const actionButton = (
    <button className={linked ? "ghost-button linked" : "ghost-button"} onClick={onAdd} disabled={linked}>
      {linked ? <Check size={15} /> : <Plus size={15} />}
      {linked ? "등록됨" : "ToDo"}
    </button>
  );

  return (
    <article className="source-item">
      <div>
        <div className="source-title-row">
          {onPriorityClick && (
            <button
              className={`priority-star ${priority}`}
              type="button"
              onClick={onPriorityClick}
              title={`우선순위: ${PRIORITY_LABELS[priority]}`}
              aria-label={`${title} 우선순위 변경`}
            >
              <Star size={16} fill="currentColor" />
            </button>
          )}
          <strong>{title}</strong>
          <span className={`priority-pill ${priority}`}>{PRIORITY_LABELS[priority]}</span>
        </div>
        <span className="source-meta">{meta}</span>
        <p>{description}</p>
      </div>
      {actionButton}
    </article>
  );
}

/**
 * 시점 이동에 사용할 단기 기억 목록과 undo/redo 버튼을 렌더링한다.
 *
 * @param {object} props
 * @param {{undo: Array<object>, redo: Array<object>}} props.historyState - undo/redo 히스토리 metadata.
 * @param {() => void} props.onClose - 팝업 닫기 handler.
 * @param {(historyId: string) => void} props.onRestore - 선택 히스토리 복원 handler.
 * @param {() => void} props.onUndo - undo 실행 handler.
 * @param {() => void} props.onRedo - redo 실행 handler.
 * @param {boolean} props.canUndo - undo 가능 여부.
 * @param {boolean} props.canRedo - redo 가능 여부.
 */
function HistoryModal({ historyState, onClose, onRestore, onUndo, onRedo, canUndo, canRedo }) {
  return (
    <div className="modal-backdrop">
      <section className="modal history-modal">
        <div className="modal-title">
          <h2>최근 기억</h2>
          <button className="text-button" onClick={onClose}>닫기</button>
        </div>
        <div className="history-actions">
          <button className="ghost-button" onClick={onUndo} disabled={!canUndo}>
            <Undo2 size={16} /> 되돌리기
          </button>
          <button className="ghost-button" onClick={onRedo} disabled={!canRedo}>
            <Redo2 size={16} /> 다시 실행
          </button>
        </div>
        <div className="history-list">
          {historyState.undo.length === 0 && <div className="empty-state">저장된 변경 이력이 없습니다.</div>}
          {historyState.undo.map((item) => (
            <article className="history-item" key={item.id}>
              <div>
                <strong>{item.summary}</strong>
                <span>{new Date(item.created_at).toLocaleString("ko-KR")}</span>
              </div>
              <button className="text-button" onClick={() => onRestore(item.id)}>이동</button>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

/** ToDo 생성, 수정, 삭제에 사용하는 상세 모달을 렌더링한다. */
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
          <input type="date" value={draft.due_date || ""} onChange={(event) => setDraft({ ...draft, due_date: event.target.value })} />
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

/** 사내쪽지를 직접 등록하는 모달을 렌더링한다. */
function MessageCreateModal({ draft, setDraft, onClose, onSave }) {
  const canSave = draft.title.trim() && draft.sender.trim();

  return (
    <div className="modal-backdrop">
      <section className="modal">
        <div className="modal-title">
          <h2>사내쪽지 등록</h2>
          <button className="text-button" type="button" onClick={onClose}>닫기</button>
        </div>
        <label>
          제목
          <input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} />
        </label>
        <div className="modal-row">
          <label>
            발신부서
            <input value={draft.sender} onChange={(event) => setDraft({ ...draft, sender: event.target.value })} />
          </label>
          <label>
            수신일
            <input type="date" value={draft.received_at || ""} onChange={(event) => setDraft({ ...draft, received_at: event.target.value })} />
          </label>
        </div>
        <label>
          우선순위
          <select value={draft.priority} onChange={(event) => setDraft({ ...draft, priority: event.target.value })}>
            <option value="high">높음</option>
            <option value="medium">보통</option>
            <option value="low">낮음</option>
          </select>
        </label>
        <label>
          내용
          <textarea value={draft.body} onChange={(event) => setDraft({ ...draft, body: event.target.value })} />
        </label>
        <div className="modal-actions">
          <button className="primary-button" type="button" onClick={onSave} disabled={!canSave}>등록</button>
        </div>
      </section>
    </div>
  );
}

/** 사후관리 고객을 직접 등록하는 모달을 렌더링한다. */
function CustomerCreateModal({ draft, setDraft, onClose, onSave }) {
  const canSave = draft.name.trim() && draft.reason.trim();

  return (
    <div className="modal-backdrop">
      <section className="modal">
        <div className="modal-title">
          <h2>사후관리 고객 등록</h2>
          <button className="text-button" type="button" onClick={onClose}>닫기</button>
        </div>
        <label>
          고객명
          <input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
        </label>
        <label>
          사후관리 사유
          <input value={draft.reason} onChange={(event) => setDraft({ ...draft, reason: event.target.value })} />
        </label>
        <div className="modal-row">
          <label>
            권장 조치
            <input value={draft.recommended_action} onChange={(event) => setDraft({ ...draft, recommended_action: event.target.value })} />
          </label>
          <label>
            예정일
            <input type="date" value={draft.scheduled_date || ""} onChange={(event) => setDraft({ ...draft, scheduled_date: event.target.value })} />
          </label>
        </div>
        <label>
          우선순위
          <select value={draft.priority} onChange={(event) => setDraft({ ...draft, priority: event.target.value })}>
            <option value="high">높음</option>
            <option value="medium">보통</option>
            <option value="low">낮음</option>
          </select>
        </label>
        <label>
          상세
          <textarea value={draft.detail} onChange={(event) => setDraft({ ...draft, detail: event.target.value })} />
        </label>
        <div className="modal-actions">
          <button className="primary-button" type="button" onClick={onSave} disabled={!canSave}>등록</button>
        </div>
      </section>
    </div>
  );
}

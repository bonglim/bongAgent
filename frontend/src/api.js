/**
 * Bong에이전트 프론트엔드 API client 모듈.
 *
 * 컴포넌트가 endpoint URL과 fetch 세부 구현에 직접 의존하지 않도록 모든 HTTP
 * 호출을 이 파일에 모은다. 각 함수는 백엔드 응답 JSON을 반환하거나, 화면에서
 * 표시할 수 있는 Error를 던진다.
 */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

/**
 * 실패한 HTTP 응답을 UI 알림에 바로 쓸 수 있는 Error로 변환한다.
 *
 * @param {Response} response - fetch가 반환한 원본 HTTP 응답.
 * @returns {Promise<unknown>} 성공 응답의 JSON body.
 */
async function parseResponse(response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "API 요청을 처리하지 못했습니다.");
  }
  return response.json();
}

/** Kanban 보드에 표시할 ToDo 목록을 조회한다. */
export async function fetchTodos() {
  return parseResponse(await fetch(`${API_BASE_URL}/api/todos`));
}

/** 우선순위 기준으로 정렬된 mock 사내쪽지를 조회한다. */
export async function fetchMessages() {
  return parseResponse(await fetch(`${API_BASE_URL}/api/messages`));
}

/** 우선순위 기준으로 정렬된 mock 사후관리 고객을 조회한다. */
export async function fetchCustomers() {
  return parseResponse(await fetch(`${API_BASE_URL}/api/customers/aftercare`));
}

/** 백엔드 설정에서 내려주는 LLM 모델 선택기 옵션을 조회한다. */
export async function fetchLlmModels() {
  return parseResponse(await fetch(`${API_BASE_URL}/api/llm/models`));
}

/** 설정 팝업에 표시할 agent API 목록을 조회한다. */
export async function fetchAgentApis() {
  return parseResponse(await fetch(`${API_BASE_URL}/api/agents`));
}

/**
 * 선택한 agent API를 직접 호출한다.
 *
 * @param {string} agentId - 호출할 agent id.
 * @param {{message: string, model?: string | null}} payload - agent 직접 호출 payload.
 */
export async function invokeAgent(agentId, payload) {
  return parseResponse(
    await fetch(`${API_BASE_URL}/api/agents/${agentId}/invoke`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

/** undo, redo, 시점 이동에 사용할 대시보드 단기 히스토리를 조회한다. */
export async function fetchHistory() {
  return parseResponse(await fetch(`${API_BASE_URL}/api/history`));
}

/** 가장 최근 변경 이전 대시보드 스냅샷으로 복구한다. */
export async function undoHistory() {
  return parseResponse(await fetch(`${API_BASE_URL}/api/history/undo`, { method: "POST" }));
}

/** 가장 최근 되돌린 대시보드 스냅샷을 다시 적용한다. */
export async function redoHistory() {
  return parseResponse(await fetch(`${API_BASE_URL}/api/history/redo`, { method: "POST" }));
}

/**
 * 선택한 히스토리 id의 대시보드 스냅샷으로 복구한다.
 *
 * @param {string} id - 복구할 히스토리 id.
 */
export async function restoreHistory(id) {
  return parseResponse(await fetch(`${API_BASE_URL}/api/history/restore/${id}`, { method: "POST" }));
}

/**
 * 상세 모달 폼에서 입력한 payload로 수동 ToDo를 생성한다.
 *
 * @param {object} payload - ToDo 생성 payload.
 */
export async function createTodo(payload) {
  return parseResponse(
    await fetch(`${API_BASE_URL}/api/todos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

/**
 * 사용자가 입력한 사내쪽지를 등록한다.
 *
 * @param {object} payload - 사내쪽지 생성 payload.
 */
export async function createMessage(payload) {
  return parseResponse(
    await fetch(`${API_BASE_URL}/api/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

/**
 * 드래그 앤 드롭, 모달 수정, 빠른 동작 후 ToDo를 부분 수정한다.
 *
 * @param {string} id - 수정할 ToDo id.
 * @param {object} payload - 부분 수정 payload.
 */
export async function updateTodo(id, payload) {
  return parseResponse(
    await fetch(`${API_BASE_URL}/api/todos/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

/**
 * 모달 또는 자연어 명령 결과에서 선택한 ToDo를 삭제한다.
 *
 * @param {string} id - 삭제할 ToDo id.
 */
export async function deleteTodo(id) {
  return parseResponse(await fetch(`${API_BASE_URL}/api/todos/${id}`, { method: "DELETE" }));
}

/**
 * 사내쪽지를 연결된 ToDo로 전환한다.
 *
 * @param {string} id - ToDo로 전환할 사내쪽지 id.
 */
export async function createTodoFromMessage(id) {
  return parseResponse(await fetch(`${API_BASE_URL}/api/todos/from-message/${id}`, { method: "POST" }));
}

/**
 * 사내쪽지 우선순위를 수정한다.
 *
 * @param {string} id - 수정할 사내쪽지 id.
 * @param {object} payload - 부분 수정 payload.
 */
export async function updateMessage(id, payload) {
  return parseResponse(
    await fetch(`${API_BASE_URL}/api/messages/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

/**
 * 사내쪽지를 삭제한다.
 *
 * @param {string} id - 삭제할 사내쪽지 id.
 */
export async function deleteMessage(id) {
  return parseResponse(await fetch(`${API_BASE_URL}/api/messages/${id}`, { method: "DELETE" }));
}

/**
 * 사후관리 고객 레코드를 연결된 ToDo로 전환한다.
 *
 * @param {string} id - ToDo로 전환할 고객 id.
 */
export async function createTodoFromCustomer(id) {
  return parseResponse(await fetch(`${API_BASE_URL}/api/todos/from-customer/${id}`, { method: "POST" }));
}

/**
 * 사용자가 입력한 사후관리 고객을 등록한다.
 *
 * @param {object} payload - 사후관리 고객 생성 payload.
 */
export async function createCustomer(payload) {
  return parseResponse(
    await fetch(`${API_BASE_URL}/api/customers/aftercare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

/**
 * 사후관리 고객 우선순위를 수정한다.
 *
 * @param {string} id - 수정할 고객 id.
 * @param {object} payload - 부분 수정 payload.
 */
export async function updateCustomer(id, payload) {
  return parseResponse(
    await fetch(`${API_BASE_URL}/api/customers/aftercare/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

/**
 * 사후관리 고객을 삭제한다.
 *
 * @param {string} id - 삭제할 고객 id.
 */
export async function deleteCustomer(id) {
  return parseResponse(await fetch(`${API_BASE_URL}/api/customers/aftercare/${id}`, { method: "DELETE" }));
}

/**
 * 자연어 입력과 선택한 LLM 모델을 assistant endpoint로 전송한다.
 *
 * @param {string} message - 사용자가 입력한 자연어 메시지.
 * @param {string | null} model - 선택된 LLM 모델 id.
 */
export async function sendAssistantCommand(message, model) {
  return parseResponse(
    await fetch(`${API_BASE_URL}/api/assistant/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, model }),
    })
  );
}

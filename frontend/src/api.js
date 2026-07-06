// API client functions are isolated here so components do not depend on raw URLs.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Convert failed HTTP responses into readable errors for UI notifications.
async function parseResponse(response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "API 요청을 처리하지 못했습니다.");
  }
  return response.json();
}

// Fetch ToDos for the Kanban board.
export async function fetchTodos() {
  return parseResponse(await fetch(`${API_BASE_URL}/api/todos`));
}

// Fetch mock internal messages sorted by priority.
export async function fetchMessages() {
  return parseResponse(await fetch(`${API_BASE_URL}/api/messages`));
}

// Fetch mock aftercare customers sorted by priority.
export async function fetchCustomers() {
  return parseResponse(await fetch(`${API_BASE_URL}/api/customers/aftercare`));
}

// Create a manual ToDo from the detail modal form.
export async function createTodo(payload) {
  return parseResponse(
    await fetch(`${API_BASE_URL}/api/todos`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

// Update a ToDo after drag-and-drop, modal edits, or quick actions.
export async function updateTodo(id, payload) {
  return parseResponse(
    await fetch(`${API_BASE_URL}/api/todos/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

// Delete a ToDo from the modal or natural-language command result.
export async function deleteTodo(id) {
  return parseResponse(await fetch(`${API_BASE_URL}/api/todos/${id}`, { method: "DELETE" }));
}

// Convert an internal message into a linked ToDo.
export async function createTodoFromMessage(id) {
  return parseResponse(await fetch(`${API_BASE_URL}/api/todos/from-message/${id}`, { method: "POST" }));
}

// Convert an aftercare customer into a linked ToDo.
export async function createTodoFromCustomer(id) {
  return parseResponse(await fetch(`${API_BASE_URL}/api/todos/from-customer/${id}`, { method: "POST" }));
}

// Send natural-language input to the rule-based assistant endpoint.
export async function sendAssistantCommand(message) {
  return parseResponse(
    await fetch(`${API_BASE_URL}/api/assistant/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    })
  );
}

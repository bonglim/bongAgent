# agent.md

## Mission

Build the Bong Agent MVP exactly as a local full-stack productivity assistant for a Korean bank employee. The product must show today's ToDos, priority internal messages, aftercare customers, and a natural-language assistant in one dense operational dashboard.

The finished app must run locally with:

- Backend: FastAPI on `http://localhost:8000`
- Frontend: Vite React on `http://localhost:5173`
- Local JSON persistence under `backend/data`
- Optional Gemini API chat fallback when `LLM_PROVIDER=gemini` and `GEMINI_API_KEY` are configured

## Product Scope

Implement a single-page dashboard named `Bong에이전트`.

Core workflows:

- View ToDos grouped by Kanban status: `할일`, `진행중`, `완료`
- Drag ToDo cards between status columns and persist the status
- Create, edit, and delete ToDos through a modal
- View priority-sorted internal messages and convert each message into a linked ToDo
- View priority-sorted aftercare customers and convert each customer into a linked ToDo
- Use a right-side chat panel for natural-language ToDo creation, status changes, deletion, and general Gemini chat
- Provide a chat hide/show icon button. When hidden, the Kanban workspace expands to the full dashboard width

Out of scope for MVP:

- Authentication and authorization
- Real customer PII integrations
- Real internal bank systems
- Database persistence
- Production deployment

## Repository Layout

Create this structure:

```text
backend/
  app/
    __init__.py
    agent.py
    config.py
    llm_provider.py
    main.py
    models.py
    repository.py
  data/
    todos.json
    messages.json
    customers.json
  requirements.txt
frontend/
  index.html
  package.json
  src/
    api.js
    App.jsx
    main.jsx
    styles.css
.env.example
README.md
agent.md
```

## Backend Requirements

Use Python, FastAPI, Pydantic, and local JSON files.

`backend/requirements.txt`:

```text
fastapi==0.115.6
uvicorn[standard]==0.34.0
pydantic-settings==2.7.1
python-dotenv==1.0.1
certifi==2026.6.17
```

### Configuration

Create `backend/app/config.py` with a `Settings` class using `pydantic_settings.BaseSettings`.

Required settings:

- `backend_cors_origins: str = "http://localhost:5173"`
- `llm_provider: str = "mock"`
- `gemini_api_key: str = ""`
- `gemini_model: str = "gemini-3.5-flash"`
- `data_dir: Path = backend/data`

Load environment from the project-root `.env`. Provide `get_settings()` with `functools.lru_cache`.

`.env.example` must include:

```env
BACKEND_CORS_ORIGINS=http://localhost:5173
LLM_PROVIDER=gemini
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash
VITE_API_BASE_URL=http://localhost:8000
```

### Data Models

Create Pydantic models in `backend/app/models.py`.

Enums via `Literal`:

- `TodoStatus = "todo" | "doing" | "done"`
- `Priority = "high" | "medium" | "low"`
- `TodoSource = "manual" | "message" | "customer" | "assistant"`
- `MessageStatus = "unread" | "todo_linked" | "done"`

Models:

- `TodoBase`: `title`, `description`, `status`, `priority`, `due_date`, `source`, `linked_type`, `linked_id`
- `TodoCreate(TodoBase)`
- `TodoUpdate`: optional editable fields
- `Todo(TodoBase)`: `id`, `created_at`, `updated_at`
- `InternalMessage`: `id`, `title`, `sender`, `received_at`, `priority`, `status`, `body`, `linked_todo_id`
- `AftercareCustomer`: `id`, `name`, `reason`, `recommended_action`, `scheduled_date`, `priority`, `detail`, `linked_todo_id`
- `AssistantCommandRequest`: `message`
- `AssistantCommandResponse`: `intent`, `reply`, `result`, `todos`

### JSON Repository

Create `backend/app/repository.py` with `JsonRepository`.

Responsibilities:

- Read/write UTF-8 JSON arrays from `backend/data`
- Use `threading.RLock` for writes
- Sort ToDos by priority and creation date
- Sort messages/customers by priority
- Create ToDos with ids like `todo_<8 hex chars>`
- Patch ToDos and update `updated_at`
- Delete ToDos and unlink any related message/customer source record
- Convert messages to linked ToDos and prevent duplicate links
- Convert aftercare customers to linked ToDos and prevent duplicate links

Priority order:

```python
{"high": 0, "medium": 1, "low": 2}
```

### Assistant Agent

Create `backend/app/agent.py` with `RuleBasedAssistantAgent`.

Command routing:

- Delete if the text contains `삭제`, `지워`, or `제거`
- Update if the text contains `진행중`, `진행 중`, `완료`, `할일로`, `변경`, or `바꿔`
- Create if the text contains `추가`, `등록`, `할일`, `todo`, or `ToDo`
- Otherwise call the configured LLM provider

Create behavior:

- Extract title by removing common command suffixes such as `추가해줘`, `추가`, `등록해줘`, `등록`, `할일로`, `ToDo로`, `todo로`
- Remove leading `오늘` or `내일`
- Limit title to 40 characters, fallback to `새 업무`
- Extract due text like `오늘 오후 3시`, `내일 오전 10시`, or simple `오늘`/`내일`
- Priority is `high` when the message contains `중요`, `긴급`, or `오늘`; otherwise `medium`
- Set source to `assistant`

Update/delete behavior:

- Match the first ToDo whose title or description shares a token with the user message, excluding command words
- If nothing matches, use the first ToDo if one exists
- If there are no ToDos, return `needs_confirmation`

### LLM Provider

Create `backend/app/llm_provider.py`.

Provider types:

- `MockLLMProvider`: deterministic Korean mock response
- `GeminiProvider`: calls Gemini API

Provider selection:

```python
provider = settings.llm_provider.lower()
if provider in {"gemini", "google"} and settings.gemini_api_key:
    return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
return MockLLMProvider()
```

Gemini behavior:

- Use Python standard library `urllib.request` to call the Gemini `generateContent` REST API
- Send requests to `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}`
- Include a Korean `systemInstruction` for a concise personal workplace assistant
- Extract the first non-empty text from `candidates[].content.parts[]`
- Return Korean error messages for invalid keys, permission issues, quota issues, and network failures

Request payload shape:

```python
payload = {
    "systemInstruction": {
        "parts": [{"text": "당신은 한국어로 답하는 개인 업무 비서입니다."}]
    },
    "contents": [{"parts": [{"text": message}]}],
}
```

### FastAPI Routes

Create `backend/app/main.py`.

Use CORS from `settings.cors_origin_list()`.

Routes:

```http
GET    /api/health
GET    /api/todos
POST   /api/todos
PATCH  /api/todos/{todo_id}
DELETE /api/todos/{todo_id}
GET    /api/messages
GET    /api/customers/aftercare
POST   /api/todos/from-message/{message_id}
POST   /api/todos/from-customer/{customer_id}
POST   /api/assistant/command
```

Return 404 with Korean details when a ToDo/message/customer is missing.

## Seed Data

Create realistic Korean mock records.

Minimum ToDos:

- High priority customer-source ToDo: `김민수 고객 만기 안내 전화`
- Medium priority manual ToDo: `오전 WM 회의 자료 확인`
- Low priority message-source done ToDo: `내부 공지 확인 완료`

Minimum internal messages:

- `고액 이체 사전 확인 요청` from `영업지원부`, high, unread
- `VIP 고객 상담 일정 조율` from `PB센터`, high, unread
- `영업점 운영 기준 변경 공지` from `준법감시부`, low, done, linked to the done ToDo

Minimum aftercare customers:

- `김민수`, `정기예금 만기 임박`, high, linked to the customer ToDo
- `이영희`, `펀드 리밸런싱 상담 필요`, high, unlinked
- `박준호`, `대출 사후관리 확인`, medium, unlinked

## Frontend Requirements

Use React 19, Vite, `lucide-react`, and `@dnd-kit`.

`frontend/package.json` dependencies:

- `@dnd-kit/core`
- `@dnd-kit/sortable`
- `@vitejs/plugin-react`
- `vite`
- `react`
- `react-dom`
- `lucide-react`

### API Client

Create `frontend/src/api.js`.

- Use `import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"`
- Implement fetch wrappers for all backend routes
- Convert non-OK responses into readable Korean errors

### App UI

Create `frontend/src/App.jsx`.

State:

- `todos`
- `messages`
- `customers`
- selected ToDo and modal draft
- `isModalOpen`
- `isChatVisible`
- chat input and chat messages
- toast notice
- loading state

Layout:

- Sticky topbar with brand `Bong에이전트`, page title `오늘의 업무 대시보드`, current Korean full date, employee text `김보람 · WM영업부`, refresh icon, settings icon
- Main grid with work area plus right chat rail
- When `isChatVisible` is false, apply `dashboard-layout chat-hidden` so the work area uses the full width
- Section heading with `ToDo Kanban`, helper copy, chat hide/show icon button, and ToDo creation button
- Three Kanban columns using statuses `todo`, `doing`, `done`
- Priority panels below Kanban for internal messages and aftercare customers
- Right chat panel with suggestions: `전화 추가`, `상태 변경`, `문구 작성`
- Modal for create/edit/delete
- Toast for notice messages

Chat toggle:

- Use `PanelRightClose` icon for `채팅 숨김`
- Use `PanelRightOpen` icon for `채팅 보기`
- The toggle button must have both `title` and `aria-label`
- Hide the `<aside className="chat-panel">` entirely when collapsed

Drag and drop:

- Use `DndContext`, `PointerSensor`, `useDroppable`, `useSortable`, and `SortableContext`
- Dragging a card onto a column updates status through `PATCH /api/todos/{id}`
- Optimistically update UI and rollback on API error

### Styling

Create `frontend/src/styles.css`.

Visual direction:

- Quiet, dense, premium dark workplace system
- Dark background, muted beige text, restrained gold accent
- No landing page or marketing hero
- No decorative blobs/orbs
- Cards should be functional and compact
- Preserve stable board dimensions to avoid layout shift

Important tokens:

```css
:root {
  --bg: #111111;
  --surface: #191919;
  --surface-2: #202020;
  --surface-3: #292929;
  --line: #34302a;
  --text: #f5f0e6;
  --muted: #a8a095;
  --gold: #f4c542;
  --gold-deep: #bb8d17;
  --danger: #e35d5d;
  --success: #5cbf7a;
}
```

Layout:

```css
body {
  min-width: 1180px;
}

.dashboard-layout {
  display: grid;
  grid-template-columns: minmax(780px, 1fr) 380px;
  gap: 22px;
  padding: 24px 28px;
}

.dashboard-layout.chat-hidden {
  grid-template-columns: minmax(780px, 1fr);
}
```

## Run Commands

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

## Verification Checklist

Run these checks before considering the implementation complete:

```bash
python3 -m py_compile backend/app/config.py backend/app/models.py backend/app/repository.py backend/app/agent.py backend/app/llm_provider.py backend/app/main.py
curl http://localhost:8000/api/health
curl http://localhost:8000/api/todos
cd frontend && npm run build
```

Browser checks:

- Dashboard renders without a blank page
- ToDo cards appear in the correct status columns
- Dragging a card persists status
- Manual ToDo create/edit/delete works
- Message-to-ToDo conversion works and disables linked message action
- Customer-to-ToDo conversion works and disables linked customer action
- Chat create command creates a ToDo
- Non-ToDo chat uses mock or Gemini provider depending on `.env`
- Chat hide/show button toggles the right panel and expands/collapses the layout

## Implementation Principles

- Keep backend route handlers thin; use repository and agent classes for behavior
- Keep frontend API calls isolated in `api.js`
- Keep JSON schema stable and human-readable
- Keep user-facing text Korean
- Do not commit real API keys
- Prefer small, direct components over premature abstraction
- Preserve existing dark KB-style UI tone and dense operational layout

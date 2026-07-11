# agent_han.md

## 목표

`Bong에이전트` MVP를 그대로 구현한다. 이 앱은 한국 은행 직원이 오늘 처리할 ToDo, 우선순위 사내쪽지, 사후관리 고객, 자연어 업무 비서를 한 화면에서 관리하는 로컬 풀스택 생산성 도구다.

완성된 앱은 아래 주소에서 동작해야 한다.

- 백엔드: FastAPI, `http://localhost:8000`
- 프론트엔드: Vite React, `http://localhost:5173`
- 저장소: `backend/data` 아래 로컬 JSON 파일
- 채팅 fallback: `LLM_PROVIDER=gemini`와 `GEMINI_API_KEY`가 설정된 경우 Gemini API 실제 호출

## 제품 범위

단일 페이지 대시보드 `Bong에이전트`를 구현한다.

핵심 기능:

- ToDo를 Kanban 상태별로 표시한다: `할일`, `진행중`, `완료`
- ToDo 카드를 드래그하여 상태 컬럼 사이에서 이동하고 변경 상태를 저장한다
- 모달에서 ToDo를 생성, 수정, 삭제한다
- 우선순위 정렬된 사내쪽지를 보여주고 각 쪽지를 연결된 ToDo로 전환한다
- 우선순위 정렬된 사후관리 고객을 보여주고 각 고객을 연결된 ToDo로 전환한다
- 우측 채팅 패널에서 자연어로 ToDo 생성, 상태 변경, 삭제, 일반 Gemini 채팅을 수행한다
- 우측 채팅창에 숨김/보기 아이콘 버튼을 제공한다
- 채팅창을 숨기면 Kanban 업무 영역이 전체 대시보드 폭을 사용해야 한다

MVP에서 제외할 것:

- 인증/권한
- 실제 고객 개인정보 연동
- 실제 사내 시스템 연동
- 데이터베이스 저장소
- 운영 배포 구성

## 저장소 구조

아래 구조로 프로젝트를 만든다.

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
agent_han.md
```

## 백엔드 구현 요구사항

Python, FastAPI, Pydantic, 로컬 JSON 파일을 사용한다.

`backend/requirements.txt`:

```text
fastapi==0.115.6
uvicorn[standard]==0.34.0
pydantic-settings==2.7.1
python-dotenv==1.0.1
certifi==2026.6.17
```

### 환경 설정

`backend/app/config.py`를 만든다.

`pydantic_settings.BaseSettings`를 사용하는 `Settings` 클래스를 구현한다.

필수 설정값:

- `backend_cors_origins: str = "http://localhost:5173"`
- `llm_provider: str = "mock"`
- `gemini_api_key: str = ""`
- `gemini_model: str = "gemini-3.5-flash"`
- `data_dir: Path = backend/data`

프로젝트 루트의 `.env` 파일을 읽어야 한다.

`get_settings()` 함수는 `functools.lru_cache`를 사용해 설정 객체를 한 번만 생성한다.

`Settings`에는 `cors_origin_list()` 메서드를 둔다. 쉼표로 구분된 origin 문자열을 strip하여 리스트로 반환한다.

`.env.example`:

```env
BACKEND_CORS_ORIGINS=http://localhost:5173
LLM_PROVIDER=gemini
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash
VITE_API_BASE_URL=http://localhost:8000
```

실제 API 키는 저장소에 커밋하지 않는다.

### 데이터 모델

`backend/app/models.py`에 Pydantic 모델을 만든다.

`Literal` 타입:

- `TodoStatus = "todo" | "doing" | "done"`
- `Priority = "high" | "medium" | "low"`
- `TodoSource = "manual" | "message" | "customer" | "assistant"`
- `MessageStatus = "unread" | "todo_linked" | "done"`

모델:

- `TodoBase`
  - `title: str`
  - `description: str = ""`
  - `status: TodoStatus = "todo"`
  - `priority: Priority = "medium"`
  - `due_date: str = ""`
  - `source: TodoSource = "manual"`
  - `linked_type: str | None = None`
  - `linked_id: str | None = None`
- `TodoCreate(TodoBase)`
- `TodoUpdate`
  - 수정 가능한 필드는 모두 optional
- `Todo(TodoBase)`
  - `id: str`
  - `created_at: datetime`
  - `updated_at: datetime`
- `InternalMessage`
  - `id`, `title`, `sender`, `received_at`, `priority`, `status`, `body`, `linked_todo_id`
- `AftercareCustomer`
  - `id`, `name`, `reason`, `recommended_action`, `scheduled_date`, `priority`, `detail`, `linked_todo_id`
- `AssistantCommandRequest`
  - `message`
- `AssistantCommandResponse`
  - `intent`
  - `reply`
  - `result`
  - `todos`

### JSON 저장소

`backend/app/repository.py`에 `JsonRepository`를 만든다.

역할:

- `backend/data`의 JSON 배열 파일을 UTF-8로 읽고 쓴다
- 쓰기 작업에는 `threading.RLock`을 사용한다
- ToDo는 우선순위와 생성일 기준으로 정렬한다
- 사내쪽지와 고객 목록은 우선순위 기준으로 정렬한다
- ToDo 생성 시 `todo_<8자리 hex>` 형태의 id를 만든다
- ToDo 수정 시 `updated_at`을 현재 시간으로 갱신한다
- ToDo 삭제 시 연결된 사내쪽지/고객 레코드의 `linked_todo_id`를 해제한다
- 사내쪽지를 ToDo로 전환할 수 있어야 한다
- 사후관리 고객을 ToDo로 전환할 수 있어야 한다
- 이미 연결된 쪽지/고객은 중복 ToDo를 만들지 말고 기존 ToDo를 반환한다

우선순위 정렬 순서:

```python
{"high": 0, "medium": 1, "low": 2}
```

필수 메서드:

- `list_todos()`
- `get_todo(todo_id)`
- `create_todo(payload)`
- `update_todo(todo_id, payload)`
- `delete_todo(todo_id)`
- `list_messages()`
- `list_customers()`
- `create_todo_from_message(message_id)`
- `create_todo_from_customer(customer_id)`

### 자연어 Agent

`backend/app/agent.py`에 `RuleBasedAssistantAgent`를 만든다.

입력 메시지 처리 순서:

1. 삭제 명령인지 확인
2. 상태 변경 명령인지 확인
3. 생성 명령인지 확인
4. 위 세 가지가 아니면 LLM provider로 채팅 처리

삭제 명령 키워드:

- `삭제`
- `지워`
- `제거`

상태 변경 키워드:

- `진행중`
- `진행 중`
- `완료`
- `할일로`
- `변경`
- `바꿔`

생성 명령 키워드:

- `추가`
- `등록`
- `할일`
- `todo`
- `ToDo`

생성 동작:

- 메시지에서 `추가해줘`, `추가`, `등록해줘`, `등록`, `할일로`, `ToDo로`, `todo로` 같은 명령어를 제거하여 제목을 만든다
- 제목 앞의 `오늘`, `내일`은 제거한다
- 제목은 40자 이내로 자른다
- 제목이 비면 `새 업무`를 사용한다
- `오늘 오후 3시`, `내일 오전 10시` 같은 날짜/시간 표현을 `due_date`로 추출한다
- `오늘` 또는 `내일`만 있어도 `due_date`에 반영한다
- 메시지에 `중요`, `긴급`, `오늘`이 있으면 우선순위는 `high`
- 그 외에는 `medium`
- `source`는 `assistant`

상태 변경 동작:

- 메시지에 `완료`가 있으면 `done`
- 메시지에 `진행중` 또는 `진행 중`이 있으면 `doing`
- 그 외에는 `todo`

ToDo 매칭:

- 명령어 토큰을 제외한 사용자 메시지 토큰을 만든다
- 각 토큰이 ToDo 제목 또는 설명에 포함되는 첫 번째 ToDo를 선택한다
- 매칭이 없으면 첫 번째 ToDo를 fallback으로 사용한다
- ToDo가 없으면 `needs_confirmation` 응답을 반환한다

### LLM Provider

`backend/app/llm_provider.py`를 만든다.

Provider 종류:

- `MockLLMProvider`
- `GeminiProvider`

`MockLLMProvider`:

- API 키가 없거나 `LLM_PROVIDER=mock`일 때 사용한다
- 한국어 mock Gemini 응답을 반환한다

`GeminiProvider`:

- Gemini generateContent REST API를 호출한다

Provider 선택:

```python
provider = settings.llm_provider.lower()
if provider in {"gemini", "google"} and settings.gemini_api_key:
    return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
return MockLLMProvider()
```

Gemini 호출 방식:

- Python 표준 라이브러리 `urllib.request`로 Gemini `generateContent` REST API를 호출한다
- 요청 URL은 `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}` 형식을 사용한다
- 한국어 개인 업무 비서 역할의 `systemInstruction`을 포함한다
- `candidates[].content.parts[]`에서 첫 번째 비어 있지 않은 `text`를 응답으로 반환한다
- API 키 오류, 권한 오류, 할당량 오류, 네트워크 오류는 한국어 안내 문구로 반환한다

요청 payload 예시:

```python
payload = {
    "systemInstruction": {
        "parts": [{"text": "당신은 한국어로 답하는 개인 업무 비서입니다."}]
    },
    "contents": [{"parts": [{"text": message}]}],
}
```

### FastAPI 라우트

`backend/app/main.py`를 만든다.

FastAPI 앱:

- title: `Bong에이전트 API`
- version: `0.1.0`
- CORS는 `settings.cors_origin_list()` 사용

라우트:

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

없는 ToDo, 쪽지, 고객은 404와 한국어 detail을 반환한다.

## 초기 데이터

`backend/data/*.json`에 현실적인 한국어 mock 데이터를 넣는다.

최소 ToDo:

- `김민수 고객 만기 안내 전화`
  - status: `todo`
  - priority: `high`
  - source: `customer`
  - linked to `customer_001`
- `오전 WM 회의 자료 확인`
  - status: `doing`
  - priority: `medium`
  - source: `manual`
- `내부 공지 확인 완료`
  - status: `done`
  - priority: `low`
  - source: `message`
  - linked to `message_003`

최소 사내쪽지:

- `고액 이체 사전 확인 요청`
  - sender: `영업지원부`
  - priority: `high`
  - status: `unread`
- `VIP 고객 상담 일정 조율`
  - sender: `PB센터`
  - priority: `high`
  - status: `unread`
- `영업점 운영 기준 변경 공지`
  - sender: `준법감시부`
  - priority: `low`
  - status: `done`
  - linked to done ToDo

최소 사후관리 고객:

- `김민수`
  - reason: `정기예금 만기 임박`
  - recommended_action: `만기 안내 전화`
  - priority: `high`
  - linked to customer ToDo
- `이영희`
  - reason: `펀드 리밸런싱 상담 필요`
  - recommended_action: `상담 예약`
  - priority: `high`
  - unlinked
- `박준호`
  - reason: `대출 사후관리 확인`
  - recommended_action: `서류 확인`
  - priority: `medium`
  - unlinked

## 프론트엔드 구현 요구사항

React 19, Vite, `lucide-react`, `@dnd-kit`을 사용한다.

`frontend/package.json` dependencies:

- `@dnd-kit/core`
- `@dnd-kit/sortable`
- `@vitejs/plugin-react`
- `vite`
- `react`
- `react-dom`
- `lucide-react`

### API 클라이언트

`frontend/src/api.js`를 만든다.

요구사항:

- `import.meta.env.VITE_API_BASE_URL || "http://localhost:8000"` 사용
- 모든 백엔드 라우트 호출 함수를 분리한다
- HTTP 오류는 사용자에게 보일 수 있는 한국어 에러로 변환한다

필수 함수:

- `fetchTodos()`
- `fetchMessages()`
- `fetchCustomers()`
- `createTodo(payload)`
- `updateTodo(id, payload)`
- `deleteTodo(id)`
- `createTodoFromMessage(id)`
- `createTodoFromCustomer(id)`
- `sendAssistantCommand(message)`

### React 앱

`frontend/src/App.jsx`를 만든다.

필수 상태:

- `todos`
- `messages`
- `customers`
- `selectedTodo`
- `draft`
- `isModalOpen`
- `isChatVisible`
- `chatInput`
- `chatMessages`
- `notice`
- `loading`

상단바:

- 브랜드: `Bong에이전트`
- 페이지 제목: `오늘의 업무 대시보드`
- 오늘 날짜를 한국어 full date로 표시
- 직원 텍스트: `김보람 · WM영업부`
- 새로고침 아이콘 버튼
- 설정 아이콘 버튼

메인 레이아웃:

- 기본은 업무 영역 + 우측 채팅 패널 2컬럼
- `isChatVisible`이 false이면 `dashboard-layout chat-hidden` 클래스를 적용한다
- 숨김 상태에서는 업무 영역이 전체 폭을 사용한다

업무 영역:

- 제목: `ToDo Kanban`
- 보조 문구: `오늘의 업무를 상태별로 정리합니다.`
- 채팅 숨김/보기 아이콘 버튼
- ToDo 생성 버튼
- Kanban 3컬럼: `할일`, `진행중`, `완료`
- 하단 우선순위 패널 2개:
  - `우선순위 사내쪽지`
  - `우선순위 사후관리 고객`

채팅 패널:

- 제목: `Gemini 채팅 / 자연어 명령`
- 상태 문구: `규칙 기반 MVP`
- 초기 assistant 메시지: `오늘 처리할 업무를 자연어로 입력해 주세요.`
- 추천 버튼:
  - `전화 추가`
  - `상태 변경`
  - `문구 작성`
- 입력 placeholder: `업무 추가, 상태 변경, 문구 작성...`
- 전송 아이콘 버튼

채팅 숨김/보기 버튼:

- `lucide-react`의 `PanelRightClose`, `PanelRightOpen`을 사용한다
- 보이는 상태에서는 `채팅 숨김`
- 숨긴 상태에서는 `채팅 보기`
- 버튼에 `title`과 `aria-label`을 모두 제공한다
- 숨김 상태에서는 `<aside className="chat-panel">` 자체를 렌더링하지 않는다

드래그 앤 드롭:

- `DndContext`, `PointerSensor`, `useDroppable`, `useSortable`, `SortableContext` 사용
- 카드가 컬럼에 드롭되면 `PATCH /api/todos/{id}`로 상태를 저장한다
- UI는 낙관적으로 업데이트하고 API 실패 시 롤백한다

모달:

- ToDo 생성/수정/삭제를 처리한다
- 필드:
  - 업무 제목
  - 업무 설명
  - 상태
  - 우선순위
  - 마감일
- 기존 ToDo 수정 시 삭제 버튼을 보여준다

토스트:

- 작업 성공/실패 메시지를 좌측 하단에 표시한다

### 스타일

`frontend/src/styles.css`를 만든다.

디자인 방향:

- 조용하고 밀도 높은 프리미엄 다크 업무 시스템
- 검정/차콜 기반 배경
- muted beige 텍스트
- gold accent
- 랜딩 페이지나 마케팅 hero 금지
- 장식용 blob/orb 금지
- 카드는 기능적이고 작게 유지
- 보드와 도구 영역은 레이아웃 shift가 적어야 한다

핵심 CSS 토큰:

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
  --shadow: 0 18px 50px rgba(0, 0, 0, 0.34);
}
```

핵심 레이아웃:

```css
body {
  margin: 0;
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

.chat-panel {
  position: sticky;
  top: 92px;
  height: calc(100vh - 116px);
  display: grid;
  grid-template-rows: auto 1fr auto auto;
  padding: 18px;
}
```

버튼:

- 아이콘 버튼은 40px 정사각형에 가깝게 만든다
- 주요 버튼은 gold 배경
- 위험 버튼은 붉은 계열
- 비활성/연결 완료 버튼은 success 색상

## 실행 방법

백엔드:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

프론트엔드:

```bash
cd frontend
npm install
npm run dev
```

브라우저:

```text
http://localhost:5173
```

## 검증 체크리스트

구현 완료 전 아래를 확인한다.

```bash
python3 -m py_compile backend/app/config.py backend/app/models.py backend/app/repository.py backend/app/agent.py backend/app/llm_provider.py backend/app/main.py
curl http://localhost:8000/api/health
curl http://localhost:8000/api/todos
cd frontend && npm run build
```

브라우저 확인:

- 대시보드가 빈 화면 없이 렌더링된다
- ToDo 카드가 상태별 컬럼에 표시된다
- 드래그 앤 드롭으로 상태가 저장된다
- 수동 ToDo 생성/수정/삭제가 동작한다
- 사내쪽지를 ToDo로 전환할 수 있다
- 연결된 사내쪽지는 버튼이 비활성화된다
- 사후관리 고객을 ToDo로 전환할 수 있다
- 연결된 고객은 버튼이 비활성화된다
- 채팅 생성 명령이 ToDo를 만든다
- 일반 채팅은 `.env`에 따라 mock 또는 Gemini provider를 사용한다
- 채팅 숨김/보기 버튼이 우측 패널을 토글한다
- 채팅 숨김 상태에서 Kanban 영역이 넓어진다

## 구현 원칙

- 백엔드 라우트 핸들러는 얇게 유지한다
- 저장소 로직은 `JsonRepository`에 둔다
- 자연어 처리 로직은 `RuleBasedAssistantAgent`에 둔다
- LLM 호출은 `LLMProvider` 경계 뒤에 둔다
- 프론트 API 호출은 `api.js`에 격리한다
- JSON 데이터는 사람이 읽기 쉬운 형식으로 유지한다
- 사용자에게 보이는 문구는 한국어로 작성한다
- 실제 API 키는 커밋하지 않는다
- 불필요한 추상화보다 작고 직접적인 컴포넌트를 우선한다
- 기존 KB 스타일의 어두운 업무 시스템 톤과 밀도 있는 레이아웃을 유지한다

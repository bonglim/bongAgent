# KB Comrade · Bong에이전트

KB Comrade는 은행 직원의 개인 업무를 한 화면에서 정리하는 AI 업무 비서 MVP입니다. ToDo Kanban, 사내쪽지, 사후관리 고객, 일정, 변경 이력을 통합하고 자연어 채팅으로 조회·등록·수정·삭제와 우선순위 재조정을 수행합니다.

## 핵심 기능

- ToDo Kanban: `할일`, `진행중`, `완료` 상태별 카드와 Drag & Drop
- ToDo CRUD: 직접 등록, 상세 수정, 삭제, 우선순위 변경
- 사내쪽지: 목록·상세·등록·삭제·ToDo 전환
- 사후관리 고객: 목록·상세·등록·삭제·ToDo 전환
- 자연어 agent: ToDo, 쪽지, 고객, 일반 질문을 의미 기반으로 라우팅
- 우선순위 재조정: 직접 날짜 기준 또는 LLM 추천으로 1~N 순위 재계산
- 조정 근거 제공: 전체 선정 기준과 항목별 사유를 채팅 답변에 표시
- LLM 선택: Gemini/OpenAI 모델 레지스트리와 API key별 라우팅
- 안전한 fallback: key가 없거나 구조화 응답이 잘못되면 mock/규칙 기반 처리
- Undo/Redo: 업무판 전체 스냅샷 기반 되돌리기, 다시 실행, 시점 복원
- Langfuse: 설정된 경우 LangGraph와 LLM generation 추적
- 반응형 UI: 데스크톱, 태블릿, 모바일 레이아웃

## 최근 반영 사항: 채팅 우선순위 재조정

사내쪽지와 사후관리 고객은 기존 `high`, `medium`, `low` 등급 외에 다음 값을 저장합니다.

| 필드 | 의미 | 예시 |
|---|---|---|
| `priority` | 화면 색상과 그룹에 사용하는 등급 | `high` |
| `priority_rank` | 전체 목록에서 중복 없는 정확한 순서 | `1` |
| `priority_reason` | 현재 순위로 조정된 데이터 기반 근거 | `최근 관리예정일 기준...` |

### 직접 지시

사용자가 날짜 방향을 명시하면 LLM을 호출하지 않고 저장된 날짜로 결정적으로 정렬합니다.

```text
사후관리 고객을 최근날짜 순으로 우선순위를 지정해 주세요.
사후관리 고객을 예정일이 빠른 순으로 재정렬해 주세요.
사내쪽지를 최근 수신일 순으로 우선순위를 설정해 주세요.
사내쪽지를 오래된 날짜 순으로 재조정해 주세요.
```

### LLM 추천

구체적인 정렬 기준 없이 재조정을 요청하면 선택된 LLM이 긴급성, 준법·보안, 금융·고객 영향, 기한, 후속 조치 필요성을 평가합니다.

```text
사후관리 고객 우선순위를 재조정해 주세요.
사내쪽지 우선순위를 재조정해 주세요.
```

LLM은 모든 항목에 `priority`, 1~N `rank`, 한국어 `reason`을 반환해야 합니다. 항목 누락, 중복 rank, 잘못된 JSON이 있으면 규칙 기반 fallback이 같은 구조의 결과를 생성합니다. 결과는 하나의 히스토리 단위로 저장되며 연결된 ToDo의 등급도 함께 갱신됩니다.

응답 예시:

```text
사후관리 고객 3명의 우선순위를 직접 지시로 재조정했습니다.
조정 기준: 최근 관리예정일 순
1. [high] 김민수 고객 - 사용자가 지정한 최근 관리예정일 기준(예정일 2026-07-14)을 적용했습니다.
2. [medium] 이영희 고객 - 사용자가 지정한 최근 관리예정일 기준(예정일 2026-07-10)을 적용했습니다.
3. [low] 박준호 고객 - 사용자가 지정한 최근 관리예정일 기준(예정일 2026-07-07)을 적용했습니다.
```

## 기술 스택

| 영역 | 기술 |
|---|---|
| Backend | Python, FastAPI, Pydantic Settings, Uvicorn |
| Agent | LangGraph 형식 StateGraph, 도메인 sub-agent |
| LLM | Gemini REST API, OpenAI Responses API, mock provider |
| Observability | Langfuse, LangChain callback |
| Storage | JSON 파일, 프로세스 내 `RLock` |
| Frontend | React 19, Vite 6, dnd-kit, Lucide React |
| Styling | 반응형 CSS, KB 다크·골드 디자인 토큰 |

## 프로젝트 구조

```text
.
├── .env.example
├── README.md
├── backend
│   ├── requirements.txt
│   ├── app
│   │   ├── main.py              # FastAPI 앱, REST endpoint, 의존성 주입
│   │   ├── models.py            # 요청/응답/저장 Pydantic 모델
│   │   ├── repository.py        # JSON CRUD, 순위 저장, Undo/Redo
│   │   ├── config.py            # .env 기반 런타임 설정
│   │   ├── llm_settings.py      # 모델 레지스트리와 API key 해석
│   │   ├── llm_provider.py      # Gemini/OpenAI/mock 라우팅
│   │   ├── observability.py     # 선택적 Langfuse 설정
│   │   ├── agent.py             # 기존 import 호환 re-export
│   │   └── agents
│   │       ├── orchestrator.py  # LangGraph 라우팅과 node 실행
│   │       ├── shared.py        # AgentContext, Protocol, helper
│   │       ├── todo_agent.py
│   │       ├── message_agent.py
│   │       ├── customer_agent.py
│   │       └── llm_agent.py
│   └── data
│       ├── todos.json
│       ├── messages.json
│       ├── customers.json
│       ├── history.json
│       └── redo.json
└── frontend
    ├── package.json
    ├── index.html
    └── src
        ├── main.jsx             # React mount 진입점
        ├── App.jsx              # 상태, 화면, 이벤트 조율
        ├── api.js               # FastAPI client 함수
        ├── llmSettings.js       # 모델 선택값 보정
        └── styles.css           # 디자인 토큰과 반응형 화면
```

`backend/.venv`, `frontend/node_modules`, `frontend/dist`, `.env`는 실행 산출물 또는 개인 설정이므로 Git 관리 대상에서 제외합니다.

## Agent 구조

```text
사용자 채팅
  ↓
POST /api/assistant/command
  ↓
RuleBasedAssistantAgent
  ↓
SemanticDomainRouter ── LLM이 message/customer/todo/general 분류
  ↓ 분류 실패 시 규칙 기반 can_handle fallback
  ├── InternalMessageManagementAgent
  │     └── InternalMessagePriorityRecommendationAgent
  ├── AftercareCustomerManagementAgent
  │     └── AftercareCustomerPriorityRecommendationAgent
  ├── TodoManagementAgent
  └── LLMQuestionAnswerAgent
```

라우팅 순서:

1. 프론트가 자연어 메시지와 선택 모델 id를 전송합니다.
2. `SemanticDomainRouter`가 `message`, `customer`, `todo`, `general` 중 하나를 선택합니다.
3. 분류가 불명확하면 각 agent의 `can_handle()` 키워드 규칙을 사용합니다.
4. 쪽지·고객 node에는 저장소의 현재 전체 데이터가 `AgentContext`로 주입됩니다.
5. 명확한 CRUD 또는 우선순위 명령만 데이터를 변경합니다.
6. 그 외 도메인 질문은 주입된 데이터만 근거로 답변합니다.
7. 일반 질문은 선택된 LLM provider로 전달됩니다.

LangGraph가 설치되지 않은 개발 환경에서도 같은 `invoke()` 계약의 fallback graph가 동작합니다.

## 데이터와 정렬 규칙

### ToDo

- 우선순위: `high → medium → low`
- 같은 우선순위에서는 생성 시각 순
- 상태: `todo`, `doing`, `done`
- 원천: `manual`, `message`, `customer`, `assistant`

### 사내쪽지와 사후관리 고객

- `priority_rank`가 있으면 숫자가 작은 항목부터 표시
- 상세 rank가 없으면 `high → medium → low` 순으로 호환 정렬
- 수동 별 버튼으로 등급을 바꾸면 이전 AI rank와 reason을 초기화
- 재조정 시 전체 항목을 상·중·하 구간으로 나누고 정확한 rank를 별도로 저장
- 원천 레코드와 연결된 ToDo의 `priority`를 동기화

### Undo/Redo

쓰기 작업 전 `todos`, `messages`, `customers` 전체를 스냅샷으로 저장합니다. 우선순위 일괄 재조정도 한 번의 undo로 복원됩니다. 히스토리는 최대 30건을 유지합니다.

## 설치 및 실행

### 요구 사항

- Python 3.11 이상
- Node.js 18 이상과 npm

### 1. 환경 설정

```bash
cp .env.example .env
```

외부 LLM 없이 실행하려면 `.env`에서 다음 값을 사용합니다.

```env
LLM_PROVIDER=mock
BACKEND_CORS_ORIGINS=http://localhost:5173
VITE_API_BASE_URL=http://localhost:8000
```

Gemini/OpenAI를 사용하려면 `LLM_PROVIDER=auto`로 설정하고 필요한 key를 입력합니다.

```env
LLM_PROVIDER=auto
LLM_MODELS=gemini-2.5-flash|gemini-2.5-flash|gemini|GEMINI_API_KEY;gpt-4o-mini|GPT4o-mini|openai|GPT4O_MINI_API_KEY
DEFAULT_LLM_MODEL=gemini-2.5-flash
GEMINI_API_KEY=
OPENAI_API_KEY=
GPT4O_MINI_API_KEY=
```

`LLM_MODELS` 형식:

```text
model_id|화면 표시명|provider|API_KEY_ENV_NAME;...
```

API key와 key 환경변수 이름은 `/api/llm/models` 공개 응답에 포함되지 않습니다.

### 2. 백엔드

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

확인:

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/todos
```

FastAPI 문서:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

### 3. 프론트엔드

새 터미널에서 실행합니다.

```bash
cd frontend
npm install
npm run dev
```

브라우저: `http://localhost:5173`

프로덕션 빌드 확인:

```bash
npm run build
```

## 자연어 명령 예시

### ToDo

```text
오늘 오후 3시에 김민수 고객에게 전화하기 추가해 줘
김민수 고객 전화 업무를 진행중으로 바꿔 줘
완료된 업무 목록 보여 줘
오전 회의 준비 업무 삭제해 줘
```

### 사내쪽지

```text
사내쪽지 목록 보여 줘
준법 관련 쪽지 내용을 자세히 알려 줘
사내쪽지 우선순위를 재조정해 줘
쪽지를 최근 수신일 순으로 우선순위를 지정해 줘
```

### 사후관리 고객

```text
사후관리 고객 목록 보여 줘
김민수 고객 상세 내용을 알려 줘
사후관리 고객 우선순위를 재조정해 줘
사후관리 고객을 최근날짜 순으로 우선순위를 지정해 줘
```

### 일반 LLM 질문

```text
고객에게 보낼 정기예금 만기 안내 문구를 작성해 줘
상담 후 감사 메시지를 정중하게 작성해 줘
```

## REST API

### 시스템과 agent

| Method | Endpoint | 설명 |
|---|---|---|
| GET | `/api/health` | 서버 상태 확인 |
| GET | `/api/llm/models` | 공개 모델 선택기 정보 |
| GET | `/api/agents` | agent API metadata |
| POST | `/api/agents/{agent_id}/invoke` | 개별 agent 직접 호출 |
| POST | `/api/assistant/command` | 채팅 orchestrator 실행 |

직접 호출 가능한 `agent_id`:

```text
orchestrator
message
message-priority
customer
customer-priority
todo
llm
```

채팅 요청 예시:

```bash
curl -X POST http://localhost:8000/api/assistant/command \
  -H 'Content-Type: application/json' \
  -d '{"message":"사후관리 고객 우선순위를 재조정해 주세요.","model":"gemini-2.5-flash"}'
```

### ToDo와 히스토리

| Method | Endpoint | 설명 |
|---|---|---|
| GET | `/api/todos` | ToDo 목록 |
| POST | `/api/todos` | ToDo 생성 |
| PATCH | `/api/todos/{todo_id}` | ToDo 부분 수정 |
| DELETE | `/api/todos/{todo_id}` | ToDo 삭제 |
| POST | `/api/todos/from-message/{message_id}` | 쪽지를 ToDo로 전환 |
| POST | `/api/todos/from-customer/{customer_id}` | 고객을 ToDo로 전환 |
| GET | `/api/history` | undo/redo metadata |
| POST | `/api/history/undo` | 최근 변경 되돌리기 |
| POST | `/api/history/redo` | 최근 되돌리기 다시 적용 |
| POST | `/api/history/restore/{history_id}` | 선택 시점 복원 |

### 사내쪽지

| Method | Endpoint | 설명 |
|---|---|---|
| GET | `/api/messages` | 저장 순위 기준 쪽지 목록 |
| POST | `/api/messages` | 쪽지 등록 |
| PATCH | `/api/messages/{message_id}` | 쪽지 우선순위 수정 |
| DELETE | `/api/messages/{message_id}` | 쪽지 삭제 |

### 사후관리 고객

| Method | Endpoint | 설명 |
|---|---|---|
| GET | `/api/customers/aftercare` | 저장 순위 기준 고객 목록 |
| POST | `/api/customers/aftercare` | 고객 등록 |
| PATCH | `/api/customers/aftercare/{customer_id}` | 고객 우선순위 수정 |
| DELETE | `/api/customers/aftercare/{customer_id}` | 고객 삭제 |
| POST | `/api/customers/aftercare/ai-recommend` | 선택 모델로 우선순위 추천 |

## 주요 응답 구조

자연어 명령은 공통 `AssistantCommandResponse`를 반환합니다.

```json
{
  "intent": "set_customer_priorities",
  "reply": "사후관리 고객 3명의 우선순위를 ...",
  "result": {
    "customers": [],
    "reasons": [
      {
        "customer_id": "customer_001",
        "name": "김민수",
        "priority": "high",
        "rank": 1,
        "reason": "관리 예정일과 금융 리스크를 우선 반영했습니다."
      }
    ],
    "summary": "관리 예정일과 고객 영향을 종합했습니다.",
    "method": "LLM 추천",
    "used_fallback": false
  },
  "todos": null
}
```

주요 intent:

- `create_todo`, `update_todo`, `delete_todo`, `query_todos`
- `create_message`, `delete_message`, `query_messages`, `set_message_priorities`
- `create_customer`, `delete_customer`, `query_customers`, `set_customer_priorities`
- `needs_confirmation`, `chat`

## Langfuse 관측성

다음 값을 모두 설정하면 tracing이 활성화됩니다.

```env
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=development
```

key가 없으면 `build_langfuse_tracing()`이 `None`을 반환하므로 로컬 기능은 영향 없이 동작합니다. 실제 Gemini/OpenAI 호출은 generation observation으로 기록되고 LangGraph 실행에는 callback handler가 전달됩니다.

## 소스 문서화 기준

- 모든 Python 모듈, 클래스, 함수에는 역할을 설명하는 docstring을 둡니다.
- 복잡한 함수는 `Args`, `Returns`, `Example`로 입력·출력·사용법을 설명합니다.
- React 컴포넌트와 API 함수는 JSDoc으로 props, payload, 반환값을 설명합니다.
- 자연어 명령이나 API payload는 실제 형태의 예시를 함께 둡니다.
- 주석은 코드 문법을 반복하지 않고 라우팅, fallback, 원자적 저장, 상태 동기화처럼 의도가 중요한 곳에 둡니다.
- CSS는 디자인 토큰, 레이아웃, 기능 영역, 반응형 breakpoint 단위로 섹션 주석을 유지합니다.

## 검증

백엔드 문법과 import 가능한 소스는 다음 명령으로 확인합니다.

```bash
backend/.venv/bin/python -m py_compile \
  backend/app/*.py \
  backend/app/agents/*.py
```

프론트엔드는 프로덕션 빌드로 JSX, import, CSS 번들링을 확인합니다.

```bash
npm --prefix frontend run build
```

상태 확인:

```bash
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5173/
```

## 현재 저장 방식과 운영 시 고려사항

현재 버전은 수업·시연용 MVP로 JSON 파일을 사용합니다.

- 단일 프로세스 내 쓰기는 `RLock`으로 보호됩니다.
- 여러 서버 프로세스가 같은 JSON 파일을 동시에 쓰는 운영 환경은 지원하지 않습니다.
- 운영 전환 시 repository 경계를 데이터베이스 구현으로 교체하고 인증·권한·감사 로그를 추가해야 합니다.
- 고객·쪽지 데이터와 API key는 실제 개인정보·비밀정보 정책에 맞게 별도 보안 저장소에서 관리해야 합니다.

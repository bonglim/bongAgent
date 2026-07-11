# Bong에이전트 MVP

Bong에이전트는 오늘 처리해야 할 ToDo, 사내쪽지, 사후관리 고객을 한 화면에서 관리하고, 자연어 명령으로 ToDo를 생성/수정/삭제할 수 있는 개인 업무 비서 MVP입니다.

## 프로젝트 구조

```text
.
├── README.md
├── agent.md              # MVP 요구사항/구현 지침 원문
├── agent_han.md          # 한국어 상세 구현 지침
├── .env.example          # 로컬 환경변수 예시(.env는 Git 제외)
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── __init__.py
│   │   ├── agent.py          # 기존 import 경로 유지용 orchestration re-export
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── orchestrator.py    # 최상위 채팅 orchestration agent
│   │   │   ├── shared.py          # AgentContext, DomainAgent, helper
│   │   │   ├── message_agent.py   # 사내쪽지 관리/우선순위 추천 sub-agent
│   │   │   ├── customer_agent.py  # 사후관리 고객 관리 sub-agent
│   │   │   ├── todo_agent.py      # ToDo 관리 sub-agent
│   │   │   └── llm_agent.py       # 일반 LLM 질문답변 fallback sub-agent
│   │   ├── config.py         # .env 기반 환경 설정
│   │   ├── llm_settings.py   # LLM 모델 목록/기본값/key env 매핑
│   │   ├── llm_provider.py   # Gemini/OpenAI/mock LLM provider
│   │   ├── main.py           # FastAPI 라우터와 API 엔드포인트
│   │   ├── models.py         # API 요청/응답 Pydantic 모델
│   │   └── repository.py     # 로컬 JSON 저장소 접근 계층
│   └── data/
│       ├── todos.json        # ToDo Kanban 데이터
│       ├── messages.json     # 사내쪽지 데이터
│       ├── customers.json    # 사후관리 고객 데이터
│       ├── history.json      # undo/restore 히스토리
│       └── redo.json         # redo 히스토리
└── frontend/
    ├── package.json
    ├── package-lock.json
    ├── index.html
    └── src/
        ├── App.jsx           # 메인 React 애플리케이션
        ├── api.js            # 백엔드 API 클라이언트
        ├── llmSettings.js    # LLM 콤보박스 설정 정규화/변경 핸들러
        ├── main.jsx          # React 진입점
        ├── styles.css        # KB 프리미엄 업무 시스템 톤의 UI 스타일
        └── assets/
            ├── kb-logo-mark.png
            ├── profile-avatar.png
            └── profile-avatar.svg
```

`backend/.venv`, `frontend/node_modules`, `frontend/dist`, `.env`는 로컬 실행 산출물 또는 개인 설정 파일이므로 Git 관리 대상에서 제외합니다.

## Agent 구조

우측 채팅창 입력은 `POST /api/assistant/command`로 백엔드에 전달되고, `backend/app/agents/orchestrator.py`의 `RuleBasedAssistantAgent`가 LangGraph 형식의 orchestrator 역할을 합니다. API 계약을 유지하기 위해 `backend/app/agent.py`는 기존 import 경로를 보존하는 re-export 파일로 남겨두었습니다.

```text
backend/
  app/
    agent.py                               # RuleBasedAssistantAgent re-export
    agents/
      orchestrator.py
        RuleBasedAssistantAgent            # LangGraph 형식 최상위 orchestrator
      shared.py
        AgentContext                       # agent 간 공유 요청 context
        DomainAgent                        # 도메인 agent Protocol
      message_agent.py
        InternalMessageManagementAgent     # 사내쪽지 조회/등록/삭제
        InternalMessagePriorityRecommendationAgent
      customer_agent.py
        AftercareCustomerManagementAgent   # 사후관리 고객 조회/등록/삭제
      todo_agent.py
        TodoManagementAgent                # ToDo 생성/수정/삭제
      llm_agent.py
        LLMQuestionAnswerAgent             # 일반 LLM 질문 답변 fallback
```

`orchestrator.py`는 `OrchestratorState`를 공유 상태로 사용하고, `message`, `customer`, `todo`, `llm` node를 조건부 edge로 연결합니다. `langgraph`가 설치되어 있으면 실제 `StateGraph`를 사용하고, 설치 전 로컬 실행 환경에서는 같은 `invoke()` 계약의 fallback graph로 동작합니다.

라우팅 우선순위:

1. `InternalMessageManagementAgent`
   - `사내쪽지`, `쪽지`, `메시지` 같은 도메인 키워드와 `등록`, `삭제`, `목록` 등의 동작 키워드를 감지합니다.
   - `JsonRepository.create_message`, `delete_message`, `list_messages`를 호출합니다.
2. `AftercareCustomerManagementAgent`
   - `사후고객`, `사후관리`, `고객관리`, `고객` 키워드와 관리 동작을 감지합니다.
   - `JsonRepository.create_customer`, `delete_customer`, `list_customers`를 호출합니다.
3. `TodoManagementAgent`
   - 기존 자연어 ToDo 명령을 처리합니다.
   - `추가`, `등록`, `할일`, `todo`, `ToDo`는 ToDo 생성으로, `진행중`, `완료`, `변경`은 수정으로, `삭제`, `지워`, `제거`는 삭제로 분류합니다.
4. `LLMQuestionAnswerAgent`
   - 위 agent가 처리하지 않는 일반 질문을 선택된 LLM provider로 전달합니다.

예시 흐름:

```text
사용자 입력
  ↓
frontend/src/App.jsx submitChat()
  ↓
frontend/src/api.js sendAssistantCommand()
  ↓
backend/app/main.py /api/assistant/command
  ↓
RuleBasedAssistantAgent.handle()
  ↓
도메인별 agent.can_handle()
  ↓
선택된 agent.handle()
  ↓
AssistantCommandResponse 반환
```

## 소스 문서화 기준

이 프로젝트는 코드 구조를 수업/시연 환경에서 바로 설명할 수 있도록 다음 기준으로 주석과 타입 정보를 유지합니다.

- Python backend
  - 모든 모듈에는 파일 역할을 설명하는 module docstring을 둡니다.
  - 모든 class/function/method에는 docstring을 둡니다.
  - 모든 함수 인자와 반환값에는 type annotation을 둡니다.
  - 저장소, agent, provider처럼 책임이 큰 클래스에는 생성자 docstring과 핵심 의사결정 주석을 둡니다.
  - 단순 대입 설명 같은 반복 주석은 피하고, 라우팅 순서, fallback, 히스토리 저장처럼 동작 의도가 중요한 부분에만 주석을 둡니다.
- Frontend
  - React 컴포넌트에는 역할 설명 주석을 둡니다.
  - props가 많은 컴포넌트와 API client 함수에는 JSDoc `@param` annotation을 둡니다.
  - TypeScript를 쓰지 않는 대신 `TodoItem`, `SourceRecord`, `AgentApiSpec` 같은 JSDoc typedef로 주요 데이터 구조를 문서화합니다.
  - CSS는 큰 화면 영역이나 기능 단위로 섹션 주석을 유지합니다.

## 설정 파일

환경 설정은 `.env`로 분리합니다. 먼저 예시 파일을 복사하세요.

```bash
cp .env.example .env
```

주요 설정:

```env
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash
OPENAI_API_KEY=
LLM_PROVIDER=auto
LLM_MODELS=gemini-2.5-flash|gemini-2.5-flash|gemini|GEMINI_API_KEY;gemini-3.5-flash|gemini-3.5-flash|gemini|GEMINI_API_KEY;gpt5.5|gpt5.5|openai|OPENAI_API_KEY;gpt-4o-mini|GPT4o-mini|openai|GPT4O_MINI_API_KEY
DEFAULT_LLM_MODEL=gemini-3.5-flash
BACKEND_CORS_ORIGINS=http://localhost:5173
VITE_API_BASE_URL=http://localhost:8000
```

채팅창 우측상단의 LLM 콤보박스는 백엔드의 `GET /api/llm/models` 응답으로 구성됩니다. 모델 목록은 소스코드가 아니라 `.env`의 `LLM_MODELS`로 관리합니다.

`LLM_MODELS` 형식:

```text
model_id|화면표시명|provider|API_KEY_ENV_NAME;...
```

예를 들어 새 OpenAI 계열 모델을 추가하려면 `.env`만 다음처럼 바꾸면 됩니다.

```env
LLM_MODELS=gemini-3.5-flash|gemini-3.5-flash|gemini|GEMINI_API_KEY;new-model|새 모델|openai|NEW_MODEL_API_KEY
DEFAULT_LLM_MODEL=new-model
NEW_MODEL_API_KEY=
```

`provider`는 현재 `gemini`, `google`, `openai`를 지원합니다. `API_KEY_ENV_NAME`에는 해당 모델이 사용할 API 키 환경변수명을 넣습니다. `LLM_PROVIDER=auto`와 각 API 키가 설정되어 있으면 선택된 모델에 맞춰 Gemini 또는 OpenAI API를 호출합니다. API 키가 없거나 `LLM_PROVIDER=mock`이면 mock 응답으로 동작합니다.

## 백엔드 실행 방법

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

백엔드 확인:

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/todos
```

## 프론트엔드 실행 방법

다른 터미널에서 실행하세요.

```bash
cd frontend
npm install
npm run dev
```

브라우저에서 `http://localhost:5173`으로 접속합니다.

## 주요 기능

- ToDo Kanban: `할일`, `진행중`, `완료` 상태별 업무 표시
- Drag & Drop: ToDo 카드를 다른 상태 컬럼으로 이동
- ToDo CRUD: 생성, 수정, 삭제, 상세 모달
- 사내쪽지 mock list: 우선순위 정렬 및 ToDo 전환
- 사후관리 고객 mock list: 우선순위 정렬 및 ToDo 전환
- 자연어 명령: ToDo 추가/상태 수정/삭제 규칙 기반 처리
- LLM 채팅 fallback: ToDo 명령이 아니면 선택한 Gemini/OpenAI 모델 또는 mock LLM provider 응답

## 자연어 명령 예시

```text
오늘 오후 3시에 김민수 고객에게 전화하기 추가해줘
김민수 고객 전화 업무를 진행중으로 바꿔줘
오전 회의 준비 업무 삭제해줘
고객에게 보낼 만기 안내 문구 작성해줘
```

## API 요약

```http
GET    /api/todos
POST   /api/todos
PATCH  /api/todos/{todo_id}
DELETE /api/todos/{todo_id}
GET    /api/messages
GET    /api/customers/aftercare
GET    /api/llm/models
POST   /api/todos/from-message/{message_id}
POST   /api/todos/from-customer/{customer_id}
POST   /api/assistant/command
```

## 개발 참고

- 데이터는 `backend/data/*.json`에 저장됩니다.
- MVP에서는 인증/권한, 실제 사내 시스템 연동, 실제 고객 개인정보 연동을 제외했습니다.
- 확장 시 `JsonRepository`를 DB repository로 교체하고, `LLMProvider`를 Gemini/OpenAI/LangChain/LangGraph 기반 구현으로 교체하는 구조를 권장합니다.

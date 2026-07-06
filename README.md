# Bong에이전트 MVP

Bong에이전트는 오늘 처리해야 할 ToDo, 사내쪽지, 사후관리 고객을 한 화면에서 관리하고, 자연어 명령으로 ToDo를 생성/수정/삭제할 수 있는 개인 업무 비서 MVP입니다.

## 프로젝트 구조

```text
backend/
  app/
    agent.py          # 규칙 기반 자연어 명령 처리
    config.py         # .env 기반 환경 설정
    llm_provider.py   # 향후 GPT-5/LangChain/LangGraph 확장용 Provider
    main.py           # FastAPI 라우터와 API 엔드포인트
    models.py         # API 요청/응답 데이터 모델
    repository.py     # 로컬 JSON 저장소 접근 계층
  data/
    todos.json
    messages.json
    customers.json
frontend/
  src/
    api.js            # 백엔드 API 클라이언트
    App.jsx           # 메인 React 애플리케이션
    styles.css        # KB 프리미엄 업무 시스템 톤의 UI 스타일
```

## 설정 파일

환경 설정은 `.env`로 분리합니다. 먼저 예시 파일을 복사하세요.

```bash
cp .env.example .env
```

주요 설정:

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.2
LLM_PROVIDER=gpt
BACKEND_CORS_ORIGINS=http://localhost:5173
VITE_API_BASE_URL=http://localhost:8000
```

`LLM_PROVIDER=gpt`와 `OPENAI_API_KEY`가 설정되어 있으면 채팅 fallback은 OpenAI Responses API를 실제 호출합니다. API 키가 없거나 `LLM_PROVIDER=mock`이면 mock 응답으로 동작합니다.

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
- GPT 채팅 fallback: ToDo 명령이 아니면 mock LLM provider 응답

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
POST   /api/todos/from-message/{message_id}
POST   /api/todos/from-customer/{customer_id}
POST   /api/assistant/command
```

## 개발 참고

- 데이터는 `backend/data/*.json`에 저장됩니다.
- MVP에서는 인증/권한, 실제 사내 시스템 연동, 실제 고객 개인정보 연동을 제외했습니다.
- 확장 시 `JsonRepository`를 DB repository로 교체하고, `LLMProvider`를 OpenAI/LangChain/LangGraph 기반 구현으로 교체하는 구조를 권장합니다.

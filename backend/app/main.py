"""Bong에이전트 MVP의 FastAPI 애플리케이션 진입점.

이 모듈은 CORS 설정, 의존성 주입 함수, REST API 라우터를 정의한다. 실제
데이터 접근은 ``JsonRepository``가 담당하고, 자연어 명령 처리는
``RuleBasedAssistantAgent``가 담당하도록 분리한다.

실행 예시::

    cd backend
    .venv/bin/uvicorn app.main:app --port 8000

상태 확인은 ``GET /api/health``, 채팅 명령은 ``POST /api/assistant/command``로
호출한다.
"""

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .agent import RuleBasedAssistantAgent
from .agents.customer_agent import AftercareCustomerManagementAgent, AftercareCustomerPriorityRecommendationAgent
from .agents.llm_agent import LLMQuestionAnswerAgent
from .agents.message_agent import InternalMessageManagementAgent, InternalMessagePriorityRecommendationAgent
from .agents.shared import AgentContext, DomainAgent
from .agents.todo_agent import TodoManagementAgent
from .config import Settings, get_settings
from .llm_settings import public_llm_models
from .llm_provider import build_llm_provider
from .observability import build_langfuse_tracing
from .models import AftercareCustomer, AftercareCustomerCreate, AftercareCustomerUpdate, AgentInvokeRequest, AssistantCommandRequest, AssistantCommandResponse, CustomerPriorityRecommendationRequest, InternalMessage, InternalMessageCreate, InternalMessageUpdate, Todo, TodoCreate, TodoUpdate
from .repository import JsonRepository


app = FastAPI(title="Bong에이전트 API", version="0.1.0")
settings = get_settings()

AGENT_API_SPECS = [
    {
        "id": "orchestrator",
        "name": "Orchestration Agent",
        "description": "입력 의도를 판별해 적절한 sub-agent로 라우팅합니다.",
        "method": "POST",
        "endpoint": "/api/agents/orchestrator/invoke",
        "request_body": {"message": "string", "model": "string | null"},
        "sample_message": "쪽지 우선순위 설정해줘",
        "related_apis": [
            {"method": "POST", "endpoint": "/api/assistant/command", "description": "채팅창 자연어 명령을 orchestrator로 전달"},
            {"method": "GET", "endpoint": "/api/agents", "description": "설정 팝업용 agent API metadata 조회"},
            {"method": "GET", "endpoint": "/api/history", "description": "명령 처리 후 히스토리 상태 조회"},
        ],
    },
    {
        "id": "message",
        "name": "사내쪽지관리 Agent",
        "description": "사내쪽지 조회, 등록, 삭제와 우선순위 추천 sub-agent 위임을 처리합니다.",
        "method": "POST",
        "endpoint": "/api/agents/message/invoke",
        "request_body": {"message": "string", "model": "string | null"},
        "sample_message": "사내쪽지 목록 보여줘",
        "related_apis": [
            {"method": "GET", "endpoint": "/api/messages", "description": "사내쪽지 목록 조회"},
            {"method": "POST", "endpoint": "/api/messages", "description": "사내쪽지 등록"},
            {"method": "PATCH", "endpoint": "/api/messages/{message_id}", "description": "사내쪽지 우선순위 수정"},
            {"method": "DELETE", "endpoint": "/api/messages/{message_id}", "description": "사내쪽지 삭제"},
            {"method": "POST", "endpoint": "/api/todos/from-message/{message_id}", "description": "사내쪽지를 ToDo로 전환"},
        ],
    },
    {
        "id": "message-priority",
        "name": "사내쪽지 우선순위 추천 Sub-agent",
        "description": "LLM 또는 fallback 규칙으로 사내쪽지 우선순위를 추천하고 저장합니다.",
        "method": "POST",
        "endpoint": "/api/agents/message-priority/invoke",
        "request_body": {"message": "string", "model": "string | null"},
        "sample_message": "쪽지 우선순위 설정해줘",
        "related_apis": [
            {"method": "GET", "endpoint": "/api/messages", "description": "우선순위 추천 대상 쪽지 조회"},
            {"method": "PATCH", "endpoint": "/api/messages/{message_id}", "description": "추천된 쪽지 우선순위 저장"},
        ],
    },
    {
        "id": "customer",
        "name": "사후고객관리 Agent",
        "description": "사후관리 고객 조회, 등록, 삭제를 처리합니다.",
        "method": "POST",
        "endpoint": "/api/agents/customer/invoke",
        "request_body": {"message": "string", "model": "string | null"},
        "sample_message": "사후관리 고객 목록 보여줘",
        "related_apis": [
            {"method": "GET", "endpoint": "/api/customers/aftercare", "description": "사후관리 고객 목록 조회"},
            {"method": "POST", "endpoint": "/api/customers/aftercare", "description": "사후관리 고객 등록"},
            {"method": "PATCH", "endpoint": "/api/customers/aftercare/{customer_id}", "description": "고객 우선순위 수정"},
            {"method": "DELETE", "endpoint": "/api/customers/aftercare/{customer_id}", "description": "사후관리 고객 삭제"},
            {"method": "POST", "endpoint": "/api/todos/from-customer/{customer_id}", "description": "고객 레코드를 ToDo로 전환"},
        ],
    },
    {
        "id": "todo",
        "name": "ToDo관리 Agent",
        "description": "자연어 ToDo 생성, 상태 변경, 삭제를 처리합니다.",
        "method": "POST",
        "endpoint": "/api/agents/todo/invoke",
        "request_body": {"message": "string", "model": "string | null"},
        "sample_message": "오늘 오후 3시에 김민수 고객 전화 추가해줘",
        "related_apis": [
            {"method": "GET", "endpoint": "/api/todos", "description": "ToDo 목록 조회"},
            {"method": "POST", "endpoint": "/api/todos", "description": "ToDo 생성"},
            {"method": "PATCH", "endpoint": "/api/todos/{todo_id}", "description": "ToDo 상태, 우선순위, 내용 수정"},
            {"method": "DELETE", "endpoint": "/api/todos/{todo_id}", "description": "ToDo 삭제"},
            {"method": "GET", "endpoint": "/api/history", "description": "ToDo 변경 이력 조회"},
        ],
    },
    {
        "id": "llm",
        "name": "LLM 질문답변 Agent",
        "description": "업무 명령이 아닌 일반 질문을 선택된 LLM provider로 전달합니다.",
        "method": "POST",
        "endpoint": "/api/agents/llm/invoke",
        "request_body": {"message": "string", "model": "string | null"},
        "sample_message": "고객에게 보낼 만기 안내 문구 작성해줘",
        "related_apis": [
            {"method": "GET", "endpoint": "/api/llm/models", "description": "선택 가능한 LLM 모델 조회"},
            {"method": "POST", "endpoint": "/api/assistant/command", "description": "일반 질문을 채팅창에서 LLM agent로 라우팅"},
        ],
    },
]

API_METHOD_SUMMARY = [
    {
        "method": "GET",
        "summary": "조회 API",
        "description": "대시보드, 설정 팝업, 모델 선택기에 필요한 데이터를 읽습니다.",
        "endpoints": [
            {"endpoint": "/api/health", "description": "서비스 상태 확인"},
            {"endpoint": "/api/llm/models", "description": "LLM 모델 옵션 조회"},
            {"endpoint": "/api/agents", "description": "Agent API 정보와 메서드 요약 조회"},
            {"endpoint": "/api/todos", "description": "ToDo 목록 조회"},
            {"endpoint": "/api/history", "description": "undo/redo 히스토리 조회"},
            {"endpoint": "/api/messages", "description": "사내쪽지 목록 조회"},
            {"endpoint": "/api/customers/aftercare", "description": "사후관리 고객 목록 조회"},
        ],
    },
    {
        "method": "POST",
        "summary": "생성/실행 API",
        "description": "새 데이터를 만들거나 agent, history, 자연어 명령을 실행합니다.",
        "endpoints": [
            {"endpoint": "/api/agents/{agent_id}/invoke", "description": "orchestrator 또는 sub-agent 직접 호출"},
            {"endpoint": "/api/assistant/command", "description": "채팅창 자연어 명령 처리"},
            {"endpoint": "/api/todos", "description": "ToDo 생성"},
            {"endpoint": "/api/todos/from-message/{message_id}", "description": "사내쪽지를 ToDo로 전환"},
            {"endpoint": "/api/todos/from-customer/{customer_id}", "description": "사후관리 고객을 ToDo로 전환"},
            {"endpoint": "/api/messages", "description": "사내쪽지 등록"},
            {"endpoint": "/api/customers/aftercare", "description": "사후관리 고객 등록"},
            {"endpoint": "/api/history/undo", "description": "이전 상태로 되돌리기"},
            {"endpoint": "/api/history/redo", "description": "되돌린 상태 다시 적용"},
            {"endpoint": "/api/history/restore/{history_id}", "description": "선택 히스토리로 복원"},
        ],
    },
    {
        "method": "PATCH",
        "summary": "부분 수정 API",
        "description": "기존 업무, 쪽지, 고객의 일부 필드를 저장합니다.",
        "endpoints": [
            {"endpoint": "/api/todos/{todo_id}", "description": "ToDo 상태, 우선순위, 내용 수정"},
            {"endpoint": "/api/messages/{message_id}", "description": "사내쪽지 우선순위 수정"},
            {"endpoint": "/api/customers/aftercare/{customer_id}", "description": "사후관리 고객 우선순위 수정"},
        ],
    },
    {
        "method": "DELETE",
        "summary": "삭제 API",
        "description": "사용자가 선택한 업무, 쪽지, 고객 데이터를 삭제합니다.",
        "endpoints": [
            {"endpoint": "/api/todos/{todo_id}", "description": "ToDo 삭제"},
            {"endpoint": "/api/messages/{message_id}", "description": "사내쪽지 삭제"},
            {"endpoint": "/api/customers/aftercare/{customer_id}", "description": "사후관리 고객 삭제"},
        ],
    },
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_repository(settings_obj: Settings = Depends(get_settings)) -> JsonRepository:
    """라우터에서 사용할 저장소 의존성을 만든다.

    Args:
        settings_obj: FastAPI 의존성 주입으로 전달되는 런타임 설정.

    Returns:
        현재 설정의 데이터 디렉터리를 사용하는 ``JsonRepository``.
    """
    # 현재 설정의 데이터 디렉터리를 사용하는 JSON 저장소 의존성을 만든다.

    return JsonRepository(settings_obj.data_dir)


def get_agent(repository: JsonRepository = Depends(get_repository)) -> RuleBasedAssistantAgent:
    """저장소와 LLM provider를 조합해 assistant agent를 만든다."""
    # 저장소와 LLM provider를 조합해 요청별 assistant agent를 만든다.

    tracing = build_langfuse_tracing(settings)
    llm_provider = build_llm_provider(settings, tracing.client if tracing else None)
    return RuleBasedAssistantAgent(repository, llm_provider, tracing.handler if tracing else None)


def _get_agent_by_id(agent_id: str, repository: JsonRepository, settings_obj: Settings) -> DomainAgent | RuleBasedAssistantAgent | None:
    """agent id에 맞는 orchestrator 또는 sub-agent 인스턴스를 만든다."""

    tracing = build_langfuse_tracing(settings_obj)
    llm_provider = build_llm_provider(settings_obj, tracing.client if tracing else None)
    agents = {
        "orchestrator": RuleBasedAssistantAgent(
            repository,
            llm_provider,
            tracing.handler if tracing else None,
        ),
        "message": InternalMessageManagementAgent(repository, llm_provider),
        "message-priority": InternalMessagePriorityRecommendationAgent(repository, llm_provider),
        "customer": AftercareCustomerManagementAgent(repository, llm_provider),
        "customer-priority": AftercareCustomerPriorityRecommendationAgent(repository, llm_provider),
        "todo": TodoManagementAgent(repository),
        "llm": LLMQuestionAnswerAgent(llm_provider),
    }
    return agents.get(agent_id)


@app.get("/api/health")
def health_check() -> dict:
    """로컬 smoke test와 배포 상태 확인용 최소 health payload를 반환한다."""
    # 로컬 실행과 배포 상태 확인을 위한 최소 health payload를 반환한다.

    return {"status": "ok", "service": "Bong에이전트"}


@app.get("/api/llm/models")
def list_llm_models(settings_obj: Settings = Depends(get_settings)) -> dict:
    """프론트엔드 모델 선택기에 필요한 LLM 모델 옵션을 반환한다."""
    # 브라우저에는 모델 id/label/provider만 내려주고 key 정보는 숨긴다.

    return public_llm_models(settings_obj)


@app.get("/api/agents")
def list_agent_apis() -> dict:
    """설정 팝업에 표시할 agent API 목록과 호출 정보를 반환한다."""
    # 프론트엔드가 agent별 API UI와 HTTP method별 요약을 구성할 수 있도록 metadata를 내려준다.

    return {
        "info_endpoint": {"method": "GET", "endpoint": "/api/agents"},
        "invoke_pattern": {"method": "POST", "endpoint": "/api/agents/{agent_id}/invoke"},
        "method_summary": API_METHOD_SUMMARY,
        "agents": AGENT_API_SPECS,
    }


@app.post("/api/agents/{agent_id}/invoke", response_model=AssistantCommandResponse)
def invoke_agent_api(
    agent_id: str,
    payload: AgentInvokeRequest,
    repository: JsonRepository = Depends(get_repository),
    settings_obj: Settings = Depends(get_settings),
) -> AssistantCommandResponse:
    """orchestrator 또는 지정한 sub-agent를 직접 호출한다."""
    # 설정 팝업의 agent API 테스트 UI에서 사용하는 직접 호출 endpoint다.

    agent = _get_agent_by_id(agent_id, repository, settings_obj)
    if not agent:
        raise HTTPException(status_code=404, detail="에이전트를 찾을 수 없습니다.")
    if agent_id == "orchestrator":
        return agent.handle(payload.message, payload.model)
    return agent.handle(AgentContext(message=payload.message.strip(), model=payload.model))


@app.get("/api/todos", response_model=list[Todo])
def list_todos(repository: JsonRepository = Depends(get_repository)) -> list[Todo]:
    """Kanban 대시보드에 표시할 전체 ToDo 목록을 반환한다."""
    # Kanban 보드에 표시할 전체 ToDo 목록을 반환한다.

    return repository.list_todos()


@app.get("/api/history")
def list_history(repository: JsonRepository = Depends(get_repository)) -> dict:
    """undo, redo, 시점 이동에 사용할 대시보드 단기 히스토리를 반환한다."""
    # 화면의 최근 기억/히스토리 모달에서 사용할 변경 이력을 반환한다.

    return repository.list_history()


@app.post("/api/history/undo")
def undo_history(repository: JsonRepository = Depends(get_repository)) -> dict:
    """대시보드를 가장 최근 변경 이전 스냅샷으로 되돌린다."""
    # 가장 최근 변경 전 상태로 되돌린다.

    message, todos = repository.undo()
    return {"message": message, "todos": todos, "history": repository.list_history()}


@app.post("/api/history/redo")
def redo_history(repository: JsonRepository = Depends(get_repository)) -> dict:
    """가장 최근 redo 스냅샷을 다시 적용한다."""
    # 되돌렸던 변경을 다시 적용한다.

    message, todos = repository.redo()
    return {"message": message, "todos": todos, "history": repository.list_history()}


@app.post("/api/history/restore/{history_id}")
def restore_history(history_id: str, repository: JsonRepository = Depends(get_repository)) -> dict:
    """선택한 히스토리 스냅샷으로 대시보드를 복구한다."""
    # 히스토리 목록에서 고른 시점으로 업무판을 이동한다.

    restored, message, todos = repository.restore_history(history_id)
    if not restored:
        raise HTTPException(status_code=404, detail=message)
    return {"message": message, "todos": todos, "history": repository.list_history()}


@app.post("/api/todos", response_model=Todo)
def create_todo(payload: TodoCreate, repository: JsonRepository = Depends(get_repository)) -> Todo:
    """프론트엔드 수동 입력 폼에서 전달된 payload로 ToDo를 생성한다."""
    # 프론트 모달에서 전달된 payload로 새 ToDo를 생성한다.

    return repository.create_todo(payload)


@app.patch("/api/todos/{todo_id}", response_model=Todo)
def update_todo(todo_id: str, payload: TodoUpdate, repository: JsonRepository = Depends(get_repository)) -> Todo:
    """카드 드래그, 모달 수정, 명령 처리 후 ToDo 일부 필드를 수정한다."""
    # 드래그, 모달 수정, 자연어 명령에서 발생한 ToDo 변경을 저장한다.

    updated = repository.update_todo(todo_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="ToDo를 찾을 수 없습니다.")
    return updated


@app.delete("/api/todos/{todo_id}")
def delete_todo(todo_id: str, repository: JsonRepository = Depends(get_repository)) -> dict:
    """ToDo를 삭제하고 원천 mock 레코드는 연결 해제 상태로 보존한다."""
    # ToDo를 삭제하고 없으면 404 오류를 반환한다.

    deleted = repository.delete_todo(todo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="ToDo를 찾을 수 없습니다.")
    return {"deleted": True, "id": todo_id}


@app.get("/api/messages", response_model=list[InternalMessage])
def list_messages(repository: JsonRepository = Depends(get_repository)) -> list[InternalMessage]:
    """우선순위 순서로 정렬된 mock 사내쪽지 목록을 반환한다."""
    # 우선순위 패널에 표시할 mock 사내쪽지 목록을 반환한다.

    return repository.list_messages()


@app.post("/api/messages", response_model=InternalMessage)
def create_message(payload: InternalMessageCreate, repository: JsonRepository = Depends(get_repository)) -> InternalMessage:
    """사용자가 입력한 사내쪽지를 새 레코드로 등록한다."""
    # 등록된 사내쪽지는 우선순위 패널에 즉시 표시되고 이후 ToDo로 전환할 수 있다.

    return repository.create_message(payload)


@app.patch("/api/messages/{message_id}", response_model=InternalMessage)
def update_message(message_id: str, payload: InternalMessageUpdate, repository: JsonRepository = Depends(get_repository)) -> InternalMessage:
    """사내쪽지의 우선순위 같은 부분 필드를 수정한다."""
    # 별 아이콘 클릭이나 LLM 추천 결과로 바뀐 사내쪽지 priority를 저장한다.

    updated = repository.update_message(message_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="사내쪽지를 찾을 수 없습니다.")
    return updated


@app.delete("/api/messages/{message_id}")
def delete_message(message_id: str, repository: JsonRepository = Depends(get_repository)) -> dict:
    """사내쪽지를 삭제하고 연결된 ToDo의 원천 링크를 정리한다."""
    # 삭제 대상이 없으면 404를 반환하고, 있으면 messages.json에서 제거한다.

    deleted = repository.delete_message(message_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="사내쪽지를 찾을 수 없습니다.")
    return {"deleted": True, "id": message_id}


@app.get("/api/customers/aftercare", response_model=list[AftercareCustomer])
def list_aftercare_customers(repository: JsonRepository = Depends(get_repository)) -> list[AftercareCustomer]:
    """우선순위 순서로 정렬된 mock 사후관리 고객 목록을 반환한다."""
    # 우선순위 패널에 표시할 mock 사후관리 고객 목록을 반환한다.

    return repository.list_customers()


@app.post("/api/customers/aftercare/ai-recommend", response_model=AssistantCommandResponse)
def recommend_aftercare_customer_priorities(
    payload: CustomerPriorityRecommendationRequest,
    repository: JsonRepository = Depends(get_repository),
    settings_obj: Settings = Depends(get_settings),
) -> AssistantCommandResponse:
    """선택한 LLM으로 사후관리 고객 우선순위와 선정 사유를 추천한다."""

    tracing = build_langfuse_tracing(settings_obj)
    llm_provider = build_llm_provider(settings_obj, tracing.client if tracing else None)
    agent = AftercareCustomerPriorityRecommendationAgent(repository, llm_provider)
    return agent.handle(AgentContext(message="사후관리 고객 우선순위 추천 및 재정렬", model=payload.model))


@app.post("/api/customers/aftercare", response_model=AftercareCustomer)
def create_aftercare_customer(
    payload: AftercareCustomerCreate,
    repository: JsonRepository = Depends(get_repository),
) -> AftercareCustomer:
    """사용자가 입력한 사후관리 고객을 새 레코드로 등록한다."""
    # 등록된 고객은 고객관리 상세 팝업과 우선순위 패널에 즉시 표시된다.

    return repository.create_customer(payload)


@app.patch("/api/customers/aftercare/{customer_id}", response_model=AftercareCustomer)
def update_aftercare_customer(
    customer_id: str,
    payload: AftercareCustomerUpdate,
    repository: JsonRepository = Depends(get_repository),
) -> AftercareCustomer:
    """사후관리 고객의 우선순위 같은 부분 필드를 수정한다."""
    # 별 아이콘 클릭이나 LLM 추천 결과로 바뀐 고객 priority를 저장한다.

    updated = repository.update_customer(customer_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="고객 정보를 찾을 수 없습니다.")
    return updated


@app.delete("/api/customers/aftercare/{customer_id}")
def delete_aftercare_customer(customer_id: str, repository: JsonRepository = Depends(get_repository)) -> dict:
    """사후관리 고객을 삭제하고 연결된 ToDo의 원천 링크를 정리한다."""
    # 삭제 대상이 없으면 404를 반환하고, 있으면 customers.json에서 제거한다.

    deleted = repository.delete_customer(customer_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="고객 정보를 찾을 수 없습니다.")
    return {"deleted": True, "id": customer_id}


@app.post("/api/todos/from-message/{message_id}", response_model=Todo)
def create_todo_from_message(message_id: str, repository: JsonRepository = Depends(get_repository)) -> Todo:
    """사내쪽지를 연결된 ToDo로 전환한다."""
    # 선택한 사내쪽지를 중복 없이 연결 ToDo로 전환한다.

    todo, message = repository.create_todo_from_message(message_id)
    if not todo:
        raise HTTPException(status_code=404, detail=message)
    return todo


@app.post("/api/todos/from-customer/{customer_id}", response_model=Todo)
def create_todo_from_customer(customer_id: str, repository: JsonRepository = Depends(get_repository)) -> Todo:
    """사후관리 고객 레코드를 연결된 ToDo로 전환한다."""
    # 선택한 사후관리 고객을 중복 없이 연결 ToDo로 전환한다.

    todo, message = repository.create_todo_from_customer(customer_id)
    if not todo:
        raise HTTPException(status_code=404, detail=message)
    return todo


@app.post("/api/assistant/command", response_model=AssistantCommandResponse)
def run_assistant_command(
    payload: AssistantCommandRequest,
    agent: RuleBasedAssistantAgent = Depends(get_agent),
) -> AssistantCommandResponse:
    """채팅 패널에서 넘어온 자연어 명령을 처리한다."""
    # 채팅 패널의 자연어 입력을 agent에 위임하고 구조화된 응답을 반환한다.

    return agent.handle(payload.message, payload.model)

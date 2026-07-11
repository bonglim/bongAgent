"""Bong에이전트 MVP의 FastAPI 애플리케이션 진입점.

이 모듈은 CORS 설정, 의존성 주입 함수, REST API 라우터를 정의한다. 실제
데이터 접근은 ``JsonRepository``가 담당하고, 자연어 명령 처리는
``RuleBasedAssistantAgent``가 담당하도록 분리한다.
"""

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .agent import RuleBasedAssistantAgent
from .config import Settings, get_settings
from .llm_settings import public_llm_models
from .llm_provider import build_llm_provider
from .models import AftercareCustomer, AftercareCustomerCreate, AftercareCustomerUpdate, AssistantCommandRequest, AssistantCommandResponse, InternalMessage, InternalMessageCreate, InternalMessageUpdate, Todo, TodoCreate, TodoUpdate
from .repository import JsonRepository


app = FastAPI(title="Bong에이전트 API", version="0.1.0")
settings = get_settings()

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

    return RuleBasedAssistantAgent(repository, build_llm_provider(settings))


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


@app.get("/api/messages")
def list_messages(repository: JsonRepository = Depends(get_repository)) -> list:
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


@app.get("/api/customers/aftercare")
def list_aftercare_customers(repository: JsonRepository = Depends(get_repository)) -> list:
    """우선순위 순서로 정렬된 mock 사후관리 고객 목록을 반환한다."""
    # 우선순위 패널에 표시할 mock 사후관리 고객 목록을 반환한다.

    return repository.list_customers()


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

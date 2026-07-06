"""FastAPI application for Bong에이전트 MVP."""

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .agent import RuleBasedAssistantAgent
from .config import Settings, get_settings
from .llm_provider import build_llm_provider
from .models import AssistantCommandRequest, AssistantCommandResponse, Todo, TodoCreate, TodoUpdate
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
    """Build a repository dependency for route handlers."""

    return JsonRepository(settings_obj.data_dir)


def get_agent(repository: JsonRepository = Depends(get_repository)) -> RuleBasedAssistantAgent:
    """Build the assistant agent with repository and LLM provider dependencies."""

    return RuleBasedAssistantAgent(repository, build_llm_provider(settings))


@app.get("/api/health")
def health_check() -> dict:
    """Return a minimal health payload for local smoke testing."""

    return {"status": "ok", "service": "Bong에이전트"}


@app.get("/api/todos", response_model=list[Todo])
def list_todos(repository: JsonRepository = Depends(get_repository)) -> list[Todo]:
    """Return all ToDos for the Kanban dashboard."""

    return repository.list_todos()


@app.post("/api/todos", response_model=Todo)
def create_todo(payload: TodoCreate, repository: JsonRepository = Depends(get_repository)) -> Todo:
    """Create a ToDo from a manual frontend form submission."""

    return repository.create_todo(payload)


@app.patch("/api/todos/{todo_id}", response_model=Todo)
def update_todo(todo_id: str, payload: TodoUpdate, repository: JsonRepository = Depends(get_repository)) -> Todo:
    """Patch a ToDo after card drag, modal edit, or command handling."""

    updated = repository.update_todo(todo_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="ToDo를 찾을 수 없습니다.")
    return updated


@app.delete("/api/todos/{todo_id}")
def delete_todo(todo_id: str, repository: JsonRepository = Depends(get_repository)) -> dict:
    """Delete a ToDo while keeping source mock records intact."""

    deleted = repository.delete_todo(todo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="ToDo를 찾을 수 없습니다.")
    return {"deleted": True, "id": todo_id}


@app.get("/api/messages")
def list_messages(repository: JsonRepository = Depends(get_repository)) -> list:
    """Return priority-sorted mock internal messages."""

    return repository.list_messages()


@app.get("/api/customers/aftercare")
def list_aftercare_customers(repository: JsonRepository = Depends(get_repository)) -> list:
    """Return priority-sorted mock aftercare customers."""

    return repository.list_customers()


@app.post("/api/todos/from-message/{message_id}", response_model=Todo)
def create_todo_from_message(message_id: str, repository: JsonRepository = Depends(get_repository)) -> Todo:
    """Convert an internal message into a linked ToDo."""

    todo, message = repository.create_todo_from_message(message_id)
    if not todo:
        raise HTTPException(status_code=404, detail=message)
    return todo


@app.post("/api/todos/from-customer/{customer_id}", response_model=Todo)
def create_todo_from_customer(customer_id: str, repository: JsonRepository = Depends(get_repository)) -> Todo:
    """Convert an aftercare customer into a linked ToDo."""

    todo, message = repository.create_todo_from_customer(customer_id)
    if not todo:
        raise HTTPException(status_code=404, detail=message)
    return todo


@app.post("/api/assistant/command", response_model=AssistantCommandResponse)
def run_assistant_command(
    payload: AssistantCommandRequest,
    agent: RuleBasedAssistantAgent = Depends(get_agent),
) -> AssistantCommandResponse:
    """Process a natural-language command from the chat panel."""

    return agent.handle(payload.message)

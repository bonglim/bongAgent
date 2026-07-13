"""Langfuse tracing client와 LangGraph callback handler를 구성한다."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from .config import Settings


@dataclass(frozen=True)
class LangfuseTracing:
    """같은 Langfuse project를 사용하는 client와 callback handler 묶음."""

    client: Langfuse
    handler: CallbackHandler


@lru_cache(maxsize=8)
def _create_client(
    public_key: str,
    secret_key: str,
    base_url: str,
    environment: str,
) -> Langfuse:
    """동일 설정의 Langfuse client를 프로세스 안에서 재사용한다."""

    return Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=base_url,
        environment=environment,
    )


def build_langfuse_tracing(settings: Settings) -> LangfuseTracing | None:
    """public/secret key가 모두 설정된 경우에만 tracing을 활성화한다."""

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None
    client = _create_client(
        settings.langfuse_public_key,
        settings.langfuse_secret_key,
        settings.langfuse_base_url,
        settings.langfuse_tracing_environment,
    )
    # CallbackHandler는 실행별 상태를 가지므로 요청마다 새 인스턴스를 만든다.
    return LangfuseTracing(
        client=client,
        handler=CallbackHandler(public_key=settings.langfuse_public_key),
    )

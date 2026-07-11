"""사내쪽지 관리와 우선순위 추천 sub-agent."""

from __future__ import annotations

import json
import re

from ..llm_provider import LLMProvider
from ..models import AssistantCommandResponse, InternalMessage, InternalMessageCreate, LLMModel
from ..repository import JsonRepository
from .shared import AgentContext, compact_title, contains_any


class InternalMessageManagementAgent:
    """채팅에서 사내쪽지 조회, 등록, 삭제 명령을 처리한다."""

    DOMAIN_WORDS = ["사내쪽지", "쪽지", "메시지", "message"]
    CREATE_WORDS = ["등록", "추가", "생성"]
    DELETE_WORDS = ["삭제", "지워", "제거"]
    LIST_WORDS = ["목록", "조회", "보여", "확인", "찾아", "검색"]
    DETAIL_WORDS = ["내용", "상세", "본문", "자세히", "전문"]
    QUESTION_WORDS = ["뭐", "무엇", "어떤", "어때", "있어", "있나", "있니", "알려", "해야", "할까"]
    PRIORITY_WORDS = ["우선순위", "우선 순위", "중요도", "순위", "priority"]
    PRIORITY_ACTION_WORDS = ["설정", "추천", "분류", "정해", "매겨", "바꿔", "변경"]
    PRIORITY_FILTERS = {
        "high": ["high", "높음", "높은", "중요", "긴급"],
        "medium": ["medium", "보통", "중간"],
        "low": ["low", "낮음", "낮은", "공지", "참고"],
    }

    def __init__(self, repository: JsonRepository, llm_provider: LLMProvider) -> None:
        """저장소와 우선순위 추천 sub-agent 의존성을 초기화한다."""

        self.repository = repository
        self.priority_agent = InternalMessagePriorityRecommendationAgent(repository, llm_provider)

    def can_handle(self, context: AgentContext) -> bool:
        """사내쪽지 도메인 키워드와 관리 동작이 함께 있는지 확인한다."""

        message = context.message
        return contains_any(message, self.DOMAIN_WORDS) and contains_any(
            message,
            self.CREATE_WORDS
            + self.DELETE_WORDS
            + self.LIST_WORDS
            + self.DETAIL_WORDS
            + self.QUESTION_WORDS
            + self.PRIORITY_WORDS
            + self.PRIORITY_ACTION_WORDS,
        )

    def handle(self, context: AgentContext) -> AssistantCommandResponse:
        """사내쪽지 조회, 삭제, 등록 명령을 실행한다."""

        message = context.message
        if self.priority_agent.can_handle(context):
            return self.priority_agent.handle(context)
        if contains_any(message, self.DELETE_WORDS):
            return self._delete_message(message)
        if contains_any(message, self.LIST_WORDS + self.DETAIL_WORDS + self.QUESTION_WORDS):
            return self._query_messages(message)
        return self._create_message(message)

    def _create_message(self, message: str) -> AssistantCommandResponse:
        """채팅 문장을 사내쪽지 등록 payload로 변환한다."""

        title = compact_title(message, self.DOMAIN_WORDS + self.CREATE_WORDS + ["해줘"], "새 사내쪽지")
        internal_message = self.repository.create_message(
            InternalMessageCreate(
                title=title,
                sender="채팅 등록",
                received_at=self._extract_due_text(message) or "오늘",
                priority="high" if contains_any(message, ["중요", "긴급"]) else "medium",
                body=message,
            )
        )
        return AssistantCommandResponse(
            intent="create_message",
            reply=f"'{internal_message.title}' 사내쪽지를 등록했습니다.",
            result=internal_message.model_dump(mode="json"),
        )

    def _delete_message(self, message: str) -> AssistantCommandResponse:
        """문장과 가장 가까운 사내쪽지를 찾아 삭제한다."""

        target = self._find_matching_message(message)
        if not target:
            return AssistantCommandResponse(intent="needs_confirmation", reply="삭제할 사내쪽지를 찾지 못했습니다.")
        self.repository.delete_message(target.id)
        return AssistantCommandResponse(
            intent="delete_message",
            reply=f"'{target.title}' 사내쪽지를 삭제했습니다.",
            result={"deleted_id": target.id},
        )

    def _query_messages(self, command: str) -> AssistantCommandResponse:
        """내부 tool 함수처럼 사내쪽지를 조건별로 조회하고 본문까지 응답한다."""

        messages = self._filter_messages(command, self.repository.list_messages())
        if not messages:
            return AssistantCommandResponse(
                intent="query_messages",
                reply="조건에 맞는 사내쪽지를 찾지 못했습니다.",
                result={"messages": []},
            )
        detail_mode = contains_any(command, self.DETAIL_WORDS) or len(messages) == 1
        reply = self._format_message_detail_reply(messages) if detail_mode else self._format_message_list_reply(messages)
        return AssistantCommandResponse(
            intent="query_messages",
            reply=reply,
            result={"messages": [message.model_dump(mode="json") for message in messages]},
        )

    def _find_matching_message(self, message: str) -> InternalMessage | None:
        """메시지 토큰과 제목/본문이 겹치는 사내쪽지를 찾는다."""

        command_words = set(self.DOMAIN_WORDS + self.DELETE_WORDS + self.LIST_WORDS + self.DETAIL_WORDS)
        tokens = [token for token in re.split(r"\s+", message) if token and token not in command_words]
        messages = self.repository.list_messages()
        for item in messages:
            if any(token in item.title or token in item.body or token in item.sender for token in tokens):
                return item
        return messages[0] if messages else None

    def _filter_messages(self, command: str, messages: list[InternalMessage]) -> list[InternalMessage]:
        """명령문에서 우선순위와 검색어를 추출해 사내쪽지 목록을 좁힌다."""

        priority = self._extract_priority_filter(command)
        tokens = self._extract_search_tokens(command)
        filtered = [message for message in messages if not priority or message.priority == priority]
        if not tokens:
            return filtered
        matches = [
            message
            for message in filtered
            if any(token in f"{message.title} {message.sender} {message.body} {message.received_at}" for token in tokens)
        ]
        return matches

    def _extract_priority_filter(self, command: str) -> str | None:
        """채팅 문장에 포함된 우선순위 표현을 priority 값으로 변환한다."""

        for priority, words in self.PRIORITY_FILTERS.items():
            if contains_any(command, words):
                return priority
        return None

    def _extract_search_tokens(self, command: str) -> list[str]:
        """사내쪽지 조회 명령에서 도메인/동작 키워드를 제외한 검색어를 뽑는다."""

        command_words = set(
            self.DOMAIN_WORDS
            + self.LIST_WORDS
            + self.DETAIL_WORDS
            + self.QUESTION_WORDS
            + self.PRIORITY_WORDS
            + self.PRIORITY_ACTION_WORDS
            + ["해줘", "줘", "중", "관련", "대한", "있는", "받은", "오늘", "내일"]
        )
        priority_words = {word for words in self.PRIORITY_FILTERS.values() for word in words}
        raw_tokens = re.split(r"[\s,./:;!?()]+", command)
        return [
            token
            for token in raw_tokens
            if len(token) >= 2
            and not any(word in token for word in command_words)
            and not any(word in token for word in priority_words)
        ]

    def _format_message_list_reply(self, messages: list[InternalMessage]) -> str:
        """여러 사내쪽지를 채팅창에서 읽기 쉬운 목록 형태로 만든다."""

        rows = [
            f"{index}. [{message.priority}] {message.title} - {message.sender} / {message.received_at}"
            for index, message in enumerate(messages[:5], start=1)
        ]
        suffix = f"\n외 {len(messages) - 5}건이 더 있습니다." if len(messages) > 5 else ""
        return f"조건에 맞는 사내쪽지 {len(messages)}건입니다.\n" + "\n".join(rows) + suffix

    def _format_message_detail_reply(self, messages: list[InternalMessage]) -> str:
        """사내쪽지 제목, 발신자, 날짜, 본문을 포함한 상세 응답을 만든다."""

        rows = [
            (
                f"{index}. [{message.priority}] {message.title}\n"
                f"   발신: {message.sender} / 수신일: {message.received_at}\n"
                f"   내용: {message.body}"
            )
            for index, message in enumerate(messages[:3], start=1)
        ]
        suffix = f"\n외 {len(messages) - 3}건은 목록에서 확인해 주세요." if len(messages) > 3 else ""
        return f"사내쪽지 상세 {min(len(messages), 3)}건입니다.\n" + "\n".join(rows) + suffix

    def _extract_due_text(self, message: str) -> str:
        """사내쪽지 수신일로 쓸 간단한 날짜 표현을 추출한다."""

        if "내일" in message:
            return "내일"
        if "오늘" in message:
            return "오늘"
        return ""


class InternalMessagePriorityRecommendationAgent:
    """LLM을 이용해 사내쪽지 우선순위를 추천하고 저장하는 sub-agent."""

    PRIORITY_VALUES = {"high", "medium", "low"}

    def __init__(self, repository: JsonRepository, llm_provider: LLMProvider) -> None:
        """추천 결과를 저장할 repository와 추천에 사용할 LLM provider를 보관한다."""

        self.repository = repository
        self.llm_provider = llm_provider

    def can_handle(self, context: AgentContext) -> bool:
        """사내쪽지 우선순위 추천/설정 명령인지 확인한다."""

        message = context.message
        has_priority = contains_any(message, InternalMessageManagementAgent.PRIORITY_WORDS)
        has_action = contains_any(message, InternalMessageManagementAgent.PRIORITY_ACTION_WORDS)
        return has_priority and has_action

    def handle(self, context: AgentContext) -> AssistantCommandResponse:
        """LLM 추천 결과를 사내쪽지 우선순위에 반영한다."""

        messages = self.repository.list_messages()
        if not messages:
            return AssistantCommandResponse(intent="set_message_priorities", reply="우선순위를 설정할 사내쪽지가 없습니다.")

        recommendations = self._recommend_with_llm(messages, context.model)
        if not recommendations:
            recommendations = self._recommend_with_rules(messages)
        updated_messages = self.repository.update_message_priorities(recommendations)
        applied = [message for message in updated_messages if message.id in recommendations]
        summary = ", ".join(f"{message.title}: {message.priority}" for message in applied[:5])
        return AssistantCommandResponse(
            intent="set_message_priorities",
            reply=f"사내쪽지 {len(applied)}건의 우선순위를 설정했습니다. {summary}",
            result={
                "messages": [message.model_dump(mode="json") for message in updated_messages],
                "recommendations": recommendations,
            },
        )

    def _recommend_with_llm(self, messages: list[InternalMessage], model: LLMModel | None) -> dict[str, str]:
        """LLM에게 우선순위 JSON을 요청하고 유효한 값만 반환한다."""

        prompt = self._build_prompt(messages)
        response = self.llm_provider.chat(prompt, model)
        return self._parse_recommendations(response, {message.id for message in messages})

    def _build_prompt(self, messages: list[InternalMessage]) -> str:
        """LLM이 JSON만 반환하도록 사내쪽지 요약 prompt를 만든다."""

        rows = [
            {
                "id": message.id,
                "title": message.title,
                "sender": message.sender,
                "received_at": message.received_at,
                "body": message.body,
                "current_priority": message.priority,
            }
            for message in messages
        ]
        return (
            "은행 직원의 사내쪽지 우선순위를 high, medium, low 중 하나로 추천하세요. "
            "긴급 처리, 준법/감사/보안, 고객 영향, 오늘 처리 필요성이 크면 high입니다. "
            "반드시 설명 없이 JSON 객체만 반환하세요. 형식: {\"message_id\":\"high|medium|low\"}. "
            f"사내쪽지 목록: {json.dumps(rows, ensure_ascii=False)}"
        )

    def _parse_recommendations(self, response: str, allowed_ids: set[str]) -> dict[str, str]:
        """LLM 응답에서 JSON 객체를 찾아 priority mapping으로 변환한다."""

        match = re.search(r"\{.*\}", response, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
        return {
            message_id: priority
            for message_id, priority in parsed.items()
            if message_id in allowed_ids and priority in self.PRIORITY_VALUES
        }

    def _recommend_with_rules(self, messages: list[InternalMessage]) -> dict[str, str]:
        """LLM 응답을 파싱하지 못했을 때 쓰는 결정적 fallback 추천."""

        high_words = ["긴급", "중요", "보안", "준법", "감사", "고액", "VIP", "오늘", "제출", "확인"]
        low_words = ["공지", "참고", "안내"]
        recommendations = {}
        for message in messages:
            text = f"{message.title} {message.sender} {message.body}"
            if contains_any(text, high_words):
                recommendations[message.id] = "high"
            elif contains_any(text, low_words):
                recommendations[message.id] = "low"
            else:
                recommendations[message.id] = "medium"
        return recommendations

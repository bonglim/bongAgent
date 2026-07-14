"""사내쪽지 관리와 우선순위 추천 sub-agent."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

from ..llm_provider import LLMProvider
from ..models import AssistantCommandResponse, InternalMessage, InternalMessageCreate, LLMModel
from ..repository import JsonRepository
from .shared import AgentContext, compact_title, contains_any


class InternalMessageManagementAgent:
    """사내쪽지 변경과 현재 대시보드 데이터 기반 질의응답을 처리한다.

    Example:
        ``"사내쪽지 내용 보여 줘"``는 읽기 전용 답변을 만들고,
        ``"쪽지 우선순위를 최근 수신일 순으로 지정해 줘"``는 재정렬을 수행한다.
    """

    DOMAIN_WORDS = ["사내쪽지", "쪽지", "메시지", "message"]
    CREATE_WORDS = ["등록", "추가", "생성"]
    DELETE_WORDS = ["삭제", "지워", "제거"]
    LIST_WORDS = ["목록", "조회", "보여", "확인", "찾아", "검색"]
    DETAIL_WORDS = ["내용", "상세", "본문", "자세히", "전문"]
    QUESTION_WORDS = ["뭐", "무엇", "어떤", "어때", "있어", "있나", "있니", "알려", "해야", "할까"]
    PRIORITY_WORDS = ["우선순위", "우선 순위", "중요도", "순위", "priority"]
    PRIORITY_ACTION_WORDS = ["설정", "지정", "추천", "분류", "정해", "매겨", "바꿔", "변경", "재조정", "재정렬", "조정"]
    PRIORITY_FILTERS = {
        "high": ["high", "높음", "높은", "중요", "긴급"],
        "medium": ["medium", "보통", "중간"],
        "low": ["low", "낮음", "낮은", "공지", "참고"],
    }

    def __init__(self, repository: JsonRepository, llm_provider: LLMProvider) -> None:
        """저장소와 우선순위 추천 sub-agent 의존성을 초기화한다."""

        self.repository = repository
        self.llm_provider = llm_provider
        self.priority_agent = InternalMessagePriorityRecommendationAgent(repository, llm_provider)

    def can_handle(self, context: AgentContext) -> bool:
        """semantic router 실패 시 사내쪽지 도메인의 최소 fallback을 제공한다."""

        return contains_any(context.message, self.DOMAIN_WORDS)

    def handle(self, context: AgentContext) -> AssistantCommandResponse:
        """명확한 변경 요청만 실행하고 나머지는 주입된 데이터로 답변한다."""

        message = context.message
        if self.priority_agent.can_handle(context):
            return self.priority_agent.handle(context)
        if contains_any(message, self.DELETE_WORDS):
            return self._delete_message(message)
        if contains_any(message, self.CREATE_WORDS):
            return self._create_message(message)
        return self._answer_with_message_data(context)

    def _answer_with_message_data(self, context: AgentContext) -> AssistantCommandResponse:
        """질문 유형과 관계없이 현재 사내쪽지 전체를 context로 사용해 답변한다."""

        messages = list(context.messages) if context.messages else self.repository.list_messages()
        if not messages:
            return AssistantCommandResponse(
                intent="query_messages",
                reply="현재 대시보드에 등록된 사내쪽지가 없습니다.",
                result={"messages": []},
            )

        prompt = self._build_data_question_prompt(context.message, messages)
        reply = self.llm_provider.chat(prompt, context.model)
        if self._should_use_data_fallback(reply):
            reply = self._format_data_fallback(messages)
        return AssistantCommandResponse(
            intent="query_messages",
            reply=reply,
            result={"messages": [message.model_dump(mode="json") for message in messages]},
        )

    def _build_data_question_prompt(self, question: str, messages: list[InternalMessage]) -> str:
        """현재 대시보드 데이터만 근거로 자유 질의응답을 수행하는 prompt를 만든다."""

        rows = [
            {
                "id": message.id,
                "title": message.title,
                "sender": message.sender,
                "received_at": message.received_at,
                "priority": message.priority,
                "status": message.status,
                "body": message.body,
                "todo_registered": bool(message.linked_todo_id),
            }
            for message in messages
        ]
        return (
            "당신은 은행 직원의 사내쪽지 업무를 지원하는 assistant입니다. "
            "반드시 제공된 현재 대시보드 데이터만 사용하고, 없는 사실은 추측하지 마세요. "
            "질문의 표현에 맞춰 요약, 검색, 비교, 우선순위 설명 또는 처리 순서를 한국어로 답하세요. "
            "이 요청은 읽기 전용이므로 어떤 데이터도 변경하지 마세요.\n"
            f"사용자 질문: {question}\n"
            f"현재 사내쪽지 데이터: {json.dumps(rows, ensure_ascii=False)}"
        )

    def _should_use_data_fallback(self, reply: str) -> bool:
        """mock 또는 provider 오류 응답이면 결정적 데이터 요약으로 대체한다."""

        return reply.startswith("현재는 mock LLM 모드입니다.") or contains_any(
            reply,
            ["API에 연결하지 못했습니다", "API 키가 유효하지", "호출 중 오류가 발생했습니다"],
        )

    def _format_data_fallback(self, messages: list[InternalMessage]) -> str:
        """LLM을 사용할 수 없어도 실제 대시보드 데이터로 기본 답변을 만든다."""

        high_count = sum(message.priority == "high" for message in messages)
        unread_count = sum(message.status == "unread" for message in messages)
        rows = [
            f"{index}. [{message.priority}] {message.title} - {message.sender} / {message.received_at}"
            for index, message in enumerate(messages[:5], start=1)
        ]
        suffix = f"\n외 {len(messages) - 5}건이 더 있습니다." if len(messages) > 5 else ""
        return (
            f"현재 사내쪽지는 총 {len(messages)}건이며, 높은 우선순위 {high_count}건, "
            f"미확인 {unread_count}건입니다.\n" + "\n".join(rows) + suffix
        )

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
    """명시적 정렬 기준 또는 LLM 추천으로 사내쪽지 우선순위를 재조정한다.

    결과는 high/medium/low 등급뿐 아니라 중복 없는 ``rank``와 각 항목의
    ``reason``을 포함하며, 채팅 답변에도 같은 근거를 순서대로 보여 준다.
    """

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
        """명시된 기준은 규칙으로, 기준이 없으면 LLM으로 순위와 사유를 결정한다."""

        messages = self.repository.list_messages()
        if not messages:
            return AssistantCommandResponse(intent="set_message_priorities", reply="우선순위를 설정할 사내쪽지가 없습니다.")

        criterion = self._explicit_date_criterion(context.message)
        used_fallback = False
        if criterion:
            recommendations, summary = self._recommend_by_date(messages, criterion)
            method = "직접 지시"
        else:
            recommendations, summary = self._recommend_with_llm(messages, context.model)
            method = "LLM 추천"
            if not recommendations:
                recommendations, summary = self._recommend_with_rules(messages)
                used_fallback = True
        updated_messages = self.repository.update_message_priority_recommendations(recommendations)
        by_id = {message.id: message for message in updated_messages}
        reasons = [
            {"message_id": item_id, "title": by_id[item_id].title, **item}
            for item_id, item in recommendations.items()
            if item_id in by_id
        ]
        reasons.sort(key=lambda item: item["rank"])
        detail = "\n".join(
            f"{item['rank']}. [{item['priority']}] {item['title']} - {item['reason']}" for item in reasons
        )
        return AssistantCommandResponse(
            intent="set_message_priorities",
            reply=f"사내쪽지 {len(reasons)}건의 우선순위를 {method}로 재조정했습니다.\n조정 기준: {summary}\n{detail}",
            result={
                "messages": [message.model_dump(mode="json") for message in updated_messages],
                "reasons": reasons,
                "summary": summary,
                "method": method,
                "used_fallback": used_fallback,
            },
        )

    def _explicit_date_criterion(self, command: str) -> str | None:
        """쪽지 재정렬 문장에서 사용자가 지정한 날짜 방향을 추출한다.

        Example:
            ``"최근날짜 순"``은 ``newest``, ``"오래된 날짜 순"``은
            ``oldest``를 반환하며 방향 표현이 없으면 LLM 추천을 위해 ``None``을 반환한다.
        """

        if contains_any(command, ["최근", "최신", "늦게 받은", "새로운 날짜", "최근날짜"]):
            return "newest"
        if contains_any(command, ["오래된", "과거", "먼저 받은", "오래된 날짜"]):
            return "oldest"
        return None

    def _recommend_by_date(
        self, messages: list[InternalMessage], criterion: str
    ) -> tuple[dict[str, dict], str]:
        """수신일 기준으로 쪽지 전체에 1~N 순위와 조정 사유를 만든다.

        Args:
            messages: 재정렬할 현재 사내쪽지 목록.
            criterion: ``newest`` 또는 ``oldest`` 날짜 방향.

        Returns:
            쪽지 id별 등급·순위·사유 mapping과 적용 기준 설명.
        """

        reverse = criterion == "newest"
        ordered = sorted(messages, key=lambda item: (self._date_sort_key(item.received_at), item.id), reverse=reverse)
        label = "최근 수신일 순" if reverse else "오래된 수신일 순"
        return self._ranked_items(
            ordered, lambda item: f"사용자가 지정한 {label} 기준(수신일 {item.received_at})을 적용했습니다."
        ), label

    def _date_sort_key(self, value: str) -> int:
        """ISO 날짜와 오늘/내일 표현을 같은 정렬 key로 변환한다.

        Example:
            직접 등록된 ``오늘`` 쪽지와 mock 데이터의 ``2026-07-14``를
            동일한 정수 축에서 비교해 최근 수신일 순으로 정렬한다.
        """

        if value == "오늘":
            return date.today().toordinal()
        if value == "내일":
            return (date.today() + timedelta(days=1)).toordinal()
        try:
            return date.fromisoformat(value[:10]).toordinal()
        except ValueError:
            return -1

    def _recommend_with_llm(
        self, messages: list[InternalMessage], model: LLMModel | None
    ) -> tuple[dict[str, dict], str]:
        """LLM에게 전체 순위와 사유 JSON을 요청한다."""

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
            "은행 직원의 사내쪽지 처리 우선순위를 전체 1위부터 순서대로 추천하세요. "
            "긴급 처리, 준법/감사/보안, 고객 영향, 오늘 처리 필요성이 크면 high입니다. "
            "모든 항목에 서로 다른 rank와 데이터에 근거한 한국어 사유를 넣으세요. "
            "반드시 JSON만 반환하세요. 형식: "
            '{"summary":"선정 기준","recommendations":'
            '[{"id":"message_id","priority":"high|medium|low","rank":1,"reason":"조정 사유"}]}. '
            f"사내쪽지 목록: {json.dumps(rows, ensure_ascii=False)}"
        )

    def _parse_recommendations(self, response: str, allowed_ids: set[str]) -> tuple[dict[str, dict], str]:
        """LLM 응답에서 누락 없는 순위, 등급, 사유를 검증한다."""

        match = re.search(r"\{.*\}", response, flags=re.DOTALL)
        if not match:
            return {}, ""
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}, ""
        recommendations = {}
        for item in parsed.get("recommendations", []):
            item_id, priority, rank = item.get("id"), item.get("priority"), item.get("rank")
            reason = str(item.get("reason", "")).strip()
            if item_id in allowed_ids and priority in self.PRIORITY_VALUES and isinstance(rank, int) and reason:
                recommendations[item_id] = {"priority": priority, "rank": rank, "reason": reason}
        ranks = {item["rank"] for item in recommendations.values()}
        if set(recommendations) != allowed_ids or ranks != set(range(1, len(allowed_ids) + 1)):
            return {}, ""
        summary = str(parsed.get("summary", "업무 긴급도와 고객 영향을 종합했습니다.")).strip()
        return recommendations, summary

    def _recommend_with_rules(self, messages: list[InternalMessage]) -> tuple[dict[str, dict], str]:
        """LLM 응답을 파싱하지 못했을 때 쓰는 결정적 fallback 추천."""

        high_words = ["긴급", "중요", "보안", "준법", "감사", "고액", "VIP", "오늘", "제출", "확인"]
        low_words = ["공지", "참고", "안내"]
        scored = []
        for message in messages:
            text = f"{message.title} {message.sender} {message.body}"
            if contains_any(text, high_words):
                score, reason = 2, "긴급·중요·준법 또는 고객 영향 키워드가 확인됩니다."
            elif contains_any(text, low_words):
                score, reason = 0, "공지·참고 성격의 안내로 분류했습니다."
            else:
                score, reason = 1, "즉시 처리를 요구하는 명시적 근거가 없어 일반 우선순위로 분류했습니다."
            scored.append((score, message.received_at, message, reason))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        ordered = [item[2] for item in scored]
        reasons = {item[2].id: item[3] for item in scored}
        return self._ranked_items(ordered, lambda item: reasons[item.id]), "긴급성, 준법·고객 영향, 수신일을 종합해 정렬했습니다."

    def _ranked_items(self, ordered: list[InternalMessage], reason_for) -> dict[str, dict]:
        """정렬된 항목에 1~N 순위와 상·중·하 등급을 부여한다."""

        count = len(ordered)
        return {
            item.id: {
                "priority": "high" if rank * 3 <= count + 2 else "medium" if rank * 3 <= count * 2 + 2 else "low",
                "rank": rank,
                "reason": reason_for(item),
            }
            for rank, item in enumerate(ordered, start=1)
        }

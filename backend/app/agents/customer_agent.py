"""사후관리 고객 관리 sub-agent."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

from ..llm_provider import LLMProvider
from ..models import AftercareCustomer, AftercareCustomerCreate, AssistantCommandResponse, LLMModel
from ..repository import JsonRepository
from .shared import AgentContext, compact_title, contains_any


class AftercareCustomerManagementAgent:
    """사후관리 고객 변경과 현재 대시보드 데이터 기반 질의응답을 처리한다.

    Example:
        ``"김민수 고객을 사후관리에 등록해 줘"``는 등록을 수행하고,
        ``"사후관리 고객 우선순위를 재조정해 줘"``는 추천 sub-agent에 위임한다.
    """

    DOMAIN_WORDS = ["사후고객", "사후관리", "고객관리", "고객"]
    FALLBACK_DOMAIN_WORDS = ["사후고객", "사후관리", "고객관리"]
    CREATE_WORDS = ["등록", "추가", "생성"]
    DELETE_WORDS = ["삭제", "지워", "제거"]
    LIST_WORDS = ["목록", "조회", "보여", "확인", "찾아", "검색"]
    DETAIL_WORDS = ["내용", "상세", "본문", "자세히", "전문"]
    QUESTION_WORDS = ["뭐", "무엇", "어떤", "어때", "있어", "있나", "있니", "알려", "해야", "할까"]
    PRIORITY_FILTERS = {
        "high": ["high", "높음", "높은", "중요", "긴급", "VIP"],
        "medium": ["medium", "보통", "중간"],
        "low": ["low", "낮음", "낮은", "서류"],
    }
    PRIORITY_WORDS = ["우선순위", "우선 순위", "중요도", "순위", "priority"]
    PRIORITY_ACTION_WORDS = ["설정", "지정", "추천", "분류", "정해", "매겨", "재정렬", "재조정", "조정", "변경"]

    def __init__(self, repository: JsonRepository, llm_provider: LLMProvider) -> None:
        """사후관리 고객 저장소와 데이터 질의응답용 LLM provider를 보관한다."""

        self.repository = repository
        self.llm_provider = llm_provider
        self.priority_agent = AftercareCustomerPriorityRecommendationAgent(repository, llm_provider)

    def can_handle(self, context: AgentContext) -> bool:
        """semantic router 실패 시 사후관리 도메인의 최소 fallback을 제공한다."""

        return contains_any(context.message, self.FALLBACK_DOMAIN_WORDS)

    def handle(self, context: AgentContext) -> AssistantCommandResponse:
        """명확한 변경 요청만 실행하고 나머지는 주입된 데이터로 답변한다."""

        message = context.message
        if self.priority_agent.can_handle(context):
            return self.priority_agent.handle(context)
        if contains_any(message, self.DELETE_WORDS):
            return self._delete_customer(message)
        if contains_any(message, self.CREATE_WORDS):
            return self._create_customer(message)
        return self._answer_with_customer_data(context)

    def _answer_with_customer_data(self, context: AgentContext) -> AssistantCommandResponse:
        """질문 유형과 관계없이 현재 사후관리 고객 전체를 사용해 답변한다."""

        customers = list(context.customers) if context.customers else self.repository.list_customers()
        if not customers:
            return AssistantCommandResponse(
                intent="query_customers",
                reply="현재 대시보드에 등록된 사후관리 고객이 없습니다.",
                result={"customers": []},
            )

        prompt = self._build_data_question_prompt(context.message, customers)
        reply = self.llm_provider.chat(prompt, context.model)
        if self._should_use_data_fallback(reply):
            reply = self._format_data_fallback(customers)
        return AssistantCommandResponse(
            intent="query_customers",
            reply=reply,
            result={"customers": [customer.model_dump(mode="json") for customer in customers]},
        )

    def _build_data_question_prompt(self, question: str, customers: list[AftercareCustomer]) -> str:
        """현재 대시보드 고객 데이터만 근거로 자유 질의응답을 수행하는 prompt를 만든다."""

        rows = [
            {
                "id": customer.id,
                "name": customer.name,
                "reason": customer.reason,
                "recommended_action": customer.recommended_action,
                "scheduled_date": customer.scheduled_date,
                "priority": customer.priority,
                "detail": customer.detail,
                "todo_registered": bool(customer.linked_todo_id),
            }
            for customer in customers
        ]
        return (
            "당신은 은행 직원의 사후관리 고객 업무를 지원하는 assistant입니다. "
            "반드시 제공된 현재 대시보드 데이터만 사용하고, 없는 사실은 추측하지 마세요. "
            "질문의 표현에 맞춰 요약, 검색, 비교, 우선순위 설명 또는 후속 조치를 한국어로 답하세요. "
            "이 요청은 읽기 전용이므로 어떤 데이터도 변경하지 마세요.\n"
            f"사용자 질문: {question}\n"
            f"현재 사후관리 고객 데이터: {json.dumps(rows, ensure_ascii=False)}"
        )

    def _should_use_data_fallback(self, reply: str) -> bool:
        """mock 또는 provider 오류 응답이면 결정적 데이터 요약으로 대체한다."""

        return reply.startswith("현재는 mock LLM 모드입니다.") or contains_any(
            reply,
            ["API에 연결하지 못했습니다", "API 키가 유효하지", "호출 중 오류가 발생했습니다"],
        )

    def _format_data_fallback(self, customers: list[AftercareCustomer]) -> str:
        """LLM을 사용할 수 없어도 실제 대시보드 고객 데이터로 기본 답변을 만든다."""

        high_count = sum(customer.priority == "high" for customer in customers)
        unlinked_count = sum(not customer.linked_todo_id for customer in customers)
        rows = [
            f"{index}. [{customer.priority}] {customer.name} 고객 - {customer.reason} / {customer.scheduled_date}"
            for index, customer in enumerate(customers[:5], start=1)
        ]
        suffix = f"\n외 {len(customers) - 5}명이 더 있습니다." if len(customers) > 5 else ""
        return (
            f"현재 사후관리 고객은 총 {len(customers)}명이며, 높은 우선순위 {high_count}명, "
            f"ToDo 미등록 {unlinked_count}명입니다.\n" + "\n".join(rows) + suffix
        )

    def _create_customer(self, message: str) -> AssistantCommandResponse:
        """채팅 문장을 사후관리 고객 등록 payload로 변환한다."""

        name = self._extract_customer_name(message)
        customer = self.repository.create_customer(
            AftercareCustomerCreate(
                name=name,
                reason=compact_title(message, self.DOMAIN_WORDS + self.CREATE_WORDS + [name, "해줘"], "사후관리 필요"),
                recommended_action="상담 및 후속 확인",
                scheduled_date=self._extract_due_text(message) or "오늘",
                priority="high" if contains_any(message, ["중요", "긴급", "VIP"]) else "medium",
                detail=message,
            )
        )
        return AssistantCommandResponse(
            intent="create_customer",
            reply=f"'{customer.name}' 고객을 사후관리 목록에 등록했습니다.",
            result=customer.model_dump(mode="json"),
        )

    def _delete_customer(self, message: str) -> AssistantCommandResponse:
        """문장과 가장 가까운 사후관리 고객을 찾아 삭제한다."""

        target = self._find_matching_customer(message)
        if not target:
            return AssistantCommandResponse(intent="needs_confirmation", reply="삭제할 사후관리 고객을 찾지 못했습니다.")
        self.repository.delete_customer(target.id)
        return AssistantCommandResponse(
            intent="delete_customer",
            reply=f"'{target.name}' 고객을 사후관리 목록에서 삭제했습니다.",
            result={"deleted_id": target.id},
        )

    def _query_customers(self, command: str) -> AssistantCommandResponse:
        """내부 tool 함수처럼 사후관리 고객을 조건별로 조회하고 상세 내용을 응답한다."""

        customers = self._filter_customers(command, self.repository.list_customers())
        if not customers:
            return AssistantCommandResponse(
                intent="query_customers",
                reply="조건에 맞는 사후관리 고객을 찾지 못했습니다.",
                result={"customers": []},
            )
        detail_mode = contains_any(command, self.DETAIL_WORDS) or len(customers) == 1
        reply = self._format_customer_detail_reply(customers) if detail_mode else self._format_customer_list_reply(customers)
        return AssistantCommandResponse(
            intent="query_customers",
            reply=reply,
            result={"customers": [customer.model_dump(mode="json") for customer in customers]},
        )

    def _extract_customer_name(self, message: str) -> str:
        """'홍길동 고객' 같은 표현에서 고객명을 추출한다."""

        match = re.search(r"([가-힣A-Za-z0-9]{2,20})\s*고객", message)
        if match and match.group(1) not in {"사후", "사후관리", "고객관리"}:
            return match.group(1)
        cleaned = compact_title(message, self.DOMAIN_WORDS + self.CREATE_WORDS + ["해줘"], "새 고객")
        return cleaned.split()[0][:20] if cleaned else "새 고객"

    def _find_matching_customer(self, message: str) -> AftercareCustomer | None:
        """메시지 토큰과 이름/사유/상세가 겹치는 고객을 찾는다."""

        command_words = set(self.DOMAIN_WORDS + self.DELETE_WORDS + self.LIST_WORDS + self.DETAIL_WORDS)
        tokens = [token for token in re.split(r"\s+", message) if token and token not in command_words]
        customers = self.repository.list_customers()
        for item in customers:
            if any(token in item.name or token in item.reason or token in item.detail for token in tokens):
                return item
        return customers[0] if customers else None

    def _filter_customers(self, command: str, customers: list[AftercareCustomer]) -> list[AftercareCustomer]:
        """명령문에서 우선순위와 검색어를 추출해 고객 목록을 좁힌다."""

        priority = self._extract_priority_filter(command)
        tokens = self._extract_search_tokens(command)
        filtered = [customer for customer in customers if not priority or customer.priority == priority]
        if not tokens:
            return filtered
        return [
            customer
            for customer in filtered
            if any(
                token
                in f"{customer.name} {customer.reason} {customer.recommended_action} {customer.scheduled_date} {customer.detail}"
                for token in tokens
            )
        ]

    def _extract_priority_filter(self, command: str) -> str | None:
        """채팅 문장에 포함된 우선순위 표현을 priority 값으로 변환한다."""

        for priority, words in self.PRIORITY_FILTERS.items():
            if contains_any(command, words):
                return priority
        return None

    def _extract_search_tokens(self, command: str) -> list[str]:
        """고객 조회 명령에서 도메인/동작 키워드를 제외한 검색어를 뽑는다."""

        command_words = set(
            self.DOMAIN_WORDS
            + self.LIST_WORDS
            + self.DETAIL_WORDS
            + self.QUESTION_WORDS
            + ["해줘", "줘", "중", "관련", "대한", "있는", "오늘", "내일", "관리", "대상"]
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

    def _format_customer_list_reply(self, customers: list[AftercareCustomer]) -> str:
        """여러 사후관리 고객을 채팅창에서 읽기 쉬운 목록 형태로 만든다."""

        rows = [
            f"{index}. [{customer.priority}] {customer.name} 고객 - {customer.reason} / {customer.scheduled_date}"
            for index, customer in enumerate(customers[:5], start=1)
        ]
        suffix = f"\n외 {len(customers) - 5}명이 더 있습니다." if len(customers) > 5 else ""
        return f"조건에 맞는 사후관리 고객 {len(customers)}명입니다.\n" + "\n".join(rows) + suffix

    def _format_customer_detail_reply(self, customers: list[AftercareCustomer]) -> str:
        """고객명, 관리 사유, 추천 조치, 상세 내용을 포함한 응답을 만든다."""

        rows = [
            (
                f"{index}. [{customer.priority}] {customer.name} 고객\n"
                f"   사유: {customer.reason} / 예정일: {customer.scheduled_date}\n"
                f"   추천 조치: {customer.recommended_action}\n"
                f"   상세: {customer.detail}"
            )
            for index, customer in enumerate(customers[:3], start=1)
        ]
        suffix = f"\n외 {len(customers) - 3}명은 목록에서 확인해 주세요." if len(customers) > 3 else ""
        return f"사후관리 고객 상세 {min(len(customers), 3)}명입니다.\n" + "\n".join(rows) + suffix

    def _extract_due_text(self, message: str) -> str:
        """고객관리 예정일로 쓸 간단한 날짜 표현을 추출한다."""

        if "내일" in message:
            return "내일"
        if "오늘" in message:
            return "오늘"
        return ""


class AftercareCustomerPriorityRecommendationAgent:
    """직접 기준 또는 LLM으로 고객 우선순위와 선정 사유를 저장하는 sub-agent.

    기준이 명시된 날짜 정렬은 LLM 호출 없이 결정적으로 수행한다. 기준 없는
    재조정 요청은 LLM의 구조화 JSON을 검증해 사용하고 실패하면 동일 데이터에
    기반한 규칙형 점수로 안전하게 보정한다.
    """

    PRIORITY_VALUES = {"high", "medium", "low"}
    PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

    def __init__(self, repository: JsonRepository, llm_provider: LLMProvider) -> None:
        """추천 대상 저장소와 선택 모델을 호출할 LLM provider를 보관한다."""

        self.repository = repository
        self.llm_provider = llm_provider

    def can_handle(self, context: AgentContext) -> bool:
        """사후고객 우선순위 추천 요청인지 확인한다."""

        return contains_any(context.message, AftercareCustomerManagementAgent.PRIORITY_WORDS) and contains_any(
            context.message, AftercareCustomerManagementAgent.PRIORITY_ACTION_WORDS
        )

    def handle(self, context: AgentContext) -> AssistantCommandResponse:
        """명시 기준 또는 LLM으로 전체 고객 순위와 사유를 저장·반환한다."""

        customers = self.repository.list_customers()
        if not customers:
            return AssistantCommandResponse(
                intent="set_customer_priorities",
                reply="우선순위를 추천할 사후관리 고객이 없습니다.",
                result={"customers": [], "reasons": [], "summary": "추천 대상 고객이 없습니다."},
            )

        criterion = self._explicit_date_criterion(context.message)
        used_fallback = False
        if criterion:
            recommendations, summary = self._recommend_by_date(customers, criterion)
            method = "직접 지시"
        else:
            recommendations, summary = self._recommend_with_llm(customers, context.model)
            method = "LLM 추천"
            if not recommendations:
                recommendations, summary = self._recommend_with_rules(customers)
                used_fallback = True

        updated_customers = self.repository.update_customer_priority_recommendations(recommendations)
        customer_by_id = {customer.id: customer for customer in updated_customers}
        reasons = [
            {
                "customer_id": customer_id,
                "name": customer_by_id[customer_id].name,
                "priority": item["priority"],
                "rank": item["rank"],
                "reason": item["reason"],
            }
            for customer_id, item in recommendations.items()
            if customer_id in customer_by_id
        ]
        reasons.sort(key=lambda item: item["rank"])
        detail = "\n".join(
            f"{item['rank']}. [{item['priority']}] {item['name']} 고객 - {item['reason']}" for item in reasons
        )
        return AssistantCommandResponse(
            intent="set_customer_priorities",
            reply=f"사후관리 고객 {len(reasons)}명의 우선순위를 {method}로 재조정했습니다.\n조정 기준: {summary}\n{detail}",
            result={
                "customers": [customer.model_dump(mode="json") for customer in updated_customers],
                "reasons": reasons,
                "summary": summary,
                "method": method,
                "used_fallback": used_fallback,
            },
        )

    def _recommend_with_llm(
        self, customers: list[AftercareCustomer], model: LLMModel | None
    ) -> tuple[dict[str, dict[str, str | int]], str]:
        """LLM의 구조화된 추천 응답을 파싱한다."""

        response = self.llm_provider.chat(self._build_prompt(customers), model)
        return self._parse_recommendations(response, {customer.id for customer in customers})

    def _explicit_date_criterion(self, command: str) -> str | None:
        """사용자가 명시한 날짜 정렬 방향을 찾는다."""

        if contains_any(command, ["최근", "최신", "늦은 예정일", "새로운 날짜", "최근날짜"]):
            return "newest"
        if contains_any(command, ["오래된", "과거", "빠른 예정일", "오래된 날짜", "예정일이 빠른"]):
            return "oldest"
        return None

    def _recommend_by_date(
        self, customers: list[AftercareCustomer], criterion: str
    ) -> tuple[dict[str, dict], str]:
        """관리 예정일 기준으로 고객 전체에 결정적인 1~N 순위를 부여한다.

        Args:
            customers: 재정렬할 현재 사후관리 고객 목록.
            criterion: ``newest``이면 최근 날짜 우선, ``oldest``이면 빠른 날짜 우선.

        Returns:
            고객 id별 등급·순위·사유 mapping과 채팅에 표시할 기준 설명.

        Example:
            ``"사후관리 고객을 최근날짜 순으로 지정해 줘"``는 ``newest``로
            해석되어 가장 최근 관리 예정일의 고객이 1순위가 된다.
        """

        reverse = criterion == "newest"
        ordered = sorted(customers, key=lambda item: (self._date_sort_key(item.scheduled_date), item.id), reverse=reverse)
        label = "최근 관리예정일 순" if reverse else "빠른 관리예정일 순"
        return self._ranked_items(
            ordered,
            lambda item: f"사용자가 지정한 {label} 기준(예정일 {item.scheduled_date})을 적용했습니다.",
        ), label

    def _date_sort_key(self, value: str) -> int:
        """ISO 날짜와 오늘/내일 표현을 같은 정렬 key로 변환한다.

        Example:
            ``2026-07-14``와 ``오늘`` 모두 날짜 ordinal 정수로 변환되므로
            문자열 형식이 섞여 있어도 시간 순서대로 비교할 수 있다.
        """

        if value == "오늘":
            return date.today().toordinal()
        if value == "내일":
            return (date.today() + timedelta(days=1)).toordinal()
        try:
            return date.fromisoformat(value[:10]).toordinal()
        except ValueError:
            return -1

    def _build_prompt(self, customers: list[AftercareCustomer]) -> str:
        """고객 업무 데이터와 평가 기준을 담은 JSON 전용 prompt를 만든다."""

        rows = [
            {
                "id": customer.id,
                "name": customer.name,
                "reason": customer.reason,
                "recommended_action": customer.recommended_action,
                "scheduled_date": customer.scheduled_date,
                "detail": customer.detail,
                "todo_registered": bool(customer.linked_todo_id),
                "current_priority": customer.priority,
            }
            for customer in customers
        ]
        return (
            "은행 직원의 사후관리 고객 처리 우선순위를 high, medium, low 중 하나로 추천하세요. "
            "기한 임박·경과, 금융 리스크, 고객 영향, 민원 가능성, 후속 조치 긴급성을 근거로 판단하세요. "
            "모든 고객에 1부터 고객 수까지 서로 다른 rank를 부여하세요. "
            "각 고객마다 제공된 데이터에서 확인 가능한 구체적인 한국어 사유를 한 문장으로 작성하세요. "
            "반드시 설명이나 markdown 없이 다음 JSON 형식만 반환하세요: "
            '{"summary":"전체 선정 기준 요약",'
            '"recommendations":[{"id":"customer_id","priority":"high|medium|low","rank":1,"reason":"선정 사유"}]}. '
            f"사후관리 고객 목록: {json.dumps(rows, ensure_ascii=False)}"
        )

    def _parse_recommendations(
        self, response: str, allowed_ids: set[str]
    ) -> tuple[dict[str, dict[str, str | int]], str]:
        """LLM JSON에서 유효한 전체 고객 추천과 요약을 추출한다."""

        match = re.search(r"\{.*\}", response, flags=re.DOTALL)
        if not match:
            return {}, ""
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}, ""
        recommendations = {}
        for item in parsed.get("recommendations", []):
            customer_id = item.get("id")
            priority = item.get("priority")
            rank = item.get("rank")
            reason = str(item.get("reason", "")).strip()
            if customer_id in allowed_ids and priority in self.PRIORITY_VALUES and isinstance(rank, int) and reason:
                recommendations[customer_id] = {"priority": priority, "rank": rank, "reason": reason}
        ranks = {item["rank"] for item in recommendations.values()}
        if set(recommendations) != allowed_ids or ranks != set(range(1, len(allowed_ids) + 1)):
            return {}, ""
        return recommendations, str(parsed.get("summary", "AI가 업무 긴급도와 고객 영향을 종합해 선정했습니다.")).strip()

    def _recommend_with_rules(
        self, customers: list[AftercareCustomer]
    ) -> tuple[dict[str, dict[str, str | int]], str]:
        """LLM을 사용할 수 없을 때 동일 데이터로 결정적 추천과 설명을 만든다."""

        today = date.today()
        risk_words = ["긴급", "민원", "연체", "만기", "VIP", "변동성", "리스크", "고액"]
        action_words = ["전화", "상담", "확인", "예약"]
        scored = []
        for customer in customers:
            text = f"{customer.reason} {customer.recommended_action} {customer.detail}"
            score = 0
            evidence = []
            matched_risk = next((word for word in risk_words if word in text), None)
            if matched_risk:
                score += 3
                evidence.append(f"'{matched_risk}' 관련 고객 영향 또는 금융 리스크가 있습니다")
            try:
                scheduled_date = date.fromisoformat(customer.scheduled_date[:10])
            except ValueError:
                scheduled_date = None
            if scheduled_date and scheduled_date <= today:
                score += 2
                evidence.append(f"관리 예정일({customer.scheduled_date})이 도래했거나 경과했습니다")
            if not customer.linked_todo_id:
                score += 1
                evidence.append("아직 ToDo로 등록되지 않았습니다")
            matched_action = next((word for word in action_words if word in customer.recommended_action), None)
            if matched_action:
                score += 1
                evidence.append(f"'{customer.recommended_action}' 후속 조치가 필요합니다")
            reason = "; ".join(evidence[:3]) or "현재 데이터에서 즉시 처리해야 할 긴급 근거가 확인되지 않았습니다"
            scored.append((score, customer.scheduled_date, customer, reason + "."))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        ordered = [item[2] for item in scored]
        reasons = {item[2].id: item[3] for item in scored}
        return self._ranked_items(ordered, lambda item: reasons[item.id]), "관리 예정일, 금융·고객 리스크, 후속 조치 필요성과 ToDo 등록 여부를 종합해 정렬했습니다."

    def _ranked_items(self, ordered: list[AftercareCustomer], reason_for) -> dict[str, dict]:
        """정렬된 고객에 1~N 순위와 상·중·하 등급을 부여한다."""

        count = len(ordered)
        return {
            item.id: {
                "priority": "high" if rank * 3 <= count + 2 else "medium" if rank * 3 <= count * 2 + 2 else "low",
                "rank": rank,
                "reason": reason_for(item),
            }
            for rank, item in enumerate(ordered, start=1)
        }

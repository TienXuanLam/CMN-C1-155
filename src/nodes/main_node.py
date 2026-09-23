"""Composite main slot for the capability-routing pipeline."""

from typing import Any

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.nodes.capability_lookup_node import CapabilityLookupNode
from src.nodes.intent_classify_node import IntentClassifyNode
from src.nodes.route_decide_node import RouteDecideNode


class MainNode(FunctionNode):
    """CapabilityLookupNode → IntentClassifyNode → RouteDecideNode."""

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(
        self,
        llm_temperature: float = 0.2,
        llm_max_tokens: int = 4096,
        timeout_s: int = 120,
        max_retry: int = 2,
        confidence_threshold: float = 0.5,
    ) -> None:
        super().__init__()
        self._capability_lookup = CapabilityLookupNode()
        self._intent_classify = IntentClassifyNode(
            llm_temperature=llm_temperature,
            llm_max_tokens=llm_max_tokens,
            timeout_s=timeout_s,
            max_retry=max_retry,
        )
        self._route_decide = RouteDecideNode(confidence_threshold=confidence_threshold)

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        emit_trace_event("capability_routing_pipeline_started", {}, state)
        updates: dict[str, Any] = {}

        result = self._capability_lookup.execute({**state, **updates})
        updates.update(result)
        if updates.get("status") == AgentStatus.ERROR:
            return updates

        result = self._intent_classify.execute({**state, **updates})
        updates.update(result)
        if updates.get("status") in (AgentStatus.RETRY, AgentStatus.ERROR):
            return updates

        result = self._route_decide.execute({**state, **updates})
        updates.update(result)
        return updates

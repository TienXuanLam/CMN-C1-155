"""AgentCore Platform v1.0"""

import json
from typing import Any

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event


class PostProcessNode(FunctionNode):
    """Format pipeline output for consumption by the agent boundary.

    S-3 output gate is enforced by Graph._enrich_output() — at the agent-class
    boundary (CR-155-02). This node is responsible only for serialization and
    S-4 trace emission.
    """

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self) -> None:
        super().__init__()

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        routing_decision = state.get("routing_decision", "")
        confidence_score = state.get("confidence_score", 0.0)
        escalation_flag = state.get("escalation_flag", False)

        result = json.dumps(
            {
                "routing_decision": routing_decision,
                "confidence_score": confidence_score,
                "escalation_flag": escalation_flag,
                "classified_intent": state.get("classified_intent", ""),
                "overlap_flag": state.get("overlap_flag", False),
            }
        )

        emit_trace_event(
            "post_process",
            {
                "routing_decision": routing_decision,
                "escalation_flag": escalation_flag,
            },
            state,
        )

        return {
            "result": result,
            "formatted_output": result,
            "status": AgentStatus.SUCCESS,
        }

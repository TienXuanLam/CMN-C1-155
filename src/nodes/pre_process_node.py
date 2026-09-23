"""AgentCore Platform v1.0"""

# Node contract (agents_layer_design.md §1):
#  - Extend FunctionNode; implement execute(state) -> dict
#  - Return ONLY the fields this node changes (never full state)
#  - Return AgentStatus enum constants — never plain strings [A1]
#  - Never import from mediator/, api/, or other agents
#
# S-1 trust gate: enforced automatically by BaseNode.__call__() via
# required_trust_level class variable (ADR-006). Do NOT add a manual
# trust check here — it conflicts with the framework gate and is dead code.
# SEC-C1155-002: the gate variable belongs on the node (BaseNode.__call__()
# reads it from the node instance), not on the agent/graph class.
#
# S-2 gate: FunctionNode.__call__() calls _security_gate_input(state) which
# delegates to _extra_security_gate_input(state). Override the _extra_ hook.
# Signature: (self, state: dict) -> dict  — return state to pass, raise to block.

import json
import re
from typing import Any

from framework.nodes.function_node import FunctionNode
from framework.security import detect_credentials, detect_injection
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

_DEVELOPER_MODE_PATTERN = re.compile(
    r"you\s+are\s+now\s+(?:in\s+)?(?:developer|dan|jailbreak)\s*mode",
    re.IGNORECASE,
)


class PreProcessNode(FunctionNode):
    """Validate and sanitize incoming input before main processing."""

    # S-1: this is the entry node handling raw external input — declare the
    # trust floor here so BaseNode.__call__() enforces it (ADR-006).
    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self) -> None:
        super().__init__()

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # Marketplace and the standalone HTTP adapter both populate only
        # `user_input` -- that is the single real data-carrying channel.
        user_input = state.get("user_input", "")

        if not user_input or not user_input.strip():
            emit_trace_event(
                "pre_process_rejected",
                {"reason": "empty_user_input"},
                state,
            )
            return {
                "status": AgentStatus.ERROR,
                "error_log": ["PreProcessNode: user_input is empty or missing"],
            }

        emit_trace_event(
            "pre_process_complete",
            {"input_len": len(user_input.strip())},
            state,
        )

        return {
            "validated_input": user_input.strip(),
            "enriched_context": json.dumps({"source": "cmn-c1-155"}),  # SEC-C1155-001: serialize to str
            "status": AgentStatus.SUCCESS,
        }

    def _extra_security_gate_input(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-2 hook called by FunctionNode._security_gate_input(state) before execute().

        Scans user_input for credential leakage and prompt-injection/jailbreak patterns.
        Returns state unchanged when clean; raises ValueError to block the request.
        """
        user_input = state.get("user_input", "")
        if not user_input:
            return state

        credentials = detect_credentials(user_input)
        if credentials:
            emit_trace_event(
                "s2_gate_violation",
                {
                    "category": "credential",
                    "credential_types": sorted({item["type"] for item in credentials}),
                    "action": "rejected",
                },
                state,
            )
            raise ValueError("S-2 gate: credential pattern detected in input")

        injections = [
            finding for finding in detect_injection(user_input) if finding.get("confidence") in {"high", "medium"}
        ]
        if injections or _DEVELOPER_MODE_PATTERN.search(user_input):
            emit_trace_event(
                "s2_gate_violation",
                {
                    "category": "injection",
                    "injection_types": sorted({item["type"] for item in injections}) or ["developer_mode"],
                    "action": "rejected",
                },
                state,
            )
            raise ValueError("S-2 gate: injection pattern detected in input")

        return state

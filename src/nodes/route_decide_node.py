"""AgentCore Platform v1.0"""

from __future__ import annotations

import json
from typing import Any

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event


class RouteDecideNode(FunctionNode):
    """Resolve overlap and decide final routing target.

    Step 1 — Overlap resolution:
      If multiple candidate_agents, pick highest match_score.
      Tie-break: lowest priority value in registered_capabilities.

    Step 2 — Routing decision:
      escalate when candidate_agents is empty OR confidence < 0.5.
      Otherwise route to resolved agent_id.

    Input:  candidate_agents (JSON str), registered_capabilities (JSON str) — SEC-C1155-001
    Output: resolved_agent (JSON str), overlap_flag,
            routing_decision, confidence_score, escalation_flag
    """

    # S-1: resolves routing for external user requests — declare the trust
    # floor so BaseNode.__call__() enforces it (ADR-006, SEC-C1155-002).
    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, confidence_threshold: float = 0.5) -> None:
        super().__init__()
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0.0 and 1.0")
        self._confidence_threshold = confidence_threshold

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        # SEC-C1155-001: deserialize JSON str fields before use
        raw_candidates = state.get("candidate_agents", "[]")
        candidate_agents: list[dict[str, Any]] = (
            json.loads(raw_candidates) if isinstance(raw_candidates, str) else raw_candidates or []
        )
        raw_capabilities = state.get("registered_capabilities", "[]")
        registered_capabilities: list[dict[str, Any]] = (
            json.loads(raw_capabilities) if isinstance(raw_capabilities, str) else raw_capabilities or []
        )

        # ── Step 1: Overlap resolution ────────────────────────────────────
        overlap_flag = len(candidate_agents) > 1
        resolved_agent: dict[str, Any] = {}

        if not candidate_agents:
            # No candidates — escalate immediately
            emit_trace_event(
                "route_decide",
                {"routing_decision": "escalate", "reason": "no_candidates"},
                state,
            )
            return {
                "resolved_agent": json.dumps({}),  # SEC-C1155-001: serialize to str
                "overlap_flag": False,
                "routing_decision": "escalate",
                "confidence_score": 0.0,
                "escalation_flag": True,
                "status": AgentStatus.SUCCESS,
            }

        if overlap_flag:
            resolved_agent = self._resolve_overlap(candidate_agents, registered_capabilities)
        else:
            resolved_agent = {
                "agent_id": candidate_agents[0].get("agent_id", ""),
                "name": self._lookup_name(
                    candidate_agents[0].get("agent_id", ""),
                    registered_capabilities,
                ),
                "confidence": candidate_agents[0].get("match_score", 0.0),
            }

        # ── Step 2: Routing decision ──────────────────────────────────────
        confidence_score: float = float(resolved_agent.get("confidence", 0.0))
        escalation_flag = confidence_score < self._confidence_threshold

        if escalation_flag:
            routing_decision = "escalate"
        else:
            routing_decision = resolved_agent.get("agent_id", "escalate")

        emit_trace_event(
            "route_decide",
            {
                "routing_decision": routing_decision,
                "confidence_score": confidence_score,
                "overlap_flag": overlap_flag,
                "escalation_flag": escalation_flag,
            },
            state,
        )

        return {
            "resolved_agent": json.dumps(resolved_agent),  # SEC-C1155-001: serialize to str
            "overlap_flag": overlap_flag,
            "routing_decision": routing_decision,
            "confidence_score": confidence_score,
            "escalation_flag": escalation_flag,
            "status": AgentStatus.SUCCESS,
        }

    def _resolve_overlap(
        self,
        candidates: list[dict[str, Any]],
        capabilities: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Pick the best candidate from multiple matches.

        Sort by match_score descending, then by priority ascending
        (lower priority number = higher precedence per registry convention).
        """
        priority_map: dict[str, int] = {c.get("agent_id", ""): c.get("priority", 999) for c in capabilities}

        sorted_candidates = sorted(
            candidates,
            key=lambda c: (
                -c.get("match_score", 0.0),
                priority_map.get(c.get("agent_id", ""), 999),
            ),
        )

        best = sorted_candidates[0]
        return {
            "agent_id": best.get("agent_id", ""),
            "name": self._lookup_name(best.get("agent_id", ""), capabilities),
            "confidence": best.get("match_score", 0.0),
        }

    def _lookup_name(self, agent_id: str, capabilities: list[dict[str, Any]]) -> str:
        """Look up the human-readable name for an agent_id from the registry."""
        for cap in capabilities:
            if cap.get("agent_id") == agent_id:
                return str(cap.get("name", agent_id))
        return agent_id

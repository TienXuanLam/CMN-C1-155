# CMN-C1-155 — Unit Tests: RouteDecideNode

import json
from unittest.mock import patch

import pytest
from src.nodes.route_decide_node import RouteDecideNode
from framework.schemas.agent_status import AgentStatus


def _state(candidate_agents, registered_capabilities):
    """Helper: build state dict with SEC-C1155-001 JSON-serialized fields."""
    return {
        "candidate_agents": json.dumps(candidate_agents),
        "registered_capabilities": json.dumps(registered_capabilities),
        "node_history": [],
        "error_log": [],
    }


class TestRouteDecideNode:
    """Unit tests for RouteDecideNode.

    Covers:
      - No candidates → immediate escalation
      - Single candidate, high confidence → route to agent
      - Single candidate, low confidence → escalation
      - Multiple candidates (overlap) → highest match_score wins
      - Multiple candidates tie-break → lowest priority wins
      - execute() method contract
    """

    def setup_method(self):
        self.node = RouteDecideNode()

    # ── BL-01: No candidates → escalate ─────────────────────────────────────

    def test_no_candidates_escalates(self):
        """BL-01: When candidate_agents is empty, route to 'escalate'."""
        result = self.node.execute(_state([], []))
        assert result["routing_decision"] == "escalate"
        assert result["escalation_flag"] is True
        assert result["overlap_flag"] is False
        assert result["confidence_score"] == 0.0
        assert result["status"] == AgentStatus.SUCCESS
        assert json.loads(result["resolved_agent"]) == {}

    # ── BL-02: Single candidate, high confidence → route ────────────────────

    def test_single_high_confidence_routes(self):
        """BL-02: Single candidate above threshold → route to its agent_id."""
        result = self.node.execute(
            _state(
                [{"agent_id": "agent-alpha", "match_score": 0.9, "matched_domain": "finance"}],
                [{"agent_id": "agent-alpha", "name": "Alpha Agent", "priority": 1}],
            )
        )
        assert result["routing_decision"] == "agent-alpha"
        assert result["escalation_flag"] is False
        assert result["overlap_flag"] is False
        assert result["confidence_score"] == pytest.approx(0.9)
        resolved = json.loads(result["resolved_agent"])  # SEC-C1155-001
        assert resolved["agent_id"] == "agent-alpha"
        assert resolved["name"] == "Alpha Agent"
        assert result["status"] == AgentStatus.SUCCESS

    # ── BL-03: Single candidate, low confidence → escalate ──────────────────

    def test_single_low_confidence_escalates(self):
        """BL-03: Single candidate below confidence threshold → escalate."""
        result = self.node.execute(
            _state(
                [{"agent_id": "agent-beta", "match_score": 0.3, "matched_domain": "hr"}],
                [{"agent_id": "agent-beta", "name": "Beta Agent", "priority": 2}],
            )
        )
        assert result["routing_decision"] == "escalate"
        assert result["escalation_flag"] is True
        assert result["confidence_score"] == pytest.approx(0.3)
        assert result["status"] == AgentStatus.SUCCESS

    # ── BL-04: Multiple candidates → highest match_score wins ───────────────

    def test_overlap_highest_score_wins(self):
        """BL-04: Multiple candidates → resolved to highest match_score."""
        result = self.node.execute(
            _state(
                [
                    {"agent_id": "agent-low", "match_score": 0.6, "matched_domain": "ops"},
                    {"agent_id": "agent-high", "match_score": 0.85, "matched_domain": "ops"},
                ],
                [
                    {"agent_id": "agent-low", "name": "Low Agent", "priority": 1},
                    {"agent_id": "agent-high", "name": "High Agent", "priority": 2},
                ],
            )
        )
        assert result["overlap_flag"] is True
        assert result["routing_decision"] == "agent-high"
        assert result["escalation_flag"] is False
        resolved = json.loads(result["resolved_agent"])
        assert resolved["agent_id"] == "agent-high"
        assert result["status"] == AgentStatus.SUCCESS

    # ── BL-05: Tie-break → lowest priority (registry) wins ──────────────────

    def test_overlap_tiebreak_by_priority(self):
        """BL-05: Equal match_score → lowest priority value (highest precedence) wins."""
        result = self.node.execute(
            _state(
                [
                    {"agent_id": "agent-p5", "match_score": 0.8, "matched_domain": "it"},
                    {"agent_id": "agent-p2", "match_score": 0.8, "matched_domain": "it"},
                ],
                [
                    {"agent_id": "agent-p5", "name": "Priority5 Agent", "priority": 5},
                    {"agent_id": "agent-p2", "name": "Priority2 Agent", "priority": 2},
                ],
            )
        )
        assert result["overlap_flag"] is True
        assert result["routing_decision"] == "agent-p2"
        resolved = json.loads(result["resolved_agent"])
        assert resolved["agent_id"] == "agent-p2"
        assert result["status"] == AgentStatus.SUCCESS

    # ── Node contract ──────────────────────────────────────────────────────────────────────────────────────────────────────

    def test_execute_method_signature(self):
        """Node contract: Node implements execute(self, state, config=None)."""
        import inspect

        assert hasattr(RouteDecideNode, "execute"), "RouteDecideNode must implement execute()"
        sig = inspect.signature(RouteDecideNode.execute)
        params = list(sig.parameters.keys())
        assert len(params) >= 2, f"execute() must accept (self, state, ...), got: {params}"
        assert params[1] == "state", f"Second parameter must be 'state', got '{params[1]}'"
        assert (
            "_invoke_impl" not in RouteDecideNode.__dict__
        ), "_invoke_impl() must not be defined — use execute() instead"

    # ── State output completeness ────────────────────────────────────────────

    def test_output_contains_required_keys(self):
        """All required state keys must be present in output."""
        result = self.node.execute(
            _state(
                [{"agent_id": "agent-x", "match_score": 0.75, "matched_domain": "gen"}],
                [],
            )
        )
        required_keys = {
            "resolved_agent",
            "overlap_flag",
            "routing_decision",
            "confidence_score",
            "escalation_flag",
            "status",
        }
        missing = required_keys - result.keys()
        assert not missing, f"Missing output keys: {missing}"
        # SEC-C1155-001: resolved_agent must be a JSON string
        assert isinstance(result["resolved_agent"], str)

    # ── BND-05: confidence_score exactly at threshold → does NOT escalate ────

    def test_confidence_exactly_at_threshold_does_not_escalate(self):
        """BND-05: match_score=0.5 → escalation_flag=False (threshold is strict <)."""
        result = self.node.execute(
            _state(
                [{"agent_id": "agent-exact", "match_score": 0.5, "matched_domain": "ops"}],
                [{"agent_id": "agent-exact", "name": "Exact Agent", "priority": 1}],
            )
        )
        assert result["escalation_flag"] is False
        assert result["routing_decision"] == "agent-exact"
        assert result["confidence_score"] == pytest.approx(0.5)
        assert result["status"] == AgentStatus.SUCCESS

    # ── BND-06: confidence_score just below threshold → escalates ────────────

    def test_confidence_just_below_threshold_escalates(self):
        """BND-06: match_score=0.499 → escalation_flag=True."""
        result = self.node.execute(
            _state(
                [{"agent_id": "agent-low", "match_score": 0.499, "matched_domain": "ops"}],
                [{"agent_id": "agent-low", "name": "Low Agent", "priority": 1}],
            )
        )
        assert result["escalation_flag"] is True
        assert result["routing_decision"] == "escalate"
        assert result["confidence_score"] == pytest.approx(0.499)

    # ── BND-07: resolved_agent.name falls back to agent_id when not in registry ─

    def test_name_fallback_to_agent_id_when_not_in_registry(self):
        """BND-07: candidate agent_id not in registered_capabilities → name = agent_id."""
        result = self.node.execute(
            _state(
                [{"agent_id": "agent-unknown", "match_score": 0.8, "matched_domain": "misc"}],
                [],  # empty registry — agent_id not found
            )
        )
        assert result["status"] == AgentStatus.SUCCESS
        resolved = json.loads(result["resolved_agent"])
        assert resolved["agent_id"] == "agent-unknown"
        assert resolved["name"] == "agent-unknown"  # fallback to agent_id

    # ── BL-17: emit_trace_event called on normal routing path ────────────────

    def test_emit_trace_event_called_on_normal_path(self):
        """BL-17: emit_trace_event('route_decide', ...) fired with all required fields."""
        with patch("src.nodes.route_decide_node.emit_trace_event") as mock_emit:
            self.node.execute(
                _state(
                    [{"agent_id": "agent-fin", "match_score": 0.9, "matched_domain": "finance"}],
                    [{"agent_id": "agent-fin", "name": "Finance Agent", "priority": 1}],
                )
            )

        mock_emit.assert_called_once()
        event_type, payload, _ = mock_emit.call_args[0]
        assert event_type == "route_decide"
        assert "routing_decision" in payload
        assert "confidence_score" in payload
        assert "overlap_flag" in payload
        assert "escalation_flag" in payload
        assert payload["routing_decision"] == "agent-fin"

    # ── BL-18: emit_trace_event called on escalation path ────────────────────

    def test_emit_trace_event_called_on_escalation_path(self):
        """BL-18: emit_trace_event('route_decide', ...) fired with reason='no_candidates'."""
        with patch("src.nodes.route_decide_node.emit_trace_event") as mock_emit:
            self.node.execute(_state([], []))

        mock_emit.assert_called_once()
        event_type, payload, _ = mock_emit.call_args[0]
        assert event_type == "route_decide"
        assert payload["routing_decision"] == "escalate"
        assert payload.get("reason") == "no_candidates"

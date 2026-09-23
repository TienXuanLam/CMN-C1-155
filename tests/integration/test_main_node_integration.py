# CMN-C1-155 — Integration Tests: MainNode end-to-end pipeline
# Tests the full CapabilityLookupNode → IntentClassifyNode → RouteDecideNode chain
# via MainNode.execute() without mocking the orchestration logic.

import json
from unittest.mock import patch

import pytest

from framework.schemas.agent_status import AgentStatus
from src.nodes.main_node import MainNode

_CAPABILITIES = [
    {
        "agent_id": "agent-finance",
        "name": "Finance Agent",
        "domains": ["finance", "reporting"],
        "description": "Handles finance and reporting queries",
        "priority": 1,
    },
    {
        "agent_id": "agent-hr",
        "name": "HR Agent",
        "domains": ["hr", "recruitment"],
        "description": "Handles HR and recruitment queries",
        "priority": 2,
    },
]


def _state(validated_input="process my finance report"):
    return {
        "correlation_id": "test-corr-001",
        "session_id": "test-sess-001",
        "trace_id": "test-trace-001",
        "thread_id": "test-thread-001",
        "validated_input": validated_input,
        "node_history": [],
        "error_log": [],
    }


class TestMainNodeIntegration:
    """Integration tests — full pipeline via MainNode. Covers INT-01..INT-07."""

    def setup_method(self):
        self.node = MainNode()

    # ── INT-01: Full success path ─────────────────────────────────────────────

    def test_full_success_path(self):
        """INT-01: Valid input + matching capability → all output fields set correctly."""
        with (
            patch.object(
                self.node._capability_lookup,
                "_load_capabilities",
                return_value=_CAPABILITIES,
            ),
            patch.object(
                self.node._intent_classify,
                "_call_llm",
                return_value={
                    "classified_intent": "finance_query",
                    "candidate_agents": [
                        {"agent_id": "agent-finance", "match_score": 0.9, "matched_domain": "finance"},
                    ],
                },
            ),
        ):
            result = self.node.execute(_state())

        assert result["status"] == AgentStatus.SUCCESS
        # SEC-C1155-001: complex fields are JSON strings
        assert json.loads(result["registered_capabilities"]) == _CAPABILITIES
        assert result["classified_intent"] == "finance_query"
        assert len(json.loads(result["candidate_agents"])) == 1
        resolved = json.loads(result["resolved_agent"])
        assert resolved["agent_id"] == "agent-finance"
        assert result["routing_decision"] == "agent-finance"
        assert result["confidence_score"] == pytest.approx(0.9)
        assert result["escalation_flag"] is False
        assert result["overlap_flag"] is False

    # ── INT-02: No match → escalation ────────────────────────────────────────

    def test_no_match_escalates(self):
        """INT-02: Valid input + no matching capability → routing_decision="escalate"."""
        with (
            patch.object(
                self.node._capability_lookup,
                "_load_capabilities",
                return_value=_CAPABILITIES,
            ),
            patch.object(
                self.node._intent_classify,
                "_call_llm",
                return_value={"classified_intent": "unknown", "candidate_agents": []},
            ),
        ):
            result = self.node.execute(_state("do something unrecognised"))

        assert result["status"] == AgentStatus.SUCCESS
        assert result["routing_decision"] == "escalate"
        assert result["escalation_flag"] is True
        assert result["confidence_score"] == pytest.approx(0.0)

    # ── INT-03: Registry failure → early ERROR ────────────────────────────────

    def test_registry_failure_early_error(self):
        """INT-03: agent.yaml missing → status=ERROR, no routing fields in result."""
        with patch.object(
            self.node._capability_lookup,
            "_load_capabilities",
            side_effect=FileNotFoundError("config/agent.yaml not found"),
        ):
            result = self.node.execute(_state())

        assert result["status"] == AgentStatus.ERROR
        assert "routing_decision" not in result
        assert "classified_intent" not in result
        assert any("CapabilityLookupNode" in e for e in result["error_log"])

    # ── INT-04: LLM failure → RETRY ──────────────────────────────────────────

    def test_llm_failure_returns_retry(self):
        """INT-04: _call_llm raises → status=RETRY, no routing fields in result."""
        with (
            patch.object(
                self.node._capability_lookup,
                "_load_capabilities",
                return_value=_CAPABILITIES,
            ),
            patch.object(
                self.node._intent_classify,
                "_call_llm",
                side_effect=ConnectionError("LLM timeout"),
            ),
        ):
            result = self.node.execute(_state())

        assert result["status"] == AgentStatus.RETRY
        assert "routing_decision" not in result
        assert any("IntentClassifyNode" in e for e in result["error_log"])

    # ── INT-05: Empty input → ERROR ───────────────────────────────────────────

    def test_empty_input_returns_error(self):
        """INT-05: validated_input="" → status=ERROR before LLM call."""
        with patch.object(
            self.node._capability_lookup,
            "_load_capabilities",
            return_value=_CAPABILITIES,
        ):
            result = self.node.execute(_state(validated_input=""))

        assert result["status"] == AgentStatus.ERROR
        assert "routing_decision" not in result

    # ── INT-06: Low confidence → escalation ──────────────────────────────────

    def test_low_confidence_escalates(self):
        """INT-06: match_score=0.2 → escalation_flag=True, routing_decision="escalate"."""
        with (
            patch.object(
                self.node._capability_lookup,
                "_load_capabilities",
                return_value=_CAPABILITIES,
            ),
            patch.object(
                self.node._intent_classify,
                "_call_llm",
                return_value={
                    "classified_intent": "finance_query",
                    "candidate_agents": [
                        {"agent_id": "agent-finance", "match_score": 0.2, "matched_domain": "finance"},
                    ],
                },
            ),
        ):
            result = self.node.execute(_state())

        assert result["status"] == AgentStatus.SUCCESS
        assert result["routing_decision"] == "escalate"
        assert result["escalation_flag"] is True
        assert result["confidence_score"] == pytest.approx(0.2)

    # ── INT-07: Overlap resolved correctly ────────────────────────────────────

    def test_overlap_resolved_highest_score_wins(self):
        """INT-07: 2 candidates with different scores → highest score wins, overlap_flag=True."""
        with (
            patch.object(
                self.node._capability_lookup,
                "_load_capabilities",
                return_value=_CAPABILITIES,
            ),
            patch.object(
                self.node._intent_classify,
                "_call_llm",
                return_value={
                    "classified_intent": "cross_domain",
                    "candidate_agents": [
                        {"agent_id": "agent-hr", "match_score": 0.7, "matched_domain": "hr"},
                        {"agent_id": "agent-finance", "match_score": 0.85, "matched_domain": "finance"},
                    ],
                },
            ),
        ):
            result = self.node.execute(_state("cross department query"))

        assert result["status"] == AgentStatus.SUCCESS
        assert result["overlap_flag"] is True
        assert result["routing_decision"] == "agent-finance"
        resolved = json.loads(result["resolved_agent"])
        assert resolved["agent_id"] == "agent-finance"
        assert result["confidence_score"] == pytest.approx(0.85)
        assert result["escalation_flag"] is False

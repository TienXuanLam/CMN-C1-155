# CMN-C1-155 — Unit Tests: MainNode

import json
from unittest.mock import patch

import pytest

from framework.schemas.agent_status import AgentStatus
from src.nodes.main_node import MainNode

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

_CAPABILITIES = [
    {
        "agent_id": "agent-finance",
        "name": "Finance Agent",
        "domains": ["finance"],
        "description": "Handles finance queries",
        "priority": 1,
    }
]

# InvocationContext.from_state() requires these fields (SubgraphContext).
_CTX_FIELDS = {
    "correlation_id": "test-corr-001",
    "session_id": "test-sess-001",
    "trace_id": "test-trace-001",
    "thread_id": "test-thread-001",
}

_CAPABILITIES_TWO = [
    {
        "agent_id": "agent-finance",
        "name": "Finance Agent",
        "domains": ["finance"],
        "description": "Handles finance queries",
        "priority": 1,
    },
    {
        "agent_id": "agent-ops",
        "name": "Ops Agent",
        "domains": ["operations"],
        "description": "Handles operations queries",
        "priority": 2,
    },
]


class TestMainNode:
    """Unit tests for MainNode (real orchestrator: Lookup → Classify → Decide)."""

    def setup_method(self):
        self.node = MainNode()

    # ── TC-01 / INT-01: Full success path ───────────────────────────────────

    def test_success_path_routes_to_agent(self):
        """TC-01/INT-01: Valid input + matching capability → routing_decision set."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "process my finance report",
            "node_history": [],
            "error_log": [],
        }
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
                        {"agent_id": "agent-finance", "match_score": 0.9, "matched_domain": "finance"}
                    ],
                },
            ),
        ):
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS
        assert result["routing_decision"] == "agent-finance"
        assert result["escalation_flag"] is False
        assert result["confidence_score"] == pytest.approx(0.9)
        # SEC-C1155-001: complex State fields are JSON strings
        assert json.loads(result["registered_capabilities"]) == _CAPABILITIES
        assert result["classified_intent"] == "finance_query"
        assert result["overlap_flag"] is False

    # ── TC-02 / INT-02: No match → escalate ────────────────────────────────

    def test_no_candidates_escalates(self):
        """TC-02/INT-02: Valid input, no capability match → escalation_flag=True."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "do something unrecognised",
            "node_history": [],
            "error_log": [],
        }
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
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS
        assert result["routing_decision"] == "escalate"
        assert result["escalation_flag"] is True
        assert result["confidence_score"] == 0.0

    # ── TC-03 / INT-03: Registry failure → ERROR ───────────────────────────

    def test_registry_load_failure_returns_error(self):
        """TC-03/INT-03: CapabilityLookupNode failure → ERROR, no further steps."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "any request",
            "node_history": [],
            "error_log": [],
        }
        with patch.object(
            self.node._capability_lookup,
            "_load_capabilities",
            side_effect=FileNotFoundError("config/agent.yaml not found"),
        ):
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.ERROR
        assert "routing_decision" not in result
        assert "classified_intent" not in result

    # ── TC-04 / INT-04: LLM failure → RETRY ───────────────────────────────

    def test_llm_failure_returns_retry(self):
        """TC-04/INT-04: IntentClassifyNode LLM failure → RETRY."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "classify this request",
            "node_history": [],
            "error_log": [],
        }
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
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.RETRY
        assert "routing_decision" not in result

    # ── TC-05 / INT-05: Empty input → ERROR ───────────────────────────────

    def test_empty_input_returns_error(self):
        """TC-05/INT-05: Empty validated_input → ERROR from IntentClassifyNode."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "",
            "node_history": [],
            "error_log": [],
        }
        with patch.object(
            self.node._capability_lookup,
            "_load_capabilities",
            return_value=_CAPABILITIES,
        ):
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.ERROR

    # ── INT-06: Low confidence → escalation ───────────────────────────────

    def test_low_confidence_escalates_via_main_node(self):
        """INT-06: LLM returns match_score=0.2 → escalation through full pipeline."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "vague request",
            "node_history": [],
            "error_log": [],
        }
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
                    "classified_intent": "weak_match",
                    "candidate_agents": [
                        {"agent_id": "agent-finance", "match_score": 0.2, "matched_domain": "finance"}
                    ],
                },
            ),
        ):
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS
        assert result["routing_decision"] == "escalate"
        assert result["confidence_score"] == pytest.approx(0.2)
        assert result["escalation_flag"] is True

    # ── INT-07: Overlap resolved via MainNode ──────────────────────────────

    def test_overlap_resolved_correctly_via_main_node(self):
        """INT-07: LLM returns 2 candidates → overlap resolved, highest score wins."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "multi-domain request",
            "node_history": [],
            "error_log": [],
        }
        with (
            patch.object(
                self.node._capability_lookup,
                "_load_capabilities",
                return_value=_CAPABILITIES_TWO,
            ),
            patch.object(
                self.node._intent_classify,
                "_call_llm",
                return_value={
                    "classified_intent": "multi_domain",
                    "candidate_agents": [
                        {"agent_id": "agent-finance", "match_score": 0.85, "matched_domain": "finance"},
                        {"agent_id": "agent-ops", "match_score": 0.6, "matched_domain": "operations"},
                    ],
                },
            ),
        ):
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS
        assert result["overlap_flag"] is True
        assert result["routing_decision"] == "agent-finance"
        assert result["escalation_flag"] is False

    # ── BND-08: node_history from input state not mutated by MainNode ────────

    def test_node_history_not_mutated_by_main_node(self):
        """BND-08: MainNode must not mutate the node_history list from input state."""
        original_history = ["InitializeNode", "PreProcessNode"]
        state = {
            **_CTX_FIELDS,
            "validated_input": "test request",
            "node_history": original_history,
            "error_log": [],
        }
        with (
            patch.object(
                self.node._capability_lookup,
                "_load_capabilities",
                return_value=_CAPABILITIES,
            ),
            patch.object(
                self.node._intent_classify,
                "_call_llm",
                return_value={"classified_intent": "finance_query", "candidate_agents": []},
            ),
        ):
            self.node.execute(state)

        # The original list must be unchanged
        assert state["node_history"] == original_history, "MainNode must not mutate the input state's node_history list"

    # ── Node contract ──────────────────────────────────────────────────────────────────────────────────────────────────────

    def test_execute_method_signature(self):
        """Node contract: execute(self, state, config=None) — no _invoke_impl."""
        import inspect

        assert hasattr(MainNode, "execute"), "MainNode must implement execute()"

        sig = inspect.signature(MainNode.execute)
        params = list(sig.parameters.keys())
        assert len(params) >= 2, f"execute() must accept (self, state, ...), got: {params}"
        assert params[1] == "state", f"Second parameter must be 'state', got '{params[1]}'"
        assert (
            "_invoke_impl" not in MainNode.__dict__
        ), "_invoke_impl() must not be defined in MainNode — use execute() instead"

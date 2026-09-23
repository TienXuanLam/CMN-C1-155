# CMN-C1-155 — Unit Tests: IntentClassifyNode

import json
from unittest.mock import patch


from framework.schemas.agent_status import AgentStatus
from src.nodes.intent_classify_node import IntentClassifyNode

_CAPABILITIES = [
    {
        "agent_id": "agent-finance",
        "name": "Finance Agent",
        "domains": ["finance"],
        "description": "Handles finance queries",
        "priority": 1,
    },
    {
        "agent_id": "agent-hr",
        "name": "HR Agent",
        "domains": ["hr"],
        "description": "Handles HR queries",
        "priority": 2,
    },
]

# SEC-C1155-001: pass registered_capabilities as JSON string in state
_CAPABILITIES_JSON = json.dumps(_CAPABILITIES)

# InvocationContext.from_state() requires these fields (SubgraphContext).
_CTX_FIELDS = {
    "correlation_id": "test-corr-001",
    "session_id": "test-sess-001",
    "trace_id": "test-trace-001",
    "thread_id": "test-thread-001",
}


class TestIntentClassifyNode:
    """Unit tests for IntentClassifyNode (BL-06..BL-11)."""

    def setup_method(self):
        self.node = IntentClassifyNode()

    # ── BL-06: Happy path — single match ────────────────────────────────────

    def test_happy_path_single_match(self):
        """BL-06: LLM returns single candidate → correct output fields (JSON str)."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "process my finance report",
            "registered_capabilities": _CAPABILITIES_JSON,
            "node_history": [],
            "error_log": [],
        }
        with patch.object(
            self.node,
            "_call_llm",
            return_value={
                "classified_intent": "finance_query",
                "candidate_agents": [{"agent_id": "agent-finance", "match_score": 0.9, "matched_domain": "finance"}],
            },
        ):
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS
        assert isinstance(result["classified_intent"], str)
        assert len(result["classified_intent"]) > 0
        # SEC-C1155-001: candidate_agents is a JSON string
        assert isinstance(result["candidate_agents"], str)
        agents = json.loads(result["candidate_agents"])
        assert len(agents) == 1
        assert "agent_id" in agents[0]
        assert "match_score" in agents[0]
        assert "matched_domain" in agents[0]

    # ── BL-07: Empty validated_input → ERROR ────────────────────────────────

    def test_empty_input_returns_error(self):
        """BL-07: Empty validated_input → status=ERROR, error_log populated."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "",
            "registered_capabilities": _CAPABILITIES_JSON,
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)

        assert result["status"] == AgentStatus.ERROR
        assert result["classified_intent"] == ""
        assert json.loads(result["candidate_agents"]) == []
        assert any("IntentClassifyNode" in e for e in result["error_log"])

    # ── BL-08: LLM failure → RETRY ──────────────────────────────────────────

    def test_llm_failure_returns_retry(self):
        """BL-08: _call_llm raises ConnectionError → status=RETRY."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "some request",
            "registered_capabilities": _CAPABILITIES_JSON,
            "node_history": [],
            "error_log": [],
        }
        with patch.object(
            self.node,
            "_call_llm",
            side_effect=ConnectionError("LLM timeout"),
        ):
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.RETRY
        assert result["classified_intent"] == ""
        assert json.loads(result["candidate_agents"]) == []
        assert len(result["error_log"]) > 0
        assert result["retry_count"] == 1

    def test_llm_failure_increments_existing_retry_count(self):
        """RETRY must increment retry_count, or the graph's route() loops forever."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "some request",
            "registered_capabilities": _CAPABILITIES_JSON,
            "node_history": [],
            "error_log": [],
            "retry_count": 1,
        }
        with patch.object(
            self.node,
            "_call_llm",
            side_effect=ConnectionError("LLM timeout"),
        ):
            result = self.node.execute(state)

        assert result["retry_count"] == 2

    # ── BL-09: LLM returns no matches ───────────────────────────────────────

    def test_no_matches_returns_success(self):
        """BL-09: LLM returns candidate_agents=[] → status=SUCCESS (valid outcome)."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "unrecognised request",
            "registered_capabilities": _CAPABILITIES_JSON,
            "node_history": [],
            "error_log": [],
        }
        with patch.object(
            self.node,
            "_call_llm",
            return_value={"classified_intent": "unknown", "candidate_agents": []},
        ):
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS
        assert isinstance(result["classified_intent"], str)
        assert json.loads(result["candidate_agents"]) == []

    # ── BL-10: LLM returns multiple matches ─────────────────────────────────

    def test_multiple_matches_returned(self):
        """BL-10: LLM returns 2+ candidates → all preserved with required fields."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "cross-department query",
            "registered_capabilities": _CAPABILITIES_JSON,
            "node_history": [],
            "error_log": [],
        }
        with patch.object(
            self.node,
            "_call_llm",
            return_value={
                "classified_intent": "multi_domain",
                "candidate_agents": [
                    {"agent_id": "agent-finance", "match_score": 0.8, "matched_domain": "finance"},
                    {"agent_id": "agent-hr", "match_score": 0.6, "matched_domain": "hr"},
                ],
            },
        ):
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS
        agents = json.loads(result["candidate_agents"])
        assert len(agents) == 2
        for agent in agents:
            assert "agent_id" in agent
            assert "match_score" in agent
            assert "matched_domain" in agent

    # ── BL-11: Empty registered_capabilities ────────────────────────────────

    def test_empty_capabilities_still_calls_llm(self):
        """BL-11: Empty capabilities JSON str → LLM called, candidate_agents=[], SUCCESS."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "some request",
            "registered_capabilities": json.dumps([]),
            "node_history": [],
            "error_log": [],
        }
        with patch.object(
            self.node,
            "_call_llm",
            return_value={"classified_intent": "general", "candidate_agents": []},
        ) as mock_llm:
            result = self.node.execute(state)

        mock_llm.assert_called_once()
        assert result["status"] == AgentStatus.SUCCESS
        assert json.loads(result["candidate_agents"]) == []

    # ── BND-04: None/missing validated_input ─────────────────────────────────

    def test_missing_validated_input_returns_error(self):
        """BND-04: validated_input absent from state → ERROR before LLM call."""
        state = {
            **_CTX_FIELDS,
            "registered_capabilities": _CAPABILITIES_JSON,
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)

        assert result["status"] == AgentStatus.ERROR
        assert result["classified_intent"] == ""
        assert json.loads(result["candidate_agents"]) == []

    # ── Output completeness ───────────────────────────────────────────────────

    def test_success_output_contains_required_keys(self):
        """Success output must include classified_intent, candidate_agents (JSON str), status."""
        state = {
            **_CTX_FIELDS,
            "validated_input": "test query",
            "registered_capabilities": _CAPABILITIES_JSON,
            "node_history": [],
            "error_log": [],
        }
        with patch.object(
            self.node,
            "_call_llm",
            return_value={"classified_intent": "test", "candidate_agents": []},
        ):
            result = self.node.execute(state)

        assert "classified_intent" in result
        assert "candidate_agents" in result
        assert isinstance(result["candidate_agents"], str)  # SEC-C1155-001
        assert "status" in result

    # ── Node contract ───────────────────────────────────────────────────────────────────────────────────────────────────────

    def test_execute_method_signature(self):
        """Node contract: execute(self, state, config=None), no _invoke_impl."""
        import inspect

        sig = inspect.signature(IntentClassifyNode.execute)
        params = list(sig.parameters.keys())
        assert params[1] == "state"
        assert "_invoke_impl" not in IntentClassifyNode.__dict__

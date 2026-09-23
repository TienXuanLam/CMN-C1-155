# CMN-C1-155 — Unit Tests: CapabilityLookupNode

import json
from unittest.mock import patch

import yaml

from framework.schemas.agent_status import AgentStatus
from src.nodes.capability_lookup_node import CapabilityLookupNode

_VALID_CAPABILITIES = [
    {
        "agent_id": "agent-finance",
        "name": "Finance Agent",
        "domains": ["finance"],
        "description": "Handles finance queries",
        "priority": 1,
    }
]


class TestCapabilityLookupNode:
    """Unit tests for CapabilityLookupNode (BL-01..BL-05)."""

    def setup_method(self):
        self.node = CapabilityLookupNode()

    # ── BL-01: Happy path ────────────────────────────────────────────────────

    def test_happy_path_loads_capabilities(self):
        """BL-01: Valid yaml with entries → registered_capabilities JSON str with correct fields."""
        state = {"validated_input": "test", "node_history": [], "error_log": []}
        with patch.object(self.node, "_load_capabilities", return_value=_VALID_CAPABILITIES):
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS
        # SEC-C1155-001: registered_capabilities is a JSON string in State
        assert isinstance(result["registered_capabilities"], str)
        caps = json.loads(result["registered_capabilities"])
        assert len(caps) == 1
        entry = caps[0]
        assert entry["agent_id"] == "agent-finance"
        assert entry["name"] == "Finance Agent"
        assert "domains" in entry
        assert "description" in entry
        assert entry["priority"] == 1

    # ── BL-02: Empty capabilities list ──────────────────────────────────────

    def test_empty_capabilities_returns_success(self):
        """BL-02: capabilities=[] → empty JSON array str, status=SUCCESS (not ERROR)."""
        state = {"validated_input": "test", "node_history": [], "error_log": []}
        with patch.object(self.node, "_load_capabilities", return_value=[]):
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS
        assert json.loads(result["registered_capabilities"]) == []

    # ── BL-03: Missing yaml file ─────────────────────────────────────────────

    def test_missing_yaml_returns_error(self):
        """BL-03: FileNotFoundError → status=ERROR, error_log populated."""
        state = {"validated_input": "test", "node_history": [], "error_log": []}
        with patch.object(
            self.node,
            "_load_capabilities",
            side_effect=FileNotFoundError("config/agent.yaml not found"),
        ):
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.ERROR
        assert json.loads(result["registered_capabilities"]) == []
        assert any("CapabilityLookupNode" in e for e in result["error_log"])

    # ── BL-04: capabilities key absent from yaml ─────────────────────────────

    def test_absent_capabilities_key_returns_empty_success(self):
        """BL-04: yaml has no capabilities key → [], status=SUCCESS."""
        state = {"validated_input": "test", "node_history": [], "error_log": []}
        with patch.object(self.node, "_load_capabilities", return_value=[]):
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.SUCCESS
        assert json.loads(result["registered_capabilities"]) == []

    # ── BL-05: Malformed yaml ────────────────────────────────────────────────

    def test_malformed_yaml_returns_error(self):
        """BL-05: yaml.YAMLError → status=ERROR, error_log populated."""
        state = {"validated_input": "test", "node_history": [], "error_log": []}
        with patch.object(
            self.node,
            "_load_capabilities",
            side_effect=yaml.YAMLError("scan error"),
        ):
            result = self.node.execute(state)

        assert result["status"] == AgentStatus.ERROR
        assert json.loads(result["registered_capabilities"]) == []
        assert len(result["error_log"]) > 0

    # ── Output completeness ───────────────────────────────────────────────────

    def test_output_contains_required_keys(self):
        """Success output must include registered_capabilities (JSON str) and status."""
        state = {"validated_input": "test", "node_history": [], "error_log": []}
        with patch.object(self.node, "_load_capabilities", return_value=_VALID_CAPABILITIES):
            result = self.node.execute(state)

        assert "registered_capabilities" in result
        assert isinstance(result["registered_capabilities"], str)  # SEC-C1155-001
        assert "status" in result

    # ── Node contract ───────────────────────────────────────────────────────────────────────────────────────────────────────

    def test_execute_method_signature(self):
        """Node contract: execute(self, state, config=None), no _invoke_impl."""
        import inspect

        sig = inspect.signature(CapabilityLookupNode.execute)
        params = list(sig.parameters.keys())
        assert params[1] == "state"
        assert "_invoke_impl" not in CapabilityLookupNode.__dict__

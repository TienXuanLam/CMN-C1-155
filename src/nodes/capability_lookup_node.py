"""AgentCore Platform v1.0"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event


class CapabilityLookupNode(FunctionNode):
    """Load agent capability registry from config/config.yaml.

    Swap point: replace this class with a Redis/KV variant for
    high-volume or frequently updated registries (design doc §6).

    Input:  validated_input (read, not modified)
    Output: registered_capabilities — JSON string (SEC-C1155-001)
    """

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL
    _CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"

    def __init__(self) -> None:
        super().__init__()

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        emit_trace_event("capability_lookup_started", {}, state)
        try:
            capabilities = self._load_capabilities()
        except Exception as exc:
            return {
                "registered_capabilities": json.dumps([]),  # SEC-C1155-001: serialize to str
                "status": AgentStatus.ERROR,
                "error_log": [f"CapabilityLookupNode: failed to load registry — {exc}"],
            }

        return {
            "registered_capabilities": json.dumps(capabilities),  # SEC-C1155-001: serialize to str
            "status": AgentStatus.SUCCESS,
        }

    def _load_capabilities(self) -> list[dict[str, Any]]:
        """Load capabilities list from config/config.yaml.

        Each entry must have: agent_id, name, domains, description, priority
        Returns empty list if capabilities key is absent.
        """
        with open(self._CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError("config root must be a mapping")
        capabilities = data.get("capabilities", []) or []
        if not isinstance(capabilities, list):
            raise ValueError("capabilities must be a list")
        required = {"agent_id", "name", "domains", "description", "priority"}
        normalized: list[dict[str, Any]] = []
        for index, capability in enumerate(capabilities):
            if not isinstance(capability, dict) or not required.issubset(capability):
                raise ValueError(f"capabilities[{index}] is missing required fields")
            normalized.append(dict(capability))
        return normalized

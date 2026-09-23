"""CMN-C1-155 capability-routing graph."""

from typing import Any

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from framework.security import detect_credentials
from shared.utils.audit_logger import emit_trace_event
from src.nodes.main_node import MainNode
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State


class Graph(AgentBaseGraph):
    """Fixed Cat 1 pipeline for capability lookup, classification and routing."""

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    @property
    def name(self) -> str:
        return "cmn-c1-155"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()
        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = MainNode(
            llm_temperature=float(self.config.get("llm_temperature", 0.2)),
            llm_max_tokens=int(self.config.get("llm_max_tokens", 4096)),
            timeout_s=int(self.config.get("timeout_s", 120)),
            max_retry=int(self.config.get("max_retry", 2)),
            confidence_threshold=float(self.config.get("confidence_threshold", 0.5)),
        )
        self._nodes["post_process"] = PostProcessNode()

    def _enrich_output(self, output: dict[str, Any], result: dict[str, Any]) -> None:
        """Block credentials at the outermost response boundary."""
        findings = detect_credentials(str(output.get("output", "")))
        if not findings:
            return
        emit_trace_event(
            "s3_gate_violation",
            {
                "credential_types": sorted({finding["type"] for finding in findings}),
                "action": "blocked",
                "field": "output",
            },
            result,
        )
        output["output"] = "BLOCKED: credential pattern detected in output"
        output["status"] = AgentStatus.ERROR.value

"""AgentCore Platform v1.0"""

# ADR-005: State must be a flat TypedDict — never Pydantic BaseModel,
# never a subclass of another TypedDict or AgentState.
# LangGraph checkpoints use msgpack serialization; inheritance hierarchies
# cause silent corruption. Declare ALL fields flat in one TypedDict.
#
# SEC-C1155-001: complex types (dict, list[dict]) must be serialized to
# Optional[str] (JSON string) on write and parsed back on read.
# Use json.dumps() before writing to State, json.loads() after reading.

from typing import Annotated, Any, Optional
import operator
from typing import TypedDict


class State(TypedDict, total=False):
    """CMN-C1-155 flat State — all fields in one TypedDict (ADR-005).

    Shared AgentState fields are redeclared here (no inheritance).
    Complex types stored as JSON strings per SEC-C1155-001.
    """

    # ── Shared (AgentState / SubgraphContext) fields ──────────────────────
    schema_version: str
    correlation_id: str
    trace_id: str
    session_id: str
    thread_id: str
    caller_trust_level: str
    caller_id: str
    status: str
    retry_count: int
    node_history: Annotated[list[str], operator.add]
    error_log: Annotated[list[str], operator.add]
    execution_time: dict[str, Any]
    user_input: str
    input_context: dict[str, Any]
    intent: str
    context: dict[str, Any]
    result: Any
    formatted_output: Optional[str]
    response_metadata: dict[str, Any]

    # ── Input ─────────────────────────────────────────────────────────────
    validated_input: Optional[str]  # sanitized user request (from pre_process)
    enriched_context: Optional[str]  # JSON: {source} — read-only after pre_process

    # ── Registry ──────────────────────────────────────────────────────────
    registered_capabilities: Optional[str]  # JSON: [{agent_id, name, domains, description, priority}]

    # ── Classification ────────────────────────────────────────────────────
    classified_intent: Optional[str]  # intent label from LLM
    candidate_agents: Optional[str]  # JSON: [{agent_id, match_score, matched_domain}]

    # ── Overlap resolution ────────────────────────────────────────────────
    resolved_agent: Optional[str]  # JSON: {agent_id, name, confidence}
    overlap_flag: Optional[bool]  # True if multiple agents matched

    # ── Routing output ────────────────────────────────────────────────────
    routing_decision: Optional[str]  # target agent_id or "escalate"
    confidence_score: Optional[float]  # 0.0–1.0
    escalation_flag: Optional[bool]  # True if no confident match found

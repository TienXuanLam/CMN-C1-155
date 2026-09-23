# CMN-C1-155 — Design Specification

**Template**: CMN-C1-155 Agent Capability Registry & Request Routing Classification Agent
**Category**: Cat 1 — Generic (CMN)
**L1 Base**: `AgentBaseGraph`
**Status**: Migrated to scaffold; SDK agenticstar-agentcore[marketplace,openai]==1.0.3
**Date**: 2026-06-04

---

## 1 — Position in AgentCore Architecture

### 1-1. Layer Model

```
Level 0 (L0): agenticstar-platform SDK   ← DO NOT import
Level 1 (L1): framework/                 ← Inherit from directly
              AgentBaseGraph, FunctionNode, InvocationContext
─────────────────────────────────────────────────────────────────────────────
CMN-C1-155 (this template)               ← L1-direct (no Level 2 base)
  src/schemas/state.py    — State (flat TypedDict — ADR-005, no AgentState inheritance)
  src/nodes/              — 6 domain nodes (see §2-2)
  src/graph/graph.py      — AgentBaseGraph subclass
  src/api/server.py       — FastAPI entry point
```

> **L1-direct policy (2026-05-18):** Templates inherit directly from Level 1 framework
> primitives only. No Level 2 base agent class (`agents/base/`) is used or expected.
> `BaseNode` sole abstract method: `execute(self, state: dict) -> dict` — no `config` param.

### 1-2. Three-Layer Separation

| Layer | Pattern | Implementation |
|-------|---------|----------------|
| State | Flat TypedDict | Primitives + JSON-serializable list/dict only. No Pydantic, no dataclass. |
| Node | Inheritance (Template Method) | Extends `FunctionNode`; implements `execute()`. Returns only changed keys. |
| Graph | Composition (Builder) | `AgentBaseGraph`; wires nodes via `register_nodes()` + `add_edges()`. |

---

## 2 — Node Flow

### 2-1. Pipeline

```
START
  → initialize              (InitializeNode — framework default)
  → pre_process             (PreProcessNode — input validation + S-2 gate)
  → main                    (MainNode — wraps 3 domain steps sequentially)
      ├─ CapabilityLookupNode   query registry, load agent descriptors
      ├─ IntentClassifyNode     LLM classify request vs capabilities
      └─ RouteDecideNode        resolve overlap and select target/escalation
  → {route}
      SUCCESS → post_process
      RETRY   → pre_process  (max 3)
      ERROR   → finalize
  → post_process            (PostProcessNode — format output + S-3 gate)
  → finalize                (FinalizeNode — framework default)
END
```

> **Implementation note:** The standard AgentBaseGraph backbone provides 3 domain slots
> (`pre_process`, `main`, `post_process`). The 4 domain steps inside `main` are
> orchestrated sequentially within `MainNode.execute()` rather than as separate
> top-level graph nodes. This keeps the outer graph Cat 1 compliant (single fixed pipeline)
> while encapsulating multi-step domain logic inside the main slot.

### 2-2. Node Specification

| Node | Class | Extends | Responsibility | Input State Fields | Output State Fields |
|------|-------|---------|----------------|--------------------|---------------------|
| initialize | `InitializeNode` | framework default | Session init, schema_version, correlation_id, caller_trust_level | `user_input` | `session_id`, `correlation_id`, `schema_version` |
| pre_process | `PreProcessNode` | `FunctionNode` | Input validation plus framework credential/injection detection | `user_input` | `validated_input`, `enriched_context`, `status` |
| main | `MainNode` | `FunctionNode` | Orchestrate 3 domain steps sequentially | `validated_input` | `routing_decision`, `confidence_score`, `escalation_flag`, `status` |
| ↳ CapabilityLookupNode | `CapabilityLookupNode` | `FunctionNode` | Load agent registry from config or external KV | `validated_input` | `registered_capabilities` |
| ↳ IntentClassifyNode | `IntentClassifyNode` | `FunctionNode` | LLM classify intent against capabilities (JSON mode) | `validated_input`, `registered_capabilities` | `classified_intent`, `candidate_agents` |
| ↳ RouteDecideNode | `RouteDecideNode` | `FunctionNode` | Resolve overlap, apply configured threshold and decide routing | `candidate_agents`, `registered_capabilities` | `resolved_agent`, `overlap_flag`, `routing_decision`, `confidence_score`, `escalation_flag` |
| post_process | `PostProcessNode` | `FunctionNode` | Format JSON response and emit audit event | `routing_decision` | `result`, `formatted_output` |
| finalize | `FinalizeNode` | framework default | Audit log, response_metadata, total_time_ms | `result` | — |

---

## 3 — State Definition

```python
class State(TypedDict, total=False):
    # ── Shared fields (redeclared from AgentState — ADR-005: no inheritance) ──
    correlation_id: str
    session_id: str
    trace_id: str
    thread_id: str
    status: str
    node_history: Annotated[list, operator.add]
    error_log: Annotated[list, operator.add]
    # ... (all AgentState fields redeclared inline)

    # ── Input ─────────────────────────────────────────────────────────────────
    validated_input: Optional[str]          # sanitized user request (from pre_process)
    enriched_context: Optional[str]         # JSON str: {source}

    # ── Registry ──────────────────────────────────────────────────────────────
    registered_capabilities: Optional[str]  # JSON str: [{agent_id, name, domains, description, priority}]

    # ── Classification ────────────────────────────────────────────────────────
    classified_intent: Optional[str]        # intent label from LLM
    candidate_agents: Optional[str]         # JSON str: [{agent_id, match_score, matched_domain}]

    # ── Overlap resolution ────────────────────────────────────────────────────
    resolved_agent: Optional[str]           # JSON str: {agent_id, name, confidence}
    overlap_flag: Optional[bool]            # True if multiple agents matched

    # ── Routing output ────────────────────────────────────────────────────────
    routing_decision: Optional[str]         # target agent_id or "escalate"
    confidence_score: Optional[float]       # 0.0–1.0
    escalation_flag: Optional[bool]         # True if no confident match found
```

> **SEC-C1155-001:** Complex types (`dict`, `list[dict]`) are serialized to
> `Optional[str]` (JSON string) in State for msgpack checkpoint compatibility.
> Nodes use `json.dumps()` on write and `json.loads()` on read.

**State Constraints (mandatory — enforced by PB-2, PB-5):**
- Flat TypedDict only — no Pydantic, no dataclass, no nested objects
- No credentials, JWT, or API keys in State
- `InvocationContext` via `InvocationContext.from_state(state)` only — never stored in State
- All fields JSON-serializable (msgpack checkpoint compatibility)

---

## 4 — Security Model

All 5 layers of the AgentCore security model are implemented.

| Layer | Implementation | Node | Detail |
|-------|---------------|------|--------|
| S-1 | `required_trust_level` | All nodes | `VERIFIED_EXTERNAL` — set in `config/agent.yaml` and enforced by `BaseNode.__call__()` automatically |
| S-2 | `_extra_security_gate_input()` | `PreProcessNode` | Framework credential and prompt-injection detectors reject unsafe input |
| S-3 | `Graph._enrich_output()` | Agent boundary | Framework credential detector blocks leaked credentials in every response path |
| S-4 | `emit_trace_event()` | `PostProcessNode`, `RouteDecideNode` | Routing decision logged with `agent_id`, `confidence_score`, `correlation_id` — from `shared.utils.audit_logger` |
| S-5 | `__init_subclass__` | Automatic (framework) | JWT pattern detection at import time — no template code required |

**Execution order:**
```
BaseNode.__call__() S-1 check
  → _security_gate_input()              [S-2, pre_process]
  → execute()                           [domain logic]
  → _security_gate_output()             [S-3, post_process]
  → emit_trace_event(type, payload, state)  [S-4, post_process — shared.utils.audit_logger]
```

---

## 5 — LLM Integration

- **Node**: `IntentClassifyNode`
- **Call pattern**: Single LLM call per invocation with structured output (JSON mode)
- **Prompt inputs**: `validated_input` (string) + serialized `registered_capabilities` (list)
- **Output**: `classified_intent` (string label) + `candidate_agents` (list of dicts)
- **Client construction**: `IntentClassifyNode._build_llm(state)` builds a fresh, secret-bound `AzureOpenAIClient` per invocation via `src.services.azure_openai_service.AzureOpenAIService.create_client(state)`, reading secrets from `InvocationContext.from_state(state)` — not constructor injection. Constructor injection (a client set once at graph construction via `config["llm"]`) is structurally unreachable on the real Marketplace path (`cli.py`/`run_agent_marketplace()` never populate `config["llm"]`) and would additionally cache one caller's authenticated client on the node instance for reuse by every subsequent caller served by that instance — see `docs/06_release_note.md`.
- **Retry**: `ConnectionPolicy` — max 3 retries, exponential backoff
- **Timeout**: 30 seconds (configured in `config/config.yaml`)

**Prompt structure (IntentClassifyNode):**
```
System: You are a routing classifier. Given the user request and available agent capabilities,
        return a JSON object: {"classified_intent": <string>, "candidate_agents": [...]}.
User:   Request: {validated_input}
        Capabilities: {registered_capabilities}
```

---

## 6 — Registry Storage Strategy

| Mode | Implementation | When to use |
|------|---------------|-------------|
| Default | `config/config.yaml` → `capabilities[]` | Base Cat 1, zero external dependency |
| Extension | Swap `CapabilityLookupNode` to query Redis / DynamoDB | High-volume, frequently updated registry |

**Capability entry format:**
```yaml
capabilities:
  - agent_id: "agent-fin-report-001"
    name: "FinancialReportAgent"
    domains: ["finance", "reporting", "compliance"]
    description: "Generates structured financial reports from raw data"
    priority: 1          # lower = higher priority when confidence is tied
```

`CapabilityLookupNode` is designed as a swap point — replacing the node class
does not require changes to any other node or the graph wiring.

---

## 7 — Error Handling & Retry Strategy

| Scenario | Handling | Output State |
|----------|----------|-------------|
| Empty / blank `user_input` | `PreProcessNode` returns `ERROR` immediately | `status=ERROR`, `error_log` populated |
| LLM call fails (timeout / network) | `ConnectionPolicy` retries up to 3×; on exhaustion sets `status=RETRY` → graph re-enters `pre_process` | `status=RETRY` |
| No capable agent found (`candidate_agents` empty) | `RouteDecideNode` sets `escalation_flag=True`, `routing_decision="escalate"` | `status=SUCCESS`, `escalation_flag=True` |
| Multiple agents match, unresolvable overlap | `OverlapResolveNode` falls back to highest `priority` in registry | `overlap_flag=True`, `resolved_agent` = highest priority |
| `confidence_score` below threshold (< 0.5) | `RouteDecideNode` sets `escalation_flag=True` regardless of match | `escalation_flag=True` |
| Security gate violation (S-2 / S-3) | `SecurityViolationError` raised → propagates to `finalize` | `status=ERROR` |

**Retry ceiling**: max 3 (configured via `config/agent.yaml` → `config.max_retry`).
After 3 retries the graph routes directly to `finalize` with `status=ERROR`.

---

## 8 — Framework Utilization

- [x] `InvocationContext` — LLM credential handle in `IntentClassifyNode`
- [x] `emit_trace_event(type, payload, state)` — routing decision logged in `RouteDecideNode` and `PostProcessNode` (from `shared.utils.audit_logger`)
- [x] `ConnectionPolicy` — retry/timeout on LLM call in `IntentClassifyNode`
- [x] `SecurityViolationError` — raised on S-2/S-3 gate failure
- [x] `_security_gate_input()` — in `PreProcessNode` (mandatory, non-bypassable)
- [x] `_security_gate_output()` — in `PostProcessNode` (mandatory, non-bypassable)
- [x] `AgentStatus` enum — `SUCCESS` / `RETRY` / `ERROR` (never plain strings)

**Composition Pattern**: Standalone (no `GraphNode` or `RemoteAgentNode`)
**Error propagation**: propagate to `finalize` — no graceful degradation at graph level

---

## 9 — Import Isolation Confirmation

- [x] Does NOT import `agenticstar-platform` SDK (Level 0) — verified by `gate-import-isolation` CI
- [x] Import targets: `framework/` (L1) and `shared/` only
- [x] No cross-template imports (`agents/domain/` siblings)

**Allowed imports:**
```python
from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.function_node import FunctionNode
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.schemas.agent_status import AgentStatus
from framework.secrets.context import bound_secrets
from shared.utils.audit_logger import emit_trace_event
from shared.secrets.inmemory_provider import InMemoryProvider
```

---

## 10 — Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | `AgentBaseGraph` | `AutonomousBaseGraph` | `AgentBaseGraph` | Fixed 6-step pipeline — deterministic routing, no autonomous loop needed |
| Domain steps placement | 4 top-level graph nodes | 4 steps inside `MainNode.execute()` | Inside `MainNode` | Keeps outer graph Cat 1 compliant (3 slots); avoids overriding `add_edges()` |
| Registry storage | Config YAML | External KV (Redis) | Config YAML (default) | Zero external dependency for base Cat 1; KV swap via `CapabilityLookupNode` substitution |
| Overlap resolution | Rule-based (priority field) | LLM re-rank | Rule-based | Deterministic, auditable; LLM re-rank adds latency and cost without clear benefit at Cat 1 |
| Confidence threshold | Fixed (0.5) | Configurable via `agent.yaml` | Fixed (0.5) | Simplicity for Cat 1 baseline; can be made configurable in a future iteration |
| No-match handling | Return error | Escalation flag + `"escalate"` decision | Escalation flag | Caller (parent agent or human) decides what to do with escalation — not this template's concern |

# Test Specification — CMN-C1-155
# Agent Capability Registry & Request Routing Classification Agent

## Test Strategy
- Coverage target: **80%**
- Test types: Unit / Integration / Proof-of-Boundary
- Test files: `tests/unit/`, `tests/integration/`, `tests/proof_of_boundary/`
- TC-IDs in this doc match docstrings in test files
- **Output field assertions are mandatory** — every test must verify the exact
  value of every output state field, not just `status`

---

## Section 1 — Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State: flat TypedDict, no Pydantic/dataclass | Type check pass | TBD |
| TC-02 | `SecurityViolationError` on invalid input | Error raised | TBD |
| TC-03 | No JWT/credential in State | `__init_subclass__` detection pass | TBD |
| TC-04 | `InvocationContext` via `InvocationContext.from_state(state)` only | Direct access raises error | TBD |
| TC-05 | `emit_trace_event()` logs recorded | Routing decision logged with `agent_id`, `confidence_score`, `correlation_id` — from `shared.utils.audit_logger` | TBD |
| TC-06 | `_security_gate_input()` non-bypassable | PII gate always executes; masked or rejected | TBD |
| TC-07 | `_security_gate_output()` non-bypassable | Content filter always executes; credential patterns blocked | TBD |
| TC-08 | `required_trust_level` enforced | `VERIFIED_EXTERNAL` required; `ANONYMOUS` caller → refused | TBD |

---

## Section 2 — Proof-of-Boundary Tests (Mandatory)

Implemented in `tests/proof_of_boundary/test_import_isolation.py` (PB-4)
and `tests/proof_of_boundary/test_state_safety.py` (PB-2, PB-5), with
PB-6 invoke-order, PB-7 conditional HITL, server injection and LLM-contract tests.

| PB-ID | Boundary | Test | Expected Result | Output Assertions | Result |
|-------|----------|------|----------------|-------------------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on `RouteDecideNode` | No silent failures | Event payload contains `routing_decision`, `confidence_score`, `overlap_flag`, `escalation_flag` | TBD |
| PB-2 | State serialization | Post-invoke State fields are primitives only; no `datetime`/`bytes`/`Decimal`/`UUID`; flat TypedDict (ADR-005 — no `AgentState` inheritance, no `BaseModel`) | No Pydantic/dataclass/arbitrary objects | All State fields are `str`, `int`, `float`, `bool`, `list`, `dict` — verified by AST scan (3 tests: `test_state_file_safety`, `test_state_fields_are_json_serializable_types`, `test_state_is_flat_typed_dict`) | PASS |
| PB-3 | L1 → External service | Template connects to external service via L1 framework | Real data retrieval | `registered_capabilities` non-empty from live registry | TBD |
| PB-4 | Import isolation | No Level 0 imports; no cross-template imports (`agents.domain`/`agents.base`); framework imports only from allowed L1 modules | AST scan: 0 violations | 0 L0 violations + 0 cross-template imports + 0 unexpected `framework.*` modules (3 tests: `test_no_prohibited_imports_in_src`, `test_no_cross_template_imports_in_src`, `test_framework_imports_only_from_allowed_modules`) | PASS |
| PB-5 | Checkpoint safety | Saved checkpoint contains no JWT/Pydantic objects; `InvocationContext` not stored in State | Checkpoint inspection pass | No credential-pattern fields + no `InvocationContext` annotation in State (2 tests: `test_state_file_safety`, `test_invocation_context_not_in_state`) | PASS |
| PB-6 | Invoke execution order | Sequence: pre_invoke → gate_input → route → impl → gate_output → trace | Order verification pass | Call order verified via mock spy on each gate method | TBD |

---

## Section 3 — Business Logic Tests

### Unit — CapabilityLookupNode

| TC-ID | Test | Input | Expected Output Fields | Expected Result | Result |
|-------|------|-------|----------------------|----------------|--------|
| BL-01 | Happy path: load from config.yaml | Valid yaml with 1+ capability entries under `capabilities:` key | `registered_capabilities`, `status` | `registered_capabilities` = JSON str of list of dicts each with `agent_id`, `name`, `domains`, `description`, `priority`; `status=SUCCESS` | PASS |
| BL-02 | Empty capabilities key | `capabilities: []` in config.yaml | `registered_capabilities`, `status` | `registered_capabilities=[]` (JSON str); `status=SUCCESS` (empty is valid, not ERROR) | PASS |
| BL-03 | Missing yaml file | File path not found | `registered_capabilities`, `status`, `error_log` | `registered_capabilities=[]`; `status=ERROR`; `error_log` contains `"CapabilityLookupNode"` and exception message | PASS |
| BL-04 | Capabilities key absent from yaml | yaml has no `capabilities` key | `registered_capabilities`, `status` | `registered_capabilities=[]`; `status=SUCCESS` | PASS |
| BL-05 | Malformed yaml | Unparseable yaml content | `registered_capabilities`, `status`, `error_log` | `registered_capabilities=[]`; `status=ERROR`; `error_log` populated | PASS |

### Unit — IntentClassifyNode

| TC-ID | Test | Input | Expected Output Fields | Expected Result | Result |
|-------|------|-------|----------------------|----------------|--------|
| BL-06 | Happy path: LLM returns single match | `validated_input="finance report"`, 1 capability | `classified_intent`, `candidate_agents`, `status` | `classified_intent` non-empty string; `candidate_agents` = list of dicts with `agent_id`, `match_score`, `matched_domain`; `status=SUCCESS` | PASS |
| BL-07 | Empty `validated_input` | `validated_input=""` | `classified_intent`, `candidate_agents`, `status`, `error_log` | `classified_intent=""`; `candidate_agents=[]`; `status=ERROR`; `error_log` contains `"IntentClassifyNode"` | PASS |
| BL-08 | LLM call fails (timeout) | `_call_llm` raises `ConnectionError` | `classified_intent`, `candidate_agents`, `status`, `error_log` | `classified_intent=""`; `candidate_agents=[]`; `status=RETRY`; `error_log` contains exception message | PASS |
| BL-09 | LLM returns no matches | `_call_llm` returns `candidate_agents=[]` | `classified_intent`, `candidate_agents`, `status` | `classified_intent` set; `candidate_agents=[]`; `status=SUCCESS` (no match is valid) | PASS |
| BL-10 | LLM returns multiple matches | `_call_llm` returns 2+ candidates | `classified_intent`, `candidate_agents`, `status` | `candidate_agents` list with 2+ entries; each has `agent_id`, `match_score`, `matched_domain`; `status=SUCCESS` | PASS |
| BL-11 | Empty registered_capabilities | `registered_capabilities=[]` | `classified_intent`, `candidate_agents`, `status` | LLM receives empty capabilities list; `candidate_agents=[]`; `status=SUCCESS` | PASS |

### Unit — RouteDecideNode

| TC-ID | Test | Input | Expected Output Fields | Expected Result | Result |
|-------|------|-------|----------------------|----------------|--------|
| BL-12 | No candidates → escalate immediately | `candidate_agents=[]` | `resolved_agent`, `overlap_flag`, `routing_decision`, `confidence_score`, `escalation_flag`, `status` | `resolved_agent={}`; `overlap_flag=False`; `routing_decision="escalate"`; `confidence_score=0.0`; `escalation_flag=True`; `status=SUCCESS` | PASS |
| BL-13 | Single candidate, high confidence | `candidate_agents=[{agent_id, match_score=0.9}]` | `resolved_agent`, `overlap_flag`, `routing_decision`, `confidence_score`, `escalation_flag`, `status` | `resolved_agent.agent_id` = candidate agent_id; `overlap_flag=False`; `routing_decision` = agent_id; `confidence_score≈0.9`; `escalation_flag=False`; `status=SUCCESS` | PASS |
| BL-14 | Single candidate, low confidence | `candidate_agents=[{agent_id, match_score=0.3}]` | `routing_decision`, `confidence_score`, `escalation_flag`, `status` | `routing_decision="escalate"`; `confidence_score≈0.3`; `escalation_flag=True`; `status=SUCCESS` | PASS |
| BL-15 | Multiple candidates — highest score wins | 2 candidates with `match_score=0.9` and `0.5` | `resolved_agent`, `overlap_flag`, `routing_decision`, `escalation_flag`, `status` | `resolved_agent.agent_id` = highest score agent; `overlap_flag=True`; `routing_decision` = highest score agent_id; `escalation_flag=False`; `status=SUCCESS` | PASS |
| BL-16 | Tie-break by registry priority | 2 candidates with equal `match_score`, priority 1 and 2 | `resolved_agent`, `routing_decision`, `overlap_flag`, `status` | `resolved_agent.agent_id` = agent with priority=1 (lower value = higher precedence); `overlap_flag=True`; `status=SUCCESS` | PASS |
| BL-17 | `emit_trace_event()` called on normal path | Any valid routing | — | Trace event `"route_decide"` emitted via `shared.utils.audit_logger` with `routing_decision`, `confidence_score`, `overlap_flag`, `escalation_flag` | TBD |
| BL-18 | `emit_trace_event()` called on escalation path | `candidate_agents=[]` | — | Trace event `"route_decide"` emitted via `shared.utils.audit_logger` with `routing_decision="escalate"`, `reason="no_candidates"` | TBD |

### Integration — end-to-end via MainNode

| TC-ID | Test | Input | Expected Output Fields | Expected Result | Result |
|-------|------|-------|----------------------|----------------|--------|
| INT-01 | Full success path | `validated_input="finance report"`, matching capability with `match_score=0.9` | All output fields | `registered_capabilities` non-empty; `classified_intent` set; `candidate_agents` non-empty; `resolved_agent.agent_id` set; `routing_decision=agent_id`; `confidence_score≈0.9`; `escalation_flag=False`; `overlap_flag=False`; `status=SUCCESS` | PASS |
| INT-02 | No match → escalation | Valid input, LLM returns `candidate_agents=[]` | `routing_decision`, `escalation_flag`, `status` | `routing_decision="escalate"`; `escalation_flag=True`; `confidence_score=0.0`; `status=SUCCESS` | PASS |
| INT-03 | Registry failure → early ERROR | `config/config.yaml` missing | `status`, `error_log` | `status=ERROR`; `error_log` contains `"CapabilityLookupNode"`; `routing_decision` key absent from result | PASS |
| INT-04 | LLM failure → RETRY | `_call_llm` raises `ConnectionError` | `status`, `error_log` | `status=RETRY`; `error_log` contains `"IntentClassifyNode"`; `routing_decision` key absent from result | PASS |
| INT-05 | Empty input → ERROR | `validated_input=""` | `status`, `error_log` | `status=ERROR`; `error_log` contains `"IntentClassifyNode"`; LLM not called | PASS |
| INT-06 | Low confidence → escalation via MainNode | LLM returns `match_score=0.2` | `routing_decision`, `confidence_score`, `escalation_flag`, `status` | `routing_decision="escalate"`; `confidence_score≈0.2`; `escalation_flag=True`; `status=SUCCESS` | PASS |
| INT-07 | Overlap resolved correctly via MainNode | LLM returns 2 candidates, different scores | `resolved_agent`, `overlap_flag`, `routing_decision`, `status` | `overlap_flag=True`; `routing_decision` = highest score agent_id; `status=SUCCESS` | PASS |

### Boundary / Negative

| TC-ID | Test | Input | Expected Output Fields | Expected Result | Result |
|-------|------|-------|----------------------|----------------|--------|
| BND-01 | Unknown intent → escalation | LLM returns `candidate_agents=[]` | `routing_decision`, `escalation_flag` | `routing_decision="escalate"`; `escalation_flag=True` | TBD |
| BND-02 | Capability overlap → tie-break by priority | 2 agents, equal `match_score`, priority 1 vs 2 | `routing_decision`, `resolved_agent` | `routing_decision` = agent with `priority=1`; `resolved_agent.agent_id` matches | TBD |
| BND-03 | Empty registry | `registered_capabilities=[]` | `routing_decision`, `escalation_flag` | LLM receives empty list; `candidate_agents=[]`; `routing_decision="escalate"`; `escalation_flag=True` | TBD |
| BND-04 | Malformed request (None input) | `user_input=None` (not set in state) | `status`, `error_log` | `status=ERROR` before LLM call; `error_log` populated | PASS |
| BND-05 | `confidence_score` exactly at threshold | `match_score=0.5` | `escalation_flag`, `routing_decision` | `escalation_flag=False` (threshold is `< 0.5`; exactly 0.5 does **not** escalate); `routing_decision=agent_id` | TBD |
| BND-06 | `confidence_score` just below threshold | `match_score=0.499` | `escalation_flag`, `routing_decision` | `escalation_flag=True`; `routing_decision="escalate"` | TBD |
| BND-07 | `resolved_agent.name` falls back to `agent_id` | Agent not in `registered_capabilities` | `resolved_agent` | `resolved_agent.name` = `agent_id` string (fallback) | TBD |
| BND-08 | `node_history` not mutated by MainNode | Any valid input | `node_history` | `node_history` value from input state unchanged in output | TBD |

---

## Test Execution Summary

- Execution date: TBD
- Total tests: 56 (8 TC + 6 PB + 18 BL + 7 INT + 8 BND + 9 contract/completeness/extended-PB)
- Pass: 35 / Fail: 0 / Skip: 0 / TBD: 21
- Note: impl #8 added 4 tests (output completeness ×2, node-contract ×2); impl #9 added 5 PB tests (import isolation ×2, state safety ×3)
- Coverage: TBD (target: 80%)



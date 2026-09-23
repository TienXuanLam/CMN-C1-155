"""LLM-backed request classification."""

from __future__ import annotations

import json
import os
from typing import Any

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.services.llm.base_llm import BaseLLM
from shared.utils.audit_logger import emit_trace_event

from src.services.azure_openai_service import AzureOpenAIService


class _MockLLM(BaseLLM):
    """STG_MOCK_MODE=true stand-in -- deterministic, no network call.

    STG-tier wiring tests only; must never be reachable in production (see
    STG_MOCK_MODE handling in _build_llm()). candidate_agents is empty
    because a hard-coded agent_id would fail _validate_result's
    registered-capability check against whatever registry the provisional
    smoke invoke's payload happens to declare.
    """

    def complete(self, _messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {"content": json.dumps({"classified_intent": "stg_mock_mode_stand_in", "candidate_agents": []})}

    def stream(self, _messages: list[Any]) -> Any:
        raise NotImplementedError("_MockLLM: stream() is not used by IntentClassifyNode")

    def bind_tools(self, _tools: list[Any]) -> "BaseLLM":
        raise NotImplementedError("_MockLLM: bind_tools() is not used by IntentClassifyNode")


_SYSTEM_PROMPT = """You classify requests against an agent capability registry.
Return JSON only with keys classified_intent and candidate_agents. Each candidate
must contain agent_id, match_score from 0 to 1, and matched_domain. Use only
agent_id values present in the supplied registry."""

_USER_PROMPT_TEMPLATE = """Request: {validated_input}

Available capabilities:
{capabilities_json}"""


class IntentClassifyNode(FunctionNode):
    """Classify a validated request against registered capabilities."""

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(
        self,
        llm_temperature: float = 0.2,
        llm_max_tokens: int = 4096,
        timeout_s: int = 120,
        max_retry: int = 2,
    ) -> None:
        super().__init__()
        self._llm_service = AzureOpenAIService(
            llm_temperature=llm_temperature,
            llm_max_tokens=llm_max_tokens,
            timeout_s=timeout_s,
            max_retry=max_retry,
        )

    def _build_llm(self, state: dict[str, Any]) -> BaseLLM:
        """Build a fresh, secret-bound LLM client for this invocation.

        Constructor-time injection (an `llm_client` param set once when the
        graph registers this node) depends on `config["llm"]` being
        populated before `agent_cls(config=...)` runs -- but neither
        `cli.py` (the real Marketplace entrypoint) nor
        `shared.bootstrap.marketplace_app.run_agent_marketplace()` ever sets
        it (verified against the installed 1.0.3 wheel: `config` is passed
        straight through, with the seam being the *caller's* responsibility
        to fill before calling it). A constructor-injected client would
        therefore always be `None` on the real Marketplace path. Worse, a
        cached `self._llm` set once at construction is shared across every
        invocation served by this node instance (registries reuse compiled
        graphs), which would leak one caller's authenticated client to every
        subsequent caller. Building per-invocation here instead avoids both
        problems, and reads secrets from `state` at call time rather than
        depending on `config` at all.

        `STG_MOCK_MODE=true` returns a deterministic `_MockLLM` instead of a
        real client -- STG-tier wiring tests only, must never be set in
        production. This is the scaffold's standard Stage 5
        provisional-deploy toggle, set "true" by the shared deploy-stg CI
        job.
        """
        if os.environ.get("STG_MOCK_MODE", "").lower() == "true":
            return _MockLLM()
        return self._llm_service.create_client(state)

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        emit_trace_event("intent_classification_started", {}, state)
        validated_input = state.get("validated_input", "")
        raw_capabilities = state.get("registered_capabilities", "[]")
        try:
            capabilities = json.loads(raw_capabilities) if isinstance(raw_capabilities, str) else raw_capabilities or []
        except (TypeError, json.JSONDecodeError):
            return {
                "classified_intent": "",
                "candidate_agents": "[]",
                "status": AgentStatus.ERROR,
                "error_log": ["IntentClassifyNode: registered_capabilities is invalid JSON"],
            }

        if not validated_input:
            return {
                "classified_intent": "",
                "candidate_agents": "[]",
                "status": AgentStatus.ERROR,
                "error_log": ["IntentClassifyNode: validated_input is empty"],
            }

        try:
            result = self._call_llm(validated_input, capabilities, state)
            self._validate_result(result, capabilities)
        except Exception as exc:
            return {
                "classified_intent": "",
                "candidate_agents": "[]",
                "status": AgentStatus.RETRY,
                "retry_count": state.get("retry_count", 0) + 1,
                "error_log": [f"IntentClassifyNode: LLM classification failed — {type(exc).__name__}"],
            }

        return {
            "classified_intent": result["classified_intent"],
            "candidate_agents": json.dumps(result["candidate_agents"]),
            "status": AgentStatus.SUCCESS,
        }

    def _call_llm(
        self,
        validated_input: str,
        capabilities: list[dict[str, Any]],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        llm = self._build_llm(state)
        response = llm.complete(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _USER_PROMPT_TEMPLATE.format(
                        validated_input=validated_input,
                        capabilities_json=json.dumps(capabilities, ensure_ascii=False),
                    ),
                },
            ]
        )
        content = response.get("content", "") if isinstance(response, dict) else str(response)
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("LLM response must be a JSON object")
        return parsed

    @staticmethod
    def _validate_result(result: dict[str, Any], capabilities: list[dict[str, Any]]) -> None:
        if not isinstance(result.get("classified_intent"), str):
            raise ValueError("classified_intent must be a string")
        candidates = result.get("candidate_agents")
        if not isinstance(candidates, list):
            raise ValueError("candidate_agents must be a list")
        allowed_ids = {cap.get("agent_id") for cap in capabilities}
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError("candidate must be an object")
            if candidate.get("agent_id") not in allowed_ids:
                raise ValueError("candidate agent_id is not registered")
            score = candidate.get("match_score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
                raise ValueError("candidate match_score must be between 0 and 1")
            if not isinstance(candidate.get("matched_domain"), str):
                raise ValueError("candidate matched_domain must be a string")

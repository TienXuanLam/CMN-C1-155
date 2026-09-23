"""Tests for the non-stub LLM classification contract."""

import json

import pytest

from src.nodes.intent_classify_node import IntentClassifyNode


class _LLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.messages = None

    def complete(self, messages: list) -> dict:
        self.messages = messages
        return {"content": self.content}


def test_injected_llm_response_is_parsed():
    llm = _LLM(
        json.dumps(
            {
                "classified_intent": "finance",
                "candidate_agents": [
                    {
                        "agent_id": "agent-fin-report-001",
                        "match_score": 0.9,
                        "matched_domain": "finance",
                    }
                ],
            }
        )
    )
    node = IntentClassifyNode()
    node._build_llm = lambda state: llm
    result = node._call_llm(
        "route finance request",
        [{"agent_id": "agent-fin-report-001"}],
        {},
    )

    assert result["classified_intent"] == "finance"
    assert llm.messages[0]["role"] == "system"
    assert "agent-fin-report-001" in llm.messages[1]["content"]


def test_malformed_llm_json_is_rejected():
    node = IntentClassifyNode()
    node._build_llm = lambda state: _LLM("not-json")

    with pytest.raises(json.JSONDecodeError):
        node._call_llm("route request", [], {})


def test_unregistered_candidate_is_rejected():
    with pytest.raises(ValueError, match="not registered"):
        IntentClassifyNode._validate_result(
            {
                "classified_intent": "finance",
                "candidate_agents": [
                    {
                        "agent_id": "UNKNOWN",
                        "match_score": 0.9,
                        "matched_domain": "finance",
                    }
                ],
            },
            [{"agent_id": "agent-fin-report-001"}],
        )

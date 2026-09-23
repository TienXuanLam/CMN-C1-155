"""PB: standalone server authentication and LLM injection."""

import importlib


def test_server_boots_without_azure_openai_secrets(monkeypatch):
    # IntentClassifyNode builds its own secret-bound AzureOpenAIClient per
    # invocation via _build_llm(state) (see its docstring) -- server.py never
    # constructs or caches an LLM client at module scope, so booting without
    # any Azure secrets present must not raise.
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)

    import src.api.server as server

    importlib.reload(server)
    assert server.app is not None
    assert server.agent is not None


def test_intent_classify_node_builds_client_per_invocation():
    # No constructor injection seam exists anymore -- confirm the node
    # exposes _build_llm(state) instead of a cached _llm attribute.
    import src.api.server as server

    node = server.agent._nodes["main"]._intent_classify
    assert not hasattr(node, "_llm")
    assert hasattr(node, "_build_llm")


def test_external_token_never_promotes_to_internal():
    import src.api.server as server
    from framework.schemas.trust_level import TrustLevel

    assert (
        server._resolve_standalone_trust(
            TrustLevel.ANONYMOUS,
            "Bearer external",
            "external",
            "runner",
        )
        is TrustLevel.VERIFIED_EXTERNAL
    )


def test_runner_token_promotes_to_internal():
    import src.api.server as server
    from framework.schemas.trust_level import TrustLevel

    assert (
        server._resolve_standalone_trust(
            TrustLevel.ANONYMOUS,
            "Bearer runner",
            "external",
            "runner",
        )
        is TrustLevel.INTERNAL
    )


def test_invalid_token_is_rejected():
    import pytest
    import src.api.server as server
    from fastapi import HTTPException
    from framework.schemas.trust_level import TrustLevel

    with pytest.raises(HTTPException) as exc:
        server._resolve_standalone_trust(
            TrustLevel.ANONYMOUS,
            "Bearer wrong",
            "external",
            "runner",
        )
    assert exc.value.status_code == 401

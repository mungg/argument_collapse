"""Provider registry — look up an :class:`~argument_collapse.inference.types.Provider`
implementation by its short string key.

The keys here are the same strings accepted by ``--provider`` on the
annotation pipelines (see for example
``annotate.pair_comparison_main_arg``). Each provider
is imported lazily so that installing only one client (for example
``openai``) does not require installing all the others.
"""
from __future__ import annotations

from typing import Callable

from argument_collapse.inference.types import Provider, ProviderSpec


def _import_openai() -> type:
    from argument_collapse.inference.providers.openai import OpenAIResponsesProvider
    return OpenAIResponsesProvider


def _import_vertex() -> type:
    from argument_collapse.inference.providers.vertex import VertexGenAIProvider
    return VertexGenAIProvider


def _import_vertex_claude() -> type:
    from argument_collapse.inference.providers.vertex_claude import VertexClaudeProvider
    return VertexClaudeProvider


def _import_openrouter() -> type:
    from argument_collapse.inference.providers.openrouter import OpenRouterChatProvider
    return OpenRouterChatProvider


# Map provider key -> a thunk returning the class. Using thunks keeps
# optional SDK imports lazy so a user only needs the SDKs for the providers
# they call.
_PROVIDER_FACTORIES: dict[str, Callable[[], type]] = {
    "openai":        _import_openai,
    "vertex":        _import_vertex,
    "vertex-claude": _import_vertex_claude,
    "openrouter":    _import_openrouter,
}


def provider_choices() -> list[str]:
    """Sorted list of registered provider keys (for argparse ``choices=``)."""
    return sorted(_PROVIDER_FACTORIES)


def get_provider(key: str) -> Provider:
    """Instantiate the provider registered under ``key``.

    Raises ``KeyError`` if ``key`` is not registered.
    """
    try:
        cls = _PROVIDER_FACTORIES[key]()
    except KeyError as exc:
        raise KeyError(
            f"unknown provider {key!r}; choose one of {provider_choices()}"
        ) from exc
    return cls()


def provider_spec(key: str) -> ProviderSpec:
    """Return the :class:`ProviderSpec` for ``key`` without instantiating
    the provider (no SDK import)."""
    try:
        cls = _PROVIDER_FACTORIES[key]()
    except KeyError as exc:
        raise KeyError(
            f"unknown provider {key!r}; choose one of {provider_choices()}"
        ) from exc
    return cls.spec

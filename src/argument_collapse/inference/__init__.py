"""Provider-side LLM clients.

Each provider's client is exposed through :func:`get_provider`. The wrappers
share a common :class:`~argument_collapse.inference.types.InferenceRequest`
input and either return a parsed JSON response or raise
:class:`~argument_collapse.inference.types.InferenceError`.
"""
from __future__ import annotations

from argument_collapse.inference.registry import (
    get_provider,
    provider_choices,
    provider_spec,
)
from argument_collapse.inference.types import (
    InferenceError,
    InferenceRequest,
    InferenceResult,
    Provider,
    ProviderSpec,
    jsonable,
)

__all__ = [
    "InferenceError",
    "InferenceRequest",
    "InferenceResult",
    "Provider",
    "ProviderSpec",
    "get_provider",
    "jsonable",
    "provider_choices",
    "provider_spec",
]

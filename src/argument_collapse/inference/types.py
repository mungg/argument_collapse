from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol


JsonDict = dict[str, Any]


@dataclass(frozen=True)
class ProviderSpec:
    """Stable metadata used for filenames, frontmatter, and sidecars."""

    key: str
    provider: str
    agent: str
    default_model: str
    default_effort: str = ""
    api_style: str = "direct"
    filename_agent: str | None = None

    @property
    def filename_prefix_agent(self) -> str:
        return self.filename_agent or self.agent


@dataclass(frozen=True)
class InferenceRequest:
    provider: str
    model: str
    system_prompt: str
    user_prompt: str
    combined_prompt: str
    condition: str
    stance: str = ""
    effort: str = ""
    scratch_dir: Path | None = None
    output_path: Path | None = None
    lead_path: Path | None = None
    request_params: Mapping[str, Any] = field(default_factory=dict)
    # Optional Vertex explicit-cache reference (a CachedContent resource name).
    # When set, the vertex provider sends `cached_content=<name>` and omits the
    # system_instruction (it lives in the cache); other providers ignore it.
    cached_content: str | None = None


@dataclass
class InferenceResult:
    text: str
    metadata: JsonDict = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""


class Provider(Protocol):
    spec: ProviderSpec

    def generate(self, request: InferenceRequest) -> InferenceResult:
        ...


class InferenceError(RuntimeError):
    """Raised when a provider call fails or returns no essay text."""


def jsonable(value: Any) -> Any:
    """Best-effort conversion of SDK response objects into sidecar-safe JSON."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump())
    if hasattr(value, "to_dict"):
        return jsonable(value.to_dict())
    return str(value)

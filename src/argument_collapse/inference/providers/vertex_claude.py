from __future__ import annotations

import os
from typing import Any

from argument_collapse.inference.types import InferenceError, InferenceRequest, InferenceResult, ProviderSpec, jsonable

VERTEX_USER_TAG_ENV = "VERTEX_USER_TAG"
CLAUDE_EFFORT_VALUES = {"low", "medium", "high"}


def _labels_from_env() -> dict[str, str]:
    user_tag = os.environ.get(VERTEX_USER_TAG_ENV, "").strip()
    if not user_tag:
        raise InferenceError(f"{VERTEX_USER_TAG_ENV} must be set before sending Vertex Claude requests.")
    return {"user": user_tag}


def _thinking_config(effort: str) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    normalized = effort.strip().lower()
    if normalized in {"", "none", "off", "disabled"}:
        return None, None
    if normalized in {"minimal"}:
        normalized = "low"
    if normalized in {"xhigh", "max"}:
        normalized = "high"
    if normalized not in CLAUDE_EFFORT_VALUES:
        raise InferenceError(
            f"Unsupported Claude-on-Vertex effort {effort!r}; use one of: low, medium, high."
        )
    return {"type": "adaptive"}, {"effort": normalized}


def _response_text(response: Any) -> str:
    parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if isinstance(block, dict):
            if block.get("type") == "text" and block.get("text"):
                parts.append(str(block["text"]))
            continue
        if getattr(block, "type", "") == "text" and getattr(block, "text", None):
            parts.append(str(block.text))
    return "\n".join(parts).strip()


class VertexClaudeProvider:
    spec = ProviderSpec(
        key="vertex-claude",
        provider="vertex-claude",
        agent="vertex-claude-api",
        default_model="claude-opus-4-7",
        default_effort="high",
        filename_agent="vertex-claude-api",
    )

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def _client_instance(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from anthropic import AnthropicVertex
        except ImportError as exc:
            raise InferenceError(
                "Install the `anthropic[vertex]` package to use --provider vertex-claude."
            ) from exc

        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        region = os.environ.get("GOOGLE_CLOUD_LOCATION", "global").strip() or "global"
        if not project:
            raise InferenceError("GOOGLE_CLOUD_PROJECT must be set before sending Vertex Claude requests.")
        return AnthropicVertex(project_id=project, region=region)

    def generate(self, request: InferenceRequest) -> InferenceResult:
        user_label = _labels_from_env()["user"]
        thinking, output_config = _thinking_config(request.effort)
        max_tokens = int(request.request_params.get("max_tokens", 4096))
        if "temperature" in request.request_params:
            raise InferenceError("Claude Opus 4.7 does not accept temperature; omit --temperature.")

        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": max_tokens,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": request.user_prompt}],
            "metadata": {"user_id": user_label},
        }
        if thinking is not None:
            payload["thinking"] = thinking
        if output_config is not None:
            payload["output_config"] = output_config

        response = self._client_instance().messages.create(**payload)
        text = _response_text(response)
        if not text:
            raise InferenceError("Vertex Claude returned no text output.")

        return InferenceResult(
            text=text,
            metadata={
                "response_id": getattr(response, "id", ""),
                "usage": jsonable(getattr(response, "usage", None)),
                "request": jsonable(payload),
            },
        )

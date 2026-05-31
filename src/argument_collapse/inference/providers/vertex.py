from __future__ import annotations

import os
from typing import Any

from argument_collapse.inference.types import InferenceError, InferenceRequest, InferenceResult, ProviderSpec, jsonable

VERTEX_USER_TAG_ENV = "VERTEX_USER_TAG"

_GEMINI3_EFFORT_TO_THINKING_LEVEL = {
    "minimal": "MINIMAL",
    "low": "LOW",
    "medium": "MEDIUM",
    "high": "HIGH",
}


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text).strip()
    parts: list[str] = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            chunk = getattr(part, "text", None)
            if chunk:
                parts.append(str(chunk))
    return "\n".join(parts).strip()


def _is_gemini3_model(model: str) -> bool:
    normalized = model.lower()
    return normalized.startswith("gemini-3") or "gemini-3." in normalized


def _supports_minimal_thinking(model: str) -> bool:
    normalized = model.lower()
    return "flash" in normalized and "pro" not in normalized


def _thinking_level(model: str, effort: str) -> str:
    if not effort:
        return ""
    normalized = effort.strip().lower()
    if normalized in {"xhigh", "max"}:
        normalized = "high"
    if normalized in {"none", "off", "disabled"}:
        raise InferenceError("Gemini 3 models do not support disabling thinking; use minimal, low, medium, or high when supported.")
    if normalized == "minimal" and not _supports_minimal_thinking(model):
        raise InferenceError(f"Vertex model {model} does not support minimal thinking; use low, medium, or high.")
    try:
        return _GEMINI3_EFFORT_TO_THINKING_LEVEL[normalized]
    except KeyError as exc:
        raise InferenceError(
            f"Unsupported Vertex effort {effort!r}; use one of: minimal, low, medium, high."
        ) from exc


def _enum_value(enum_cls: Any, name: str) -> Any:
    return getattr(enum_cls, name, name)


def _safety_settings(types: Any) -> list[Any]:
    categories = [
        "HARM_CATEGORY_DANGEROUS_CONTENT",
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_HATE_SPEECH",
    ]
    threshold = _enum_value(types.HarmBlockThreshold, "BLOCK_NONE")
    return [
        types.SafetySetting(
            category=_enum_value(types.HarmCategory, category),
            threshold=threshold,
        )
        for category in categories
    ]


def _labels_from_env() -> dict[str, str]:
    user_tag = os.environ.get(VERTEX_USER_TAG_ENV, "").strip()
    if not user_tag:
        raise InferenceError(f"{VERTEX_USER_TAG_ENV} must be set before sending Vertex requests.")
    return {"user": user_tag}


class VertexGenAIProvider:
    spec = ProviderSpec(
        key="vertex",
        provider="vertex",
        agent="vertex-api",
        default_model="gemini-3.1-pro-preview",
        default_effort="high",
        filename_agent="vertex-api",
    )

    def __init__(self, client: Any | None = None, types_module: Any | None = None) -> None:
        self._client = client
        self._types = types_module

    def _client_and_types(self) -> tuple[Any, Any]:
        if self._client is not None and self._types is not None:
            return self._client, self._types
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise InferenceError("Install the `google-genai` package to use --provider vertex.") from exc

        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
        # Per-request HTTP timeout in milliseconds. Default 2 min covers
        # normal short calls (judge, toulmin: 1-3s) and most essay
        # generation (typically <60s, sometimes 90s at high effort) while
        # surfacing the `minimal` empty-output hang reasonably fast.
        # Override per-script via VERTEX_REQUEST_TIMEOUT_MS if needed.
        timeout_ms = int(os.environ.get("VERTEX_REQUEST_TIMEOUT_MS", "120000"))
        http_options = types.HttpOptions(timeout=timeout_ms)
        client_kwargs: dict[str, Any] = {"vertexai": True, "http_options": http_options}
        if project:
            client_kwargs["project"] = project
            client_kwargs["location"] = location
        client = genai.Client(**client_kwargs)
        return client, types

    def create_cache(self, *, model: str, system_instruction: str,
                     cached_text: str, ttl_seconds: int = 1800) -> str:
        """Create a Vertex explicit context cache holding the system
        instruction + a fixed text block (e.g. the cohort's lead essay).
        Returns the CachedContent resource name to pass as
        `InferenceRequest.cached_content`. Raises InferenceError on failure
        (e.g. content below the model's minimum-token threshold) so callers
        can fall back to an inline request."""
        client, types = self._client_and_types()
        try:
            cache = client.caches.create(
                model=model,
                config=types.CreateCachedContentConfig(
                    system_instruction=system_instruction,
                    contents=[types.Content(role="user",
                                            parts=[types.Part(text=cached_text)])],
                    ttl=f"{int(ttl_seconds)}s",
                ),
            )
        except Exception as exc:
            raise InferenceError(f"Vertex cache create failed: {exc}") from exc
        return cache.name

    def delete_cache(self, name: str) -> None:
        """Best-effort delete of a context cache. Never raises."""
        try:
            client, _ = self._client_and_types()
            client.caches.delete(name=name)
        except Exception:
            pass

    def generate(self, request: InferenceRequest) -> InferenceResult:
        client, types = self._client_and_types()
        config_params = {
            "safety_settings": _safety_settings(types),
            "labels": _labels_from_env(),
        }
        if request.cached_content:
            # System instruction + cached context live in the cache; the API
            # rejects setting system_instruction alongside cached_content.
            config_params["cached_content"] = request.cached_content
        else:
            config_params["system_instruction"] = request.system_prompt
        config_params.update(dict(request.request_params))
        if request.effort and _is_gemini3_model(request.model):
            config_params["thinking_config"] = types.ThinkingConfig(
                thinking_level=getattr(types.ThinkingLevel, _thinking_level(request.model, request.effort))
            )
        config = types.GenerateContentConfig(**config_params)
        try:
            response = client.models.generate_content(
                model=request.model,
                contents=request.user_prompt,
                config=config,
            )
        except Exception as exc:
            # Translate transport-level errors (httpx timeouts, gRPC
            # DeadlineExceeded, network issues) into InferenceError so the
            # runner's per-task error handling logs them and frees the
            # worker. Without this, a hung connection would block the
            # worker thread indefinitely.
            msg = str(exc).lower()
            if "timeout" in msg or "deadline" in msg or "timed out" in msg:
                raise InferenceError(f"Vertex request timed out: {exc}") from exc
            raise InferenceError(f"Vertex request failed: {exc}") from exc
        text = _response_text(response)
        if not text:
            raise InferenceError("Vertex returned no text output.")

        return InferenceResult(
            text=text,
            metadata={
                "response_id": getattr(response, "response_id", ""),
                "usage": jsonable(getattr(response, "usage_metadata", None)),
                "request": {
                    "model": request.model,
                    "contents": request.user_prompt,
                    "config": jsonable(config_params),
                },
            },
        )

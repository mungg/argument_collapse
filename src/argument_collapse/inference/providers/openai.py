from __future__ import annotations

import os
from typing import Any

from argument_collapse.inference.types import InferenceError, InferenceRequest, InferenceResult, ProviderSpec, jsonable


def _collect_response_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return str(text).strip()

    parts: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            chunk = getattr(content, "text", None)
            if chunk:
                parts.append(str(chunk))
    return "\n".join(parts).strip()


class OpenAIResponsesProvider:
    spec = ProviderSpec(
        key="openai",
        provider="openai",
        agent="openai-api",
        default_model="gpt-5.4",
        filename_agent="openai-api",
    )

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def _client_or_default(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise InferenceError("Install the `openai` package to use --provider openai.") from exc
        # Per-request client timeout in seconds. Default 600s (10 min)
        # covers the slowest legitimate diversified batched calls observed
        # (claude ran ~7.5 min on an 11-essay BR cohort) while catching
        # hung connections quickly. max_retries=0 is critical: the OpenAI SDK
        # default is 2 silent retries on timeout, so a 600s timeout
        # otherwise becomes ~30 min of waiting. Surface timeouts as
        # InferenceError so the worker pool can fail the task and continue.
        timeout_s = float(os.environ.get("OPENAI_REQUEST_TIMEOUT_S", "600"))
        return OpenAI(timeout=timeout_s, max_retries=0)

    def generate(self, request: InferenceRequest) -> InferenceResult:
        client = self._client_or_default()
        payload: dict[str, Any] = {
            "model": request.model,
            "instructions": request.system_prompt,
            "input": request.user_prompt,
        }
        if request.effort:
            payload["reasoning"] = {"effort": request.effort}
        payload.update(dict(request.request_params))

        try:
            response = client.responses.create(**payload)
        except Exception as exc:  # openai.APITimeoutError, APIConnectionError, etc.
            msg = str(exc).lower()
            if "timeout" in msg or "timed out" in msg or exc.__class__.__name__ == "APITimeoutError":
                raise InferenceError(f"OpenAI request timed out: {exc}") from exc
            raise
        text = _collect_response_text(response)
        if not text:
            raise InferenceError("OpenAI returned no text output.")

        return InferenceResult(
            text=text,
            metadata={
                "response_id": getattr(response, "id", ""),
                "usage": jsonable(getattr(response, "usage", None)),
                "request": jsonable(payload),
            },
        )

"""OpenRouter Chat Completions provider.

Uses the OpenAI Python SDK pointed at OpenRouter's `/api/v1` base URL.
OpenRouter exposes hundreds of model slugs (e.g. `anthropic/claude-opus-4.7`,
`deepseek/deepseek-v4-pro`, `moonshotai/kimi-k2.6`) behind one OpenAI-compatible
chat-completions endpoint.

Environment variables:
  OPENROUTER_API_KEY        — required.
  OPENROUTER_HTTP_REFERER   — optional URL for app-attribution.
  OPENROUTER_TITLE          — optional app name (default: argument-collapse).

How `--effort` is mapped: any non-empty effort value is forwarded as
`reasoning.effort` in the request body. OpenRouter's documented values
are "low" | "medium" | "high"; the project's "minimal" is sent through
unchanged (some target models accept it, others may not).

For Anthropic-style explicit budgeting (e.g. Claude with a fixed thinking-
token budget) or DeepSeek's `reasoning.enabled` toggle, callers can pass
an explicit `reasoning` dict in `InferenceRequest.request_params`, which
overrides the effort-derived value.

For provider-routing (e.g. force Anthropic-native serving for Claude),
pass a `provider` dict in `InferenceRequest.request_params`. It travels
via `extra_body` to OpenRouter without going through the OpenAI SDK's
schema validation.

OpenRouter docs:
  - https://openrouter.ai/docs/app-attribution
  - https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
  - https://openrouter.ai/docs/use-cases/usage-accounting
  - https://openrouter.ai/docs/guides/routing/provider-selection
"""
from __future__ import annotations

import os
from typing import Any

from argument_collapse.inference.types import InferenceError, InferenceRequest, InferenceResult, ProviderSpec, jsonable


def _message_text(completion: Any) -> str:
    """Extract assistant text from a chat-completions response."""
    choices = getattr(completion, "choices", []) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", "") if message is not None else ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(getattr(item, "text", "")))
        return "\n".join(part for part in parts if part).strip()
    return str(content or "").strip()


def _reasoning_from_message(completion: Any) -> dict[str, Any]:
    """Extract reasoning trace + structured reasoning_details from a
    chat-completions response. Returns {} if neither is present."""
    choices = getattr(completion, "choices", []) or []
    if not choices:
        return {}
    message = getattr(choices[0], "message", None)
    if message is None:
        return {}
    out: dict[str, Any] = {}
    reasoning = getattr(message, "reasoning", None)
    if reasoning:
        out["reasoning"] = str(reasoning)
    details = getattr(message, "reasoning_details", None)
    if details:
        out["reasoning_details"] = jsonable(details)
    return out


def _is_anthropic_claude(model: str | None) -> bool:
    return bool(model) and model.startswith("anthropic/claude-")


def _build_reasoning(model: str | None, effort: str | None,
                      explicit: dict[str, Any] | None) -> dict[str, Any] | None:
    """Resolve OpenRouter's `reasoning` block.

    Precedence:
      1. Explicit `reasoning` dict in request_params (caller knows best).
      2. For Anthropic Claude 4.6+/4.7 models, `reasoning.effort` and
         `reasoning.max_tokens` are documented as IGNORED (adaptive thinking
         is mandatory). Translate any non-empty effort to
         `reasoning.enabled: true` so thinking is at least turned on.
      3. For other reasoning models (OpenAI o-series, Gemini 3, DeepSeek,
         Kimi), pass effort through as `reasoning.effort`.
      4. Otherwise omit the reasoning block entirely.
    """
    if isinstance(explicit, dict) and explicit:
        return explicit
    if _is_anthropic_claude(model):
        return {"enabled": True} if effort else None
    if effort:
        return {"effort": effort}
    return None


def _resolve_verbosity(model: str | None,
                        explicit: str | None) -> str | None:
    """Resolve OpenRouter's `verbosity` parameter.

    For Anthropic Claude 4.7, `temperature`, `reasoning.effort`, and
    `reasoning.max_tokens` are all ignored — `verbosity` (which maps to
    Anthropic's `output_config.effort`) is the only remaining lever for
    response effort. Default to "high" for Claude unless the caller
    overrides; pass through whatever the caller sets for non-Claude models.

    Why "high" not "medium": empirical testing on essay prompts showed
    low/medium/high produce nearly identical output (~360 words, 0
    reasoning tokens), while "max" triggers extended thinking at ~4x cost.
    "high" sits at the upper edge of the "no-cost-jump" plateau, giving
    Claude the most response effort we can ask for without paying the
    "max" cost premium.
    """
    if explicit is not None:
        return explicit
    if _is_anthropic_claude(model):
        return "high"
    return None


class OpenRouterChatProvider:
    spec = ProviderSpec(
        key="openrouter",
        provider="openrouter",
        agent="openrouter-api",
        default_model="anthropic/claude-opus-4.7",
        filename_agent="openrouter-api",
    )

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def _client_or_default(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise InferenceError(
                "Install the `openai` package to use --provider openrouter."
            ) from exc
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise InferenceError(
                "OPENROUTER_API_KEY is required for --provider openrouter."
            )
        # Per-request client timeout in seconds. Default 600s (10 min)
        # covers the slowest legitimate diversified batches observed
        # (claude on 11-essay BR cohorts ran ~7.5 min) while catching hung
        # connections quickly. max_retries=0 is critical: the OpenAI SDK
        # default is 2 silent retries on timeout, so a 600s timeout
        # otherwise becomes ~30 min of waiting per call. Surface timeouts
        # as InferenceError so the worker pool marks the task failed and
        # continues.
        timeout_s = float(os.environ.get("OPENROUTER_REQUEST_TIMEOUT_S", "600"))
        return OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            timeout=timeout_s,
            max_retries=0,
        )

    def generate(self, request: InferenceRequest) -> InferenceResult:
        client = self._client_or_default()

        # Standard chat-completions body
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
        }

        # Sort request_params into:
        #   - extra_body fields (OpenRouter-specific, not in OpenAI SDK schema)
        #   - top-level kwargs (max_tokens, temperature, top_p, etc.)
        params = dict(request.request_params)
        explicit_reasoning = params.pop("reasoning", None)
        explicit_verbosity = params.pop("verbosity", None)
        provider_routing = params.pop("provider", None)
        payload.update(params)

        extra_body: dict[str, Any] = {}
        reasoning = _build_reasoning(request.model, request.effort, explicit_reasoning)
        if reasoning is not None:
            extra_body["reasoning"] = reasoning
        verbosity = _resolve_verbosity(request.model, explicit_verbosity)
        if verbosity is not None:
            extra_body["verbosity"] = verbosity
        if isinstance(provider_routing, dict) and provider_routing:
            extra_body["provider"] = provider_routing
        # Always include cost/usage accounting in the response. OpenRouter
        # returns usage on non-streaming calls by default, but the explicit
        # flag is harmless and future-proof.
        extra_body["usage"] = {"include": True}

        # App-attribution headers. `X-Title` is the canonical name;
        # `X-OpenRouter-Title` is an accepted alias.
        extra_headers = {
            key: value
            for key, value in {
                "HTTP-Referer": os.environ.get("OPENROUTER_HTTP_REFERER"),
                "X-Title": os.environ.get("OPENROUTER_TITLE", "argument-collapse"),
            }.items()
            if value
        }

        kwargs: dict[str, Any] = {**payload, "extra_body": extra_body}
        if extra_headers:
            kwargs["extra_headers"] = extra_headers

        try:
            completion = client.chat.completions.create(**kwargs)
        except Exception as exc:  # openai.APITimeoutError, APIConnectionError, etc.
            msg = str(exc).lower()
            if "timeout" in msg or "timed out" in msg or exc.__class__.__name__ == "APITimeoutError":
                raise InferenceError(f"OpenRouter request timed out: {exc}") from exc
            raise
        text = _message_text(completion)
        if not text:
            raise InferenceError("OpenRouter returned no text output.")

        return InferenceResult(
            text=text,
            metadata={
                "response_id": getattr(completion, "id", ""),
                # OpenRouter echoes the resolved model slug (may differ from
                # requested if a route fell back); record both.
                "served_model": getattr(completion, "model", request.model),
                "provider_name": getattr(completion, "provider", None),
                "usage": jsonable(getattr(completion, "usage", None)),
                # Reasoning trace + structured details (empty for non-
                # reasoning models or when {"reasoning": {"exclude": true}}).
                **_reasoning_from_message(completion),
                "request": jsonable(payload),
                "extra_body": jsonable(extra_body),
                "extra_headers": extra_headers,
            },
        )

import json
import logging
from typing import Any

import httpx

from apps.llm.base import BaseLLMClient
from apps.llm.json_utils import extract_json_object

logger = logging.getLogger(__name__)

try:
    import openai
except ImportError:
    openai = None


class OpenAICompatibleLLMClient(BaseLLMClient):
    """OpenAI or any OpenAI-compatible HTTP API (DeepSeek, local gateways)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        name: str = "openai_compatible",
    ):
        if not openai:
            raise ImportError("openai package is required")
        self.name = name
        http_client = httpx.Client(timeout=120)
        kwargs = {"api_key": api_key, "http_client": http_client}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai.OpenAI(**kwargs)

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float = 0.3,
        timeout_seconds: float = 120,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        response = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=temperature,
            timeout=timeout_seconds,
        )
        text = response.choices[0].message.content or "{}"
        usage: dict[str, Any] = {}
        if response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", None),
                "completion_tokens": getattr(response.usage, "completion_tokens", None),
            }
        try:
            return json.loads(text), usage
        except json.JSONDecodeError:
            extracted = extract_json_object(text)
            return json.loads(extracted), usage

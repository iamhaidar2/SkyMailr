import logging
import os

from django.conf import settings

from apps.llm.base import BaseLLMClient
from apps.llm.dummy_client import DummyLLMClient
from apps.llm.openai_client import OpenAICompatibleLLMClient

logger = logging.getLogger(__name__)

try:
    import anthropic
except ImportError:
    anthropic = None


class AnthropicJsonClient(BaseLLMClient):
    """Claude — parse JSON from message text (no native json_schema in all models)."""

    name = "anthropic"

    def __init__(self, api_key: str):
        if not anthropic:
            raise ImportError("anthropic package required for AnthropicJsonClient")
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float = 0.3,
        timeout_seconds: float = 120,
    ) -> tuple[dict, dict]:
        import json

        from apps.llm.json_utils import extract_json_object

        msg = self._client.messages.create(
            model=model,
            max_tokens=8192,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            timeout=timeout_seconds,
        )
        text = msg.content[0].text
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = json.loads(extract_json_object(text))
        usage = {}
        if getattr(msg, "usage", None):
            usage = {
                "prompt_tokens": msg.usage.input_tokens,
                "completion_tokens": msg.usage.output_tokens,
            }
        return parsed, usage


def get_llm_client() -> BaseLLMClient:
    """
    Factory aligned with BrainList `LLM_PROVIDER`:
    dummy | openai | deepseek | anthropic
    """
    provider = getattr(settings, "LLM_PROVIDER", os.getenv("LLM_PROVIDER", "dummy")).lower()

    if provider == "dummy":
        return DummyLLMClient()

    if provider == "openai":
        key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY")
        if not key:
            logger.warning("OPENAI_API_KEY missing; falling back to dummy LLM")
            return DummyLLMClient()
        base = (settings.OPENAI_BASE_URL or os.getenv("OPENAI_BASE_URL") or "").strip() or None
        return OpenAICompatibleLLMClient(api_key=key, base_url=base, name="openai")

    if provider == "deepseek":
        key = settings.DEEPSEEK_API_KEY or os.getenv("DEEPSEEK_API_KEY")
        if not key:
            logger.warning("DEEPSEEK_API_KEY missing; falling back to dummy LLM")
            return DummyLLMClient()
        base = settings.DEEPSEEK_BASE_URL or os.getenv(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        )
        return OpenAICompatibleLLMClient(api_key=key, base_url=base, name="deepseek")

    if provider == "anthropic":
        key = settings.ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            logger.warning("ANTHROPIC_API_KEY missing; falling back to dummy LLM")
            return DummyLLMClient()
        return AnthropicJsonClient(api_key=key)

    return DummyLLMClient()

from abc import ABC, abstractmethod
from typing import Any


class BaseLLMClient(ABC):
    """LLM abstraction — BrainList-compatible providers via env + router."""

    name: str = "base"

    @abstractmethod
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float = 0.3,
        timeout_seconds: float = 120,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Return (parsed_json_dict, usage_metadata).
        usage_metadata may include prompt_tokens, completion_tokens.
        """

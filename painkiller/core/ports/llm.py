"""LLM Port contract."""

from abc import ABC, abstractmethod
from typing import TypeVar, Type
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMPort(ABC):
    """Abstract port for querying Large Language Models."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str = "gpt-4o",
        temperature: float = 0.2,
    ) -> str:
        """Generate a text completion from the LLM."""
        pass

    @abstractmethod
    async def structured_output(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: str = "",
        model: str = "gpt-4o",
    ) -> T:
        """Generate a structured Pydantic response from the LLM."""
        pass

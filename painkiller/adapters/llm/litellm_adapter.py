"""LiteLLM adapter implementing LLMPort with custom endpoints support (like NVIDIA Build / NIM)."""

import json
import os
from typing import Optional, Type, TypeVar
import litellm
from pydantic import BaseModel

from painkiller.core.ports.llm import LLMPort

T = TypeVar("T", bound=BaseModel)


class LiteLLMAdapter(LLMPort):
    """Multi-provider LLM adapter powered by LiteLLM with support for custom endpoints."""

    def __init__(
        self,
        default_model: Optional[str] = None,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        # Prioritize environment configuration
        self.default_model = (
            os.environ.get("PAINKILLER_LLM_MODEL")
            or default_model
            or "gpt-4o"
        )
        self.api_base = (
            os.environ.get("PAINKILLER_LLM_API_BASE")
            or os.environ.get("OPENAI_API_BASE")
            or os.environ.get("NVIDIA_API_BASE")
            or api_base
        )
        self.api_key = (
            os.environ.get("PAINKILLER_LLM_API_KEY")
            or os.environ.get("NVIDIA_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or api_key
        )

    async def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str = "",
        temperature: float = 0.2,
    ) -> str:
        chosen_model = model or self.default_model
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict = {
            "model": chosen_model,
            "messages": messages,
            "temperature": temperature,
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key

        response = await litellm.acompletion(**kwargs)
        return response.choices[0].message.content or ""

    async def structured_output(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: str = "",
        model: str = "",
    ) -> T:
        chosen_model = model or self.default_model
        sys_msg = (
            system_prompt + "\nVocê deve retornar EXCLUSIVAMENTE um objeto JSON válido correspondente ao schema solicitado."
        )
        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        full_prompt = f"{prompt}\n\nSchema esperado:\n{schema_json}"

        response_text = await self.complete(
            prompt=full_prompt,
            system_prompt=sys_msg,
            model=chosen_model,
            temperature=0.0,
        )

        # Clean markdown codeblocks if present
        clean_text = response_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]

        data = json.loads(clean_text.strip())
        return response_model.model_validate(data)

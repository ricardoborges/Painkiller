"""LiteLLM adapter implementing LLMPort."""

import json
from typing import Type, TypeVar
import litellm
from pydantic import BaseModel

from painkiller.core.ports.llm import LLMPort

T = TypeVar("T", bound=BaseModel)


class LiteLLMAdapter(LLMPort):
    """Multi-provider LLM adapter powered by LiteLLM."""

    def __init__(self, default_model: str = "gpt-4o"):
        self.default_model = default_model

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

        response = await litellm.acompletion(
            model=chosen_model,
            messages=messages,
            temperature=temperature,
        )
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

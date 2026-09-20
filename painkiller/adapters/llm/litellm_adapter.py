"""LiteLLM adapter implementing LLMPort with custom endpoints support (including NVIDIA Build NIM)."""

import json
import os
import re
from typing import Optional, Type, TypeVar
import httpx
import litellm
from pydantic import BaseModel

from painkiller.core.ports.llm import LLMPort

T = TypeVar("T", bound=BaseModel)


class LiteLLMAdapter(LLMPort):
    """Multi-provider LLM adapter with native support for NVIDIA Build NIM and LiteLLM."""

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
            or "moonshotai/kimi-k3"
        ).strip().strip('"').strip("'")

        self.api_base = (
            os.environ.get("PAINKILLER_LLM_API_BASE")
            or os.environ.get("OPENAI_API_BASE")
            or os.environ.get("NVIDIA_API_BASE")
            or api_base
            or ""
        ).strip().strip('"').strip("'")

        self.api_key = (
            os.environ.get("PAINKILLER_LLM_API_KEY")
            or os.environ.get("NVIDIA_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or api_key
            or ""
        ).strip().strip('"').strip("'")

    @property
    def is_nvidia(self) -> bool:
        return "nvidia.com" in self.api_base or (self.api_key and self.api_key.startswith("nvapi-"))

    async def _complete_nvidia(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 1.0,
        max_tokens: int = 4096,
    ) -> str:
        """Call NVIDIA Build NIM directly with streaming to handle reasoning tokens and long horizons."""
        base_url = self.api_base.rstrip("/") if self.api_base else "https://integrate.api.nvidia.com/v1"
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        }
        clean_model = model.replace("openai/", "")
        payload = {
            "model": clean_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise RuntimeError(f"NVIDIA API error ({response.status_code}): {error_text.decode('utf-8', errors='replace')}")

                content_chunks = []
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                content_chunks.append(content)
                    except Exception:
                        continue

                return "".join(content_chunks).strip()

    async def complete(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str = "",
        temperature: float = 0.7,
    ) -> str:
        chosen_model = model or self.default_model
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        if self.is_nvidia:
            return await self._complete_nvidia(
                messages=messages,
                model=chosen_model,
                temperature=temperature,
            )

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
            system_prompt
            + "\nIMPORTANTE: Você deve responder EXCLUSIVAMENTE em formato JSON válido, sem texto explicativo adicional antes ou depois."
        )
        schema_json = json.dumps(response_model.model_json_schema(), indent=2, ensure_ascii=False)
        full_prompt = f"{prompt}\n\nSchema JSON esperado:\n```json\n{schema_json}\n```\nResponda apenas o JSON:"

        response_text = await self.complete(
            prompt=full_prompt,
            system_prompt=sys_msg,
            model=chosen_model,
            temperature=0.3 if self.is_nvidia else 0.0,
        )

        clean_text = response_text.strip()
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_text)
        if json_match:
            clean_text = json_match.group(1).strip()
        elif "{" in clean_text and "}" in clean_text:
            first_brace = clean_text.find("{")
            last_brace = clean_text.rfind("}")
            clean_text = clean_text[first_brace : last_brace + 1].strip()

        data = json.loads(clean_text)
        return response_model.model_validate(data)

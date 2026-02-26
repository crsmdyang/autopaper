from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Optional, Dict, List, Union

import requests

from auto_paper.config import settings


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    raw: dict


class OpenAIChatCompletionsClient:
    """
    Minimal OpenAI-compatible Chat Completions client via HTTP.
    - Uses: POST {base_url}/chat/completions
    - Requires env: OPENAI_API_KEY
    - NOTE: OpenAI API evolves; if your account uses a newer endpoint, update here.
    """
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.openai_api_key
        self.base_url = (base_url or settings.openai_base_url).rstrip("/")
        self.model = model or settings.openai_model
        if not self.api_key:
            raise LLMError("OPENAI_API_KEY is not set. Put it in .env or environment variables.")

    def chat_text(
        self,
        system: str,
        user: Union[str, List[Dict[str, Any]]],
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        # Best-effort request with basic retries
        last_err = None
        for attempt in range(3):
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=60)
                if r.status_code >= 400:
                    raise LLMError(f"OpenAI API error {r.status_code}: {r.text[:500]}")
                data = r.json()
                text = data["choices"][0]["message"]["content"]
                return LLMResponse(text=text, raw=data)
            except Exception as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"LLM request failed after retries: {last_err}")

    def chat_json(
        self,
        system: str,
        user: Union[str, List[Dict[str, Any]]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> dict:
        # Enforce JSON-only output by instruction; also try response_format if supported.
        json_system = system.strip() + "\n\nYou MUST output ONLY valid JSON. No markdown."
        json_user = user.strip() if isinstance(user, str) else user

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": json_system},
                {"role": "user", "content": json_user},
            ],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        # Attempt JSON mode if supported by your endpoint/model.
        # Some models/endpoints may reject this; we fall back automatically.
        payload["response_format"] = {"type": "json_object"}

        last_err = None
        for attempt in range(3):
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=60)
                if r.status_code >= 400:
                    # Fallback: some models reject response_format or multimodal+json combos.
                    # Retry once without response_format.
                    if r.status_code in (400, 404) and payload.get("response_format") is not None:
                        payload2 = dict(payload)
                        payload2.pop("response_format", None)
                        r2 = requests.post(url, headers=headers, json=payload2, timeout=60)
                        if r2.status_code < 400:
                            data = r2.json()
                            text = data["choices"][0]["message"]["content"]
                            try:
                                return json.loads(text)
                            except json.JSONDecodeError:
                                start = text.find("{")
                                end = text.rfind("}")
                                if start != -1 and end != -1 and end > start:
                                    return json.loads(text[start:end+1])
                                raise
                        raise LLMError(f"OpenAI API error {r.status_code}: {r.text[:500]}")
                    raise LLMError(f"OpenAI API error {r.status_code}: {r.text[:500]}")
                data = r.json()
                text = data["choices"][0]["message"]["content"]
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    # salvage: try to extract first JSON object
                    start = text.find("{")
                    end = text.rfind("}")
                    if start != -1 and end != -1 and end > start:
                        return json.loads(text[start:end+1])
                    raise
            except Exception as e:
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"LLM JSON request failed after retries: {last_err}")

"""Gemini client built on the official `google-genai` SDK."""

from __future__ import annotations

import os
from collections.abc import Iterator

from google import genai
from google.genai import errors, types

from core.base import LLMError, Usage

# Model codes from https://ai.google.dev/gemini-api/docs/models (checked 2026-10).
GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-4-argon",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
]
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


class GeminiClient:
    provider = "Gemini"

    def __init__(self, model: str = DEFAULT_GEMINI_MODEL, api_key: str | None = None):
        key = api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            raise LLMError("Thiếu GEMINI_API_KEY. Điền key vào file .env rồi chạy lại.")
        self.model = model
        self.last_usage = Usage()
        self.last_truncated = False
        self._client = genai.Client(api_key=key)

    def stream(self, system: str, prompt: str, max_tokens: int) -> Iterator[str]:
        self.last_usage = Usage()
        self.last_truncated = False
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
        )
        last = None
        try:
            for chunk in self._client.models.generate_content_stream(
                model=self.model, contents=prompt, config=config
            ):
                last = chunk
                if chunk.text:
                    yield chunk.text
        except errors.ClientError as e:
            if e.code in (401, 403) or "API key" in str(e):
                raise LLMError("Gemini: API key không hợp lệ hoặc không có quyền.") from e
            if e.code == 404:
                raise LLMError(f"Gemini: không tìm thấy model {self.model} (404).") from e
            if e.code == 429:
                raise LLMError("Gemini: vượt hạn mức (429). Thử lại sau.") from e
            raise LLMError(f"Gemini: lỗi API {e.code}: {e.message}") from e
        except errors.APIError as e:
            raise LLMError(f"Gemini: lỗi máy chủ {e.code}: {e.message}") from e
        except Exception as e:  # network errors come from the SDK's HTTP layer
            raise LLMError(f"Gemini: không gọi được API ({type(e).__name__}: {e}).") from e

        if last is not None and last.usage_metadata is not None:
            meta = last.usage_metadata
            self.last_usage = Usage(
                meta.prompt_token_count or 0,
                (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0),
            )
        if last is not None and last.candidates:
            reason = last.candidates[0].finish_reason
            self.last_truncated = reason == types.FinishReason.MAX_TOKENS

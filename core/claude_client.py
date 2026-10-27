"""Claude client built on the official `anthropic` SDK."""

from __future__ import annotations

import os
from collections.abc import Iterator

import anthropic

from core.base import LLMError, Usage

# Model IDs from the Anthropic models overview (checked 2026-10).
CLAUDE_MODELS = [
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
    "claude-fable-5-1",
]
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"

# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeClient:
    provider = "Claude"

    def __init__(self, model: str = DEFAULT_CLAUDE_MODEL, api_key: str | None = None):
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("Thiếu ANTHROPIC_API_KEY. Điền key vào file .env rồi chạy lại.")
        self.model = model
        self.last_usage = Usage()
        self.last_truncated = False
        self._client = anthropic.Anthropic(api_key=key)

    def stream(self, system: str, prompt: str, max_tokens: int) -> Iterator[str]:
        self.last_usage = Usage()
        self.last_truncated = False
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            # Lower effort keeps thinking (which counts against max_tokens) short.
            "output_config": {"effort": "low"},
        }
        if self.model in _FALLBACK_MODELS:
            kwargs["betas"] = [_FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        try:
            with self._client.beta.messages.stream(**kwargs) as stream:
                yield from stream.text_stream
                message = stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise LLMError("Claude: API key không hợp lệ (401). Kiểm tra ANTHROPIC_API_KEY.") from e
        except anthropic.PermissionDeniedError as e:
            raise LLMError(f"Claude: không có quyền dùng model {self.model} (403).") from e
        except anthropic.NotFoundError as e:
            raise LLMError(f"Claude: không tìm thấy model {self.model} (404).") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Claude: vượt giới hạn tốc độ/hạn mức (429). Thử lại sau.") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude: lỗi API {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Claude: không kết nối được tới API (mạng/timeout).") from e

        self.last_usage = Usage(message.usage.input_tokens, message.usage.output_tokens)
        if message.stop_reason == "refusal":
            raise LLMError("Claude từ chối trả lời yêu cầu này (refusal).")
        self.last_truncated = message.stop_reason == "max_tokens"

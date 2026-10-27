"""Shared types for model clients."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol


class LLMError(Exception):
    """A user-facing error from a model provider (missing key, API failure, refusal...)."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMClient(Protocol):
    """Streams one reply. After the iterator is exhausted, `last_usage` holds its token usage."""

    provider: str  # "Claude" or "Gemini"
    model: str
    last_usage: Usage
    last_truncated: bool

    def stream(self, system: str, prompt: str, max_tokens: int) -> Iterator[str]: ...

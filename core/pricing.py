"""Estimated USD cost per model (standard paid tier, text, per 1M tokens).

Sources (read 2026-10-27):
- Claude: Anthropic models overview / pricing.
- Gemini: https://ai.google.dev/gemini-api/docs/pricing (output price includes thinking tokens).
Each model maps to a list of (effective_from, input_price, output_price), oldest first.
"""

from __future__ import annotations

from datetime import date

from core.base import Usage

_EPOCH = date(2000, 1, 1)

PRICES: dict[str, list[tuple[date, float, float]]] = {
    "claude-opus-5-5": [(_EPOCH, 4.00, 20.00)],
    "claude-sonnet-5-5": [(_EPOCH, 2.00, 10.00)],
    # Haiku 5.5 is $0.50/$2.50 above 100K-token prompts; debate prompts stay far below that.
    "claude-haiku-5-5": [(_EPOCH, 0.10, 0.50)],
    "claude-fable-5-1": [(_EPOCH, 10.00, 50.00)],
    "gemini-4-argon": [(_EPOCH, 2.00, 10.00), (date(2026, 12, 1), 4.00, 20.00)],
    "gemini-3.8-flash": [(_EPOCH, 0.75, 3.75), (date(2027, 1, 1), 1.50, 7.50)],
    "gemini-3.6-flash": [(_EPOCH, 0.75, 3.75), (date(2027, 1, 1), 1.50, 7.50)],
    "gemini-3.5-flash-lite": [(_EPOCH, 0.30, 2.50)],
}


def price_for(model: str, on: date | None = None) -> tuple[float, float] | None:
    """(input, output) USD per 1M tokens, or None for an unknown model. 'mock:' is ignored."""
    tiers = PRICES.get(model.removeprefix("mock:"))
    if not tiers:
        return None
    on = on or date.today()
    current = tiers[0]
    for tier in tiers:
        if tier[0] <= on:
            current = tier
    return current[1], current[2]


def cost_usd(model: str, usage: Usage, on: date | None = None) -> float | None:
    price = price_for(model, on)
    if price is None:
        return None
    return (usage.input_tokens * price[0] + usage.output_tokens * price[1]) / 1_000_000

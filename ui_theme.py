"""Page CSS for the Streamlit UI, following the apple-design skill.

Translucent chrome over scrolling content, cards whose depth grows with their size,
instant press feedback, size-specific type tracking, and fallbacks for reduced
motion, reduced transparency and increased contrast.
"""

from __future__ import annotations

LIGHT = {
    "glass": "rgba(255, 255, 255, 0.72)",
    "glass_solid": "#ffffff",
    "card": "#f5f5f7",
    "card_edge": "rgba(0, 0, 0, 0.06)",
    "shadow_sm": "0 1px 2px rgba(0, 0, 0, 0.04), 0 2px 8px rgba(0, 0, 0, 0.04)",
    "shadow_lg": "0 2px 4px rgba(0, 0, 0, 0.04), 0 12px 32px rgba(0, 0, 0, 0.08)",
    "muted": "#6e6e73",
    "contrast_edge": "#1d1d1f",
}
DARK = {
    "glass": "rgba(17, 17, 19, 0.72)",
    "glass_solid": "#111113",
    "card": "#1f1f22",
    "card_edge": "rgba(255, 255, 255, 0.07)",
    "shadow_sm": "0 1px 2px rgba(0, 0, 0, 0.4)",
    "shadow_lg": "0 2px 6px rgba(0, 0, 0, 0.45), 0 16px 40px rgba(0, 0, 0, 0.35)",
    "muted": "#a1a1a6",
    "contrast_edge": "#f5f5f7",
}

# Score-chart line colour per theme; both pass the dataviz palette validator.
SCORE_COLORS = {"light": "#c4613f", "dark": "#d9714c"}


def page_css(dark: bool) -> str:
    c = DARK if dark else LIGHT
    return f"""<style>
/* Typography: tracking and leading are size-specific. */
h1 {{ letter-spacing: -0.025em; line-height: 1.08; }}
h2, h3 {{ letter-spacing: -0.015em; line-height: 1.2; }}
.ad-subtitle {{ color: {c["muted"]}; font-size: 1.05rem; line-height: 1.45; margin: -0.4rem 0 1.2rem; }}
.ad-section {{ color: {c["muted"]}; font-size: 0.72rem; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase; margin: 1.1rem 0 0.15rem; }}

/* Translucent header: content scrolls underneath instead of below a fixed strip. */
[data-testid="stHeader"] {{
  background: {c["glass"]};
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
}}

/* Model replies: small cards, light depth. Headings inside stay modest. */
[data-testid="stChatMessage"] {{
  background: {c["card"]};
  border: 1px solid {c["card_edge"]};
  border-radius: 16px;
  padding: 0.9rem 1.1rem;
  box-shadow: {c["shadow_sm"]};
  margin-bottom: 0.6rem;
}}
[data-testid="stChatMessage"] h1, .st-key-history_view h1 {{ font-size: 1.3rem; }}
[data-testid="stChatMessage"] h2, .st-key-history_view h2 {{ font-size: 1.12rem; }}
[data-testid="stChatMessage"] h3, [data-testid="stChatMessage"] h4,
.st-key-history_view h3, .st-key-history_view h4 {{ font-size: 1rem; }}

/* Bigger surfaces read thicker: the final result carries the deepest shadow. */
.st-key-final_box {{
  border: 1px solid {c["card_edge"]} !important;
  border-radius: 20px !important;
  box-shadow: {c["shadow_lg"]};
  padding: 0.4rem 0.6rem;
}}
/* The result already sits on the deepest card; no second card inside it. */
.st-key-final_box [data-testid="stChatMessage"] {{
  background: transparent; border: none; box-shadow: none; padding-left: 0.2rem;
}}
.st-key-metrics_box {{
  background: {c["card"]};
  border: 1px solid {c["card_edge"]};
  border-radius: 18px;
  padding: 0.9rem 1.2rem 0.5rem;
}}
.st-key-empty_state {{
  background: {c["card"]};
  border-radius: 18px;
  padding: 1.2rem 1.4rem;
}}

/* Feedback lives on the press, and it is instant. */
.stButton button, .stDownloadButton button {{
  transition: transform 100ms ease-out, filter 150ms ease-out;
}}
.stButton button:active, .stDownloadButton button:active {{ transform: scale(0.97); }}
.stButton button:hover:not(:disabled), .stDownloadButton button:hover:not(:disabled) {{
  filter: brightness(0.97);
}}

@media (prefers-reduced-motion: reduce) {{
  .stButton button, .stDownloadButton button {{ transition: filter 150ms ease; }}
  .stButton button:active, .stDownloadButton button:active {{ transform: none; }}
}}
@media (prefers-reduced-transparency: reduce) {{
  [data-testid="stHeader"] {{ background: {c["glass_solid"]}; backdrop-filter: none;
    -webkit-backdrop-filter: none; }}
}}
@media (prefers-contrast: more) {{
  [data-testid="stChatMessage"], .st-key-final_box, /* The result already sits on the deepest card; no second card inside it. */
.st-key-final_box [data-testid="stChatMessage"] {{
  background: transparent; border: none; box-shadow: none; padding-left: 0.2rem;
}}
.st-key-metrics_box {{
    border: 1px solid {c["contrast_edge"]} !important; box-shadow: none;
  }}
}}
</style>"""

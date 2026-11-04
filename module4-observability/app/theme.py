"""
Chart palette and Plotly defaults.

Colours come from a validated palette, not from taste. The categorical and
status sets were each run through the data-viz validator against this
dashboard's actual surface (#fcfcfb), not a generic white.

Two results worth carrying forward:

  * The status set clears CVD separation and the normal-vision floor
    (worst adjacent pair delta-E 18.9 normal, 9.1 deutan).
  * `warning` sits below 3:1 contrast on a light surface. That is inherent
    to the reserved status palette and the mitigation is mandatory, not
    optional: every status mark ships with a visible count label and a text
    legend, and every chart has a table view beside it. Colour never carries
    meaning on its own here.
"""
from __future__ import annotations

# --- Surfaces and ink -----------------------------------------------------
SURFACE = "#fcfcfb"        # chart surface
PLANE = "#f9f9f7"          # page behind the cards
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

# --- Categorical, in fixed slot order. Never cycled. ----------------------
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
          "#e87ba4", "#008300", "#4a3aa7", "#e34948"]

# --- Status. Reserved: never reused as a series colour. -------------------
GOOD = "#0ca30c"
WARNING = "#fab219"
CRITICAL = "#d03b3b"
NEUTRAL = "#898781"

# Check-in states. `serious` is deliberately unused: putting it beside
# `warning` is the one pair in the status palette that falls below the
# normal-vision separation floor.
STATUS_COLOR = {
    "approved": GOOD,
    "flagged": WARNING,
    "rejected": CRITICAL,
    "appealed": SERIES[0],
    "pending": NEUTRAL,
}

# Icons, so a state is never conveyed by colour alone.
STATUS_ICON = {
    "approved": "✓",
    "flagged": "!",
    "rejected": "✕",
    "appealed": "↻",
    "pending": "•",
}

RISK_COLOR = {"low": GOOD, "medium": WARNING, "high": CRITICAL}

RISK_LEVEL_COLOR = {
    "LOW": GOOD, "MEDIUM": WARNING, "HIGH": CRITICAL, "CRITICAL": CRITICAL,
}


def status_label(status: str) -> str:
    """Icon plus word. Used everywhere a status appears."""
    return f"{STATUS_ICON.get(status, '•')} {status.capitalize()}"


# --- Badges -----------------------------------------------------------------
# A badge is a tinted pill: pale fill, dark text in the same hue, icon plus
# word. The raw status colours are too light to carry text (warning is under
# 3:1), so the text uses a darkened shade that clears 4.5:1 on its own fill.
# Tone -> (fill, text, accent).
TONE = {
    "good": ("#e7f5e7", "#0a6b0a", GOOD),
    "warning": ("#fff4d9", "#7a5200", WARNING),
    "critical": ("#fbe7e7", "#a42a2a", CRITICAL),
    "info": ("#e6effb", "#1c5aa8", SERIES[0]),
    "neutral": ("#efeee9", "#52514e", NEUTRAL),
}

CHECKIN_TONE = {
    "approved": "good", "flagged": "warning", "rejected": "critical",
    "appealed": "info", "pending": "neutral",
}

SESSION_TONE = {
    "active": "good", "scheduled": "info",
    "closed": "neutral", "cancelled": "critical",
}
SESSION_ICON = {"active": "●", "scheduled": "◷", "closed": "■", "cancelled": "✕"}

RISK_LEVEL_TONE = {
    "LOW": "good", "MEDIUM": "warning", "HIGH": "critical", "CRITICAL": "critical",
}


def badge(text: str, tone: str) -> str:
    """HTML pill. Pass text that already carries its icon."""
    fill, ink, _ = TONE.get(tone, TONE["neutral"])
    return (f'<span class="saiv-badge" style="background:{fill};color:{ink}">'
            f'{text}</span>')


def checkin_badge(status: str) -> str:
    return badge(status_label(status), CHECKIN_TONE.get(status, "neutral"))


def session_badge(status: str) -> str:
    return badge(f"{SESSION_ICON.get(status, '•')} {status.capitalize()}",
                 SESSION_TONE.get(status, "neutral"))


def checkin_cell_style(value: str) -> str:
    """
    pandas Styler hook for a Status column holding status_label() text.
    st.dataframe renders Styler fills and text colours, so the table gets
    the same badge colours as the cards.
    """
    word = str(value).split(" ", 1)[-1].lower()
    tone = CHECKIN_TONE.get(word)
    if not tone:
        return ""
    fill, ink, _ = TONE[tone]
    return f"background-color: {fill}; color: {ink}; font-weight: 600"


def kpi_grid(cards: list) -> str:
    """
    A row of KPI cards as one CSS grid.

    st.metric cards in st.columns size to their own content, so a card with
    a delta line ends up taller than its neighbours. Grid items stretch to
    the tallest item in the row, and every card always renders a footer
    line, so the row stays level whatever the numbers are.

    Each card: {"label", "value", "foot", "tone" (optional)}. A tone colours
    the top accent and the value, and the footer becomes a badge.
    """
    parts = []
    for card in cards:
        tone = card.get("tone")
        if tone:
            fill, ink, accent = TONE[tone]
            style = f"border-top:3px solid {accent}"
            value_style = f"color:{ink}"
            foot = badge(card["foot"], tone)
        else:
            style = "border-top:3px solid transparent"
            value_style = ""
            foot = f'<span class="saiv-kpi-note">{card.get("foot", "")}</span>'
        parts.append(
            f'<div class="saiv-kpi" style="{style}">'
            f'<div class="saiv-kpi-label">{card["label"]}</div>'
            f'<div class="saiv-kpi-value" style="{value_style}">{card["value"]}</div>'
            f'<div class="saiv-kpi-foot">{foot}</div>'
            f'</div>')
    return f'<div class="saiv-kpis">{"".join(parts)}</div>'


def base_layout(height: int = 260, show_legend: bool = False) -> dict:
    """
    Plotly layout shared by every chart.

    Recessive chrome: hairline horizontal gridlines only, no vertical ones,
    no plot border, no chartjunk. Axis and tick text in muted ink so the
    data is the darkest thing on the surface.
    """
    return {
        "height": height,
        "margin": {"l": 8, "r": 8, "t": 8, "b": 8},
        "paper_bgcolor": SURFACE,
        "plot_bgcolor": SURFACE,
        "font": {"family": "system-ui, -apple-system, 'Segoe UI', sans-serif",
                 "size": 12, "color": INK_SECONDARY},
        "showlegend": show_legend,
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02,
                   "xanchor": "left", "x": 0, "font": {"color": INK_SECONDARY}},
        "hoverlabel": {"bgcolor": SURFACE, "bordercolor": AXIS,
                       "font": {"color": INK, "size": 12}},
        "xaxis": {"showgrid": False, "zeroline": False,
                  "linecolor": AXIS, "tickfont": {"color": INK_MUTED}},
        "yaxis": {"showgrid": True, "gridcolor": GRID, "gridwidth": 1,
                  "zeroline": True, "zerolinecolor": AXIS,
                  "linecolor": "rgba(0,0,0,0)",
                  "tickfont": {"color": INK_MUTED},
                  # Counts always start at zero. A truncated axis makes a
                  # small difference look enormous, which is the single
                  # easiest way to mislead with an attendance chart.
                  "rangemode": "tozero"},
    }


CSS = f"""
<style>
  .block-container {{ padding-top: 2rem; max-width: 1200px; }}
  [data-testid="stMetric"] {{
      background: {SURFACE};
      border: 1px solid rgba(11,11,11,0.10);
      border-radius: 12px;
      padding: 14px 16px;
  }}
  [data-testid="stMetricLabel"] p {{
      font-size: 0.78rem; color: {INK_SECONDARY};
  }}
  .saiv-card {{
      background: {SURFACE};
      border: 1px solid rgba(11,11,11,0.10);
      border-radius: 12px;
      padding: 16px 18px;
      margin-bottom: 12px;
  }}
  .saiv-chart-title {{
      font-size: 0.9rem; font-weight: 600; color: {INK};
      margin: 0 0 2px 0;
  }}
  .saiv-chart-sub {{
      font-size: 0.78rem; color: {INK_MUTED}; margin: 0 0 8px 0;
  }}
  .saiv-kpis {{
      display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px; margin: 4px 0 12px 0;
  }}
  @media (max-width: 900px) {{
      .saiv-kpis {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  }}
  .saiv-kpi {{
      background: {SURFACE};
      border: 1px solid rgba(11,11,11,0.10);
      border-radius: 12px;
      padding: 12px 16px 14px;
      display: flex; flex-direction: column;
  }}
  .saiv-kpi-label {{ font-size: 0.78rem; color: {INK_SECONDARY}; }}
  .saiv-kpi-value {{
      font-size: 2rem; line-height: 1.2; color: {INK};
      font-variant-numeric: tabular-nums; margin: 4px 0 8px;
  }}
  .saiv-kpi-foot {{ margin-top: auto; min-height: 22px; }}
  .saiv-kpi-note {{ font-size: 0.75rem; color: {INK_MUTED}; }}
  .saiv-kpis.compact .saiv-kpi-value {{ font-size: 1.5rem; }}
  .saiv-badge {{
      display: inline-block; padding: 2px 9px; border-radius: 999px;
      font-size: 0.74rem; font-weight: 600; line-height: 1.5;
      white-space: nowrap;
  }}
  .saiv-today {{ list-style: none; margin: 0; padding: 0; }}
  .saiv-today li {{
      display: grid; grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px; align-items: start;
      padding: 9px 0; border-bottom: 1px solid {GRID};
  }}
  .saiv-today li:last-child {{ border-bottom: none; }}
  .saiv-today .t {{
      font-size: 0.75rem; font-weight: 600; color: {INK_SECONDARY};
      font-variant-numeric: tabular-nums;
  }}
  .saiv-today .n {{
      font-size: 0.9rem; font-weight: 600; color: {INK}; margin: 1px 0;
      overflow-wrap: anywhere;
  }}
  .saiv-today .m {{ font-size: 0.75rem; color: {INK_MUTED}; }}
  .saiv-today .r {{ text-align: right; padding-top: 2px; }}
  .saiv-today .c {{
      font-size: 0.72rem; color: {INK_MUTED}; margin-top: 3px;
      font-variant-numeric: tabular-nums;
  }}
  /* Tables scroll rather than squash on a narrow screen, per the module 4
     design guidance. */
  [data-testid="stDataFrame"] {{ overflow-x: auto; }}
</style>
"""

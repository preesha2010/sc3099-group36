"""
Shared chart builders.

Every chart here follows the same rules, and they are worth stating because
they are the ones that get broken by accident:

  * counts always start the y axis at zero
  * no pie charts, no dual axes, no gridline clutter
  * a status colour never appears without a text label beside it
  * every chart has a table view underneath it, so the numbers are readable
    exactly as well as approximately
"""
from __future__ import annotations

from typing import Dict, List

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import theme


def _frame(title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<p class="saiv-chart-title">{title}</p>'
        + (f'<p class="saiv-chart-sub">{subtitle}</p>' if subtitle else ""),
        unsafe_allow_html=True,
    )


def _show(figure: go.Figure, table: pd.DataFrame, label: str) -> None:
    """
    Chart, then the same numbers as a table.

    The table is not decoration. Three of the status colours sit below 3:1
    contrast on a light surface, and the palette's relief rule says that
    obligates visible labels or a table view. This is that table view.

    Note: st.plotly_chart in Streamlit 1.30 has no `key` parameter. It has
    **kwargs, so passing one is swallowed silently and forwarded to Plotly
    rather than raising, which is a good way to spend an hour confused.
    """
    st.plotly_chart(figure, use_container_width=True,
                    config={"displayModeBar": False})
    with st.expander(f"Table view · {label}"):
        st.dataframe(table, use_container_width=True, hide_index=True)


def trend_line(points: List[Dict], title: str, subtitle: str = "") -> None:
    """Check-ins per day. One series, so no legend: the title names it."""
    _frame(title, subtitle)
    if not points:
        st.caption("No data for this period.")
        return
    frame = pd.DataFrame(points)
    figure = go.Figure(go.Scatter(
        x=frame["date"], y=frame["count"],
        mode="lines+markers",
        line={"color": theme.SERIES[0], "width": 2},
        marker={"size": 8, "color": theme.SERIES[0]},
        hovertemplate="%{x}<br>%{y} check-ins<extra></extra>",
    ))
    layout = theme.base_layout(220)
    layout["hovermode"] = "x unified"        # crosshair, per the interaction rules
    figure.update_layout(**layout)
    _show(figure, frame.rename(columns={"date": "Date", "count": "Check-ins"}), title)


def status_composition(counts: Dict[str, int], title: str,
                       subtitle: str = "") -> None:
    """
    One horizontal stacked bar: parts of a whole, four states.

    A pie was the obvious choice and is the wrong one. Comparing angles is
    harder than comparing lengths, and the question an instructor actually
    asks is "how many need my attention", which reads straight off a
    labelled bar.
    """
    _frame(title, subtitle)
    ordered = [s for s in ("approved", "flagged", "rejected", "appealed", "pending")
               if counts.get(s)]
    total = sum(counts.get(s, 0) for s in ordered)
    if not total:
        st.caption("No check-ins yet.")
        return

    figure = go.Figure()
    for status in ordered:
        value = counts[status]
        figure.add_bar(
            y=[""], x=[value], orientation="h",
            name=theme.status_label(status),
            marker={"color": theme.STATUS_COLOR[status],
                    # 2px surface gap between adjacent fills.
                    "line": {"color": theme.SURFACE, "width": 2}},
            # Direct label on every segment. This is the mandatory relief for
            # the status colours that sit below 3:1 on a light surface.
            text=[str(value)], textposition="inside",
            insidetextfont={"color": "#ffffff", "size": 13},
            hovertemplate=f"{theme.status_label(status)}: %{{x}}<extra></extra>",
        )
    layout = theme.base_layout(120, show_legend=True)
    layout["barmode"] = "stack"
    layout["xaxis"] = {"showgrid": False, "zeroline": False, "visible": False}
    layout["yaxis"] = {"showgrid": False, "zeroline": False, "visible": False}
    figure.update_layout(**layout)

    table = pd.DataFrame([
        {"Status": theme.status_label(s), "Count": counts[s],
         "Share": f"{counts[s] / total:.0%}"} for s in ordered
    ])
    _show(figure, table, title)


def attendance_bars(rows: List[Dict], title: str, subtitle: str = "") -> None:
    """Attendance rate per session. Single series, so no legend."""
    _frame(title, subtitle)
    if not rows:
        st.caption("No sessions in this range.")
        return
    frame = pd.DataFrame(rows)
    frame["percent"] = (frame["attendance_rate"] * 100).round(1)
    figure = go.Figure(go.Bar(
        x=frame["name"], y=frame["percent"],
        marker={"color": theme.SERIES[0],
                "line": {"color": theme.SURFACE, "width": 2}},
        text=frame["percent"].map(lambda v: f"{v:.0f}%"),
        textposition="outside",
        outsidetextfont={"color": theme.INK_SECONDARY, "size": 11},
        hovertemplate="%{x}<br>%{y:.1f}% attended<extra></extra>",
    ))
    layout = theme.base_layout(260)
    layout["yaxis"]["ticksuffix"] = "%"
    layout["yaxis"]["range"] = [0, 108]      # headroom for the outside labels
    figure.update_layout(**layout)
    _show(figure, frame[["name", "date", "checked_in", "percent"]].rename(columns={
        "name": "Session", "date": "Date", "checked_in": "Checked in",
        "percent": "Attendance %"}), title)


def risk_bars(distribution: Dict[str, int], title: str,
              subtitle: str = "") -> None:
    """
    Risk bands. Status colours, ordered low to high, each labelled.

    `serious` from the status palette is deliberately not used: beside
    `warning` it is the one pair that falls under the normal-vision
    separation floor, so the three-band split is the safe one.
    """
    _frame(title, subtitle)
    bands = ["low", "medium", "high"]
    values = [distribution.get(b, 0) for b in bands]
    if not sum(values):
        st.caption("No check-ins yet.")
        return
    labels = ["Low (< 0.3)", "Medium (0.3 to 0.5)", "High (>= 0.5)"]
    figure = go.Figure(go.Bar(
        x=labels, y=values,
        marker={"color": [theme.RISK_COLOR[b] for b in bands],
                "line": {"color": theme.SURFACE, "width": 2}},
        text=[str(v) for v in values], textposition="outside",
        outsidetextfont={"color": theme.INK_SECONDARY, "size": 12},
        hovertemplate="%{x}<br>%{y} check-ins<extra></extra>",
    ))
    layout = theme.base_layout(240)
    layout["yaxis"]["range"] = [0, max(values) * 1.25 + 1]
    figure.update_layout(**layout)
    _show(figure, pd.DataFrame({"Risk band": labels, "Check-ins": values}),
          title)


def arrival_timeline(points: List[Dict], title: str, subtitle: str = "") -> None:
    """When people actually turned up, in five minute buckets."""
    _frame(title, subtitle)
    if not points:
        st.caption("No check-ins yet.")
        return
    frame = pd.DataFrame(points)
    figure = go.Figure(go.Bar(
        x=frame["minute"], y=frame["count"],
        marker={"color": theme.SERIES[0],
                "line": {"color": theme.SURFACE, "width": 2}},
        hovertemplate="%{x} min after opening<br>%{y} check-ins<extra></extra>",
    ))
    layout = theme.base_layout(200)
    layout["xaxis"]["title"] = {"text": "Minutes after check-in opened",
                                "font": {"color": theme.INK_MUTED, "size": 11}}
    figure.update_layout(**layout)
    _show(figure, frame.rename(columns={"minute": "Minutes after opening",
                                        "count": "Check-ins"}),
          title)

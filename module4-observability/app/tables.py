"""
Every table in the dashboard goes through show().

Why: st.dataframe left to size itself can get stuck readjusting. It fits its
columns to the space it has; if that makes a scrollbar appear inside the
table, the space shrinks, the columns are refitted, the scrollbar goes, the
space grows back, and round it goes. On screen the table twitches without
anything being touched.

show() breaks the loop at the height:

  * the height is fixed from the row count, plus room for a horizontal
    scrollbar, so every row always fits whether or not that scrollbar is
    showing; the table never needs a vertical scrollbar, so the width it
    fits its columns to never changes
  * long tables cap at MAX_ROWS visible rows and then always scroll, which
    is just as stable, because the scrollbar is then always there

Column widths stay automatic, so every column stays on screen; pass widths
only where a column should be pinned.
"""
from __future__ import annotations

from typing import Dict, Optional, Union

import pandas as pd
import streamlit as st
from pandas.io.formats.style import Styler

ROW_PX = 35          # st.dataframe row height in Streamlit 1.30, header included
BORDER_PX = 3
HSCROLL_PX = 16      # room for a horizontal scrollbar (Windows draws ~15 px)
MAX_ROWS = 12


def show(data: Union[pd.DataFrame, Styler],
         widths: Optional[Dict[str, str]] = None) -> None:
    """Render a table with a fixed height. widths: column -> small/medium/large."""
    frame = data.data if isinstance(data, Styler) else data
    rows = min(max(len(frame), 1), MAX_ROWS)
    config = ({col: st.column_config.Column(width=w) for col, w in widths.items()}
              if widths else None)
    st.dataframe(data, hide_index=True, use_container_width=True,
                 height=ROW_PX * (rows + 1) + BORDER_PX + HSCROLL_PX,
                 column_config=config)

"""Today's Top Deals - Streamlit app.

Shows games currently free on the Epic Games Store and the biggest Steam
discounts, flagging all-time low (ATL) prices. Price history is stored in
data/history.json and refreshed daily by a GitHub Actions cron job.
"""

import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from deal_checker import (
    fetch_epic,
    fetch_steam,
    fmt_price,
    load_history,
    save_history,
    today_utc,
    update_history,
)

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "data", "history.json")

st.set_page_config(
    page_title="Today's Top Deals",
    page_icon=":video_game:",
    layout="wide",
)

EMBED = st.query_params.get("embed", "false") == "true"


@st.cache_data(ttl=1800, show_spinner=False)
def get_deals():
    """Fetch fresh data (cached for 30 minutes) and merge into history."""
    steam = fetch_steam()
    epic = fetch_epic()
    history = load_history(HISTORY_PATH)
    report = update_history(history, steam, epic, today_utc())
    try:
        save_history(history, HISTORY_PATH)
    except OSError:
        pass
    return report, history, epic


def format_end_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%b %d, %H:%M")
    except ValueError:
        return "soon"


def main():
    st.title(":video_game: Today's Top Deals")
    st.caption(
        "Automatically refreshed. Free games on the Epic Games Store, the biggest "
        "Steam discounts and all-time low (ATL) price alerts."
    )

    report, history, epic = get_deals()

    # ------------------------------------------------------------------ epic
    @st.fragment(run_every="1h")
    def epic_section():
        st.subheader(":blue[Free on the Epic Games Store right now]")
        epic_free = [
            g for g in epic["current"] if g["is_free"]
        ]
        if not epic_free:
            st.info("No free game is running at this moment.")
        else:
            cols = st.columns(min(len(epic_free), 3))
            for i, game in enumerate(epic_free):
                with cols[i % 3]:
                    st.markdown(f"### {game['title']}")
                    st.markdown(
                        f"~~{game['original_price']}~~ **FREE**\n\n"
                        f"Claim until **{format_end_date(game['end'])}**"
                    )
                    if game["url"]:
                        st.markdown(f"[Claim it]({game['url']})")

        upcoming = [g for g in epic["upcoming"]]
        if upcoming:
            st.subheader(":clock3: Upcoming Epic giveaways")
            for game in upcoming:
                start = game["start"]
                if start:
                    try:
                        dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone()
                        when = f"from {dt.strftime('%b %d')}"
                    except ValueError:
                        when = "soon"
                else:
                    when = "soon"
                st.markdown(f"- **{game['title']}** - free {when}")

    epic_section()

    # ----------------------------------------------------------------- steam
    st.subheader(":fire: Biggest Steam discounts today")

    deals = pd.DataFrame([
        {
            "Game": g["name"],
            "Price": g["final_formatted"],
            "Discount": f"-{g['discount_pct']}%",
            "All-time low": (
                ":medal: NEW LOW!" if g["is_new_atl"]
                else (":white_check_mark: at low" if g["min_price"] is not None
                      and g["final"] == g["min_price"] else "")
            ),
            "Link": g["url"],
        }
        for g in report["steam"]
        if g["discount_pct"] > 0 and g["final"] is not None
    ])
    deals = deals.sort_values("Discount", key=lambda s: s.str.rstrip("%").str.lstrip("-").astype(int), ascending=False)

    if deals.empty:
        st.info("No active Steam discounts right now.")
    else:
        deals.index = deals.index + 1
        st.dataframe(
            deals,
            hide_index=False,
            column_config={
                "Game": st.column_config.TextColumn(width="large"),
                "Price": st.column_config.TextColumn(width="small"),
                "Discount": st.column_config.TextColumn(width="small"),
                "All-time low": st.column_config.TextColumn(width="small"),
                "Link": st.column_config.LinkColumn("Store"),
            },
            width="stretch",
        )

        new_lows = deals[deals["All-time low"].eq(":medal: NEW LOW!")]
        if not new_lows.empty:
            st.success(
                "**:medal: New all-time lows today:** "
                + ", ".join(new_lows["Game"].tolist())
            )

    # ------------------------------------------------------- price history
    st.subheader(":chart_with_upwards_trend: Price history")
    watched = list(history["steam"].values())
    if not watched:
        st.info("No price history yet - it builds up automatically each day.")
    else:
        name = st.selectbox(
            "Pick a game to view its price history",
            options=sorted({g["name"] for g in watched}),
        )
        record = next(g for g in watched if g["name"] == name)
        series = pd.Series(record["prices"]).sort_index()
        if len(series) >= 1:
            st.line_chart(series / 100, y_label="Price")
            cur = record.get("currency") or "USD"
            st.markdown(
                f"All-time low: **{fmt_price(record['min_price'], cur)}** "
                f"on {record['min_date']} ({cur})"
            )

    st.caption(
        "Prices are in USD and checked daily. Discounts come from the Steam "
        "storefront API and free games from the Epic Games Store public API. "
        f"Last updated: {history.get('updated', 'unknown')}."
    )


main()

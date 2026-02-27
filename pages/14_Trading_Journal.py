"""
Trading Journal
Daily trade log, performance analytics, and pattern analysis.
Data lives in '📈 Trading Journal' sheet of the masterfile.
"""

import streamlit as st
import pandas as pd
from datetime import date
from utils.sheets import get_spreadsheet
from utils.auth import require_auth

st.set_page_config(
    page_title="Trading Journal",
    page_icon="📈",
    layout="wide",
)

require_auth("personal")

SHEET_NAME  = "📈 Trading Journal"
DATA_START  = 12   # First data row (row 11 = header)

HEADERS = [
    "Date", "Paper/Real", "Day/Swing", "Direction", "Ticker",
    "Price In", "Stop Loss", "Take Profit", "Stopped Out",
    "Date Out", "Price Out", "Comments", "Mood",
    "Points P/L", "$ P/L",
]

MOODS   = ["", "Calm", "Confident", "Casual", "Eager", "Excited",
           "Tired", "Anxious", "Panicky", "Stubborn", "Emotional", "Other"]
TICKERS = ["MES", "M2K", "Other"]
POINT_VALUE = 5.0   # MES and M2K: $5 per point


# ─── Sheet helpers ────────────────────────────────────────────────────────────

def _ws():
    return get_spreadsheet().worksheet(SHEET_NAME)


@st.cache_data(ttl=120)
def load_account_info() -> tuple[float, float]:
    """Returns (year_start_balance, current_balance)."""
    try:
        ws    = _ws()
        start = ws.acell("B9").value
        cur   = ws.acell("B10").value
        return (
            float(str(start).replace(",", "").replace("$", "")),
            float(str(cur).replace(",", "").replace("$", "")),
        )
    except Exception:
        return 0.0, 0.0


@st.cache_data(ttl=120)
def load_trades() -> pd.DataFrame:
    ws       = _ws()
    all_vals = ws.get_all_values()
    if len(all_vals) < DATA_START:
        return pd.DataFrame(columns=HEADERS)

    rows = []
    for i, raw in enumerate(all_vals[DATA_START - 1:], start=DATA_START):
        if not any(str(v).strip() for v in raw):
            continue
        padded = raw + [""] * max(0, len(HEADERS) - len(raw))
        d = dict(zip(HEADERS, padded[:len(HEADERS)]))
        d["_row"] = i
        rows.append(d)

    if not rows:
        return pd.DataFrame(columns=HEADERS)

    df = pd.DataFrame(rows)
    df["Date"]       = pd.to_datetime(df["Date"], errors="coerce")
    df["Points P/L"] = pd.to_numeric(df["Points P/L"], errors="coerce")
    df["$ P/L"]      = pd.to_numeric(df["$ P/L"], errors="coerce")
    df["Price In"]   = pd.to_numeric(df["Price In"], errors="coerce")
    df["Price Out"]  = pd.to_numeric(df["Price Out"], errors="coerce")

    # Fill missing dollar P/L from points
    mask = df["$ P/L"].isna() & df["Points P/L"].notna()
    df.loc[mask, "$ P/L"] = df.loc[mask, "Points P/L"] * POINT_VALUE

    def result(row):
        pl = row["Points P/L"]
        if pd.isna(pl):
            return "Unknown"
        if pl > 0:
            return "Win"
        elif pl < 0:
            return "Loss"
        return "Breakeven"

    df["Result"] = df.apply(result, axis=1)
    df["Mood"]   = df["Mood"].fillna("").str.strip()
    df["Ticker"] = df["Ticker"].fillna("").str.strip()
    return df.sort_values("Date", na_position="last").reset_index(drop=True)


def add_trade_row(row_data: list) -> None:
    ws       = _ws()
    all_vals = ws.get_all_values()
    next_row = DATA_START
    for i, raw in enumerate(all_vals[DATA_START - 1:], start=DATA_START):
        if not any(str(v).strip() for v in raw):
            next_row = i
            break
    else:
        next_row = len(all_vals) + 1
    ws.update(f"A{next_row}:O{next_row}", [row_data], value_input_option="USER_ENTERED")


# ─── Page ─────────────────────────────────────────────────────────────────────

st.title("📈 Trading Journal")

if st.button("🔄 Refresh"):
    st.cache_data.clear()
    st.rerun()

df                          = load_trades()
year_start, account_balance = load_account_info()
ytd_pct = ((account_balance - year_start) / year_start * 100) if year_start > 0 else 0.0
ytd_dollar = account_balance - year_start

# Only trades with a P/L recorded
df_s = df[df["Points P/L"].notna()].copy()

wins = df_s[df_s["Result"] == "Win"]
losses = df_s[df_s["Result"] == "Loss"]
bes    = df_s[df_s["Result"] == "Breakeven"]

total      = len(df_s)
win_count  = len(wins)
loss_count = len(losses)
be_count   = len(bes)
win_rate   = (win_count / total * 100) if total > 0 else 0.0

total_pts  = df_s["Points P/L"].sum()
total_pnl  = df_s["$ P/L"].sum()
avg_win    = wins["Points P/L"].mean()  if win_count  > 0 else 0.0
avg_loss   = abs(losses["Points P/L"].mean()) if loss_count > 0 else 0.0
rr         = (avg_win / avg_loss) if avg_loss > 0 else 0.0

# Current streak
streak, streak_type = 0, ""
for res in df_s["Result"].iloc[::-1]:
    if res == "Unknown":
        continue
    if streak == 0:
        streak_type, streak = res, 1
    elif res == streak_type:
        streak += 1
    else:
        break


# ─── Dashboard ────────────────────────────────────────────────────────────────

st.markdown('<div class="section-label">Performance Dashboard</div>',
            unsafe_allow_html=True)

c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
wr_diff = win_rate - 60
c1.metric("Account Balance", f"${account_balance:,.2f} USD")
c2.metric("YTD Return",      f"{ytd_pct:.2f}%",
          delta=f"${ytd_dollar:+,.2f} since Jan 1",
          delta_color="normal" if ytd_dollar >= 0 else "inverse")
c3.metric("Win Rate",     f"{win_rate:.1f}%",
          delta=f"{wr_diff:+.1f}% vs 60% goal",
          delta_color="normal" if wr_diff >= 0 else "inverse")
c4.metric("Trades",       str(total))
c5.metric("W / L / BE",   f"{win_count} / {loss_count} / {be_count}")
c6.metric("Total Points", f"{total_pts:+.2f}")
c7.metric("Total P&L",    f"${total_pnl:+.2f}")
rr_label = "above 2R goal" if rr >= 2 else "below 2R goal"
c8.metric("Avg R:R",      f"{rr:.2f}:1",
          delta=f"{rr_label}",
          delta_color="normal" if rr >= 2 else "inverse")

st.divider()


# ─── YTD Account Chart ────────────────────────────────────────────────────────

if year_start > 0 and account_balance > 0:
    from datetime import datetime
    today = datetime.today().date()
    ytd_df = pd.DataFrame({
        "Date":    [pd.Timestamp("2026-01-01"), pd.Timestamp(today)],
        "Balance": [year_start, account_balance],
    }).set_index("Date")

    st.markdown('<div class="section-label">Account Balance — 2026 YTD</div>',
                unsafe_allow_html=True)
    colour = "#2d6a9f" if account_balance >= year_start else "#c0392b"
    st.line_chart(ytd_df, color=[colour])
    st.caption(
        f"Jan 1: **${year_start:,.2f}**  ·  "
        f"Today: **${account_balance:,.2f}**  ·  "
        f"Change: **{ytd_pct:+.2f}% (${ytd_dollar:+,.2f})**"
    )

st.divider()


# ─── Charts ───────────────────────────────────────────────────────────────────

dated = df_s[df_s["Date"].notna()].sort_values("Date").copy()
if len(dated) > 1:
    dated["Cumulative P&L"] = dated["$ P/L"].cumsum()

    col_chart, col_dist = st.columns([3, 1])
    with col_chart:
        st.markdown('<div class="section-label">Cumulative P&L ($)</div>',
                    unsafe_allow_html=True)
        st.line_chart(dated.set_index("Date")[["Cumulative P&L"]], color=["#2d6a9f"])

    with col_dist:
        st.markdown('<div class="section-label">Trade Results</div>',
                    unsafe_allow_html=True)
        dist = pd.DataFrame({
            "Count": [win_count, loss_count, be_count]
        }, index=["Win", "Loss", "Breakeven"])
        st.bar_chart(dist, color=["#2d6a9f"])

    st.divider()


# ─── Add Trade ────────────────────────────────────────────────────────────────

with st.expander("➕ Add Trade"):
    c1, c2, c3 = st.columns(3)
    t_date   = c1.date_input("Date",          value=date.today(), key="t_date")
    t_type   = c2.selectbox("Paper / Real",   ["Paper Trade", "Real Trade"], key="t_type")
    t_style  = c3.selectbox("Day / Swing",    ["Day Trade", "Swing Trade"],  key="t_style")

    c4, c5, c6 = st.columns(3)
    t_dir    = c4.selectbox("Direction",      ["Long", "Short"],   key="t_dir")
    t_ticker = c5.selectbox("Ticker",         TICKERS,             key="t_ticker")
    t_mood   = c6.selectbox("Mood",           MOODS,               key="t_mood")

    c7, c8, c9 = st.columns(3)
    t_entry  = c7.number_input("Price In",    min_value=0.0, step=0.25, format="%.2f", key="t_entry")
    t_stop   = c8.text_input( "Stop Loss (price or No)", value="No", key="t_stop")
    t_tp     = c9.text_input( "Take Profit (price or No)", value="No", key="t_tp")

    c10, c11 = st.columns(2)
    t_exit    = c10.number_input("Price Out",  min_value=0.0, step=0.25, format="%.2f", key="t_exit")
    t_stopped = c11.selectbox("Stopped Out?", ["No", "Yes"], key="t_stopped")

    t_comments = st.text_area("Why I Took It / Comments", key="t_comments")

    # Auto-calculate
    pts, dollars = None, None
    if t_entry > 0 and t_exit > 0:
        pts    = (t_exit - t_entry) if t_dir == "Long" else (t_entry - t_exit)
        dollars = round(pts * POINT_VALUE, 2)
        colour = "green" if pts > 0 else ("red" if pts < 0 else "gray")
        st.markdown(
            f"<span style='color:{colour}; font-weight:700; font-size:1.05rem;'>"
            f"P/L: {pts:+.2f} pts = ${dollars:+.2f}</span>",
            unsafe_allow_html=True,
        )

    if st.button("✅ Save Trade", type="primary", use_container_width=True, key="t_save"):
        if t_entry == 0:
            st.error("Enter a Price In.")
        else:
            row = [
                t_date.strftime("%Y-%m-%d"),
                t_type, t_style, t_dir, t_ticker,
                t_entry, t_stop, t_tp, t_stopped,
                t_date.strftime("%Y-%m-%d"),
                t_exit if t_exit > 0 else "",
                t_comments, t_mood,
                round(pts, 2) if pts is not None else "",
                dollars if dollars is not None else "",
            ]
            add_trade_row(row)
            label = f"{pts:+.2f} pts" if pts is not None else "saved"
            st.success(f"Trade saved — {t_dir} {t_ticker} {label}")
            st.cache_data.clear()
            st.rerun()

st.divider()


# ─── Recent Trades ────────────────────────────────────────────────────────────

st.markdown('<div class="section-label">Recent Trades</div>', unsafe_allow_html=True)
if not df_s.empty:
    show = ["Date", "Paper/Real", "Direction", "Ticker", "Price In",
            "Price Out", "Points P/L", "$ P/L", "Mood", "Result", "Comments"]
    show   = [c for c in show if c in df_s.columns]
    recent = df_s[show].tail(20).copy()
    recent["Date"] = recent["Date"].dt.strftime("%b %d, %Y")
    recent = recent.iloc[::-1].reset_index(drop=True)
    st.dataframe(recent, use_container_width=True, hide_index=True)
else:
    st.info("No trades logged yet.")

st.divider()


# ─── Analyzer ─────────────────────────────────────────────────────────────────

st.markdown('<div class="section-label">Performance Analyzer</div>',
            unsafe_allow_html=True)

if total < 5:
    st.info("Log at least 5 trades to unlock the analyzer.")
else:
    tab1, tab2, tab3, tab4 = st.tabs(
        ["Direction", "Mood", "Symbol", "Insights"])

    with tab1:
        by_dir = df_s.groupby("Direction").agg(
            Trades   =("Result", "count"),
            Wins     =("Result", lambda x: (x == "Win").sum()),
            AvgPts   =("Points P/L", "mean"),
            TotalPnL =("$ P/L", "sum"),
        ).reset_index()
        by_dir["Win Rate"] = (by_dir["Wins"] / by_dir["Trades"] * 100).round(1).astype(str) + "%"
        by_dir["Avg Pts"]  = by_dir["AvgPts"].round(2)
        by_dir["Total P&L"] = by_dir["TotalPnL"].apply(lambda x: f"${x:+.2f}")
        st.dataframe(by_dir[["Direction", "Trades", "Win Rate", "Avg Pts", "Total P&L"]],
                     use_container_width=True, hide_index=True)

    with tab2:
        mood_df = df_s[df_s["Mood"] != ""]
        if mood_df.empty:
            st.info("No mood data recorded yet.")
        else:
            by_mood = mood_df.groupby("Mood").agg(
                Trades =("Result", "count"),
                Wins   =("Result", lambda x: (x == "Win").sum()),
                AvgPts =("Points P/L", "mean"),
            ).reset_index()
            by_mood["Win Rate"] = (by_mood["Wins"] / by_mood["Trades"] * 100).round(1).astype(str) + "%"
            by_mood["Avg Pts"]  = by_mood["AvgPts"].round(2)
            by_mood = by_mood.sort_values("Wins", ascending=False)
            st.dataframe(by_mood[["Mood", "Trades", "Win Rate", "Avg Pts"]],
                         use_container_width=True, hide_index=True)

    with tab3:
        by_tick = df_s.groupby("Ticker").agg(
            Trades   =("Result", "count"),
            Wins     =("Result", lambda x: (x == "Win").sum()),
            AvgPts   =("Points P/L", "mean"),
            TotalPnL =("$ P/L", "sum"),
        ).reset_index()
        by_tick["Win Rate"] = (by_tick["Wins"] / by_tick["Trades"] * 100).round(1).astype(str) + "%"
        by_tick["Avg Pts"]  = by_tick["AvgPts"].round(2)
        by_tick["Total P&L"] = by_tick["TotalPnL"].apply(lambda x: f"${x:+.2f}")
        st.dataframe(by_tick[["Ticker", "Trades", "Win Rate", "Avg Pts", "Total P&L"]],
                     use_container_width=True, hide_index=True)

    with tab4:
        insights = []

        # Win rate vs goal
        if win_rate >= 60:
            insights.append(
                f"✅ **Win rate {win_rate:.1f}% — above your 60% goal.** Keep doing what you're doing.")
        else:
            insights.append(
                f"⚠️ **Win rate {win_rate:.1f}% — {60 - win_rate:.1f}% below your 60% goal.** "
                f"Focus on trade selection — be more patient waiting for your setup.")

        # R:R vs goal
        if rr >= 2:
            insights.append(
                f"✅ **Avg R:R {rr:.2f}:1 — meeting your 2R goal.** Letting winners run.")
        else:
            insights.append(
                f"⚠️ **Avg R:R {rr:.2f}:1 — below your 2R goal.** "
                f"Winners avg {avg_win:.1f} pts, losers avg {avg_loss:.1f} pts. "
                f"Either cut losses faster or hold winners longer.")

        # Mood: Calm vs Excited
        mood_df2 = df_s[df_s["Mood"] != ""]
        if not mood_df2.empty:
            calm_trades = mood_df2[mood_df2["Mood"] == "Calm"]
            excited_trades = mood_df2[mood_df2["Mood"] == "Excited"]
            if len(calm_trades) >= 2 and len(excited_trades) >= 2:
                calm_wr = (calm_trades["Result"] == "Win").mean() * 100
                excited_wr = (excited_trades["Result"] == "Win").mean() * 100
                if calm_wr > excited_wr + 10:
                    insights.append(
                        f"🧠 **Calm: {calm_wr:.0f}% win rate vs Excited: {excited_wr:.0f}%.** "
                        f"Your best trades happen when you're calm and patient.")
                elif excited_wr > calm_wr + 10:
                    insights.append(
                        f"🧠 **Excited: {excited_wr:.0f}% vs Calm: {calm_wr:.0f}%.** "
                        f"Interesting — you perform well when excited. Watch for overtrading though.")

            # Negative mood warning
            bad_moods = ["Anxious", "Panicky", "Emotional", "Stubborn"]
            bad_df = mood_df2[mood_df2["Mood"].isin(bad_moods)]
            if len(bad_df) >= 2:
                bad_wr = (bad_df["Result"] == "Win").mean() * 100
                if bad_wr < win_rate - 10:
                    insights.append(
                        f"🚨 **Win rate drops to {bad_wr:.0f}% when trading {', '.join(bad_df['Mood'].unique())}.** "
                        f"If you're in one of these states, step away from the screen.")

        # Direction bias
        long_df  = df_s[df_s["Direction"] == "Long"]
        short_df = df_s[df_s["Direction"] == "Short"]
        if len(long_df) >= 3 and len(short_df) >= 3:
            long_wr  = (long_df["Result"]  == "Win").mean() * 100
            short_wr = (short_df["Result"] == "Win").mean() * 100
            better   = "Long" if long_wr > short_wr else "Short"
            diff     = abs(long_wr - short_wr)
            if diff > 10:
                insights.append(
                    f"📊 **Long {long_wr:.0f}% vs Short {short_wr:.0f}% win rate.** "
                    f"You perform better going {better}. Consider sizing up on {better} setups.")

        # Paper vs Real
        paper_df = df_s[df_s["Paper/Real"] == "Paper Trade"]
        real_df  = df_s[df_s["Paper/Real"] == "Real Trade"]
        if len(paper_df) >= 3 and len(real_df) >= 3:
            paper_wr = (paper_df["Result"] == "Win").mean() * 100
            real_wr  = (real_df["Result"]  == "Win").mean() * 100
            if paper_wr - real_wr > 15:
                insights.append(
                    f"💡 **Paper: {paper_wr:.0f}% win rate vs Real: {real_wr:.0f}%.** "
                    f"That's a big gap — emotions are likely hurting your real trading. "
                    f"Trade your real account exactly like your paper account.")

        # Streak
        if streak >= 2:
            if streak_type == "Win":
                insights.append(
                    f"🔥 **{streak}-trade win streak.** Great momentum — stay disciplined, don't get cocky.")
            elif streak_type == "Loss":
                insights.append(
                    f"❌ **{streak}-trade loss streak.** Step back. Review your last trades before the next one. "
                    f"Are you chasing? Trading outside your setup?")

        if insights:
            for insight in insights:
                st.markdown(insight)
                st.write("")
        else:
            st.info("Keep adding trades — insights will appear as your data grows.")

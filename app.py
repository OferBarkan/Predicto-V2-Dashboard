import streamlit as st
import pandas as pd
import gspread
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adset import AdSet
import json

# ============== UI & PAGE CONFIG ==============
st.set_page_config(page_title="Predicto Ads Dashboard", layout="wide")
st.title("Predicto Ads Dashboard")

# ============== DATA CONNECTIONS ==============
# Google Sheets
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds_dict = json.loads(st.secrets["GOOGLE_SHEETS_CREDENTIALS"])
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
client = gspread.authorize(creds)

# Facebook API
FacebookAdsApi.init(
    st.secrets["FB_APP_ID"],
    st.secrets["FB_APP_SECRET"],
    st.secrets["FB_ACCESS_TOKEN"]
)

# Read sheets
spreadsheet_id = "1wRDzNImkWSDmS5uZAgaECFO7X8HO2XO2f69FqQ1Qu7k"
sheet = client.open_by_key(spreadsheet_id)

def read_ws(ws_name: str) -> pd.DataFrame:
    try:
        return pd.DataFrame(sheet.worksheet(ws_name).get_all_records())
    except Exception:
        return pd.DataFrame()

roas_df = read_ws("ROAS")
man_df  = read_ws("Manual Control")

# ============== HELPERS ==============
def ymd(d): 
    if isinstance(d, datetime):
        d = d.date()
    return d.strftime("%Y-%m-%d")

def parse_account(ad_name: str) -> str:
    # Account = הספרה הראשונה לפני המקף הראשון
    # דוגמא: "3-ch83080_xxx_yyy_cat..." -> "3"
    if not isinstance(ad_name, str):
        return ""
    ad_name = ad_name.strip()
    if len(ad_name) >= 2 and ad_name[0].isdigit() and ad_name[1] == "-":
        return ad_name[0]
    # fallback עדין: חיפוש ריגקס
    import re
    m = re.match(r"^\s*(\d)-", ad_name)
    return m.group(1) if m else ""

def parse_channel_id(ad_name: str) -> str:
    # בין ה-'-' הראשון לבין ה'_' הראשון
    # "3-ch83080_domain_bm_cat..." -> "ch83080"
    if not isinstance(ad_name, str):
        return ""
    import re
    m = re.match(r"^\s*\d-([^_]+)", ad_name)
    return m.group(1) if m else ""

def parse_domain(ad_name: str) -> str:
    # הטוקן אחרי ה'_' הראשון
    import re
    if not isinstance(ad_name, str):
        return "UNKNOWN"
    m = re.match(r"^\s*\d-[^_]+_([^_]+)", ad_name)
    return m.group(1) if m else "UNKNOWN"

def parse_buying_method(ad_name: str) -> str:
    # הטוקן אחרי ה'_' השני
    import re
    if not isinstance(ad_name, str):
        return "UNKNOWN"
    m = re.match(r"^\s*\d-[^_]+_[^_]+_([^_]+)", ad_name)
    return m.group(1) if m else "UNKNOWN"

def parse_category(ad_name: str) -> str:
    # הטוקן אחרי ה'_' השלישי
    import re
    if not isinstance(ad_name, str):
        return "UNKNOWN"
    m = re.match(r"^\s*\d-[^_]+_[^_]+_[^_]+_([^_]+)", ad_name)
    return m.group(1) if m else "UNKNOWN"

def clean_roas_column(series: pd.Series) -> pd.Series:
    # מקבל ROAS שאולי כתוב "120%" וממיר ל-1.2
    return (
        series.astype(str)
        .str.replace("%", "", regex=False)
        .str.strip()
        .replace("", "0")
        .astype(float) / 100
    )

def format_roas(val):
    try:
        if pd.isna(val): 
            return ""
        val = float(val)
    except:
        return ""
    color = "#B31B1B" if val < 0.7 else "#FDC1C5" if val < 0.95 else "#FBEEAC" if val < 1.10 else "#93C572" if val < 1.4 else "#019529"
    return f"<div style='background-color:{color}; padding:4px 8px; border-radius:4px; text-align:center; color:black'><b>{val:.0%}</b></div>"

# ============== GUARDS ==============
if roas_df.empty:
    st.warning("ROAS sheet is empty or not accessible.")
    st.stop()

# Normalize base columns and types
for col in ["Date", "Ad Name", "Custom Channel ID", "ROAS", "Spend (USD)", "Revenue (USD)", "Profit (USD)"]:
    if col not in roas_df.columns:
        roas_df[col] = None

# parse numeric
roas_df["Spend (USD)"]   = pd.to_numeric(roas_df["Spend (USD)"], errors="coerce").fillna(0.0)
roas_df["Revenue (USD)"] = pd.to_numeric(roas_df["Revenue (USD)"], errors="coerce").fillna(0.0)
roas_df["Profit (USD)"]  = pd.to_numeric(roas_df["Profit (USD)"], errors="coerce").fillna(0.0)

# enrich from Ad Name by new naming convention
roas_df["Account"]         = roas_df["Ad Name"].apply(parse_account)
roas_df["Domain"]          = roas_df["Ad Name"].apply(parse_domain)
roas_df["Buying Method"]   = roas_df["Ad Name"].apply(parse_buying_method)
roas_df["Category"]        = roas_df["Ad Name"].apply(parse_category)

# In case Custom Channel ID is missing in ROAS, derive it (מומלץ שה־ETL ימלא מראש)
if "Custom Channel ID" in roas_df.columns:
    missing_ccid = roas_df["Custom Channel ID"].isna() | (roas_df["Custom Channel ID"].astype(str).str.strip() == "")
    roas_df.loc[missing_ccid, "Custom Channel ID"] = roas_df.loc[missing_ccid, "Ad Name"].apply(parse_channel_id)
else:
    roas_df["Custom Channel ID"] = roas_df["Ad Name"].apply(parse_channel_id)

# ============== DATE PICKER: SINGLE vs RANGE ==============
today = datetime.today().date()
view_mode = st.radio("Date scope", ["Single day", "Date range"], horizontal=True)

if view_mode == "Single day":
    date = st.date_input("Select Date", today)
    if isinstance(date, tuple):
        st.stop()
    date = pd.to_datetime(date).date()
    date_str      = ymd(date)
    prev_day_str  = ymd(date - timedelta(days=1))
    prev2_day_str = ymd(date - timedelta(days=2))

    df = roas_df[roas_df["Date"] == date_str].copy()
    if df.empty:
        st.warning("No data available for the selected date.")
        st.stop()

    show_dbf = True

else:
    preset = st.selectbox(
        "Quick ranges",
        ["Last 7 days", "Last 14 days", "Last 30 days", "This month", "Last month", "Custom"]
    )

    if preset == "This month":
        start = today.replace(day=1)
        end   = today
    elif preset == "Last month":
        first_this = today.replace(day=1)
        last_prev  = first_this - timedelta(days=1)
        start = last_prev.replace(day=1)
        end   = last_prev
    elif preset == "Last 7 days":
        start = today - timedelta(days=6)
        end   = today
    elif preset == "Last 14 days":
        start = today - timedelta(days=13)
        end   = today
    elif preset == "Last 30 days":
        start = today - timedelta(days=29)
        end   = today
    else:
        start_end = st.date_input("Pick date range", (today - timedelta(days=6), today))
        if not isinstance(start_end, (list, tuple)) or len(start_end) != 2:
            st.stop()
        start, end = start_end
        start = pd.to_datetime(start).date()
        end   = pd.to_datetime(end).date()

    start_str, end_str = ymd(start), ymd(end)
    df = roas_df[(roas_df["Date"] >= start_str) & (roas_df["Date"] <= end_str)].copy()
    if df.empty:
        st.warning("No data available for the selected range.")
        st.stop()

    show_dbf = False

# ============== CALCULATIONS (PER MODE) ==============
# Aggregate / attach DBF
if show_dbf:
    # DBF ו-2DBF לפי Custom Channel ID (יוניקי)
    roas_prev = roas_df[roas_df["Date"] == prev_day_str][
        ["Custom Channel ID", "ROAS"]
    ].rename(columns={"ROAS": "DBF"})

    roas_prev2 = roas_df[roas_df["Date"] == prev2_day_str][
        ["Custom Channel ID", "ROAS"]
    ].rename(columns={"ROAS": "2DBF"})

    # ניקוי מזהים למיזוג
    df["Custom Channel ID"] = df["Custom Channel ID"].astype(str).str.strip()
    roas_prev["Custom Channel ID"]  = roas_prev["Custom Channel ID"].astype(str).str.strip()
    roas_prev2["Custom Channel ID"] = roas_prev2["Custom Channel ID"].astype(str).str.strip()

    df = df.merge(roas_prev,  on=["Custom Channel ID"], how="left")
    df = df.merge(roas_prev2, on=["Custom Channel ID"], how="left")
else:
    # טווח ימים – סכימה לפי Ad Name + Channel (לשימור גרנולריות של מודעות שונות לאותו ערוץ, אם יהיו)
    group_cols = ["Ad Name", "Custom Channel ID", "Account", "Domain", "Buying Method", "Category"]
    df = (
        df.groupby(group_cols, as_index=False)[["Spend (USD)", "Revenue (USD)", "Profit (USD)"]]
          .sum()
    )
    df["DBF"]  = None
    df["2DBF"] = None

# לחשב ROAS מחודש (למקרה שהעמודה המקורית חסרה/טקסטואלית)
df["Spend (USD)"]   = pd.to_numeric(df["Spend (USD)"], errors="coerce").fillna(0.0)
df["Revenue (USD)"] = pd.to_numeric(df["Revenue (USD)"], errors="coerce").fillna(0.0)
df["Profit (USD)"]  = df["Revenue (USD)"] - df["Spend (USD)"]
df["ROAS"]          = df["Revenue (USD)"] / df["Spend (USD)"]
df["ROAS"]          = df["ROAS"].replace([float("inf"), -float("inf")], 0).fillna(0)

if show_dbf:
    df["DBF"]  = clean_roas_column(df["DBF"])
    df["2DBF"] = clean_roas_column(df["2DBF"])

# ============== MERGE MANUAL CONTROL (BUDGET/STATUS) ==============
# הכנה של עמודות נחוצות מהטאב
need_cols = ["Ad Name","Ad Set ID","Current Budget (ILS)","Current Status"]
for c in need_cols:
    if c not in man_df.columns:
        man_df[c] = None

man_df["Current Budget (ILS)"] = pd.to_numeric(man_df["Current Budget (ILS)"], errors="coerce").fillna(0.0)

df = df.merge(
    man_df[need_cols],
    on="Ad Name",
    how="left"
)

# עמודות "חדשות" נשלטות באפליקציה (לא מהשיטס)
df["Current Budget"] = df["Current Budget (ILS)"]
df["New Budget"]     = 0.0
df["New Status"]     = None

# ============== ENRICH (META FIELDS FROM AD NAME) IF NOT PRESENT ==============
for col, func in [
    ("Account", parse_account),
    ("Domain", parse_domain),
    ("Buying Method", parse_buying_method),
    ("Category", parse_category),
]:
    if col not in df.columns:
        df[col] = df["Ad Name"].apply(func)
    else:
        # מלא חוסרים (אם הגיע מה-merge עם סכימה)
        df[col] = df[col].fillna(df["Ad Name"].apply(func))

# ============== SUMMARY (TOP METRICS) ==============
st.markdown("---")
st.markdown("### Summary")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Spend",   f"${df['Spend (USD)'].sum():,.2f}")
col2.metric("Total Revenue", f"${df['Revenue (USD)'].sum():,.2f}")
col3.metric("Total Profit",  f"${df['Profit (USD)'].sum():,.2f}")
total_roas = df["Revenue (USD)"].sum() / df["Spend (USD)"].sum() if df["Spend (USD)"].sum() else 0
col4.metric("Total ROAS", f"{total_roas:.0%}")

# ============== FILTERS ROW ==============
st.subheader("Ad Set Control Panel")

# ארבעה פילטרים צרים + ספייסר
c_account, c_status, c_cat, c_dom, _spacer = st.columns([1, 1, 1, 1, 4])

with c_account:
    account_options = ["All"] + sorted([a for a in df["Account"].astype(str).unique() if a])
    selected_account = st.selectbox(
        "Filter by Account",
        account_options,
        index=0,
        key="filter_account"
    )

with c_status:
    status_filter = st.selectbox(
        "Filter by Ad Set Status",
        ["All", "ACTIVE only", "PAUSED only"],
        index=0,
        key="filter_status"
    )

# ↓ מחוץ ל-with כדי להריץ אחרי שה-DF מוכן
# בנה Status For Filter נכון: New Status אם קיים, אחרת Current Status
df["Status For Filter"] = df["New Status"]
df["Status For Filter"] = df["Status For Filter"].where(df["Status For Filter"].notna(), df["Current Status"])
df["Status For Filter"] = df["Status For Filter"].astype(str).str.upper().str.strip()
# נטרל ערכי טקסט "NONE" / "NAN" ריקים
df["Status For Filter"] = df["Status For Filter"].replace({"NONE": "", "NAN": ""})


with c_cat:
    category_options = ["All"] + sorted(df["Category"].dropna().astype(str).unique())
    selected_category = st.selectbox(
        "Filter by Category",
        category_options,
        index=0,
        key="filter_category"
    )

with c_dom:
    domain_options = ["All"] + sorted(df["Domain"].dropna().astype(str).unique())
    selected_domain = st.selectbox(
        "Filter by Domain",
        domain_options,
        index=0,
        key="filter_domain"
    )

# החלת הפילטרים
if selected_account != "All":
    df = df[df["Account"].astype(str) == str(selected_account)]

if status_filter == "ACTIVE only":
    df = df[df["Status For Filter"] == "ACTIVE"]
elif status_filter == "PAUSED only":
    df = df[df["Status For Filter"] == "PAUSED"]

if selected_category != "All":
    df = df[df["Category"] == selected_category]

if selected_domain != "All":
    df = df[df["Domain"] == selected_domain]

# ============== ROAS CELL FORMATTER ==============
def roas_cell(val):
    return format_roas(val)

# ============== TABLE HEADERS (DYNAMIC) ==============
if show_dbf:
    header_cols = st.columns([3, 0.8, 0.8, 0.8, 1, 1, 1, 1, 1, 1, 0.8, 1])
    headers = ["Ad Name", "Spend", "Revenue", "Profit", "ROAS", "DBF", "2DBF", "Current Budget", "New Budget", "New Status", "Action", "AdSet Status"]
else:
    header_cols = st.columns([3, 0.8, 0.8, 0.8, 1, 1, 1, 1, 0.8, 1])
    headers = ["Ad Name", "Spend", "Revenue", "Profit", "ROAS", "Current Budget", "New Budget", "New Status", "Action", "AdSet Status"]

for col, title in zip(header_cols, headers):
    col.markdown(f"**{title}**")

# ============== ROWS + ACTIONS ==============
batched_changes = []  # collect only changed rows

for i, row in df.iterrows():
    if show_dbf:
        cols = st.columns([3, 0.8, 0.8, 0.8, 1, 1, 1, 1, 1, 1, 0.8, 1])
    else:
        cols = st.columns([3, 0.8, 0.8, 0.8, 1, 1, 1, 1, 0.8, 1])

    # Base cells
    cols[0].markdown(row.get("Ad Name", ""))
    cols[1].markdown(f"${float(row.get('Spend (USD)', 0)):.2f}")
    cols[2].markdown(f"${float(row.get('Revenue (USD)', 0)):.2f}")
    cols[3].markdown(f"${float(row.get('Profit (USD)', 0)):.2f}")
    cols[4].markdown(roas_cell(row.get("ROAS", 0)), unsafe_allow_html=True)

    if show_dbf:
        cols[5].markdown(roas_cell(row.get("DBF", None)),  unsafe_allow_html=True)
        cols[6].markdown(roas_cell(row.get("2DBF", None)), unsafe_allow_html=True)
        cols[7].markdown(f"{float(row.get('Current Budget', 0)):.1f}")
        budget_col_i        = 8
        status_col_i        = 9
        action_col_i        = 10
        status_badge_col_i  = 11
    else:
        cols[5].markdown(f"{float(row.get('Current Budget', 0)):.1f}")
        budget_col_i        = 6
        status_col_i        = 7
        action_col_i        = 8
        status_badge_col_i  = 9

    # Inputs (New Budget / New Status) — באפליקציה בלבד
    try:
        default_budget = float(row.get("New Budget", 0)) if pd.notna(row.get("New Budget", 0)) else 0.0
    except:
        default_budget = 0.0

    new_budget = cols[budget_col_i].number_input(" ", value=default_budget, step=1.0,
                                                 key=f"budget_{i}", label_visibility="collapsed")

    cur_status = str(row.get("Current Status", "ACTIVE")).upper().strip()
    status_index = 0 if cur_status == "ACTIVE" else 1
    new_status = cols[status_col_i].selectbox(" ", options=["ACTIVE", "PAUSED"], index=status_index,
                                              key=f"status_{i}", label_visibility="collapsed")

    # Detect changes
    current_budget = float(row.get("Current Budget", 0) or 0)
    budget_changed = (new_budget > 0) and (abs(new_budget - current_budget) >= 0.5)
    status_changed = (new_status != cur_status)

    update_params = {}
    if budget_changed:
        # Facebook expects "minor units"
        update_params["daily_budget"] = int(round(new_budget * 100))
    if status_changed:
        update_params["status"] = new_status

    adset_id = str(row.get("Ad Set ID", "")).strip().replace("'", "")

    # Add to batch only if something changed
    if adset_id and update_params:
        batched_changes.append({
            "adset_id": adset_id,
            "ad_name": row.get("Ad Name", ""),
            "params": update_params
        })

    # Row-level Apply
    if cols[action_col_i].button("Apply", key=f"apply_{i}"):
        try:
            if adset_id and update_params:
                AdSet(adset_id).api_update(params=update_params)
                st.success(f"✔️ Updated {row.get('Ad Name','')}")
            else:
                st.warning(f"⚠️ No valid updates for {row.get('Ad Name','')}")
        except Exception as e:
            st.error(f"❌ Failed to update {row.get('Ad Name','')}: {e}")

    # Status badge
    status = new_status if status_changed else cur_status
    color = "#D4EDDA" if status == "ACTIVE" else "#5c5b5b" if status == "PAUSED" else "#666666"
    cols[status_badge_col_i].markdown(
        f"<div style='background-color:{color}; padding:4px 8px; border-radius:4px; text-align:center; color:black'><b>{status}</b></div>",
        unsafe_allow_html=True
    )

# ============== TOTALS ROW ==============
sum_spend  = float(df["Spend (USD)"].sum())
sum_rev    = float(df["Revenue (USD)"].sum())
sum_profit = float(df["Profit (USD)"].sum())
sum_roas   = (sum_rev / sum_spend) if sum_spend else 0

st.markdown("—")  # thin divider

if show_dbf:
    sum_cols = st.columns([2, 1, 1, 1, 1, 1, 1, 1.2, 1.2, 1, 0.8, 1])
else:
    sum_cols = st.columns([2, 1, 1, 1, 1, 1.2, 1.2, 1, 0.8, 1])

sum_cols[0].markdown("**Total (filtered)**")
sum_cols[1].markdown(f"**${sum_spend:,.2f}**")
sum_cols[2].markdown(f"**${sum_rev:,.2f}**")
sum_cols[3].markdown(f"**${sum_profit:,.2f}**")
sum_cols[4].markdown(format_roas(sum_roas), unsafe_allow_html=True)
for idx in range(5, len(sum_cols)):
    sum_cols[idx].markdown("")

# ============== APPLY ALL (BATCH) ==============
st.markdown("---")
with st.container():
    left, right = st.columns([3, 1])
    with left:
        st.caption(f"{len(batched_changes)} change(s) ready to apply")
        with st.expander("Show pending changes"):
            st.write([
                {"ad_name": x["ad_name"], **x["params"]}
                for x in batched_changes
            ])
    with right:
        if st.button("Apply All Changes"):
            successes, failures = 0, 0
            for upd in batched_changes:
                try:
                    AdSet(upd["adset_id"]).api_update(params=upd["params"])
                    successes += 1
                except Exception as e:
                    failures += 1
                    st.error(f"❌ {upd['ad_name']}: {e}")
            if successes:
                st.success(f"✔️ Applied {successes} update(s)")
            if failures:
                st.warning(f"⚠️ {failures} update(s) failed")

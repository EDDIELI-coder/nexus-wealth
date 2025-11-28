import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import gspread
from google.oauth2.service_account import Credentials
from datetime import date
from streamlit import runtime
import os
import sys
import json

# --- 1. 系統設定 ---
st.set_page_config(page_title="NEXUS: Wealth Command", layout="wide", page_icon="🌌")

# CSS 樣式
st.markdown("""
    <style>
    /* 全局字體設定 */
    h1, h2, h3, h4, h5, h6, p, label, li, td, th, .stDataFrame, .stTable {
        font-family: "Roboto", "Microsoft JhengHei", sans-serif !important;
        line-height: 1.6 !important;
        letter-spacing: 0.5px;
    }
    
    /* 修正下拉選單高度 */
    .stSelectbox div[data-baseweb="select"] > div { min-height: 45px; }
    
    /* 卡片樣式 */
    .nexus-card {
        background-color: #1a1a1a; border: 1px solid #333; border-radius: 10px;
        padding: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.5);
        height: 140px; display: flex; flex-direction: column; justify-content: center;
    }
    .nexus-label { color: #aaa; font-size: 16px; font-weight: 700; margin-bottom: 8px; }
    .nexus-value { color: #00F0FF; font-size: 32px; font-weight: 700; text-shadow: 0 0 10px rgba(0,240,255,0.3); }
    .nexus-value-red { color: #ff4b4b !important; font-size: 32px; font-weight: 700; text-shadow: 0 0 10px rgba(255, 75, 75, 0.3); }
    .nexus-value-orange { color: #ffa500 !important; font-size: 32px; font-weight: 700; text-shadow: 0 0 10px rgba(255, 165, 0, 0.3); }
    
    /* 自訂總值顯示樣式 */
    .cat-val-label { font-size: 14px; color: #aaa; font-weight: bold; margin-bottom: 0px; }
    .cat-val-num { font-size: 36px; font-weight: bold; color: #00F0FF; text-shadow: 0 0 8px rgba(0,240,255,0.2); line-height: 1.2; }
    .cat-val-num-red { font-size: 36px; font-weight: bold; color: #ff4b4b; text-shadow: 0 0 8px rgba(255, 75, 75, 0.2); line-height: 1.2; }

    /* 按鈕樣式 */
    div.stButton > button {
        width: 100%; min-height: 45px; border-radius: 8px; border: 1px solid #444;
        background: linear-gradient(145deg, #222, #181818); transition: all 0.3s;
    }
    div.stButton > button:hover { border-color: #00F0FF; transform: translateY(-2px); }
    
    hr { margin: 1.5em 0; border-color: #444; }
    section[data-testid="stSidebar"] { background-color: #0e0e0e; border-right: 1px solid #222; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 雲端資料庫核心 (效能優化版) ---

ADMIN_DB_NAME = "nexus_data"
EXCHANGE_RATE = 32.5 

# 【關鍵優化】加入快取 (Cache)，避免每次動作都重新連線 Google，大幅提升速度並減少錯誤
@st.cache_resource(ttl=600) # 快取 10 分鐘
def get_google_client():
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive'
    ]
    try:
        if "gcp_service_account" not in st.secrets:
            st.error("❌ 找不到 Secrets 設定。")
            return None

        creds_dict = dict(st.secrets["gcp_service_account"])
        if "private_key" in creds_dict:
            key = creds_dict["private_key"]
            if "\\n" in key: key = key.replace("\\n", "\n")
            creds_dict["private_key"] = key

        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"🔥 連線錯誤: {e}")
        return None

def check_login(username, password):
    try:
        client = get_google_client()
        if not client: return None
        sh = client.open(ADMIN_DB_NAME)
        ws = sh.worksheet("Users")
        users_data = ws.get_all_records()
        for user in users_data:
            if str(user.get('Username')).strip() == str(username).strip() and \
               str(user.get('Password')).strip() == str(password).strip():
                return str(user.get('Target_Sheet'))
        return None
    except: return None

def init_user_sheet(target_sheet_name):
    client = get_google_client()
    if not client: return None
    try:
        sh = client.open(target_sheet_name)
    except:
        st.error(f"❌ 找不到試算表：{target_sheet_name}")
        st.stop()
    
    required = {
        "US_Stocks": ["代號", "名稱", "股數", "類別", "自訂價格", "參考市價"],
        "TW_Stocks": ["代號", "名稱", "股數", "類別", "自訂價格", "參考市價"],
        "Fixed_Assets": ["資產項目", "現值", "類別"],
        "Liabilities": ["負債項目", "金額", "每月扣款"],
        "Settings": ["Key", "Value"],
        "History": ["Date", "Net_Worth", "Total_Assets", "Total_Liabilities", "Monthly_Payment"]
    }
    try:
        curr_titles = [ws.title for ws in sh.worksheets()]
        for title, headers in required.items():
            if title not in curr_titles:
                ws = sh.add_worksheet(title=title, rows=50, cols=10)
                ws.append_row(headers)
    except: pass
    return sh

# --- 3. 資料邏輯 ---

def load_data_from_cloud(target_sheet):
    try:
        sh = init_user_sheet(target_sheet)
        if not sh: return

        def read_ws(title, cols):
            try:
                data = sh.worksheet(title).get_all_records()
                df = pd.DataFrame(data)
                for c in cols:
                    if c not in df.columns: df[c] = ""
                return df
            except: return pd.DataFrame(columns=cols)

        st.session_state.us_data = read_ws("US_Stocks", ["代號", "名稱", "股數", "類別", "自訂價格", "參考市價"])
        st.session_state.tw_data = read_ws("TW_Stocks", ["代號", "名稱", "股數", "類別", "自訂價格", "參考市價"])
        st.session_state.fixed_data = read_ws("Fixed_Assets", ["資產項目", "現值", "類別"])
        st.session_state.liab_data = read_ws("Liabilities", ["負債項目", "金額", "每月扣款"])
        
        settings_df = read_ws("Settings", ["Key", "Value"])
        settings = dict(zip(settings_df['Key'], settings_df['Value'])) if not settings_df.empty else {}
        st.session_state.saved_expense = float(settings.get("expense", 850000))
        st.session_state.saved_age = int(settings.get("age", 27))
        st.session_state.saved_savings = float(settings.get("savings", 325000))
        st.session_state.saved_return = float(settings.get("return_rate", 11.0))
        st.session_state.data_loaded = True
    except Exception as e: st.error(f"資料讀取錯誤: {e}")

def save_data_to_cloud(target_sheet):
    try:
        sh = init_user_sheet(target_sheet)
        if not sh: return

        def write_ws(title, df):
            try:
                ws = sh.worksheet(title)
                ws.clear()
                
                df_clean = df.copy()
                num_cols = ["股數", "現值", "金額", "自訂價格", "參考市價", "每月扣款"]
                for c in num_cols:
                    if c in df_clean.columns:
                        df_clean[c] = pd.to_numeric(df_clean[c], errors='coerce').fillna(0)

                if "代號" in df_clean.columns:
                    df_clean = df_clean[
                        (df_clean["代號"].astype(str).str.strip() != "") & 
                        (df_clean["代號"].astype(str).str.strip().lower() != "nan") &
                        (df_clean["代號"].astype(str).str.strip() != "0")
                    ]
                elif "資產項目" in df_clean.columns:
                    df_clean = df_clean[df_clean["資產項目"].astype(str).str.strip() != ""]
                elif "負債項目" in df_clean.columns:
                    df_clean = df_clean[df_clean["負債項目"].astype(str).str.strip() != ""]

                if not df_clean.empty:
                    df_clean = df_clean.fillna("")
                    ws.update([df_clean.columns.values.tolist()] + df_clean.values.tolist())
                else: 
                    ws.update([df.columns.values.tolist()])
            except Exception as e:
                print(f"Write Error {title}: {e}")

        write_ws("US_Stocks", pd.DataFrame(st.session_state.us_data))
        write_ws("TW_Stocks", pd.DataFrame(st.session_state.tw_data))
        write_ws("Fixed_Assets", pd.DataFrame(st.session_state.fixed_data))
        write_ws("Liabilities", pd.DataFrame(st.session_state.liab_data))
        
        settings_data = pd.DataFrame([
            {"Key": "expense", "Value": st.session_state.saved_expense},
            {"Key": "age", "Value": st.session_state.saved_age},
            {"Key": "savings", "Value": st.session_state.saved_savings},
            {"Key": "return_rate", "Value": st.session_state.saved_return}
        ])
        write_ws("Settings", settings_data)
        st.toast("✅ 雲端同步完成", icon="☁️")
        
    except Exception as e: st.error(f"存檔失敗: {e}")

def save_daily_record_cloud(target_sheet, net_worth, assets, liabilities, monthly_payment):
    today = str(date.today())
    try:
        sh = init_user_sheet(target_sheet)
        if not sh: return
        ws = sh.worksheet("History")
        try:
            records = ws.get_all_records()
            df = pd.DataFrame(records)
            if not df.empty and str(today) in df['Date'].astype(str).values: return
        except: pass
        ws.append_row([today, net_worth, assets, liabilities, monthly_payment])
    except: pass

def get_precise_price(ticker):
    try:
        if not ticker: return 0
        stock = yf.Ticker(str(ticker).strip())
        price = 0.0
        if hasattr(stock, 'fast_info'): price = stock.fast_info.get('last_price', 0.0)
        if price == 0: price = stock.info.get('regularMarketPrice', 0.0)
        if price == 0:
            hist = stock.history(period="1d")
            if not hist.empty: price = hist['Close'].iloc[-1]
        return float(price)
    except: return 0.0

def update_portfolio_data(df, category_default):
    df = pd.DataFrame(df)
    if df.empty: return df
    
    if "股數" in df.columns:
        df["股數"] = pd.to_numeric(df["股數"], errors='coerce').fillna(0)
    
    with st.status(f"🚀 更新 {category_default}...", expanded=True) as status:
        for index, row in df.iterrows():
            ticker = str(row.get("代號", "")).strip().upper()
            if not ticker or ticker == "NAN" or ticker == "NONE": continue
            status.update(label=f"下載: {ticker}...", state="running")
            price = get_precise_price(ticker)
            if price > 0: df.at[index, "參考市價"] = price
            
            if pd.isna(row.get("名稱")) or str(row.get("名稱")) == "":
                try: df.at[index, "名稱"] = yf.Ticker(ticker).info.get('shortName', ticker)
                except: pass
            if pd.isna(row.get("類別")) or str(row.get("類別")) == "":
                df.at[index, "類別"] = category_default
        status.update(label="✅ 完成", state="complete", expanded=False)
    return df

def parse_file(uploaded_file, import_type):
    try:
        if uploaded_file.name.endswith('.csv'): 
            try: df = pd.read_csv(uploaded_file, encoding='utf-8')
            except: df = pd.read_csv(uploaded_file, encoding='cp950')
        elif uploaded_file.name.endswith(('.xls', '.xlsx')): df = pd.read_excel(uploaded_file)
        else: return None, "格式不支援"

        df.columns = [str(c).lower().strip() for c in df.columns]
        new_data = []
        if import_type in ["stock_us", "stock_tw"]:
            ticker_col = next((c for c in df.columns if c in ['ticker', 'symbol', '代號', '股票代號']), None)
            shares_col = next((c for c in df.columns if c in ['shares', 'quantity', '股數', '數量', 'qty']), None)
            price_col = next((c for c in df.columns if c in ['price', 'cost', '自訂價格', '成本']), None)
            if not ticker_col or not shares_col: return None, "缺少 [代號] 或 [股數]"
            df[ticker_col] = df[ticker_col].astype(str).str.strip().str.upper()
            df[shares_col] = pd.to_numeric(df[shares_col], errors='coerce').fillna(0)
            for _, row in df.iterrows():
                new_data.append({
                    "代號": row[ticker_col], "名稱": "", 
                    "股數": float(row[shares_col]),
                    "類別": "美股" if import_type == "stock_us" else "台股",
                    "自訂價格": float(row[price_col]) if price_col else 0.0, "參考市價": 0.0
                })
        elif import_type == "fixed":
            name_col = next((c for c in df.columns if c in ['item', 'name', '資產項目', '名稱']), None)
            val_col = next((c for c in df.columns if c in ['value', 'amount', '現值', '金額']), None)
            if not name_col or not val_col: return None, "缺少 [資產項目] 或 [現值]"
            for _, row in df.iterrows():
                new_data.append({"資產項目": row[name_col], "現值": float(row[val_col]), "類別": "固定資產"})
        elif import_type == "liab":
            name_col = next((c for c in df.columns if c in ['item', 'name', '負債項目', '名稱']), None)
            amount_col = next((c for c in df.columns if c in ['amount', '金額']), None)
            monthly_col = next((c for c in df.columns if c in ['monthly', 'payment', '每月扣款']), None)
            if not name_col or not amount_col: return None, "缺少 [負債項目] 或 [金額]"
            for _, row in df.iterrows():
                m_val = float(row[monthly_col]) if monthly_col else 0.0
                new_data.append({"負債項目": row[name_col], "金額": float(row[amount_col]), "每月扣款": m_val})
        return pd.DataFrame(new_data), None
    except Exception as e: return None, str(e)

def calculate_fire_curves_advanced(current_age, investable_assets, house_value, savings, invest_return, house_growth, inflation, custom_expense, include_house_growth):
    ages = list(range(current_age, 66))
    curr_invest = investable_assets
    curr_house = house_value
    wealth_curve = [curr_invest + curr_house]
    levels = {"Lean": 600000, "Barista": 800000, "Regular": 1000000, "Fat": 2500000}
    level_curves = {k: [v * 25] for k, v in levels.items()}
    custom_target = [custom_expense * 25]
    curr_levels = {k: v * 25 for k, v in levels.items()}
    curr_custom = custom_expense * 25
    for _ in range(len(ages) - 1):
        curr_invest = (curr_invest + savings) * (1 + invest_return/100)
        if include_house_growth and curr_house > 0: curr_house = curr_house * (1 + house_growth/100)
        wealth_curve.append(curr_invest + curr_house)
        for k in curr_levels:
            curr_levels[k] *= (1 + inflation/100)
            level_curves[k].append(curr_levels[k])
        curr_custom *= (1 + inflation/100)
        custom_target.append(curr_custom)
    return ages, wealth_curve, level_curves, custom_target

def predict_portfolio_return_detail(df_assets, include_house):
    if df_assets.empty: return 5.0, "無資產"
    returns_map = {"美股": 10.0, "台股": 8.0, "虛擬貨幣": 25.0, "現金": 1.0, "房產": 3.0, "固定資產": 3.0}
    df_calc = df_assets.copy()
    msg_prefix = "⚠️ **AI 計算模式：含房產**" if include_house else "✅ **AI 計算模式：排除房產**"
    if not include_house:
        df_calc = df_calc[~df_calc['類別'].str.contains('房產|固定|地產', na=False)]
    total_val = df_calc["價值"].sum()
    if total_val == 0: return 5.0, "無有效資產可計算"
    weighted_return = 0.0
    explanation = [f"**{msg_prefix}**"]
    grouped = df_calc.groupby("類別")["價值"].sum()
    for cat, val in grouped.items():
        r = 3.0
        for k, v in returns_map.items():
            if k in str(cat): r = v; break
        weight = val / total_val
        weighted_return += r * weight
        explanation.append(f"• **{cat}**: 佔比 {weight*100:.1f}% x 預期 {r}%")
    return round(weighted_return, 2), "\n".join(explanation)

def login_page():
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("<h1 style='text-align: center;'>🔐 NEXUS Login</h1>", unsafe_allow_html=True)
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Access System 🚀")
            if submitted:
                target_sheet = check_login(username, password)
                if target_sheet:
                    st.session_state.logged_in = True
                    st.session_state.current_user = username
                    st.session_state.target_sheet = target_sheet
                    st.rerun()
                else: st.error("Access Denied.")

def main_app():
    with st.sidebar:
        st.info(f"👤 User: **{st.session_state.current_user}**")
        privacy_mode = st.toggle("👁️ **隱私模式**", value=False)
        st.divider()
        if st.button("☁️ **同步存檔**", type="primary"): save_data_to_cloud(st.session_state.target_sheet)
        st.divider()
        if st.button("🚪 登出系統"):
            st.session_state.clear()
            st.rerun()

    def fmt_money(val): return "****" if privacy_mode else f"${val:,.0f}"

    if not st.session_state.get('data_loaded'):
        with st.spinner("正在從雲端載入您的資產數據..."):
            load_data_from_cloud(st.session_state.target_sheet)

    st.title(f"🌌 NEXUS: {st.session_state.current_user}'s Command")
    if 'fire_states' not in st.session_state: st.session_state.fire_states = {"Lean": True, "Barista": True, "Regular": True, "Fat": True}
    
    def ensure_cols(df, cols):
        if df.empty: return pd.DataFrame(columns=cols)
        for c in cols:
            if c not in df.columns:
                df[c] = 0 if c in ["金額", "每月扣款", "現值", "股數"] else ""
        return df

    df_us = ensure_cols(pd.DataFrame(st.session_state.us_data), ["代號", "名稱", "股數", "類別", "自訂價格", "參考市價"])
    df_tw = ensure_cols(pd.DataFrame(st.session_state.tw_data), ["代號", "名稱", "股數", "類別", "自訂價格", "參考市價"])
    df_fixed = ensure_cols(pd.DataFrame(st.session_state.fixed_data), ["資產項目", "現值", "類別"])
    df_liab = ensure_cols(pd.DataFrame(st.session_state.liab_data), ["負債項目", "金額", "每月扣款"])

    assets_list = []
    if not df_us.empty:
        for _, row in df_us.iterrows():
            p = float(row.get("自訂價格", 0) or 0)
            if p <= 0: p = float(row.get("參考市價", 0) or 0)
            v = p * float(row.get("股數", 0) or 0) * EXCHANGE_RATE
            code = str(row.get("代號", "")).strip()
            if code and code != "None" and v > 0:
                disp_name = code
                assets_list.append({"資產": disp_name, "類別": row.get("類別","美股"), "價值": v})
    
    if not df_tw.empty:
        for _, row in df_tw.iterrows():
            p = float(row.get("自訂價格", 0) or 0)
            if p <= 0: p = float(row.get("參考市價", 0) or 0)
            v = p * float(row.get("股數", 0) or 0)
            code = str(row.get("代號", "")).strip()
            if code and code != "None" and v > 0:
                disp_name = code
                assets_list.append({"資產": disp_name, "類別": row.get("類別","台股"), "價值": v})
    
    if not df_fixed.empty:
        for _, row in df_fixed.iterrows():
            name = str(row.get("資產項目", "")).strip()
            v = float(row.get("現值", 0) or 0)
            if name and name != "None" and v > 0:
                assets_list.append({"資產": name, "類別": row.get("類別","固定"), "價值": v})

    df_assets = pd.DataFrame(assets_list)
    if df_assets.empty:
        df_assets = pd.DataFrame(columns=["資產", "類別", "價值"])
        total_assets = 0
    else:
        total_assets = df_assets["價值"].sum()
    
    total_liab = pd.to_numeric(df_liab["金額"], errors='coerce').fillna(0).sum() if not df_liab.empty else 0
    total_monthly = pd.to_numeric(df_liab["每月扣款"], errors='coerce').fillna(0).sum() if not df_liab.empty else 0
    
    net_worth = total_assets - total_liab

    save_daily_record_cloud(st.session_state.target_sheet, net_worth, total_assets, total_liab, total_monthly)

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown(f"""<div class="nexus-card"><div class="nexus-label">💰 淨資產 (Net Worth)</div><div class="nexus-value">{fmt_money(net_worth)}</div></div>""", unsafe_allow_html=True)
    with c2: st.markdown(f"""<div class="nexus-card"><div class="nexus-label">🏦 總資產 (Total Assets)</div><div class="nexus-value">{fmt_money(total_assets)}</div></div>""", unsafe_allow_html=True)
    with c3: st.markdown(f"""<div class="nexus-card"><div class="nexus-label">💳 總負債 (Liabilities)</div><div class="nexus-value-red">{fmt_money(total_liab)}</div></div>""", unsafe_allow_html=True)
    with c4: st.markdown(f"""<div class="nexus-card"><div class="nexus-label">💸 月支出 (Burn Rate)</div><div class="nexus-value-orange">{fmt_money(total_monthly)}</div></div>""", unsafe_allow_html=True)

    st.divider()
    tab_edit, tab_fire, tab_vis, tab_hist = st.tabs(["📝 **Asset Editor**", "🔥 **FIRE Analytics**", "📊 **Visuals**", "📈 **History**"])

    with tab_edit:
        c_btn, _ = st.columns([1, 4])
        with c_btn:
            if st.button("⚡ **UPDATE PRICES (更新股價)**", type="primary"):
                st.session_state.us_data = update_portfolio_data(st.session_state.us_data, "美股").to_dict('records')
                st.session_state.tw_data = update_portfolio_data(st.session_state.tw_data, "台股").to_dict('records')
                save_data_to_cloud(st.session_state.target_sheet)
                st.rerun()

        with st.expander("📂 **Smart Import (匯入 Excel/CSV)**"):
            import_type = st.selectbox("匯入類型", ["🇺🇸 美股/Crypto", "🇹🇼 台股", "🏠 固定資產", "💳 負債"])
            f = st.file_uploader("檔案上傳", type=['csv','xlsx'])
            if f and st.button("確認匯入"):
                map_t = {"🇺🇸 美股/Crypto":"stock_us", "🇹🇼 台股":"stock_tw", "🏠 固定資產":"fixed", "💳 負債":"liab"}
                target_k = {"stock_us":"us_data", "stock_tw":"tw_data", "fixed":"fixed_data", "liab":"liab_data"}[map_t[import_type]]
                df_new, err = parse_file(f, map_t[import_type])
                if df_new is not None:
                    st.session_state[target_k] = df_new.to_dict('records')
                    save_data_to_cloud(st.session_state.target_sheet)
                    st.success("匯入成功！")
                    st.rerun()
                else: st.error(err)

        def show_editor(title, key, cols, rate=1.0, is_liability=False):
            with st.container(border=True):
                st.markdown(f"#### {title}")
                
                df = pd.DataFrame(st.session_state[key])
                if df.empty: df = pd.DataFrame(columns=cols)
                
                for c in df.columns:
                    if c in ["股數", "現值", "金額", "自訂價格", "參考市價", "每月扣款"]:
                        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
                    else:
                        df[c] = df[c].astype(str).replace("nan", "")

                total_cat_val = 0
                vals = []
                if "股數" in df.columns:
                    for _, r in df.iterrows():
                        p = float(r.get("自訂價格",0))
                        if p<=0: p = float(r.get("參考市價",0))
                        v = p * float(r.get("股數",0)) * rate
                        vals.append(v)
                    df["總價值(TWD)"] = vals
                    total_cat_val = sum(vals)
                    
                    if total_cat_val > 0:
                        df["佔比 (%)"] = df["總價值(TWD)"] / total_cat_val
                    else:
                        df["佔比 (%)"] = 0
                elif "現值" in df.columns:
                    df["總價值(TWD)"] = pd.to_numeric(df["現值"], errors='coerce').fillna(0)
                    total_cat_val = df["總價值(TWD)"].sum()
                    if total_cat_val > 0:
                         df["佔比 (%)"] = df["總價值(TWD)"] / total_cat_val
                    else:
                        df["佔比 (%)"] = 0
                elif "金額" in df.columns:
                    df["總價值(TWD)"] = pd.to_numeric(df["金額"], errors='coerce').fillna(0)
                    total_cat_val = df["總價值(TWD)"].sum()
                    if total_cat_val > 0:
                         df["佔比 (%)"] = df["總價值(TWD)"] / total_cat_val
                    else:
                        df["佔比 (%)"] = 0

                df["❌"] = False
                
                preferred_order = ["❌", "代號", "名稱", "股數", "類別", "自訂價格", "參考市價", "資產項目", "現值", "負債項目", "金額", "每月扣款", "總價值(TWD)", "佔比 (%)"]
                final_cols = [c for c in preferred_order if c in df.columns]
                remaining = [c for c in df.columns if c not in final_cols]
                df = df[final_cols + remaining]

                num_class = "cat-val-num-red" if is_liability else "cat-val-num"
                val_str = "****" if privacy_mode else f"${total_cat_val:,.0f}"
                
                st.markdown(f"""<div><p class='cat-val-label'>類別總值 (TWD)</p><p class='{num_class}'>{val_str}</p></div>""", unsafe_allow_html=True)

                cfg = {}
                if privacy_mode:
                    df.loc[:, df.columns != "❌"] = "****"
                    cfg = {c: st.column_config.Column(disabled=True) for c in df.columns}
                    cfg["❌"] = st.column_config.CheckboxColumn(disabled=True)
                else:
                    cfg = {
                        "總價值(TWD)": st.column_config.NumberColumn(label="總價值(TWD)", format="$%d", disabled=True),
                        "佔比 (%)": st.column_config.ProgressColumn(label="佔比 (%)", format="%.1f%%", min_value=0.0, max_value=1.0), 
                        "❌": st.column_config.CheckboxColumn(label="❌", width="small", help="勾選後刪除"),
                        "代號": st.column_config.TextColumn(label="代號", width="small"),
                        "名稱": st.column_config.TextColumn(label="名稱", width="medium"),
                        "股數": st.column_config.NumberColumn(label="股數", format="%.4f"),
                        "類別": st.column_config.TextColumn(label="類別", width="small"),
                        "自訂價格": st.column_config.NumberColumn(label="自訂價格", format="%.2f"),
                        "參考市價": st.column_config.NumberColumn(label="參考市價", format="%.2f", disabled=False),
                        "資產項目": st.column_config.TextColumn(label="資產項目", width="medium"),
                        "現值": st.column_config.NumberColumn(label="現值", format="$%d"),
                        "負債項目": st.column_config.TextColumn(label="負債項目", width="medium"),
                        "金額": st.column_config.NumberColumn(label="金額", format="$%d"),
                        "每月扣款": st.column_config.NumberColumn(label="每月扣款", format="$%d")
                    }
                
                edited = st.data_editor(
                    df, 
                    num_rows="fixed",
                    key=f"e_{key}", 
                    column_config=cfg,
                    column_order=list(df.columns),
                    use_container_width=True
                )

                # 【關鍵優化】批次新增
                col_n, col_btn = st.columns([1, 2])
                rows_to_add = col_n.number_input("行數", min_value=1, max_value=20, value=1, key=f"num_{key}", label_visibility="collapsed")
                
                if col_btn.button(f"➕ 新增 {rows_to_add} 筆", key=f"add_{key}"):
                    new_row = {c: "" for c in cols}
                    if "類別" in cols: 
                        if "us" in key: new_row["類別"] = "美股"
                        elif "tw" in key: new_row["類別"] = "台股"
                        elif "fixed" in key: new_row["類別"] = "固定"
                    
                    current_data = st.session_state[key]
                    if isinstance(current_data, pd.DataFrame):
                        current_data = current_data.to_dict('records')
                    
                    # 批次追加
                    for _ in range(rows_to_add):
                        current_data.append(new_row.copy())
                        
                    st.session_state[key] = current_data
                    st.rerun()

                if not privacy_mode:
                    if edited["❌"].any():
                        edited = edited[~edited["❌"]]
                        cols_to_save = [c for c in edited.columns if c not in ["總價值(TWD)", "佔比 (%)", "❌"]]
                        st.session_state[key] = edited[cols_to_save].to_dict('records')
                        st.toast("已刪除項目")
                        st.rerun()
                    else:
                        cols_to_save = [c for c in edited.columns if c not in ["總價值(TWD)", "佔比 (%)", "❌"]]
                        st.session_state[key] = edited[cols_to_save].to_dict('records')

        c1, c2 = st.columns(2)
        with c1: show_editor("🇺🇸 美股/虛擬貨幣 (US Stocks & Crypto)", "us_data", ["代號","名稱","股數","類別","自訂價格","參考市價"], EXCHANGE_RATE)
        with c2: show_editor("🇹🇼 台股 (TW Stocks)", "tw_data", ["代號","名稱","股數","類別","自訂價格","參考市價"], 1.0)
        c3, c4 = st.columns(2)
        with c3: show_editor("🏠 固定資產", "fixed_data", ["資產項目","現值","類別"])
        with c4: show_editor("💳 負債", "liab_data", ["負債項目","金額","每月扣款"], is_liability=True)

    with tab_fire:
        c_f1, c_f2 = st.columns([1, 2])
        with c_f1:
            st.subheader("參數設定")
            include_house = st.checkbox("納入房產計算", value=True)
            if st.button("🤖 AI 分析預期報酬率"):
                r, exp = predict_portfolio_return_detail(df_assets, include_house)
                st.session_state.saved_return = r
                st.info(exp)
            my_return = st.slider("年化報酬率 (%)", 0.0, 20.0, float(st.session_state.saved_return), 0.1)
            my_expense = st.number_input("目標年支出", value=float(st.session_state.saved_expense), step=10000.0)
            my_age = st.number_input("目前年齡", value=int(st.session_state.saved_age))
            my_savings = st.number_input("年儲蓄金額", value=float(st.session_state.saved_savings), step=10000.0)
            if my_return != st.session_state.saved_return or my_expense != st.session_state.saved_expense:
                st.session_state.saved_return = my_return
                st.session_state.saved_expense = my_expense
                st.session_state.saved_age = my_age
                st.session_state.saved_savings = my_savings
        with c_f2:
            st.subheader("資產累積預測")
            if not df_assets.empty:
                base_wealth = net_worth if include_house else (net_worth - df_assets[df_assets['類別'].str.contains('房產|固定', na=False)]['價值'].sum())
                house_part = df_assets[df_assets['類別'].str.contains('房產|固定', na=False)]['價值'].sum() if include_house else 0
            else:
                base_wealth = 0
                house_part = 0

            ages, wealth_c, fire_c, custom_c = calculate_fire_curves_advanced(
                my_age, base_wealth - house_part, house_part, my_savings, my_return, 3.0, 3.0, my_expense, include_house
            )
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=ages, y=wealth_c, name="預測資產", line=dict(color='#00F0FF', width=4)))
            fig.add_trace(go.Scatter(x=ages, y=custom_c, name="FIRE 目標", line=dict(color='#FFD166', dash='dot')))
            fig.update_layout(template="plotly_dark", height=500, xaxis_title="年齡", yaxis_title="資產 (TWD)")
            st.plotly_chart(fig, use_container_width=True)

    with tab_vis:
        if not df_assets.empty:
            c_v1, c_v2 = st.columns([1, 1])
            with c_v1:
                st.subheader("資產分佈")
                fig = px.sunburst(df_assets, path=['類別', '資產'], values='價值', color='類別')
                fig.update_traces(textinfo="label+percent root", insidetextorientation='horizontal')
                fig.update_layout(
                    template="plotly_dark",
                    margin=dict(t=20, l=20, r=20, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)
            with c_v2:
                st.subheader("持倉排行")
                df_show = df_assets.copy()
                total_val = df_show["價值"].sum()
                df_show["佔比 (%)"] = (df_show["價值"] / total_val * 100)
                df_show = df_show.sort_values("價值", ascending=False)
                
                if privacy_mode: 
                    df_show['價值'] = "****"
                    df_show['佔比 (%)'] = 0
                
                st.dataframe(
                    df_show, 
                    use_container_width=True, 
                    hide_index=True,
                    column_config={
                        "資產": st.column_config.TextColumn("資產代號", width="small"),
                        "類別": st.column_config.TextColumn("類別", width="small"),
                        "價值": st.column_config.NumberColumn("總價值 (TWD)", format="$%d"),
                        "佔比 (%)": st.column_config.ProgressColumn(
                            "佔比 (%)", 
                            format="%.1f%%", 
                            min_value=0, 
                            max_value=100
                        ),
                    }
                )

    with tab_hist:
        st.subheader("資產成長紀錄 (Cloud History)")
        try:
            sh = init_user_sheet(st.session_state.target_sheet)
            data = sh.worksheet("History").get_all_records()
            if data:
                df_hist = pd.DataFrame(data)
                fig = px.line(df_hist, x='Date', y='Net_Worth', title="淨資產趨勢", markers=True)
                fig.update_layout(template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
            else: st.info("尚無歷史紀錄，明日將自動生成第一筆。")
        except: st.warning("讀取歷史紀錄時發生錯誤")

if __name__ == "__main__":
    if "logged_in" not in st.session_state: st.session_state.logged_in = False
    if st.session_state.logged_in: main_app()
    else: login_page()

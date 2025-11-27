import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import os
import sys
import json
from datetime import date
from streamlit import runtime

# --- Google Sheets 雲端連線套件 ---
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. 系統設定 ---
st.set_page_config(page_title="NEXUS: Wealth Command", layout="wide", page_icon="🌌")

# CSS 樣式 (保留你原本的設計)
st.markdown("""
    <style>
    h1, h2, h3, h4, h5, h6, p, label, li, td, th, .stDataFrame, .stTable {
        font-family: "Roboto", "Helvetica Neue", "Microsoft JhengHei", sans-serif !important;
        font-weight: 700 !important;
        line-height: 1.6 !important;
        letter-spacing: 0.5px;
    }
    .stSelectbox div[data-baseweb="select"] > div { min-height: 45px; }
    .streamlit-expanderHeader { font-weight: 700 !important; font-size: 16px !important; }
    .nexus-card {
        background-color: #1a1a1a; border: 1px solid #333; border-radius: 10px;
        padding: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.5);
        height: 140px; display: flex; flex-direction: column; justify-content: center;
    }
    .nexus-label { color: #aaa; font-size: 16px; font-weight: 700; margin-bottom: 8px; }
    .nexus-value { color: #00F0FF; font-size: 32px; font-weight: 700; text-shadow: 0 0 10px rgba(0,240,255,0.3); }
    .nexus-value-red { color: #ff4b4b !important; font-size: 32px; font-weight: 700; text-shadow: 0 0 10px rgba(255, 75, 75, 0.3); }
    .nexus-value-orange { color: #ffa500 !important; font-size: 32px; font-weight: 700; text-shadow: 0 0 10px rgba(255, 165, 0, 0.3); }
    div.stButton > button {
        width: 100%; min-height: 90px; border-radius: 12px; border: 1px solid #444;
        background: linear-gradient(145deg, #222, #181818); transition: all 0.3s;
        white-space: pre-wrap !important; padding: 15px !important; line-height: 1.5 !important;
    }
    div.stButton > button:hover { border-color: #00F0FF; transform: translateY(-2px); }
    div.stButton > button p { color: white !important; font-weight: 800 !important; margin: 0 !important; }
    hr { margin: 1.5em 0; border-color: #444; }
    section[data-testid="stSidebar"] { background-color: #0e0e0e; border-right: 1px solid #222; }
    g.slicetext { font-weight: 900 !important; font-size: 14px !important; fill: white !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 雲端資料庫連結 (Google Sheets) ---

# 你的 Google Sheet 名稱 (請確保機器人有權限編輯這個檔案)
SHEET_NAME = "nexus_data" 

def get_google_sheet_client():
    """連線到 Google Sheets"""
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    # 從 Streamlit Secrets 讀取金鑰
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

def init_google_sheets():
    """初始化：如果分頁不存在，自動建立"""
    client = get_google_sheet_client()
    try:
        sh = client.open(SHEET_NAME)
    except gspread.SpreadsheetNotFound:
        st.error(f"❌ 找不到名為 '{SHEET_NAME}' 的試算表。請先在 Google Drive 建立，並分享給機器人。")
        st.stop()

    required_worksheets = {
        "US_Stocks": ["代號", "名稱", "股數", "類別", "自訂價格", "參考市價"],
        "TW_Stocks": ["代號", "名稱", "股數", "類別", "自訂價格", "參考市價"],
        "Fixed_Assets": ["資產項目", "現值", "類別"],
        "Liabilities": ["負債項目", "金額", "每月扣款"],
        "Settings": ["Key", "Value"],
        "History": ["Date", "Net_Worth", "Total_Assets", "Total_Liabilities", "Monthly_Payment"]
    }

    try:
        current_titles = [ws.title for ws in sh.worksheets()]
        for sheet_title, headers in required_worksheets.items():
            if sheet_title not in current_titles:
                ws = sh.add_worksheet(title=sheet_title, rows=100, cols=10)
                ws.append_row(headers)
    except Exception as e:
        st.warning(f"初始化檢查時發生警告: {e}")
    
    return sh

# --- 讀取資料 (從雲端) ---
def load_data_from_cloud():
    """從 Google Sheets 讀取所有資料到 Session State"""
    try:
        sh = init_google_sheets()
        
        # 讀取各分頁
        def read_ws(title, default_data):
            try:
                ws = sh.worksheet(title)
                data = ws.get_all_records()
                if not data: return pd.DataFrame(default_data)
                return pd.DataFrame(data)
            except:
                return pd.DataFrame(default_data)

        # 預設範例資料 (若雲端全空)
        default_us = [{"代號": "VT", "名稱": "Vanguard World", "股數": 0, "類別": "美股", "自訂價格": 0, "參考市價": 0}]
        default_tw = [{"代號": "006208.TW", "名稱": "富邦台50", "股數": 0, "類別": "台股", "自訂價格": 0, "參考市價": 0}]
        default_fixed = [{"資產項目": "現金", "現值": 0, "類別": "現金"}]
        default_liab = [{"負債項目": "無", "金額": 0, "每月扣款": 0}]

        st.session_state.us_data = read_ws("US_Stocks", default_us)
        st.session_state.tw_data = read_ws("TW_Stocks", default_tw)
        st.session_state.fixed_data = read_ws("Fixed_Assets", default_fixed)
        st.session_state.liab_data = read_ws("Liabilities", default_liab)
        
        # 讀取設定 (Settings)
        settings_df = read_ws("Settings", [])
        settings_dict = dict(zip(settings_df['Key'], settings_df['Value'])) if not settings_df.empty else {}
        
        st.session_state.saved_expense = float(settings_dict.get("expense", 850000))
        st.session_state.saved_age = int(settings_dict.get("age", 27))
        st.session_state.saved_savings = float(settings_dict.get("savings", 325000))
        st.session_state.saved_return = float(settings_dict.get("return_rate", 11.0))
        
        st.session_state.data_loaded = True
        
    except Exception as e:
        st.error(f"雲端讀取失敗: {e}")

# --- 寫入資料 (到雲端) ---
def save_data_to_cloud(expense, age, savings, return_rate):
    """將資料寫回 Google Sheets"""
    try:
        sh = init_google_sheets()
        
        def write_ws(title, df):
            try:
                ws = sh.worksheet(title)
                ws.clear()
                # 寫入標題與內容
                ws.update([df.columns.values.tolist()] + df.values.tolist())
            except Exception as e:
                st.error(f"寫入 {title} 失敗: {e}")

        # 寫入各大表格
        write_ws("US_Stocks", st.session_state.us_data)
        write_ws("TW_Stocks", st.session_state.tw_data)
        write_ws("Fixed_Assets", st.session_state.fixed_data)
        write_ws("Liabilities", st.session_state.liab_data)
        
        # 寫入設定
        settings_data = pd.DataFrame([
            {"Key": "expense", "Value": expense},
            {"Key": "age", "Value": age},
            {"Key": "savings", "Value": savings},
            {"Key": "return_rate", "Value": return_rate}
        ])
        write_ws("Settings", settings_data)
        
        st.toast("✅ 雲端存檔完成！", icon="☁️")
    except Exception as e:
        st.error(f"存檔失敗: {e}")

def save_daily_record_cloud(net_worth, assets, liabilities, monthly_payment):
    """寫入歷史紀錄到雲端"""
    today = str(date.today())
    try:
        sh = init_google_sheets()
        ws = sh.worksheet("History")
        
        # 檢查今天是否已存在
        try:
            records = ws.get_all_records()
            df = pd.DataFrame(records)
            if not df.empty and str(today) in df['Date'].astype(str).values:
                # 今天已經有紀錄，不做重複寫入 (避免 API 爆炸)
                return
        except:
            pass
            
        # 寫入新的一行
        ws.append_row([today, net_worth, assets, liabilities, monthly_payment])
    except Exception as e:
        print(f"歷史紀錄寫入失敗: {e}")

# --- 3. 核心邏輯 (保留原版) ---
def get_precise_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = 0.0
        if hasattr(stock, 'fast_info'): price = stock.fast_info.get('last_price', 0.0)
        if price == 0: price = stock.info.get('regularMarketPrice', 0.0)
        if price == 0:
            hist = stock.history(period="1d")
            if not hist.empty: price = hist['Close'].iloc[-1]
        return float(price)
    except: return 0.0

def get_symbol_name(ticker):
    try:
        stock = yf.Ticker(ticker)
        name = stock.info.get('shortName') or stock.info.get('longName')
        return name if name else ticker
    except: return ticker

def parse_file(uploaded_file, import_type):
    # 這裡的邏輯與原本相同，僅需確保回傳格式正確
    try:
        if uploaded_file.name.endswith('.csv'): 
            try:
                df = pd.read_csv(uploaded_file, encoding='utf-8')
            except:
                df = pd.read_csv(uploaded_file, encoding='cp950')
        elif uploaded_file.name.endswith(('.xls', '.xlsx')): 
            df = pd.read_excel(uploaded_file)
        else: return None, "僅支援 Excel/CSV"

        df.columns = [str(c).lower().strip() for c in df.columns]
        new_data = []

        if import_type in ["stock_us", "stock_tw"]:
            ticker_col = next((c for c in df.columns if c in ['ticker', 'symbol', '代號', '股票代號']), None)
            shares_col = next((c for c in df.columns if c in ['shares', 'quantity', '股數', '數量', 'qty']), None)
            price_col = next((c for c in df.columns if c in ['price', 'cost', '自訂價格', '成本', 'avg_price']), None)
            
            if not ticker_col or not shares_col: return None, "缺少 [代號] 或 [股數]"
            
            df[ticker_col] = df[ticker_col].astype(str).str.strip().str.upper()
            df[shares_col] = pd.to_numeric(df[shares_col], errors='coerce').fillna(0.0)
            if price_col: df[price_col] = pd.to_numeric(df[price_col], errors='coerce').fillna(0.0)
            
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
            df[name_col] = df[name_col].astype(str)
            df[val_col] = pd.to_numeric(df[val_col], errors='coerce').fillna(0.0)
            for _, row in df.iterrows():
                new_data.append({"資產項目": row[name_col], "現值": float(row[val_col]), "類別": "固定資產"})
        elif import_type == "liab":
            name_col = next((c for c in df.columns if c in ['item', 'name', '負債項目', '名稱']), None)
            amount_col = next((c for c in df.columns if c in ['amount', '金額']), None)
            monthly_col = next((c for c in df.columns if c in ['monthly', 'payment', '每月扣款', '月付']), None)
            if not name_col or not amount_col: return None, "缺少 [負債項目] 或 [金額]"
            df[name_col] = df[name_col].astype(str)
            df[amount_col] = pd.to_numeric(df[amount_col], errors='coerce').fillna(0.0)
            for _, row in df.iterrows():
                m_val = 0.0
                if monthly_col: m_val = float(pd.to_numeric(row[monthly_col], errors='coerce') or 0.0)
                new_data.append({"負債項目": row[name_col], "金額": float(row[amount_col]), "每月扣款": m_val})
        return pd.DataFrame(new_data), None
    except Exception as e: return None, str(e)

# --- AI 與 計算 邏輯 ---
def predict_portfolio_return_detail(df_assets, include_house):
    if df_assets.empty: return 5.0, "無資產"
    returns_map = {"美股": 10.0, "台股": 8.0, "虛擬貨幣": 25.0, "現金": 1.0}
    house_keywords = '房產|固定資產|地產|House|Estate|Fixed'
    
    if not include_house:
        df_calc = df_assets[~df_assets['類別'].str.contains(house_keywords, case=False, na=False)].copy()
        msg_prefix = "✅ **AI 計算模式：排除房產/固定資產 (僅計算流動資產)**"
    else:
        df_calc = df_assets.copy()
        msg_prefix = "⚠️ **AI 計算模式：包含房產 (以 3% 增值率平均)**"
        returns_map.update({"房產": 3.0, "固定資產": 3.0, "地產": 3.0})

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
        contribution = r * weight
        weighted_return += contribution
        explanation.append(f"• **{cat}**: 佔比 {weight*100:.1f}% x 預期 {r}% = **+{contribution:.2f}%**")

    return round(weighted_return, 2), "\n".join(explanation)

def update_portfolio_data(df, category_default):
    if df.empty: return df
    with st.status(f"🚀 **更新 {category_default}...**", expanded=True) as status:
        for index, row in df.iterrows():
            ticker = str(row.get("代號", "")).strip().upper()
            if not ticker or ticker == "None": continue
            status.update(label=f"下載: {ticker}...", state="running")
            price = get_precise_price(ticker)
            if price > 0: df.at[index, "參考市價"] = price
            if pd.isna(row.get("名稱")) or row.get("名稱") == "":
                name = get_symbol_name(ticker)
                if name: df.at[index, "名稱"] = name
            if pd.isna(row.get("類別")) or row.get("類別") == "":
                df.at[index, "類別"] = category_default
        status.update(label="✅ 完成", state="complete", expanded=False)
    return df

EXCHANGE_RATE = 32.5 

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

# --- 4. 主程式 (UI) ---
def main():
    # 載入資料 (Session State)
    if 'data_loaded' not in st.session_state:
        load_data_from_cloud() # 改為從雲端讀取

    # 初始化 Session State (防止報錯)
    if 'fire_states' not in st.session_state: st.session_state.fire_states = {"Lean": True, "Barista": True, "Regular": True, "Fat": True}
    if 'ai_return_rate' not in st.session_state: st.session_state.ai_return_rate = st.session_state.get('saved_return', 11.0)
    if 'ai_explanation' not in st.session_state: st.session_state.ai_explanation = ""
    if 'last_include_house' not in st.session_state: st.session_state.last_include_house = True

    # 隱私模式 Sidebar
    with st.sidebar:
        st.header("⚙️ **系統控制**")
        privacy_mode = st.toggle("👁️ **隱私模式 (Hide Values)**", value=False)
        
        st.markdown("---")
        # 新增手動雲端同步按鈕 (避免頻繁寫入 API)
        if st.button("☁️ **同步儲存到雲端**", type="primary", help="將目前的變更寫入 Google Sheets"):
            save_data_to_cloud(st.session_state.saved_expense, st.session_state.saved_age, st.session_state.saved_savings, st.session_state.saved_return)

    def fmt_money(val): return "****" if privacy_mode else f"${val:,.0f}"

    st.title("🌌 **NEXUS: Cloud Wealth Command**")

    # 資產計算
    assets_list = []
    # 確保資料是 DataFrame 格式
    df_us = pd.DataFrame(st.session_state.us_data)
    df_tw = pd.DataFrame(st.session_state.tw_data)
    df_fixed = pd.DataFrame(st.session_state.fixed_data)
    df_liab = pd.DataFrame(st.session_state.liab_data)

    for df_source, cat_def, rate in [(df_us, "美股", EXCHANGE_RATE), (df_tw, "台股", 1.0)]:
        if not df_source.empty:
            for i, row in df_source.iterrows():
                p = float(row.get("自訂價格", 0) or 0)
                if p <= 0: p = float(row.get("參考市價", 0) or 0)
                s = float(row.get("股數", 0) or 0)
                v = p * s * rate
                assets_list.append({"資產": row.get("名稱",""), "類別": row.get("類別", cat_def), "價值": v})
    
    if not df_fixed.empty:
        for _, row in df_fixed.iterrows():
            assets_list.append({"資產": row.get("資產項目",""), "類別": row.get("類別","固定資產"), "價值": float(row.get("現值", 0))})

    df_assets = pd.DataFrame(assets_list)
    total_assets = df_assets["價值"].sum() if not df_assets.empty else 0
    total_liab = df_liab["金額"].sum() if not df_liab.empty else 0
    total_monthly = df_liab["每月扣款"].sum() if not df_liab.empty else 0
    net_worth = total_assets - total_liab
    
    # 自動寫入歷史紀錄 (可以考慮加上時間判斷，這裡先設為每次重新整理都會嘗試寫一次，但函數內有防重複機制)
    save_daily_record_cloud(net_worth, total_assets, total_liab, total_monthly)

    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown(f"""<div class="nexus-card"><div class="nexus-label">💰 淨資產 (Net Worth)</div><div class="nexus-value">{fmt_money(net_worth)}</div></div>""", unsafe_allow_html=True)
    with c2: st.markdown(f"""<div class="nexus-card"><div class="nexus-label">🏦 總資產 (Total Assets)</div><div class="nexus-value">{fmt_money(total_assets)}</div></div>""", unsafe_allow_html=True)
    with c3: st.markdown(f"""<div class="nexus-card"><div class="nexus-label">💳 總負債 (Liabilities)</div><div class="nexus-value-red">{fmt_money(total_liab)}</div></div>""", unsafe_allow_html=True)
    with c4: st.markdown(f"""<div class="nexus-card"><div class="nexus-label">💸 月支出 (Burn Rate)</div><div class="nexus-value-orange">{fmt_money(total_monthly)}</div></div>""", unsafe_allow_html=True)

    st.divider()
    tab_edit, tab_fire, tab_detail, tab_hist = st.tabs(["📝 **Asset Editor**", "🔥 **FIRE Analytics**", "📊 **Visuals**", "📈 **History**"])

    # === Tab 1: Editor ===
    with tab_edit:
        with st.expander("📂 **智能匯入 (Smart Import)**", expanded=False):
            st.info("支援 CSV / Excel 單檔匯入 (取代現有資料)。")
            import_target = st.selectbox("📥 選擇匯入目標", ["🇺🇸 美股/Crypto", "🇹🇼 台股", "🏠 固定資產", "💳 負債"])
            uploaded_file = st.file_uploader("拖曳檔案到此處", type=['csv','xls','xlsx'], accept_multiple_files=False)
            
            if uploaded_file and st.button("🚀 **確認匯入**"):
                map_type = {"🇺🇸 美股/Crypto": "stock_us", "🇹🇼 台股": "stock_tw", "🏠 固定資產": "fixed", "💳 負債": "liab"}
                target_key = {"stock_us": "us_data", "stock_tw": "tw_data", "fixed": "fixed_data", "liab": "liab_data"}[map_type[import_target]]
                df_new, err = parse_file(uploaded_file, map_type[import_target])
                if df_new is not None:
                    st.session_state[target_key] = df_new
                    save_data_to_cloud(st.session_state.saved_expense, st.session_state.saved_age, st.session_state.saved_savings, st.session_state.saved_return)
                    st.success(f"✅ 成功匯入 {len(df_new)} 筆")
                    st.rerun()
                else: st.error(f"❌ {err}")

        st.divider()
        col_btn, col_info = st.columns([1, 3])
        with col_btn:
            if st.button("⚡ **UPDATE PRICES**", type="primary"):
                st.session_state.us_data = update_portfolio_data(st.session_state.us_data, "美股")
                st.session_state.tw_data = update_portfolio_data(st.session_state.tw_data, "台股")
                save_data_to_cloud(st.session_state.saved_expense, st.session_state.saved_age, st.session_state.saved_savings, st.session_state.saved_return)
                st.rerun()

        def show_asset_table(title, df_key, rate=1.0):
            with st.container(border=True):
                df = st.session_state[df_key].copy()
                # 確保數值欄位為數字
                for col in ["股數", "自訂價格", "參考市價"]:
                    if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                
                vals = []
                for _, row in df.iterrows():
                    p = row.get("自訂價格", 0.0)
                    if p <= 0: p = row.get("參考市價", 0.0) or 0.0
                    vals.append(p * row.get("股數", 0.0) * rate)
                df["總價值(TWD)"] = vals
                total_sec = sum(vals)
                
                st.markdown(f"#### {title}")
                st.metric(f"{title} 總值", fmt_money(total_sec))
                
                if privacy_mode:
                    cols_cfg = {c: st.column_config.Column(disabled=True) for c in df.columns}
                    df.loc[:] = "****"
                else:
                    cols_cfg = {
                        "參考市價": st.column_config.NumberColumn(format="$%.2f", disabled=True), 
                        "總價值(TWD)": st.column_config.NumberColumn(format="$%.0f", disabled=True),
                        "佔比%": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100)
                    }
                    df["佔比%"] = (df["總價值(TWD)"] / total_sec * 100) if total_sec > 0 else 0.0

                edited = st.data_editor(df, num_rows="dynamic", key=f"editor_{df_key}", column_config=cols_cfg)
                if not privacy_mode: 
                    # 即時更新 Session State，但不馬上存雲端 (避免 API 爆炸)
                    st.session_state[df_key] = edited.drop(columns=["總價值(TWD)", "佔比%"], errors="ignore")

        c1, c2 = st.columns(2)
        with c1: show_asset_table("🇺🇸 US Stocks & Crypto", "us_data", EXCHANGE_RATE)
        with c2: show_asset_table("🇹🇼 TW Stocks", "tw_data", 1.0)
        st.divider()
        c3, c4 = st.columns(2)
        with c3:
            with st.container(border=True):
                df_fixed = st.session_state.fixed_data.copy()
                if "現值" in df_fixed.columns: df_fixed["現值"] = pd.to_numeric(df_fixed["現值"], errors='coerce').fillna(0)
                total_fixed = df_fixed["現值"].sum()
                st.markdown("#### 🏠 Fixed Assets"); st.metric("Fixed Assets 總值", fmt_money(total_fixed))
                if privacy_mode: df_fixed.loc[:] = "****"
                edited_fixed = st.data_editor(df_fixed, num_rows="dynamic", key="e_fix")
                if not privacy_mode: st.session_state.fixed_data = edited_fixed

        with c4:
            with st.container(border=True):
                df_liab = st.session_state.liab_data.copy()
                if "金額" in df_liab.columns: df_liab["金額"] = pd.to_numeric(df_liab["金額"], errors='coerce').fillna(0)
                total_l = df_liab["金額"].sum()
                st.markdown(f"#### 💳 Liabilities")
                val_disp = "****" if privacy_mode else f"${total_l:,.0f}"
                st.markdown(f"""<div style="font-size: 26px; font-weight: bold; color: #ff4b4b; text-shadow: 0 0 10px rgba(255, 75, 75, 0.3); margin-bottom: 10px;">{val_disp}</div>""", unsafe_allow_html=True)
                if privacy_mode: df_liab.loc[:] = "****"
                edited_liab = st.data_editor(df_liab, num_rows="dynamic", key="e_liab")
                if not privacy_mode: st.session_state.liab_data = edited_liab

    # === Tab 2: FIRE ===
    with tab_fire:
        c_f1, c_f2 = st.columns([1, 3])
        with c_f1:
            st.subheader("🎛️ **Scenario**")
            fire_help = {"Lean": "🌱 年支出60萬", "Barista": "☕ 年支出80萬", "Regular": "🏡 年支出100萬", "Fat": "🥂 年支出250萬"}
            fire_cards = [("Lean", "🌱 LEAN", "$60萬/yr"), ("Barista", "☕ BARISTA", "$80萬/yr"), ("Regular", "🏡 REGULAR", "$100萬/yr"), ("Fat", "🥂 FAT", "$250萬/yr")]
            r1 = st.columns(2); r2 = st.columns(2)
            for idx, (key, label, note) in enumerate(fire_cards):
                is_active = st.session_state.fire_states[key]
                curr = r1[idx] if idx < 2 else r2[idx-2]
                if curr.button(f"{label}\n{note}", key=f"btn_{key}", type="primary" if is_active else "secondary", help=fire_help[key]):
                    st.session_state.fire_states[key] = not st.session_state.fire_states[key]
                    st.rerun()

            st.divider()
            include_house = st.checkbox("✅ **納入固定資產 (房產)**", value=True)
            if include_house != st.session_state.last_include_house:
                st.session_state.last_include_house = include_house
                r, exp = predict_portfolio_return_detail(df_assets, include_house)
                st.session_state.ai_return_rate = r; st.session_state.ai_explanation = exp
                st.rerun()

            use_net_worth = st.checkbox("✅ **扣除負債 (淨資產)**", value=True)
            house_val = df_assets[df_assets['類別'].str.contains('房產|地產|固定', na=False)]['價值'].sum()
            mortgage_debt = st.session_state.liab_data[st.session_state.liab_data['負債項目'].str.contains('房|屋|貸', na=False)]['金額'].sum() if not st.session_state.liab_data.empty else 0
            
            calc_wealth = total_assets; current_house_component = house_val
            if not include_house: calc_wealth -= house_val; current_house_component = 0
            if use_net_worth:
                if not include_house: calc_wealth -= (total_liab - mortgage_debt)
                else: calc_wealth -= total_liab
            investable_part = calc_wealth - (current_house_component if include_house else 0)
            
            st.info(f"💡 目前計算基礎 ({( '含房產' if include_house else '排除房產' )}):"); st.metric("📊 **基數**", fmt_money(calc_wealth))
            st.divider()
            
            if st.button("🤖 **AI 分析報酬率**"):
                r, exp = predict_portfolio_return_detail(df_assets, include_house)
                st.session_state.ai_return_rate = r; st.session_state.ai_explanation = exp
                save_data_to_cloud(st.session_state.saved_expense, st.session_state.saved_age, st.session_state.saved_savings, r)
            
            my_return = st.slider("**投資年化報酬 %**", 0.0, 30.0, float(st.session_state.ai_return_rate), 0.1)
            if st.session_state.ai_explanation: st.markdown(st.session_state.ai_explanation)
            
            include_house_growth = st.checkbox("📈 **納入房產增值 (3%/年)**", value=False, disabled=not include_house)
            my_expense = st.number_input("**目標年支出**", value=float(st.session_state.saved_expense), step=50000.0)
            my_age = st.number_input("**年齡**", int(st.session_state.saved_age))
            my_savings = st.number_input("**年儲蓄**", float(st.session_state.saved_savings))
            
            # 更新 session state
            st.session_state.saved_expense = my_expense
            st.session_state.saved_age = my_age
            st.session_state.saved_savings = my_savings
            st.session_state.saved_return = my_return

        with c_f2:
            st.subheader("📈 **Freedom Trajectory**")
            ages, wealth_curve, fire_curves, custom_target = calculate_fire_curves_advanced(my_age, investable_part, current_house_component, my_savings, my_return, 3.0, 3.0, my_expense, include_house_growth)
            fig = go.Figure()
            
            hover_temp = "<b>%{x}歲</b><br>資產: ****<extra></extra>" if privacy_mode else "<b>%{x}歲</b><br>資產: $%{y:,.0f}<extra></extra>"
            final_txt = "<b>****</b>" if privacy_mode else f"<b>${wealth_curve[-1]/10000:.0f}萬</b>"
            fig.add_trace(go.Scatter(x=ages, y=wealth_curve, name="🚀 My Wealth", line=dict(color='#00F0FF', width=5), hovertemplate=hover_temp))
            fig.add_annotation(x=ages[-1], y=wealth_curve[-1], text=final_txt, showarrow=True, arrowhead=1, ax=-40, ay=-40, font=dict(color='#00F0FF', size=16))
            
            colors = {'Lean': '#EF476F', 'Barista': '#FFD166', 'Regular': '#06D6A0', 'Fat': '#118AB2'}
            for label, curve in fire_curves.items():
                if st.session_state.fire_states.get(label.split()[0], True):
                    fig.add_trace(go.Scatter(x=ages, y=curve, name=label, line=dict(color=colors.get(label.split()[0], '#888'), width=2, dash='dot'), opacity=0.7))
            fig.update_layout(template="plotly_dark", height=600, title=f"<b>資產累積預測</b>", yaxis_title="<b>金額 (TWD)</b>")
            st.plotly_chart(fig, use_container_width=True)

    # === Tab 3: Visuals ===
    with tab_detail:
        c1, c2 = st.columns([1, 1])
        with c1:
            st.subheader("🗺️ **Asset Allocation**")
            if not df_assets.empty:
                df_plot = df_assets[df_assets['價值'] > 0].sort_values("價值", ascending=False)
                fig_sun = px.sunburst(df_plot, path=['類別', '資產'], values='價值', color='類別', color_discrete_map={'美股': '#3b82f6', '台股': '#ef4444', '虛擬貨幣': '#f59e0b', '房產': '#10b981'})
                info_mode = "label" if privacy_mode else "label+percent root"
                fig_sun.update_traces(textinfo=info_mode, sort=False)
                fig_sun.update_layout(height=500, margin=dict(t=0, l=0, r=0, b=0), template="plotly_dark")
                st.plotly_chart(fig_sun, use_container_width=True)
        with c2:
            st.subheader("📊 **Holdings Rank**")
            if not df_assets.empty:
                df_view = df_assets.copy()
                df_view["佔比"] = (df_view["價值"] / df_view["價值"].sum()) * 100
                if privacy_mode:
                    df_view["價值"] = "****"; df_view["佔比"] = "****"
                st.dataframe(df_view[["資產", "類別", "價值", "佔比"]].sort_values("價值", ascending=False), use_container_width=True, hide_index=True)

    # === Tab 4: History ===
    with tab_hist:
        st.subheader("📈 **History Log** (Cloud)")
        try:
            sh = init_google_sheets()
            ws = sh.worksheet("History")
            hist_data = ws.get_all_records()
            if hist_data:
                df_hist = pd.DataFrame(hist_data)
                st.plotly_chart(px.line(df_hist, x='Date', y=['Net_Worth', 'Total_Assets'], markers=True).update_layout(template="plotly_dark", height=400), use_container_width=True)
        except:
            st.info("尚無歷史紀錄")

if __name__ == "__main__":
    if runtime.exists(): main()
    else:
        import subprocess
        subprocess.run([sys.executable, "-m", "streamlit", "run", os.path.abspath(__file__)])

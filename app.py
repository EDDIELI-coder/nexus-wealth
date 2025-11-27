import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import date
import time

# --- 1. 系統設定 (NEXUS v8.0 Cloud Flagship) ---
st.set_page_config(page_title="NEXUS: Cloud Command", layout="wide", page_icon="☁️")

# Google Sheets 設定
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
SHEET_NAME = "NEXUS_Data"
KEY_FILE = "service_account.json"

# CSS: 延續 v7.0 的完美介面
st.markdown("""
    <style>
    /* 全局字體 */
    html, body, [class*="css"], div, label, p, span, h1, h2, h3, h4, h5, h6 {
        font-family: "Roboto", "Helvetica Neue", "Microsoft JhengHei", sans-serif !important;
        font-weight: 700 !important;
        line-height: 1.6 !important;
        letter-spacing: 0.5px;
    }
    .stSelectbox div[data-baseweb="select"] > div { min-height: 45px; }
    
    /* 卡片樣式 */
    .nexus-card {
        background-color: #1a1a1a; border: 1px solid #333; border-radius: 10px; padding: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.5); height: 140px; display: flex; flex-direction: column; justify-content: center;
    }
    .nexus-label { color: #aaa; font-size: 16px; font-weight: 700; margin-bottom: 8px; }
    .nexus-value { color: #00F0FF; font-size: 32px; font-weight: 700; text-shadow: 0 0 10px rgba(0,240,255,0.3); }
    .nexus-value-red { color: #ff4b4b !important; font-size: 32px; font-weight: 700; text-shadow: 0 0 10px rgba(255, 75, 75, 0.3); }
    .nexus-value-orange { color: #ffa500 !important; font-size: 32px; font-weight: 700; text-shadow: 0 0 10px rgba(255, 165, 0, 0.3); }
    
    /* 按鈕樣式 */
    div.stButton > button {
        width: 100%; height: auto !important; min-height: 90px; border-radius: 12px; border: 1px solid #444;
        background: linear-gradient(145deg, #222, #181818); transition: all 0.3s; padding: 15px !important;
        white-space: pre-wrap !important; line-height: 1.5 !important;
    }
    div.stButton > button:hover { border-color: #00F0FF; transform: translateY(-2px); }
    div.stButton > button p { font-size: 16px !important; color: white !important; font-weight: 800 !important; margin: 0 !important; }
    
    hr { margin: 1.5em 0; border-color: #444; }
    section[data-testid="stSidebar"] { background-color: #0e0e0e; border-right: 1px solid #222; }
    g.slicetext { font-weight: 900 !important; font-size: 14px !important; fill: white !important; }
    </style>
""", unsafe_allow_html=True)

# --- 2. Google Sheets 連線核心 ---
@st.cache_resource
def get_gspread_client():
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(KEY_FILE, SCOPE)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        return None

def load_data_from_cloud():
    """從雲端讀取所有資料"""
    client = get_gspread_client()
    if not client: return None
    
    try: sheet = client.open(SHEET_NAME)
    except: return None # 找不到表

    data = {}
    # 定義各分頁結構
    configs = {
        'us': ("US_Stocks", ["代號", "名稱", "股數", "類別", "自訂價格", "參考市價"]),
        'tw': ("TW_Stocks", ["代號", "名稱", "股數", "類別", "自訂價格", "參考市價"]),
        'fixed': ("Fixed_Assets", ["資產項目", "現值", "類別"]),
        'liab': ("Liabilities", ["負債項目", "金額", "每月扣款"]),
        'history': ("History", ['Date', 'Net_Worth', 'Total_Assets', 'Total_Liabilities', 'Monthly_Payment']),
        'settings': ("Settings", ["Key", "Value"]) # 用來存年齡、支出等設定
    }

    for key, (ws_name, cols) in configs.items():
        try:
            ws = sheet.worksheet(ws_name)
            records = ws.get_all_records()
            df = pd.DataFrame(records)
            # 強制轉型，避免字串問題
            if not df.empty:
                for c in ['股數', '自訂價格', '參考市價', '現值', '金額', '每月扣款', 'Value']:
                    if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            else:
                df = pd.DataFrame(columns=cols)
            data[key] = df
        except:
            data[key] = pd.DataFrame(columns=cols)
            
    return data

def save_data_to_cloud(type_key, df):
    """儲存特定資料表到雲端"""
    client = get_gspread_client()
    if not client: return
    sheet = client.open(SHEET_NAME)
    
    map_name = {
        "us_data": "US_Stocks", "tw_data": "TW_Stocks", 
        "fixed_data": "Fixed_Assets", "liab_data": "Liabilities", 
        "history_data": "History", "settings": "Settings"
    }
    ws_name = map_name.get(type_key)
    
    try:
        try: ws = sheet.worksheet(ws_name)
        except: ws = sheet.add_worksheet(title=ws_name, rows="100", cols="20")
        
        ws.clear()
        # 轉為 list 寫入，確保 header 存在
        content = [df.columns.values.tolist()] + df.astype(str).values.tolist()
        ws.update(content)
    except Exception as e:
        st.error(f"雲端存檔失敗 ({ws_name}): {e}")

def save_settings_to_cloud(exp, age, sav, ret):
    """特別儲存使用者設定值"""
    df = pd.DataFrame([
        {"Key": "expense", "Value": exp},
        {"Key": "age", "Value": age},
        {"Key": "savings", "Value": sav},
        {"Key": "return_rate", "Value": ret}
    ])
    save_data_to_cloud("settings", df)

# --- 3. 核心運算 ---
def get_precise_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = stock.fast_info.get('last_price', 0.0)
        if price == 0: price = stock.info.get('regularMarketPrice', 0.0)
        if price == 0:
            hist = stock.history(period="1d")
            if not hist.empty: price = hist['Close'].iloc[-1]
        return float(price)
    except: return 0.0

def get_symbol_name(ticker):
    try: return yf.Ticker(ticker).info.get('shortName', ticker)
    except: return ticker

def update_portfolio_data(df, category_default):
    if df.empty: return df
    with st.status(f"🚀 **雲端更新中: {category_default}...**", expanded=True) as status:
        for index, row in df.iterrows():
            ticker = str(row.get("代號", "")).strip().upper()
            if not ticker: continue
            status.update(label=f"下載: {ticker}...", state="running")
            price = get_precise_price(ticker)
            if price > 0: df.at[index, "參考市價"] = price
            if not row.get("名稱"): df.at[index, "名稱"] = get_symbol_name(ticker)
            if not row.get("類別"): df.at[index, "類別"] = category_default
        status.update(label="✅ 完成", state="complete", expanded=False)
    return df

# --- 4. AI 邏輯 ---
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
        returns_map.update({"房產": 3.0, "固定資產": 3.0})
    
    total = df_calc["價值"].sum()
    if total == 0: return 5.0, "無有效資產"
    
    w_ret = 0.0
    exp = [msg_prefix]
    for cat, val in df_calc.groupby("類別")["價值"].sum().items():
        r = 3.0
        for k, v in returns_map.items(): 
            if k in str(cat): r = v; break
        w_ret += (r * (val/total))
        exp.append(f"• **{cat}**: {val/total*100:.1f}% x {r}%")
    return round(w_ret, 2), "\n".join(exp)

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
            curr_levels[k] *= (1 + inflation/100); level_curves[k].append(curr_levels[k])
        curr_custom *= (1 + inflation/100); custom_target.append(curr_custom)
    return ages, wealth_curve, level_curves, custom_target

# --- 5. 預設資料 (第一次連線初始化用) ---
DEFAULT_US = [{"代號": "VT", "名稱": "Vanguard World", "股數": 0.0, "類別": "美股", "自訂價格": 0.0, "參考市價": 0.0}]
DEFAULT_TW = [{"代號": "006208.TW", "名稱": "富邦台50", "股數": 0.0, "類別": "台股", "自訂價格": 0.0, "參考市價": 0.0}]

# --- 6. 主程式 ---
def main():
    # 初始化：從雲端載入資料
    if 'cloud_data_loaded' not in st.session_state:
        with st.spinner("☁️ 正在連線 Google 雲端資料庫..."):
            cloud = load_data_from_cloud()
            if cloud:
                st.session_state.us_data = cloud['us'] if not cloud['us'].empty else pd.DataFrame(DEFAULT_US)
                st.session_state.tw_data = cloud['tw'] if not cloud['tw'].empty else pd.DataFrame(DEFAULT_TW)
                st.session_state.fixed_data = cloud['fixed']
                st.session_state.liab_data = cloud['liab']
                st.session_state.history_data = cloud['history']
                
                # 載入設定 (如果有的話)
                settings_df = cloud['settings']
                if not settings_df.empty:
                    s_dict = dict(zip(settings_df['Key'], settings_df['Value']))
                    st.session_state.saved_expense = float(s_dict.get('expense', 850000))
                    st.session_state.saved_age = int(s_dict.get('age', 27))
                    st.session_state.saved_savings = float(s_dict.get('savings', 325000))
                    st.session_state.saved_return = float(s_dict.get('return_rate', 11.0))
                else:
                    st.session_state.saved_expense = 850000
                    st.session_state.saved_age = 27
                    st.session_state.saved_savings = 325000
                    st.session_state.saved_return = 11.0
                
                st.session_state.cloud_data_loaded = True
            else:
                st.error("連線失敗，請檢查 service_account.json")
                st.stop()

    if 'fire_states' not in st.session_state: st.session_state.fire_states = {"Lean": True, "Barista": True, "Regular": True, "Fat": True}
    if 'ai_return_rate' not in st.session_state: st.session_state.ai_return_rate = st.session_state.saved_return
    if 'ai_explanation' not in st.session_state: st.session_state.ai_explanation = ""
    if 'last_include_house' not in st.session_state: st.session_state.last_include_house = True

    with st.sidebar:
        st.header("⚙️ **系統控制**")
        if st.button("🔄 **重新載入 (從雲端)**"):
            st.cache_resource.clear()
            del st.session_state['cloud_data_loaded']
            st.rerun()

    st.title("🌌 **NEXUS: Cloud Command**")

    # 資產計算
    EXCHANGE_RATE = 32.5
    assets = []
    for df, cat, rate in [(st.session_state.us_data, "美股", EXCHANGE_RATE), (st.session_state.tw_data, "台股", 1.0)]:
        for _, row in df.iterrows():
            v = float(row.get("股數",0)) * (float(row.get("自訂價格",0)) or float(row.get("參考市價",0))) * rate
            assets.append({"類別": row.get("類別", cat), "價值": v, "資產": row.get("名稱","")})
            
    for _, row in st.session_state.fixed_data.iterrows():
        assets.append({"類別": row.get("類別","固定資產"), "價值": float(row.get("現值",0)), "資產": row.get("資產項目","")})
        
    df_assets = pd.DataFrame(assets)
    total_assets = df_assets["價值"].sum() if not df_assets.empty else 0
    total_liab = st.session_state.liab_data["金額"].sum() if not st.session_state.liab_data.empty else 0
    monthly_burn = st.session_state.liab_data["每月扣款"].sum() if not st.session_state.liab_data.empty else 0
    net_worth = total_assets - total_liab

    # 歷史紀錄 (若日期變更則寫入雲端)
    today_str = str(date.today())
    hist_df = st.session_state.history_data
    if hist_df.empty or str(hist_df.iloc[-1]['Date']) != today_str:
        new_row = pd.DataFrame([[today_str, net_worth, total_assets, total_liab, monthly_burn]], columns=hist_df.columns)
        hist_df = pd.concat([hist_df, new_row], ignore_index=True)
        st.session_state.history_data = hist_df
        save_data_to_cloud("history_data", hist_df)

    # KPI
    c1, c2, c3, c4 = st.columns(4)
    with c1: st.markdown(f"""<div class="nexus-card"><div class="nexus-label">💰 淨資產</div><div class="nexus-value">${net_worth:,.0f}</div></div>""", unsafe_allow_html=True)
    with c2: st.markdown(f"""<div class="nexus-card"><div class="nexus-label">🏦 總資產</div><div class="nexus-value">${total_assets:,.0f}</div></div>""", unsafe_allow_html=True)
    with c3: st.markdown(f"""<div class="nexus-card"><div class="nexus-label">💳 總負債</div><div class="nexus-value-red">${total_liab:,.0f}</div></div>""", unsafe_allow_html=True)
    with c4: st.markdown(f"""<div class="nexus-card"><div class="nexus-label">💸 月支出</div><div class="nexus-value-orange">${monthly_burn:,.0f}</div></div>""", unsafe_allow_html=True)

    st.divider()
    tab_edit, tab_fire, tab_vis, tab_hist = st.tabs(["📝 **Editor**", "🔥 **FIRE**", "📊 **Visuals**", "📈 **History**"])

    # === Tab 1: Editor (即時雲端同步) ===
    with tab_edit:
        c_btn, _ = st.columns([1,3])
        if c_btn.button("⚡ **UPDATE PRICES (Sync Cloud)**", type="primary"):
            st.session_state.us_data = update_portfolio_data(st.session_state.us_data, "美股")
            save_data_to_cloud("us_data", st.session_state.us_data)
            
            st.session_state.tw_data = update_portfolio_data(st.session_state.tw_data, "台股")
            save_data_to_cloud("tw_data", st.session_state.tw_data)
            st.rerun()

        c1, c2 = st.columns(2)
        with c1:
            with st.container(border=True):
                st.markdown("#### 🇺🇸 US Stocks")
                ed = st.data_editor(st.session_state.us_data, num_rows="dynamic", key="e1")
                if not ed.equals(st.session_state.us_data):
                    st.session_state.us_data = ed
                    save_data_to_cloud("us_data", ed)
        with c2:
            with st.container(border=True):
                st.markdown("#### 🇹🇼 TW Stocks")
                ed = st.data_editor(st.session_state.tw_data, num_rows="dynamic", key="e2")
                if not ed.equals(st.session_state.tw_data):
                    st.session_state.tw_data = ed
                    save_data_to_cloud("tw_data", ed)
        
        st.divider()
        c3, c4 = st.columns(2)
        with c3:
            with st.container(border=True):
                st.markdown("#### 🏠 Fixed Assets")
                ed = st.data_editor(st.session_state.fixed_data, num_rows="dynamic", key="e3")
                if not ed.equals(st.session_state.fixed_data):
                    st.session_state.fixed_data = ed
                    save_data_to_cloud("fixed_data", ed)
        with c4:
            with st.container(border=True):
                st.markdown("#### 💳 Liabilities")
                st.markdown(f"""<div style="font-size: 26px; font-weight: bold; color: #ff4b4b; margin-bottom: 10px;">${total_liab:,.0f}</div>""", unsafe_allow_html=True)
                ed = st.data_editor(st.session_state.liab_data, num_rows="dynamic", key="e4")
                if not ed.equals(st.session_state.liab_data):
                    st.session_state.liab_data = ed
                    save_data_to_cloud("liab_data", ed)

    # === Tab 2: FIRE ===
    with tab_fire:
        c1, c2 = st.columns([1,2])
        with c1:
            inc_house = st.checkbox("✅ 納入房產", True)
            if inc_house != st.session_state.last_include_house:
                st.session_state.last_include_house = inc_house
                r, exp = predict_portfolio_return_detail(df_assets, inc_house)
                st.session_state.ai_return_rate = r; st.session_state.ai_explanation = exp
                st.rerun()
            
            if st.button("🤖 AI 分析"):
                r, exp = predict_portfolio_return_detail(df_assets, inc_house)
                st.session_state.ai_return_rate = r; st.session_state.ai_explanation = exp
            
            rate = st.slider("報酬率 %", 0.0, 30.0, st.session_state.ai_return_rate)
            if st.session_state.ai_explanation: st.markdown(st.session_state.ai_explanation)
            
            exp = st.number_input("年支出", value=st.session_state.saved_expense)
            age = st.number_input("年齡", value=st.session_state.saved_age)
            sav = st.number_input("年儲蓄", value=st.session_state.saved_savings)
            
            # 即時存檔設定
            if exp != st.session_state.saved_expense or age != st.session_state.saved_age or sav != st.session_state.saved_savings:
                save_settings_to_cloud(exp, age, sav, rate)

        with c2:
            base = total_assets if inc_house else (total_assets - df_assets[df_assets['類別'].str.contains('房產', na=False)]['價值'].sum())
            ages, wealth, curves, targets = calculate_fire_curves_advanced(age, base, 0, sav, rate, 3.0, 3.0, exp, True)
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=ages, y=wealth, name="My Wealth", line=dict(color='#00F0FF', width=4)))
            fig.add_annotation(x=ages[-1], y=wealth[-1], text=f"<b>${wealth[-1]/10000:.0f}萬</b>", showarrow=True, arrowhead=1, ax=-40, ay=-40, font=dict(color='#00F0FF', size=16))
            
            colors = {'Lean': '#EF476F', 'Barista': '#FFD166', 'Regular': '#06D6A0', 'Fat': '#118AB2'}
            for label, curve in curves.items():
                if st.session_state.fire_states.get(label.split()[0], True):
                    fig.add_trace(go.Scatter(x=ages, y=curve, name=label, line=dict(color=colors.get(label.split()[0], '#888'), width=2, dash='dot'), opacity=0.7))
            
            fig.update_layout(template="plotly_dark", height=500, title="資產預測")
            st.plotly_chart(fig, use_container_width=True)

    # === Tab 3: Visuals ===
    with tab_vis:
        if not df_assets.empty:
            fig = px.sunburst(df_assets, path=['類別', '資產'], values='價值', color='類別')
            fig.update_layout(template="plotly_dark", height=600)
            st.plotly_chart(fig, use_container_width=True)

    # === Tab 4: History ===
    with tab_hist:
        if not st.session_state.history_data.empty:
            fig = px.line(st.session_state.history_data, x='Date', y=['Net_Worth', 'Total_Assets'])
            fig.update_layout(template="plotly_dark", height=500)
            st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()
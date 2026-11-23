import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from streamlit_lightweight_charts import renderLightweightCharts

# Tam Ekran TradingView Görünümü Ayarları
st.set_page_config(page_title="TradingView BIST 2H", layout="wide")

st.markdown("""
    <style>
        .block-container { padding-top: 1rem; padding-bottom: 0rem; padding-left: 1rem; padding-right: 1rem; }
        header { visibility: hidden; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# ÜST ARAÇ ÇUBUĞU
# ==========================================
col1, col2, col3, col4, col5, col6 = st.columns([1.5, 1, 1, 1, 1, 1])
with col1:
    hisse_kodu = st.text_input("Hisse Kodu", value="TRALT", label_visibility="collapsed", placeholder="Hisse Kodu (Örn: TRALT)").upper().strip()
with col2:
    zaman_dilimi = st.selectbox("Periyot", ["2 Saatlik (2H)", "1 Saatlik (1H)", "Günlük (1D)"], label_visibility="collapsed")
with col3:
    key_value = st.number_input("Key Value", value=2.5, step=0.1, format="%.1f")
with col4:
    atr_period = st.number_input("ATR", value=10, step=1)
with col5:
    st.write("")
    yenile = st.button("🔄 Yenile", use_container_width=True)
with col6:
    st.write("")
    st.caption(f"📊 {hisse_kodu}.IS")

ticker_symbol = f"{hisse_kodu}.IS" if not hisse_kodu.endswith(".IS") else hisse_kodu

# ==========================================
# VERİ ÇEKME VE KAPANIŞ FİYATI EŞİTLEME
# ==========================================
@st.cache_data(ttl=300)
def get_data(symbol, tf):
    # Gerçek son kapanış fiyatını almak için günlük veriyi kontrol et
    df_daily = yf.download(symbol, period="5d", interval="1d", progress=False)
    real_last_close = None
    if not df_daily.empty:
        if isinstance(df_daily.columns, pd.MultiIndex):
            df_daily.columns = df_daily.columns.get_level_values(0)
        real_last_close = float(df_daily['Close'].dropna().iloc[-1])

    if tf == "Günlük (1D)":
        df = yf.download(symbol, period="1y", interval="1d", progress=False)
        if df.empty: return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        return df.dropna()
    else:
        df = yf.download(symbol, period="60d", interval="1h", progress=False)
        if df.empty: return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_convert('Europe/Istanbul')
        
        if tf == "2 Saatlik (2H)":
            df = df.resample('2h', origin='start_day', offset='10h').agg({
                'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
            }).dropna()
        
        # Son mumun kapanışını karanlık oda/kapanış seansı fiyatıyla eşitle
        if real_last_close is not None and len(df) > 0:
            df.iloc[-1, df.columns.get_loc('Close')] = real_last_close
            if real_last_close > df.iloc[-1]['High']:
                df.iloc[-1, df.columns.get_loc('High')] = real_last_close
            if real_last_close < df.iloc[-1]['Low']:
                df.iloc[-1, df.columns.get_loc('Low')] = real_last_close
                
        return df

# ==========================================
# ORİJİNAL UT BOT + EMA 5/10/14 HESAPLAMA
# ==========================================
def calculate_ut_bot(df, key_val, atr_per):
    df = df.copy()
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    true_range = np.max(pd.concat([high_low, high_close, low_close], axis=1), axis=1)
    df['ATR'] = true_range.ewm(alpha=1/atr_per, min_periods=atr_per, adjust=False).mean()
    
    loss = key_val * df['ATR']
    src = df['Close'].values
    loss_val = loss.values
    
    trailing_stop = np.zeros(len(df))
    for i in range(len(df)):
        if i == 0 or np.isnan(loss_val[i]):
            trailing_stop[i] = src[i] - (loss_val[i] if not np.isnan(loss_val[i]) else 0)
        else:
            prev_stop = trailing_stop[i-1]
            if src[i] > prev_stop and src[i-1] > prev_stop:
                trailing_stop[i] = max(prev_stop, src[i] - loss_val[i])
            elif src[i] < prev_stop and src[i-1] < prev_stop:
                trailing_stop[i] = min(prev_stop, src[i] + loss_val[i])
            elif src[i] > prev_stop:
                trailing_stop[i] = src[i] - loss_val[i]
            else:
                trailing_stop[i] = src[i] + loss_val[i]
                
    df['TrailingStop'] = trailing_stop
    df['EMA5'] = df['Close'].ewm(span=5, adjust=False).mean()
    df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
    df['EMA14'] = df['Close'].ewm(span=14, adjust=False).mean()
    
    bull_trend = (df['EMA5'] > df['EMA10']) & (df['EMA10'] > df['EMA14'])
    bear_trend = (df['EMA5'] < df['EMA10']) & (df['EMA10'] < df['EMA14'])
    
    ut_buy = (df['Close'] > df['TrailingStop']) & (df['Close'].shift(1) <= df['TrailingStop'].shift(1))
    ut_sell = (df['Close'] < df['TrailingStop']) & (df['Close'].shift(1) >= df['TrailingStop'].shift(1))
    
    df['BuySignal'] = ut_buy & bull_trend
    df['SellSignal'] = ut_sell & bear_trend
    return df

# ==========================================
# TRADINGVIEW GRAFİK ÇİZİMİ
# ==========================================
df_raw = get_data(ticker_symbol, zaman_dilimi)

if df_raw.empty:
    st.error(f"'{hisse_kodu}' için veri bulunamadı.")
else:
    df = calculate_ut_bot(df_raw, key_value, atr_period)
    
    candles, ema5_data, ema10_data, ema14_data, stop_data, markers = [], [], [], [], [], []
    
    for idx, row in df.iterrows():
        t = int(idx.timestamp()) if zaman_dilimi != "Günlük (1D)" else idx.strftime('%Y-%m-%d')
        
        candles.append({
            "time": t, "open": round(float(row['Open']), 2), "high": round(float(row['High']), 2),
            "low": round(float(row['Low']), 2), "close": round(float(row['Close']), 2)
        })
        ema5_data.append({"time": t, "value": round(float(row['EMA5']), 2)})
        ema10_data.append({"time": t, "value": round(float(row['EMA10']), 2)})
        ema14_data.append({"time": t, "value": round(float(row['EMA14']), 2)})
        
        stop_color = '#26a69a' if row['Close'] > row['TrailingStop'] else '#ef5350'
        stop_data.append({"time": t, "value": round(float(row['TrailingStop']), 2), "color": stop_color})
        
        if row['BuySignal']:
            markers.append({
                "time": t, "position": "belowBar", "color": "#26a69a",
                "shape": "arrowUp", "text": "AL"
            })
        elif row['SellSignal']:
            markers.append({
                "time": t, "position": "aboveBar", "color": "#ef5350",
                "shape": "arrowDown", "text": "SAT"
            })

    chartOptions = {
        "height": 680,
        "layout": {
            "background": {"type": "solid", "color": "#131722"},
            "textColor": "#d1d4dc",
        },
        "grid": {
            "vertLines": {"color": "#1e222d"},
            "horzLines": {"color": "#1e222d"},
        },
        "crosshair": {"mode": 0},
        "rightPriceScale": {"borderColor": "#2a2e39"},
        "timeScale": {"borderColor": "#2a2e39", "timeVisible": True, "secondsVisible": False},
    }

    series = [
        {
            "type": "Candlestick",
            "data": candles,
            "options": {
                "upColor": "#26a69a", "downColor": "#ef5350",
                "borderVisible": False, "wickUpColor": "#26a69a", "wickDownColor": "#ef5350"
            },
            "markers": markers
        },
        {"type": "Line", "data": stop_data, "options": {"lineWidth": 2, "title": "UT Bot"}},
        {"type": "Line", "data": ema5_data, "options": {"color": "#2962FF", "lineWidth": 1, "title": "EMA 5"}},
        {"type": "Line", "data": ema10_data, "options": {"color": "#FF6D00", "lineWidth": 1, "title": "EMA 10"}},
        {"type": "Line", "data": ema14_data, "options": {"color": "#9C27B0", "lineWidth": 1, "title": "EMA 14"}}
    ]

    renderLightweightCharts([{"chart": chartOptions, "series": series}], "tv_chart")
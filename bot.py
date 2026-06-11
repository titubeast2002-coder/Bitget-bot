import hashlib
import hmac
import time
import requests
import json
import os
import math
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
#  CONFIGURAZIONE
# ═══════════════════════════════════════════════════════════════
API_KEY    = os.environ.get("API_KEY")
SECRET_KEY = os.environ.get("SECRET_KEY")
PASSPHRASE = os.environ.get("PASSPHRASE")

BASE_URL      = "https://api.bitget.com"
SYMBOL        = "BTCUSDT"
TRADE_USDT    = 20
MAX_TRADES    = 3         # massimo trade aperti contemporaneamente
TRAIL_PCT     = 0.015
CHECK_EVERY   = 900       # 15 minuti

# ═══════════════════════════════════════════════════════════════
#  FIRMA API
# ═══════════════════════════════════════════════════════════════
def sign(message, secret):
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest().hex()

def get_headers(method, path, body=""):
    ts = str(int(time.time() * 1000))
    body_str = json.dumps(body) if body else ""
    msg = ts + method.upper() + path + body_str
    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign(msg, SECRET_KEY),
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }

# ═══════════════════════════════════════════════════════════════
#  DATI DI MERCATO
# ═══════════════════════════════════════════════════════════════
def get_price():
    r = requests.get(f"{BASE_URL}/api/v2/spot/market/tickers?symbol={SYMBOL}", timeout=10)
    return float(r.json()["data"][0]["lastPr"])

def get_candles(granularity="15m", limit=200):
    r = requests.get(
        f"{BASE_URL}/api/v2/spot/market/candles?symbol={SYMBOL}&granularity={granularity}&limit={limit}",
        timeout=10
    )
    data = r.json()["data"]
    opens   = [float(c[1]) for c in data]
    highs   = [float(c[2]) for c in data]
    lows    = [float(c[3]) for c in data]
    closes  = [float(c[4]) for c in data]
    volumes = [float(c[5]) for c in data]
    return opens, highs, lows, closes, volumes

def get_orderbook():
    r = requests.get(f"{BASE_URL}/api/v2/spot/market/orderbook?symbol={SYMBOL}&limit=20", timeout=10)
    data = r.json()["data"]
    bids = [(float(b[0]), float(b[1])) for b in data["bids"][:10]]
    asks = [(float(a[0]), float(a[1])) for a in data["asks"][:10]]
    bid_vol = sum(b[1] for b in bids)
    ask_vol = sum(a[1] for a in asks)
    # pressure: >1 = più compratori, <1 = più venditori
    pressure = bid_vol / ask_vol if ask_vol > 0 else 1
    return pressure

def get_funding_rate():
    try:
        r = requests.get(f"{BASE_URL}/api/v2/mix/market/current-fund-rate?symbol=BTCUSDT&productType=USDT-FUTURES", timeout=10)
        return float(r.json()["data"][0]["fundingRate"])
    except:
        return 0.0

def get_crypto_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        value = int(r.json()["data"][0]["value"])
        label = r.json()["data"][0]["value_classification"]
        return value, label
    except:
        return 50, "Neutral"

# ═══════════════════════════════════════════════════════════════
#  INDICATORI TECNICI
# ═══════════════════════════════════════════════════════════════
def calc_rsi(closes, period=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0: return 100
    return 100 - (100 / (1 + ag / al))

def calc_ema(closes, period):
    if len(closes) < period:
        return sum(closes) / len(closes)
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_sma(closes, period):
    return sum(closes[-period:]) / period

def calc_bollinger(closes, period=20):
    recent = closes[-period:]
    mean = sum(recent) / period
    std = math.sqrt(sum((x - mean)**2 for x in recent) / period)
    return mean - 2*std, mean, mean + 2*std

def calc_macd(closes):
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd = ema12 - ema26
    macd_series = []
    for i in range(26, len(closes)):
        e12 = calc_ema(closes[:i], 12)
        e26 = calc_ema(closes[:i], 26)
        macd_series.append(e12 - e26)
    signal = calc_ema(macd_series[-9:], 9) if len(macd_series) >= 9 else macd
    return macd, signal, macd - signal

def calc_stochastic(closes, highs, lows, period=14):
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    if hh == ll: return 50
    return (closes[-1] - ll) / (hh - ll) * 100

def calc_atr(closes, highs, lows, period=14):
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    return sum(trs[-period:]) / period

def calc_adx(highs, lows, closes, period=14):
    """Average Directional Index — misura forza del trend"""
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(closes)):
        h_diff = highs[i] - highs[i-1]
        l_diff = lows[i-1] - lows[i]
        plus_dm.append(h_diff if h_diff > l_diff and h_diff > 0 else 0)
        minus_dm.append(l_diff if l_diff > h_diff and l_diff > 0 else 0)
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    atr = sum(trs[-period:]) / period
    if atr == 0: return 0
    plus_di  = (sum(plus_dm[-period:]) / period) / atr * 100
    minus_di = (sum(minus_dm[-period:]) / period) / atr * 100
    if plus_di + minus_di == 0: return 0
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100
    return dx

def calc_obv(closes, volumes):
    """On Balance Volume — conferma trend con volume"""
    obv = 0
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]:
            obv += volumes[i]
        elif closes[i] < closes[i-1]:
            obv -= volumes[i]
    return obv

def calc_williams_r(closes, highs, lows, period=14):
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    if hh == ll: return -50
    return (hh - closes[-1]) / (hh - ll) * -100

def detect_candle_patterns(opens, highs, lows, closes):
    """Riconosce pattern candele giapponesi"""
    patterns = []
    if len(closes) < 3: return patterns

    o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
    po, ph, pl, pc = opens[-2], highs[-2], lows[-2], closes[-2]
    body = abs(c - o)
    total = h - l if h != l else 0.001
    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l

    # Hammer (bullish)
    if lower_shadow > 2 * body and upper_shadow < body and c > o:
        patterns.append(("HAMMER", "bullish"))

    # Shooting Star (bearish)
    if upper_shadow > 2 * body and lower_shadow < body and c < o:
        patterns.append(("SHOOTING_STAR", "bearish"))

    # Bullish Engulfing
    if pc > po and c > o and c > po and o < pc:
        patterns.append(("BULLISH_ENGULFING", "bullish"))

    # Bearish Engulfing
    if pc < po and c < o and c < po and o > pc:
        patterns.append(("BEARISH_ENGULFING", "bearish"))

    # Doji (indecisione)
    if body / total < 0.1:
        patterns.append(("DOJI", "neutral"))

    # Morning Star (3 candele, molto bullish)
    if len(closes) >= 3:
        o2, c2 = opens[-3], closes[-3]
        if c2 < o2 and abs(pc - po) < abs(c2 - o2) * 0.3 and c > o and c > (o2 + c2) / 2:
            patterns.append(("MORNING_STAR", "bullish"))

    return patterns

def market_regime(closes, highs, lows):
    ema50  = calc_ema(closes[-60:],  50)
    ema200 = calc_ema(closes[-100:], 100)
    adx    = calc_adx(highs, lows, closes)

    if adx > 25:
        regime = "TRENDING"
        direction = "BULL" if ema50 > ema200 else "BEAR"
    else:
        regime = "SIDEWAYS"
        direction = "NEUTRAL"
    return regime, direction, adx

def support_resistance(closes, highs, lows, lookback=50):
    recent_highs = highs[-lookback:]
    recent_lows  = lows[-lookback:]
    resistance = max(recent_highs)
    support    = min(recent_lows)
    return support, resistance

def multi_timeframe_bias():
    """Analizza 15min + 1h + 4h per conferma direzione"""
    scores = {"bull": 0, "bear": 0}
    for tf in ["15m", "1H", "4H"]:
        try:
            _, h, l, c, _ = get_candles(granularity=tf, limit=50)
            ema9  = calc_ema(c, 9)
            ema21 = calc_ema(c, 21)
            rsi   = calc_rsi(c)
            if ema9 > ema21 and rsi > 50: scores["bull"] += 1
            elif ema9 < ema21 and rsi < 50: scores["bear"] += 1
        except:
            pass
    if scores["bull"] >= 2: return "BULL"
    elif scores["bear"] >= 2: return "BEAR"
    return "MIXED"

# ═══════════════════════════════════════════════════════════════
#  KELLY CRITERION — sizing ottimale
# ═══════════════════════════════════════════════════════════════
def kelly_size(trade_log, base_amount=TRADE_USDT):
    if len(trade_log) < 10:
        return base_amount
    recent = [t for t in trade_log[-20:] if "profit" in t]
    if not recent: return base_amount
    wins   = [t["profit"] for t in recent if t["profit"] > 0]
    losses = [abs(t["profit"]) for t in recent if t["profit"] <= 0]
    if not losses: return base_amount * 1.5
    win_rate = len(wins) / len(recent)
    avg_win  = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0.01
    kelly    = win_rate - (1 - win_rate) / (avg_win / avg_loss)
    kelly    = max(0.1, min(kelly, 0.5))  # clamp 10%-50%
    return round(base_amount * kelly * 2, 2)

# ═══════════════════════════════════════════════════════════════
#  ADATTAMENTO AUTOMATICO PARAMETRI
# ═══════════════════════════════════════════════════════════════
def adapt_params(trade_log):
    base_sl = 0.03
    base_tp = 0.05
    if len(trade_log) < 5:
        return 30, 70, base_sl, base_tp

    recent   = trade_log[-10:]
    wins     = sum(1 for t in recent if t.get("profit", 0) > 0)
    win_rate = wins / len(recent)

    if win_rate > 0.65:
        return 33, 67, 0.025, 0.065   # più aggressivo
    elif win_rate < 0.35:
        return 25, 75, 0.02, 0.04     # più conservativo
    return 30, 70, base_sl, base_tp

# ═══════════════════════════════════════════════════════════════
#  PUMP & DUMP DETECTOR
# ═══════════════════════════════════════════════════════════════
def detect_manipulation(closes, volumes):
    if len(closes) < 5: return False
    price_change = abs(closes[-1] - closes[-5]) / closes[-5]
    avg_vol = sum(volumes[-20:-5]) / 15 if len(volumes) > 20 else sum(volumes) / len(volumes)
    vol_spike = volumes[-1] / avg_vol if avg_vol > 0 else 1
    # Spike di prezzo >5% con volume 5x = possibile manipolazione
    if price_change > 0.05 and vol_spike > 5:
        return True
    return False

# ═══════════════════════════════════════════════════════════════
#  ORDINI
# ═══════════════════════════════════════════════════════════════
def place_order(side, amount_usdt):
    price = get_price()
    qty   = round(amount_usdt / price, 6)
    path  = "/api/v2/spot/trade/place-order"
    body  = {"symbol": SYMBOL, "side": side, "orderType": "market", "force": "gtc", "size": str(qty)}
    headers = get_headers("POST", path, body)
    r = requests.post(BASE_URL + path, headers=headers, json=body, timeout=10)
    return r.json(), price

# ═══════════════════════════════════════════════════════════════
#  LOG & STATS
# ═══════════════════════════════════════════════════════════════
def log(msg):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open("bot_log.txt", "a") as f:
        f.write(line + "\n")

def print_stats(trade_log):
    trades = [t for t in trade_log if "profit" in t]
    if not trades: return
    wins      = sum(1 for t in trades if t["profit"] > 0)
    total_pnl = sum(t["profit"] for t in trades) * 100
    best      = max(t["profit"] for t in trades) * 100
    worst     = min(t["profit"] for t in trades) * 100
    log(f"📊 STATS | Trade: {len(trades)} | Win: {wins/len(trades)*100:.0f}% | P&L: {total_pnl:.2f}% | Best: +{best:.2f}% | Worst: {worst:.2f}%")

# ═══════════════════════════════════════════════════════════════
#  BOT PRINCIPALE
# ═══════════════════════════════════════════════════════════════
def run_bot():
    log("=" * 65)
    log("🤖  BOT AI BITGET — VERSIONE ELITE — AVVIATO")
    log("=" * 65)

    position      = None
    entry_price   = None
    highest_price = None
    trade_log     = []
    cycle         = 0

    while True:
        try:
            cycle += 1
            opens, highs, lows, closes, volumes = get_candles()
            price = get_price()

            # ── INDICATORI ────────────────────────────────────
            rsi                    = calc_rsi(closes)
            ema9                   = calc_ema(closes, 9)
            ema21                  = calc_ema(closes, 21)
            ema50                  = calc_ema(closes, 50)
            ema200                 = calc_ema(closes, 200)
            bb_low, bb_mid, bb_up  = calc_bollinger(closes)
            macd, sig, hist        = calc_macd(closes)
            stoch                  = calc_stochastic(closes, highs, lows)
            atr                    = calc_atr(closes, highs, lows)
            adx                    = calc_adx(highs, lows, closes)
            obv                    = calc_obv(closes, volumes)
            will_r                 = calc_williams_r(closes, highs, lows)
            patterns               = detect_candle_patterns(opens, highs, lows, closes)
            regime, direction, _   = market_regime(closes, highs, lows)
            support, resistance    = support_resistance(closes, highs, lows)
            mtf_bias               = multi_timeframe_bias()
            orderbook_pressure     = get_orderbook()
            funding_rate           = get_funding_rate()
            fear_greed, fg_label   = get_crypto_fear_greed()
            manipulation           = detect_manipulation(closes, volumes)
            rsi_buy, rsi_sell, sl, tp = adapt_params(trade_log)
            trade_size             = kelly_size(trade_log)

            log(f"──── Ciclo #{cycle} ────────────────────────────────────")
            log(f"💰 Prezzo: {price:.2f} | ATR: {atr:.1f} | ADX: {adx:.1f} | OBV: {obv:.0f}")
            log(f"📈 RSI: {rsi:.1f} | Stoch: {stoch:.1f} | Williams%R: {will_r:.1f}")
            log(f"📉 MACD hist: {hist:.2f} | EMA9/21/50/200: {ema9:.0f}/{ema21:.0f}/{ema50:.0f}/{ema200:.0f}")
            log(f"📊 BB: {bb_low:.0f}-{bb_up:.0f} | Support: {support:.0f} | Resist: {resistance:.0f}")
            log(f"🌐 Fear&Greed: {fear_greed} ({fg_label}) | Funding: {funding_rate:.4f} | OrderBook: {orderbook_pressure:.2f}x")
            log(f"🔀 Regime: {regime}/{direction} | MTF: {mtf_bias} | Posizione: {position} | Size: ${trade_size}")
            if patterns:
                log(f"🕯️  Pattern: {[p[0] for p in patterns]}")
            if manipulation:
                log("⚠️  MANIPOLAZIONE RILEVATA — skip ciclo")
                time.sleep(CHECK_EVERY)
                continue

            # ── GESTIONE POSIZIONE APERTA ─────────────────────
            if position == "long" and entry_price:
                if highest_price is None or price > highest_price:
                    highest_price = price
                change   = (price - entry_price) / entry_price
                drawdown = (price - highest_price) / highest_price

                if change > 0.02 and drawdown <= -TRAIL_PCT:
                    log(f"🔴 TRAILING STOP | Max: {highest_price:.2f} | P&L: {change*100:.2f}%")
                    res, _ = place_order("sell", trade_size)
                    trade_log.append({"side": "sell", "reason": "trailing", "profit": change})
                    log(f"Ordine: {res}")
                    position = None; entry_price = None; highest_price = None
                    print_stats(trade_log); time.sleep(CHECK_EVERY); continue

                if change <= -sl:
                    log(f"🔴 STOP LOSS | Perdita: {change*100:.2f}%")
                    res, _ = place_order("sell", trade_size)
                    trade_log.append({"side": "sell", "reason": "stop_loss", "profit": change})
                    log(f"Ordine: {res}")
                    position = None; entry_price = None; highest_price = None
                    print_stats(trade_log); time.sleep(CHECK_EVERY); continue

                if change >= tp:
                    log(f"🟢 TAKE PROFIT | Guadagno: {change*100:.2f}%")
                    res, _ = place_order("sell", trade_size)
                    trade_log.append({"side": "sell", "reason": "take_profit", "profit": change})
                    log(f"Ordine: {res}")
                    position = None; entry_price = None; highest_price = None
                    print_stats(trade_log); time.sleep(CHECK_EVERY); continue

            # ── SCORING BUY ───────────────────────────────────
            buy = 0
            if rsi < rsi_buy:                          buy += 2
            if stoch < 20:                             buy += 2
            if will_r < -80:                           buy += 1
            if price < bb_low:                         buy += 2
            if hist > 0:                               buy += 1
            if ema9 > ema21:                           buy += 1
            if ema50 > ema200:                         buy += 1
            if direction == "BULL":                    buy += 2
            if mtf_bias == "BULL":                     buy += 2
            if orderbook_pressure > 1.3:               buy += 1
            if fear_greed < 25:                        buy += 2  # extreme fear = buy
            if funding_rate < -0.001:                  buy += 1  # funding negativo = longs scarsi
            if price < support * 1.01:                 buy += 1
            if any(p[1] == "bullish" for p in patterns): buy += 2
            if adx > 25 and direction == "BULL":       buy += 1

            # ── SCORING SELL ──────────────────────────────────
            sell = 0
            if rsi > rsi_sell:                         sell += 2
            if stoch > 80:                             sell += 2
            if will_r > -20:                           sell += 1
            if price > bb_up:                          sell += 2
            if hist < 0:                               sell += 1
            if ema9 < ema21:                           sell += 1
            if ema50 < ema200:                         sell += 1
            if direction == "BEAR":                    sell += 2
            if mtf_bias == "BEAR":                     sell += 2
            if orderbook_pressure < 0.7:               sell += 1
            if fear_greed > 75:                        sell += 2  # extreme greed = sell
            if funding_rate > 0.001:                   sell += 1
            if price > resistance * 0.99:              sell += 1
            if any(p[1] == "bearish" for p in patterns): sell += 2
            if adx > 25 and direction == "BEAR":       sell += 1

            log(f"🎯 Score BUY: {buy}/24 | Score SELL: {sell}/24 | Soglia: 12")

            # ── ESEGUI ────────────────────────────────────────
            if buy >= 12 and position != "long":
                log(f"🟢 COMPRO! Score: {buy}/24 | Size: ${trade_size}")
                res, entry_price = place_order("buy", trade_size)
                highest_price = entry_price
                trade_log.append({"side": "buy", "score": buy, "price": entry_price})
                log(f"Ordine: {res} | Entry: {entry_price:.2f}")
                position = "long"

            elif sell >= 12 and position == "long":
                log(f"🔴 VENDO! Score: {sell}/24")
                res, exit_price = place_order("sell", trade_size)
                profit = (exit_price - entry_price) / entry_price if entry_price else 0
                trade_log.append({"side": "sell", "score": sell, "profit": profit})
                log(f"Ordine: {res} | P&L: {profit*100:.2f}%")
                position = None; entry_price = None; highest_price = None
                print_stats(trade_log)

            else:
                log(f"⏳ Nessun segnale sufficiente — aspetto")

        except Exception as e:
            log(f"❌ ERRORE: {e}")

        time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    run_bot()

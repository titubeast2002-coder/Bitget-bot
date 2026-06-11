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
TRAIL_PCT     = 0.015
CHECK_EVERY   = 900

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
#  DATI DI MERCATO — con controlli robusti
# ═══════════════════════════════════════════════════════════════
def get_price():
    r = requests.get(f"{BASE_URL}/api/v2/spot/market/tickers?symbol={SYMBOL}", timeout=10)
    data = r.json()
    if not data or "data" not in data or not data["data"]:
        raise Exception("Risposta vuota da tickers")
    return float(data["data"][0]["lastPr"])

def get_candles(granularity="15min", limit=200):
    url = f"{BASE_URL}/api/v2/spot/market/candles?symbol={SYMBOL}&granularity={granularity}&limit={limit}"
    r = requests.get(url, timeout=10)
    data = r.json()
    if not data or "data" not in data or not data["data"]:
        raise Exception(f"Risposta vuota da candles ({granularity})")
    candles = data["data"]
    opens   = [float(c[1]) for c in candles]
    highs   = [float(c[2]) for c in candles]
    lows    = [float(c[3]) for c in candles]
    closes  = [float(c[4]) for c in candles]
    volumes = [float(c[5]) for c in candles]
    return opens, highs, lows, closes, volumes

def get_orderbook():
    try:
        r = requests.get(f"{BASE_URL}/api/v2/spot/market/orderbook?symbol={SYMBOL}&limit=20", timeout=10)
        data = r.json()
        if not data or "data" not in data:
            return 1.0
        bids = data["data"].get("bids", [])
        asks = data["data"].get("asks", [])
        bid_vol = sum(float(b[1]) for b in bids[:10])
        ask_vol = sum(float(a[1]) for a in asks[:10])
        return bid_vol / ask_vol if ask_vol > 0 else 1.0
    except:
        return 1.0

def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        value = int(r.json()["data"][0]["value"])
        label = r.json()["data"][0]["value_classification"]
        return value, label
    except:
        return 50, "Neutral"

# ═══════════════════════════════════════════════════════════════
#  INDICATORI
# ═══════════════════════════════════════════════════════════════
def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
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
    if not closes or len(closes) < 2:
        return closes[-1] if closes else 0
    period = min(period, len(closes))
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_bollinger(closes, period=20):
    if len(closes) < period:
        period = len(closes)
    recent = closes[-period:]
    mean = sum(recent) / period
    std = math.sqrt(sum((x - mean)**2 for x in recent) / period)
    return mean - 2*std, mean, mean + 2*std

def calc_macd(closes):
    if len(closes) < 26:
        return 0, 0, 0
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
    if len(closes) < period:
        return 50
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    if hh == ll: return 50
    return (closes[-1] - ll) / (hh - ll) * 100

def calc_atr(closes, highs, lows, period=14):
    if len(closes) < 2:
        return 0
    trs = []
    for i in range(1, len(closes)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
    period = min(period, len(trs))
    return sum(trs[-period:]) / period

def calc_williams_r(closes, highs, lows, period=14):
    if len(closes) < period:
        return -50
    hh = max(highs[-period:])
    ll = min(lows[-period:])
    if hh == ll: return -50
    return (hh - closes[-1]) / (hh - ll) * -100

def market_regime(closes, highs, lows):
    ema50  = calc_ema(closes[-60:], 50) if len(closes) >= 50 else calc_ema(closes, len(closes))
    ema200 = calc_ema(closes[-200:], 200) if len(closes) >= 200 else calc_ema(closes, len(closes))
    if ema50 > ema200 * 1.01: return "BULL"
    elif ema50 < ema200 * 0.99: return "BEAR"
    return "SIDEWAYS"

def detect_patterns(opens, highs, lows, closes):
    patterns = []
    if len(closes) < 2: return patterns
    o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
    po, ph, pl, pc = opens[-2], highs[-2], lows[-2], closes[-2]
    body = abs(c - o)
    total = h - l if h != l else 0.001
    lower_shadow = min(o, c) - l
    upper_shadow = h - max(o, c)
    if lower_shadow > 2 * body and upper_shadow < body and c > o:
        patterns.append(("HAMMER", "bullish"))
    if upper_shadow > 2 * body and lower_shadow < body and c < o:
        patterns.append(("SHOOTING_STAR", "bearish"))
    if pc > po and c > o and c > po and o < pc:
        patterns.append(("BULLISH_ENGULFING", "bullish"))
    if pc < po and c < o and c < po and o > pc:
        patterns.append(("BEARISH_ENGULFING", "bearish"))
    if body / total < 0.1:
        patterns.append(("DOJI", "neutral"))
    return patterns

def adapt_params(trade_log):
    if len(trade_log) < 5:
        return 30, 70, 0.03, 0.05
    recent = trade_log[-10:]
    wins = sum(1 for t in recent if t.get("profit", 0) > 0)
    win_rate = wins / len(recent)
    if win_rate > 0.65: return 33, 67, 0.025, 0.06
    elif win_rate < 0.35: return 25, 75, 0.02, 0.04
    return 30, 70, 0.03, 0.05

def kelly_size(trade_log):
    if len(trade_log) < 10: return TRADE_USDT
    recent = [t for t in trade_log[-20:] if "profit" in t]
    if not recent: return TRADE_USDT
    wins   = [t["profit"] for t in recent if t["profit"] > 0]
    losses = [abs(t["profit"]) for t in recent if t["profit"] <= 0]
    if not losses: return TRADE_USDT * 1.5
    win_rate = len(wins) / len(recent)
    avg_win  = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses)
    kelly    = win_rate - (1 - win_rate) / (avg_win / avg_loss) if avg_loss > 0 else 0.25
    kelly    = max(0.1, min(kelly, 0.5))
    return round(TRADE_USDT * kelly * 2, 2)

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
#  LOG
# ═══════════════════════════════════════════════════════════════
def log(msg):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open("bot_log.txt", "a") as f:
        f.write(line + "\n")

def print_stats(trade_log):
    trades = [t for t in trade_log if "profit" in t]
    if not trades: return
    wins = sum(1 for t in trades if t["profit"] > 0)
    total_pnl = sum(t["profit"] for t in trades) * 100
    log(f"📊 STATS | Trade: {len(trades)} | Win: {wins/len(trades)*100:.0f}% | P&L: {total_pnl:.2f}%")

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
            opens, highs, lows, closes, volumes = get_candles(granularity="15min")
            price = get_price()

            rsi                    = calc_rsi(closes)
            ema9                   = calc_ema(closes, 9)
            ema21                  = calc_ema(closes, 21)
            ema50                  = calc_ema(closes, 50)
            ema200                 = calc_ema(closes, 200)
            bb_low, bb_mid, bb_up  = calc_bollinger(closes)
            macd, sig, hist        = calc_macd(closes)
            stoch                  = calc_stochastic(closes, highs, lows)
            atr                    = calc_atr(closes, highs, lows)
            will_r                 = calc_williams_r(closes, highs, lows)
            patterns               = detect_patterns(opens, highs, lows, closes)
            regime                 = market_regime(closes, highs, lows)
            ob_pressure            = get_orderbook()
            fear_greed, fg_label   = get_fear_greed()
            rsi_buy, rsi_sell, sl, tp = adapt_params(trade_log)
            trade_size             = kelly_size(trade_log)

            log(f"──── Ciclo #{cycle} ─────────────────────────────────")
            log(f"💰 Prezzo: {price:.2f} | RSI: {rsi:.1f} | Stoch: {stoch:.1f} | Williams: {will_r:.1f}")
            log(f"📈 EMA 9/21/50/200: {ema9:.0f}/{ema21:.0f}/{ema50:.0f}/{ema200:.0f}")
            log(f"📉 BB: {bb_low:.0f}-{bb_up:.0f} | MACD hist: {hist:.2f} | ATR: {atr:.2f}")
            log(f"🌐 Fear&Greed: {fear_greed} ({fg_label}) | OrderBook: {ob_pressure:.2f}x | Regime: {regime}")
            if patterns:
                log(f"🕯️  Pattern: {[p[0] for p in patterns]}")

            # ── GESTIONE POSIZIONE ────────────────────────────
            if position == "long" and entry_price:
                if highest_price is None or price > highest_price:
                    highest_price = price
                change   = (price - entry_price) / entry_price
                drawdown = (price - highest_price) / highest_price

                if change > 0.02 and drawdown <= -TRAIL_PCT:
                    log(f"🔴 TRAILING STOP | P&L: {change*100:.2f}%")
                    res, _ = place_order("sell", trade_size)
                    trade_log.append({"side": "sell", "reason": "trailing", "profit": change})
                    position = None; entry_price = None; highest_price = None
                    print_stats(trade_log); time.sleep(CHECK_EVERY); continue

                if change <= -sl:
                    log(f"🔴 STOP LOSS | Perdita: {change*100:.2f}%")
                    res, _ = place_order("sell", trade_size)
                    trade_log.append({"side": "sell", "reason": "stop_loss", "profit": change})
                    position = None; entry_price = None; highest_price = None
                    print_stats(trade_log); time.sleep(CHECK_EVERY); continue

                if change >= tp:
                    log(f"🟢 TAKE PROFIT | Guadagno: {change*100:.2f}%")
                    res, _ = place_order("sell", trade_size)
                    trade_log.append({"side": "sell", "reason": "take_profit", "profit": change})
                    position = None; entry_price = None; highest_price = None
                    print_stats(trade_log); time.sleep(CHECK_EVERY); continue

                log(f"📊 Posizione aperta | Entry: {entry_price:.2f} | P&L: {change*100:.2f}%")

            # ── SCORING ───────────────────────────────────────
            buy = 0
            if rsi < rsi_buy:                            buy += 2
            if stoch < 20:                               buy += 2
            if will_r < -80:                             buy += 1
            if price < bb_low:                           buy += 2
            if hist > 0:                                 buy += 1
            if ema9 > ema21:                             buy += 1
            if ema50 > ema200:                           buy += 1
            if regime == "BULL":                         buy += 2
            if ob_pressure > 1.3:                        buy += 1
            if fear_greed < 25:                          buy += 2
            if any(p[1] == "bullish" for p in patterns): buy += 2

            sell = 0
            if rsi > rsi_sell:                           sell += 2
            if stoch > 80:                               sell += 2
            if will_r > -20:                             sell += 1
            if price > bb_up:                            sell += 2
            if hist < 0:                                 sell += 1
            if ema9 < ema21:                             sell += 1
            if ema50 < ema200:                           sell += 1
            if regime == "BEAR":                         sell += 2
            if ob_pressure < 0.7:                        sell += 1
            if fear_greed > 75:                          sell += 2
            if any(p[1] == "bearish" for p in patterns): sell += 2

            log(f"🎯 BUY: {buy}/21 | SELL: {sell}/21 | Soglia: 10")

            if buy >= 10 and position != "long":
                log(f"🟢 COMPRO! Score: {buy}/21 | Size: ${trade_size}")
                res, entry_price = place_order("buy", trade_size)
                highest_price = entry_price
                trade_log.append({"side": "buy", "score": buy, "price": entry_price})
                log(f"Ordine: {res}")
                position = "long"

            elif sell >= 10 and position == "long":
                log(f"🔴 VENDO! Score: {sell}/21")
                res, exit_price = place_order("sell", trade_size)
                profit = (exit_price - entry_price) / entry_price if entry_price else 0
                trade_log.append({"side": "sell", "score": sell, "profit": profit})
                log(f"Ordine: {res} | P&L: {profit*100:.2f}%")
                position = None; entry_price = None; highest_price = None
                print_stats(trade_log)

            else:
                log("⏳ Nessun segnale sufficiente — aspetto")

        except Exception as e:
            log(f"❌ ERRORE: {e}")

        time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    run_bot()

import hashlib
import hmac
import time
import requests
import json
import os
import math
import statistics
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
#  CONFIGURAZIONE
# ═══════════════════════════════════════════════════════════════
API_KEY           = os.environ.get("API_KEY")
SECRET_KEY        = os.environ.get("SECRET_KEY")
PASSPHRASE        = os.environ.get("PASSPHRASE")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

BASE_URL    = "https://api.bitget.com"
SYMBOL      = "BTCUSDT"
TRADE_USDT  = 20
TRAIL_PCT   = 0.015
CHECK_EVERY = 300  # 5 minuti

MEMORY_FILE = "ai_memory.json"

# ═══════════════════════════════════════════════════════════════
#  MEMORIA AI — il bot ricorda tutto
# ═══════════════════════════════════════════════════════════════
def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return {
        "trades": [],
        "lessons": [],
        "params": {
            "stop_loss": 0.03,
            "take_profit": 0.05,
            "buy_threshold": 12,
            "trade_size": TRADE_USDT
        },
        "stats": {
            "total_trades": 0,
            "wins": 0,
            "total_pnl": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0
        },
        "cycle": 0
    }

def save_memory(memory):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)

# ═══════════════════════════════════════════════════════════════
#  FIRMA API BITGET
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
    data = r.json()
    if not data or "data" not in data or not data["data"]:
        raise Exception("Risposta vuota da tickers")
    return float(data["data"][0]["lastPr"])

def get_candles(granularity="5min", limit=100):
    url = f"{BASE_URL}/api/v2/spot/market/candles?symbol={SYMBOL}&granularity={granularity}&limit={limit}"
    r = requests.get(url, timeout=10)
    data = r.json()
    if not data or "data" not in data or not data["data"]:
        raise Exception("Risposta vuota da candles")
    candles = data["data"]
    opens   = [float(c[1]) for c in candles]
    highs   = [float(c[2]) for c in candles]
    lows    = [float(c[3]) for c in candles]
    closes  = [float(c[4]) for c in candles]
    volumes = [float(c[5]) for c in candles]
    return opens, highs, lows, closes, volumes

def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        return int(r.json()["data"][0]["value"]), r.json()["data"][0]["value_classification"]
    except:
        return 50, "Neutral"

def get_orderbook_pressure():
    try:
        r = requests.get(f"{BASE_URL}/api/v2/spot/market/orderbook?symbol={SYMBOL}&limit=20", timeout=10)
        data = r.json()
        if not data or "data" not in data: return 1.0
        bids = data["data"].get("bids", [])
        asks = data["data"].get("asks", [])
        bid_vol = sum(float(b[1]) for b in bids[:10])
        ask_vol = sum(float(a[1]) for a in asks[:10])
        return bid_vol / ask_vol if ask_vol > 0 else 1.0
    except:
        return 1.0

# ═══════════════════════════════════════════════════════════════
#  INDICATORI
# ═══════════════════════════════════════════════════════════════
def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return 50
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
    if not closes: return 0
    period = min(period, len(closes))
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
    return ema

def calc_bollinger(closes, period=20):
    period = min(period, len(closes))
    recent = closes[-period:]
    mean = sum(recent) / period
    std = math.sqrt(sum((x - mean)**2 for x in recent) / period)
    return mean - 2*std, mean, mean + 2*std

def calc_macd(closes):
    if len(closes) < 26: return 0, 0, 0
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

def calc_atr(closes, highs, lows, period=14):
    if len(closes) < 2: return 0
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, len(closes))]
    period = min(period, len(trs))
    return sum(trs[-period:]) / period

def mean_reversion_signal(closes, period=50):
    if len(closes) < period: return 0
    mean = sum(closes[-period:]) / period
    std  = statistics.stdev(closes[-period:])
    z = (closes[-1] - mean) / std if std > 0 else 0
    if z < -2: return 2
    if z < -1.5: return 1
    if z > 2: return -2
    if z > 1.5: return -1
    return 0

def momentum_signal(closes, period=20):
    if len(closes) < period + 1: return 0
    mom = (closes[-1] - closes[-period]) / closes[-period] * 100
    if mom > 3: return 2
    if mom > 1: return 1
    if mom < -3: return -2
    if mom < -1: return -1
    return 0

def ichimoku_signal(highs, lows, closes):
    if len(closes) < 52: return 0
    tenkan = (max(highs[-9:]) + min(lows[-9:])) / 2
    kijun  = (max(highs[-26:]) + min(lows[-26:])) / 2
    span_a = (tenkan + kijun) / 2
    span_b = (max(highs[-52:]) + min(lows[-52:])) / 2
    price  = closes[-1]
    cloud_top = max(span_a, span_b)
    cloud_bot = min(span_a, span_b)
    if price > cloud_top and tenkan > kijun: return 2
    if price > cloud_top: return 1
    if price < cloud_bot and tenkan < kijun: return -2
    if price < cloud_bot: return -1
    return 0

# ═══════════════════════════════════════════════════════════════
#  CERVELLO AI — Claude decide
# ═══════════════════════════════════════════════════════════════
def ai_decision(market_data, memory, position):
    recent_trades = memory["trades"][-5:] if memory["trades"] else []
    lessons = memory["lessons"][-5:] if memory["lessons"] else []
    stats = memory["stats"]

    prompt = f"""Sei un AI trader esperto su Bitcoin. Analizza questi dati e decidi cosa fare.

DATI MERCATO ATTUALI:
- Prezzo BTC: ${market_data['price']:.2f}
- RSI (14): {market_data['rsi']:.1f}
- MACD histogram: {market_data['macd_hist']:.4f}
- Bollinger: Low={market_data['bb_low']:.0f} / Mid={market_data['bb_mid']:.0f} / High={market_data['bb_up']:.0f}
- EMA 9/21/50: {market_data['ema9']:.0f}/{market_data['ema21']:.0f}/{market_data['ema50']:.0f}
- ATR: {market_data['atr']:.2f}
- Mean Reversion signal: {market_data['mr_signal']} (-2=forte sell, 0=neutro, 2=forte buy)
- Momentum signal: {market_data['mom_signal']}
- Ichimoku signal: {market_data['ichi_signal']}
- Fear & Greed Index: {market_data['fear_greed']} ({market_data['fg_label']})
- Orderbook pressure: {market_data['ob_pressure']:.2f} (>1=piu compratori, <1=piu venditori)

POSIZIONE ATTUALE: {position if position else 'Nessuna posizione aperta'}
{f"Entry price: ${market_data.get('entry_price', 0):.2f}" if position else ""}
{f"P&L attuale: {market_data.get('current_pnl', 0):.2f}%" if position else ""}

STORICO RECENTE ({len(recent_trades)} trade):
{json.dumps(recent_trades, indent=2) if recent_trades else "Nessun trade ancora"}

LEZIONI APPRESE:
{chr(10).join(lessons) if lessons else "Nessuna lezione ancora"}

STATISTICHE:
- Trade totali: {stats['total_trades']}
- Win rate: {stats['wins']}/{stats['total_trades']} ({stats['wins']/max(stats['total_trades'],1)*100:.0f}%)
- P&L totale: {stats['total_pnl']:.2f}%

PARAMETRI ATTUALI:
- Stop loss: {memory['params']['stop_loss']*100:.1f}%
- Take profit: {memory['params']['take_profit']*100:.1f}%
- Trade size: ${memory['params']['trade_size']}

Rispondi SOLO in questo formato JSON esatto:
{{
  "action": "BUY" o "SELL" o "HOLD",
  "confidence": numero da 0 a 100,
  "reasoning": "spiegazione breve in italiano",
  "lesson": "cosa hai imparato da questa analisi",
  "suggested_params": {{
    "stop_loss": numero es 0.03,
    "take_profit": numero es 0.05,
    "trade_size": numero es 20
  }}
}}"""

    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        result = response.json()
        text = result["content"][0]["text"]
        # Pulisce e parsa il JSON
        text = text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except Exception as e:
        return {
            "action": "HOLD",
            "confidence": 0,
            "reasoning": f"Errore AI: {e}",
            "lesson": "",
            "suggested_params": memory["params"]
        }

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

# ═══════════════════════════════════════════════════════════════
#  BOT PRINCIPALE
# ═══════════════════════════════════════════════════════════════
def run_bot():
    log("=" * 65)
    log("🤖  BOT AI CLAUDE — VERSIONE AUTONOMA — AVVIATO")
    log("=" * 65)

    memory        = load_memory()
    position      = None
    entry_price   = None
    highest_price = None

    while True:
        try:
            memory["cycle"] += 1
            cycle = memory["cycle"]

            opens, highs, lows, closes, volumes = get_candles()
            price = get_price()

            rsi                   = calc_rsi(closes)
            ema9                  = calc_ema(closes, 9)
            ema21                 = calc_ema(closes, 21)
            ema50                 = calc_ema(closes, 50)
            bb_low, bb_mid, bb_up = calc_bollinger(closes)
            macd, sig, hist       = calc_macd(closes)
            atr                   = calc_atr(closes, highs, lows)
            mr_signal             = mean_reversion_signal(closes)
            mom_signal            = momentum_signal(closes)
            ichi_signal           = ichimoku_signal(highs, lows, closes)
            fear_greed, fg_label  = get_fear_greed()
            ob_pressure           = get_orderbook_pressure()

            current_pnl = 0
            if position == "long" and entry_price:
                current_pnl = (price - entry_price) / entry_price * 100
                if highest_price is None or price > highest_price:
                    highest_price = price
                change   = (price - entry_price) / entry_price
                drawdown = (price - highest_price) / highest_price

                # Stop loss e trailing automatici (sicurezza)
                sl = memory["params"]["stop_loss"]
                tp = memory["params"]["take_profit"]
                trade_size = memory["params"]["trade_size"]

                if change > 0.02 and drawdown <= -TRAIL_PCT:
                    log(f"🔴 TRAILING STOP automatico | P&L: {change*100:.2f}%")
                    res, _ = place_order("sell", trade_size)
                    memory["trades"].append({"side": "sell", "reason": "trailing_stop", "profit": round(change*100, 2), "price": price})
                    memory["stats"]["total_trades"] += 1
                    memory["stats"]["total_pnl"] += change * 100
                    if change > 0: memory["stats"]["wins"] += 1
                    memory["stats"]["best_trade"] = max(memory["stats"]["best_trade"], change*100)
                    memory["stats"]["worst_trade"] = min(memory["stats"]["worst_trade"], change*100)
                    save_memory(memory)
                    position = None; entry_price = None; highest_price = None
                    time.sleep(CHECK_EVERY); continue

                if change <= -sl:
                    log(f"🔴 STOP LOSS automatico | Perdita: {change*100:.2f}%")
                    res, _ = place_order("sell", trade_size)
                    memory["trades"].append({"side": "sell", "reason": "stop_loss", "profit": round(change*100, 2), "price": price})
                    memory["stats"]["total_trades"] += 1
                    memory["stats"]["total_pnl"] += change * 100
                    if change > 0: memory["stats"]["wins"] += 1
                    memory["stats"]["worst_trade"] = min(memory["stats"]["worst_trade"], change*100)
                    save_memory(memory)
                    position = None; entry_price = None; highest_price = None
                    time.sleep(CHECK_EVERY); continue

            # Prepara dati per Claude
            market_data = {
                "price": price,
                "rsi": rsi,
                "ema9": ema9, "ema21": ema21, "ema50": ema50,
                "bb_low": bb_low, "bb_mid": bb_mid, "bb_up": bb_up,
                "macd_hist": hist,
                "atr": atr,
                "mr_signal": mr_signal,
                "mom_signal": mom_signal,
                "ichi_signal": ichi_signal,
                "fear_greed": fear_greed,
                "fg_label": fg_label,
                "ob_pressure": ob_pressure,
                "entry_price": entry_price or 0,
                "current_pnl": current_pnl
            }

            log(f"──── Ciclo #{cycle} ─────────────────────────────────")
            log(f"💰 Prezzo: {price:.2f} | RSI: {rsi:.1f} | ATR: {atr:.2f}")
            log(f"🧠 Chiedo a Claude AI...")

            # Claude decide
            decision = ai_decision(market_data, memory, position)

            action     = decision.get("action", "HOLD")
            confidence = decision.get("confidence", 0)
            reasoning  = decision.get("reasoning", "")
            lesson     = decision.get("lesson", "")
            new_params = decision.get("suggested_params", {})

            log(f"🤖 Claude dice: {action} (confidenza: {confidence}%)")
            log(f"💭 Ragionamento: {reasoning}")

            # Salva lezione
            if lesson:
                memory["lessons"].append(f"[Ciclo {cycle}] {lesson}")
                if len(memory["lessons"]) > 50:
                    memory["lessons"] = memory["lessons"][-50:]

            # Aggiorna parametri suggeriti da Claude (auto-miglioramento)
            if new_params and confidence > 70:
                old_params = memory["params"].copy()
                memory["params"]["stop_loss"]   = max(0.01, min(0.05, new_params.get("stop_loss", memory["params"]["stop_loss"])))
                memory["params"]["take_profit"] = max(0.02, min(0.10, new_params.get("take_profit", memory["params"]["take_profit"])))
                memory["params"]["trade_size"]  = max(5, min(TRADE_USDT, new_params.get("trade_size", memory["params"]["trade_size"])))
                if memory["params"] != old_params:
                    log(f"⚙️  Auto-miglioramento parametri: SL={memory['params']['stop_loss']*100:.1f}% TP={memory['params']['take_profit']*100:.1f}% Size=${memory['params']['trade_size']}")

            trade_size = memory["params"]["trade_size"]

            # Esegui decisione
            if action == "BUY" and confidence >= 65 and position != "long":
                log(f"🟢 COMPRO per ordine di Claude! Confidenza: {confidence}%")
                res, entry_price = place_order("buy", trade_size)
                highest_price = entry_price
                memory["trades"].append({"side": "buy", "reason": "claude_ai", "confidence": confidence, "price": entry_price})
                log(f"Ordine eseguito: {res} | Entry: {entry_price:.2f}")
                position = "long"

            elif action == "SELL" and confidence >= 65 and position == "long":
                log(f"🔴 VENDO per ordine di Claude! Confidenza: {confidence}%")
                res, exit_price = place_order("sell", trade_size)
                profit = (exit_price - entry_price) / entry_price if entry_price else 0
                memory["trades"].append({"side": "sell", "reason": "claude_ai", "confidence": confidence, "profit": round(profit*100, 2), "price": exit_price})
                memory["stats"]["total_trades"] += 1
                memory["stats"]["total_pnl"] += profit * 100
                if profit > 0:
                    memory["stats"]["wins"] += 1
                    log(f"✅ Trade vincente! P&L: +{profit*100:.2f}%")
                else:
                    log(f"❌ Trade perdente. P&L: {profit*100:.2f}%")
                memory["stats"]["best_trade"]  = max(memory["stats"]["best_trade"], profit*100)
                memory["stats"]["worst_trade"] = min(memory["stats"]["worst_trade"], profit*100)
                position = None; entry_price = None; highest_price = None

            else:
                log(f"⏳ HOLD — Claude aspetta momento migliore")

            # Stats ogni 10 cicli
            if cycle % 10 == 0:
                s = memory["stats"]
                wr = s["wins"]/max(s["total_trades"],1)*100
                log(f"📊 STATS | Trade: {s['total_trades']} | Win: {wr:.0f}% | P&L: {s['total_pnl']:.2f}% | Params: SL={memory['params']['stop_loss']*100:.1f}% TP={memory['params']['take_profit']*100:.1f}%")

            save_memory(memory)

        except Exception as e:
            log(f"❌ ERRORE: {e}")

        time.sleep(CHECK_EVERY)

if __name__ == "__main__":
    run_bot()

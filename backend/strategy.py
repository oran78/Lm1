"""
Klop Apex — Pro Scalper v2.2
EMA 9/21 + RSI 14 + ATR 14 + ADX 14 + Session Filter
Tuned for $10 Exness XAUUSD micro flips
"""
import math
from datetime import datetime, timezone

def _ema(data, period):
    if not data or len(data) < period:
        return data[-1] if data else 0
    k = 2 / (period + 1)
    e = sum(data[:period]) / period
    for v in data[period:]:
        e = v * k + e * (1 - k)
    return e

def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    # Wilder smoothing
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return 100 - (100 / (1 + rs))

def _atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.8  # XAU default ~ $0.80
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i-1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.8
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr

def _adx(candles, period=14):
    """
    Returns (adx_value, plus_di, minus_di) — trend strength filter
    ADX < 15 = choppy, > 20 = trending
    """
    if len(candles) < period * 2:
        return 18.0, 20.0, 20.0
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]

    # True range + DM
    trs, plus_dms, minus_dms = [], [], []
    for i in range(1, len(candles)):
        tr = max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1]))
        trs.append(tr)
        up = highs[i] - highs[i-1]
        dn = lows[i-1] - lows[i]
        plus_dms.append(up if up > dn and up > 0 else 0)
        minus_dms.append(dn if dn > up and dn > 0 else 0)

    def wilder(arr, p):
        v = sum(arr[:p]) / p
        for x in arr[p:]:
            v = (v * (p - 1) + x) / p
        return v

    atr = wilder(trs, period)
    if atr == 0:
        return 15.0, 20.0, 20.0
    plus_di = (wilder(plus_dms, period) / atr) * 100
    minus_di = (wilder(minus_dms, period) / atr) * 100
    dx_vals = []
    for i in range(period, len(trs)):
        # recompute rolling DX for last value only — simplified: use smoothed
        pass
    denom = plus_di + minus_di
    dx = (abs(plus_di - minus_di) / denom * 100) if denom else 0
    # ADX as smoothed DX — approx using DX itself for scalper (fast)
    adx = dx  # for M5 scalper, raw DX is responsive enough; full ADX needs longer smooth
    # clamp
    return max(0, min(100, adx)), plus_di, minus_di

def _session_ok():
    """
    Allow only high-liquidity sessions: London (07-16 UTC) + New York (12-21 UTC)
    = 07-21 UTC. Block Asian chop 21-07 UTC.
    Returns (ok: bool, label)
    """
    now = datetime.now(timezone.utc)
    h = now.hour
    if 7 <= h < 21:
        return True, f"Active session {h:02d}UTC"
    return False, f"Asian / low liquidity {h:02d}UTC — paused"

def analyze_symbol(candles, spread=None):
    if not candles or len(candles) < 30:
        return {"signal": "HOLD", "reason": "Loading candles (need 30)…", "adx": 0, "atr": 0, "rsi": 50}

    closes = [c["close"] for c in candles]
    price = closes[-1]

    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    # previous EMAs for crossover detection
    prev_ema9 = _ema(closes[:-1], 9)
    prev_ema21 = _ema(closes[:-1], 21)

    rsi = _rsi(closes, 14)
    atr = _atr(candles, 14)
    adx, pdi, mdi = _adx(candles, 14)
    session_ok, session_label = _session_ok()

    # derived levels
    ema_gap = abs(ema9 - ema21)
    min_gap = max(0.35, atr * 0.18)  # must have meaningful separation — avoids chop whipsaw

    signal = "HOLD"
    reason = f"Waiting — ADX {adx:.1f} RSI {rsi:.1f} ATR {atr:.2f}"
    confidence = 0

    # veto checks
    if not session_ok:
        return {
            "signal": "HOLD", "reason": f"⏸ {session_label} — bot paused (London+NY only 07-21 UTC)",
            "price": round(price, 2), "rsi": round(rsi, 1), "atr": round(atr, 3),
            "adx": round(adx, 1), "pdi": round(pdi, 1), "mdi": round(mdi, 1),
            "ema9": round(ema9, 2), "ema21": round(ema21, 2), "session": session_label, "confidence": 0
        }

    if adx < 14:
        reason = f"Choppy — ADX {adx:.1f} < 14 (no trend) • {session_label}"
    elif ema_gap < min_gap:
        reason = f"Flat — EMA gap {ema_gap:.2f} < {min_gap:.2f} (ATR filter) • ADX {adx:.1f}"
    elif rsi > 78 or rsi < 22:
        # extreme RSI — warn, don't enter counter-trend without cross
        signal = "OVERBOUGHT_WARN" if rsi > 78 else "OVERSOLD_WARN"
        reason = f"{'Overbought' if rsi>78 else 'Oversold'} RSI {rsi:.1f} • waiting pullback"
    else:
        # crossover entries — now gated by ADX + ATR + RSI window
        buy_cross = ema9 > ema21 and prev_ema9 <= prev_ema21
        sell_cross = ema9 < ema21 and prev_ema9 >= prev_ema21

        if buy_cross and rsi < 68 and rsi > 32 and adx >= 14 and pdi > mdi:
            # momentum BUY needs +DI > -DI
            signal = "BUY"
            confidence = min(95, int(55 + (adx - 14) * 1.6 + (68 - rsi) * 0.4))
            reason = f"BUY ▶ EMA9 {ema9:.2f} × EMA21 {ema21:.2f} • RSI {rsi:.1f} • ADX {adx:.1f} • ATR {atr:.2f} • {session_label}"
        elif sell_cross and rsi > 32 and rsi < 68 and adx >= 14 and mdi > pdi:
            signal = "SELL"
            confidence = min(95, int(55 + (adx - 14) * 1.6 + (rsi - 32) * 0.4))
            reason = f"SELL ▼ EMA9 {ema9:.2f} × EMA21 {ema21:.2f} • RSI {rsi:.1f} • ADX {adx:.1f} • ATR {atr:.2f} • {session_label}"
        else:
            # direction bias without fresh cross but strong trend — allow continuation
            if ema9 > ema21 and rsi < 60 and rsi > 45 and adx >= 18 and pdi > mdi and ema_gap >= min_gap:
                # trending up, pullback entry — weaker
                pass  # stay HOLD to avoid overtrading; only cross entries fire
            reason = f"HOLD — ADX {adx:.1f} RSI {rsi:.1f} EMA gap {ema_gap:.2f} • {session_label}"

    return {
        "signal": signal,
        "reason": reason,
        "price": round(price, 2),
        "rsi": round(rsi, 1),
        "atr": round(atr, 3),
        "adx": round(adx, 1),
        "pdi": round(pdi, 1),
        "mdi": round(mdi, 1),
        "ema9": round(ema9, 2),
        "ema21": round(ema21, 2),
        "session": session_label,
        "confidence": confidence,
        "spread": spread,
    }

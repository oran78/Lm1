"""
Klop Apex — Scalper strategy v2.3 (fixed)
EMA 9/21 + RSI 14 + ATR 14 + proper Wilder ADX 14 + session filter.

Fixes vs v2.2:
  * Signals are evaluated on the LAST CLOSED candle only (no repainting on the forming candle).
  * ADX is now a real Wilder-smoothed ADX (v2.2 used raw DX, which is very noisy).
  * EMA cross uses proper EMA series (previous value is exact).
  * Added a 2nd setup (trend-continuation / EMA9 reclaim) so the bot can scalp more than only crosses.
  * Spread filter is relative to ATR.
  * `session_filter` config is honoured.
  * Every result carries `candle_time` so the engine takes at most one trade per candle.
"""
from datetime import datetime, timezone


def _ema_series(data, period):
    if len(data) < period:
        return []
    k = 2.0 / (period + 1)
    e = sum(data[:period]) / period
    out = [e]
    for v in data[period:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def _ema(data, period):
    s = _ema_series(data, period)
    return s[-1] if s else (data[-1] if data else 0.0)


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
    if avg_l == 0:
        return 100.0 if avg_g > 0 else 50.0
    return 100.0 - (100.0 / (1.0 + avg_g / avg_l))


def _atr(candles, period=14):
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return (sum(trs) / len(trs)) if trs else 0.0
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _adx(candles, period=14):
    """Real Wilder ADX -> (adx, +DI, -DI). Needs >= 2*period+1 candles, else zeros."""
    if len(candles) < 2 * period + 1:
        return 0.0, 0.0, 0.0
    trs, pdm, mdm = [], [], []
    for i in range(1, len(candles)):
        h, l = candles[i]["high"], candles[i]["low"]
        ph, pl, pc = candles[i - 1]["high"], candles[i - 1]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        up, dn = h - ph, pl - l
        pdm.append(up if (up > dn and up > 0) else 0.0)
        mdm.append(dn if (dn > up and dn > 0) else 0.0)
    s_tr, s_p, s_m = sum(trs[:period]), sum(pdm[:period]), sum(mdm[:period])
    dxs, pdi, mdi = [], 0.0, 0.0
    for i in range(period, len(trs) + 1):
        if i > period:
            s_tr = s_tr - s_tr / period + trs[i - 1]
            s_p = s_p - s_p / period + pdm[i - 1]
            s_m = s_m - s_m / period + mdm[i - 1]
        if s_tr <= 0:
            dxs.append(0.0)
            continue
        pdi, mdi = 100.0 * s_p / s_tr, 100.0 * s_m / s_tr
        denom = pdi + mdi
        dxs.append(100.0 * abs(pdi - mdi) / denom if denom else 0.0)
    if len(dxs) < period:
        return 0.0, pdi, mdi
    adx = sum(dxs[:period]) / period
    for dx in dxs[period:]:
        adx = (adx * (period - 1) + dx) / period
    return max(0.0, min(100.0, adx)), pdi, mdi


def _session_ok(now=None):
    """London + New York liquidity window, 07:00-21:00 UTC, weekdays only."""
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False, "Weekend — market closed"
    h = now.hour
    if 7 <= h < 21:
        return True, f"Active session {h:02d}UTC"
    return False, f"Asian / low liquidity {h:02d}UTC — paused"


def analyze_symbol(candles, spread=None, session_filter=True, drop_forming=True,
                   adx_min=18.0, now=None):
    """
    candles : oldest -> newest. Last element is normally the still-forming candle (drop_forming=True).
    spread  : in points (price diff * 100), same unit the tick API returns.
    """
    base = {"signal": "HOLD", "confidence": 0, "setup": None, "adx": 0, "atr": 0, "rsi": 50,
            "pdi": 0, "mdi": 0, "candle_time": None, "spread": spread}
    data = candles[:-1] if (drop_forming and candles) else list(candles or [])
    if len(data) < 40:
        return {**base, "reason": f"Loading candles ({len(data)}/40 closed)…"}

    closes = [c["close"] for c in data]
    last, prev = data[-1], data[-2]
    price = last["close"]
    e9s, e21s = _ema_series(closes, 9), _ema_series(closes, 21)
    ema9, ema21, p_ema9, p_ema21 = e9s[-1], e21s[-1], e9s[-2], e21s[-2]
    rsi = _rsi(closes, 14)
    atr = _atr(data, 14)
    adx, pdi, mdi = _adx(data, 14)
    ok, session_label = _session_ok(now)

    out = {**base, "price": round(price, 2), "rsi": round(rsi, 1), "atr": round(atr, 3),
           "adx": round(adx, 1), "pdi": round(pdi, 1), "mdi": round(mdi, 1),
           "ema9": round(ema9, 2), "ema21": round(ema21, 2), "session": session_label,
           "candle_time": last.get("time")}

    if session_filter and not ok:
        return {**out, "reason": f"⏸ {session_label} — bot paused (London+NY only)"}
    if atr <= 0:
        return {**out, "reason": "ATR is zero — no volatility data"}
    if spread and (spread / 100.0) > atr * 0.25:
        return {**out, "reason": f"Spread {spread/100.0:.2f} > 25% of ATR {atr:.2f} — skip"}

    ema_gap = abs(ema9 - ema21)
    min_gap = atr * 0.18

    if adx < adx_min:
        return {**out, "reason": f"Choppy — ADX {adx:.1f} < {adx_min:.0f} • {session_label}"}
    if rsi > 78 or rsi < 22:
        return {**out, "signal": "OVERBOUGHT_WARN" if rsi > 78 else "OVERSOLD_WARN",
                "reason": f"{'Overbought' if rsi > 78 else 'Oversold'} RSI {rsi:.1f} — waiting pullback"}

    bull_cross = ema9 > ema21 and p_ema9 <= p_ema21
    bear_cross = ema9 < ema21 and p_ema9 >= p_ema21

    # Setup 1: fresh EMA cross with trend confirmation
    if bull_cross and ema_gap >= min_gap * 0.5 and 35 < rsi < 68 and pdi > mdi:
        return {**out, "signal": "BUY", "setup": "EMA_CROSS",
                "confidence": min(95, int(55 + (adx - adx_min) * 1.6 + (68 - rsi) * 0.4)),
                "reason": f"BUY ▶ EMA9×EMA21 cross • RSI {rsi:.1f} • ADX {adx:.1f} • ATR {atr:.2f}"}
    if bear_cross and ema_gap >= min_gap * 0.5 and 32 < rsi < 65 and mdi > pdi:
        return {**out, "signal": "SELL", "setup": "EMA_CROSS",
                "confidence": min(95, int(55 + (adx - adx_min) * 1.6 + (rsi - 32) * 0.4)),
                "reason": f"SELL ▼ EMA9×EMA21 cross • RSI {rsi:.1f} • ADX {adx:.1f} • ATR {atr:.2f}"}

    # Setup 2: trend continuation — price dipped under EMA9 and the last candle reclaimed it
    if adx >= adx_min + 2 and ema_gap >= min_gap:
        if (ema9 > ema21 and pdi > mdi and prev["close"] < p_ema9 and last["close"] > ema9
                and last["close"] > last["open"] and 42 < rsi < 66):
            return {**out, "signal": "BUY", "setup": "PULLBACK", "confidence": min(85, int(50 + adx)),
                    "reason": f"BUY ▶ pullback reclaimed EMA9 • RSI {rsi:.1f} • ADX {adx:.1f}"}
        if (ema9 < ema21 and mdi > pdi and prev["close"] > p_ema9 and last["close"] < ema9
                and last["close"] < last["open"] and 34 < rsi < 58):
            return {**out, "signal": "SELL", "setup": "PULLBACK", "confidence": min(85, int(50 + adx)),
                    "reason": f"SELL ▼ pullback rejected at EMA9 • RSI {rsi:.1f} • ADX {adx:.1f}"}

    return {**out, "reason": f"HOLD — ADX {adx:.1f} RSI {rsi:.1f} gap {ema_gap:.2f} • {session_label}"}

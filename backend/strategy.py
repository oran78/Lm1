"""
Klop Apex — Momentum Pullback Scalper v2.5 (XAUUSD, M1/M5)

Rules (all evaluated on CLOSED candles only — nothing repaints):
  1. Trend bias   : EMA9 > EMA21 and EMA21 rising  -> BUY only
                    EMA9 < EMA21 and EMA21 falling -> SELL only
                    |EMA9 - EMA21| < 0.3 * ATR     -> CHOP, no trading
  2. Planned setup: with a bias, price pulls back into / toward the EMA9-EMA21 zone while RSI(14) cools
                    to 42-58  ->  state PLANNED_SETUP, planned_entry_price = EMA9
  3. Trigger      : the closed candle touches the zone and closes with a rejection (bullish for BUY,
                    bearish for SELL) back beyond EMA9  ->  signal BUY / SELL
                    Blocked if spread > 35 points or > 0.5 * ATR.
  4. Trade plan   : SL = 1.2 * ATR from entry (pushed past the pullback swing if needed, max 2 ATR), TP = 1.8 * ATR
                    (stretched to keep R:R >= 1.5),
                    break-even at +1R -> SL = entry +/- spread.   See plan_trade() / break_even_sl().
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


# ---------------------------------------------------------------------------------------------- tunables
CHOP_ATR_FRAC = 0.25        # |EMA9-EMA21| below this fraction of ATR  => CHOP
SLOPE_BARS = 3             # EMA21 angle is measured over this many closed candles
RSI_BAND = (38.0, 62.0)    # Pro Scalper: flexible pullback band    # RSI must cool into this band during the pullback
RSI_LOOKBACK = 3           # ...measured over the last N closed candles
APPROACH_ATR = 0.85        # Pro Scalper: rapid approach zone        # price within this many ATR of the zone counts as "pulling back"
SWING_BARS = 3             # swing window = pullback candle(s) + trigger candle
MAX_SPREAD_ATR = 0.5       # spread veto relative to ATR
MIN_RR = 1.5
SWING_BUFFER_ATR = 0.1     # stop sits this far beyond the swing extreme
MAX_SL_ATR = 2.0           # skip the trade if the stop would need to be wider than this many ATR


def _rsi_cooled(closes, side):
    """Lowest (BUY) / highest (SELL) RSI over the last RSI_LOOKBACK closed candles."""
    vals = [_rsi(closes[:len(closes) - k], 14) for k in range(RSI_LOOKBACK) if len(closes) - k > 15]
    if not vals:
        return 50.0
    return min(vals) if side == "BUY" else max(vals)


def _rejection(side, c, e9):
    """Candle-close rejection. BUY: bullish close back above EMA9 with a real body or a lower-wick tail."""
    rng = c["high"] - c["low"]
    if rng <= 0:
        return False, 0.0
    body = abs(c["close"] - c["open"]) / rng
    if side == "BUY":
        wick = (min(c["open"], c["close"]) - c["low"]) / rng
        ok = c["close"] > c["open"] and c["close"] > e9 and (body >= 0.4 or wick >= 0.4)
    else:
        wick = (c["high"] - max(c["open"], c["close"])) / rng
        ok = c["close"] < c["open"] and c["close"] < e9 and (body >= 0.4 or wick >= 0.4)
    return ok, max(body, wick)


def analyze_symbol(candles, spread=None, session_filter=True, drop_forming=True,
                   max_spread_points=35.0, now=None):
    """
    candles : oldest -> newest. Last element is normally the still-forming candle (drop_forming=True).
    spread  : in points (price diff * 100), same unit the tick API returns.

    Returns a dict. `signal` is BUY / SELL / HOLD. `state` is one of:
      WARMUP, PAUSED, CHOP, NO_TREND, WATCH, PLANNED_SETUP, INVALIDATED, BLOCKED, TRIGGERED
    PLANNED_SETUP carries `planned_side` and `planned_entry_price` (= EMA9).
    """
    base = {"signal": "HOLD", "state": "WARMUP", "confidence": 0, "setup": None, "bias": None,
            "planned_side": None, "planned_entry_price": None,
            "adx": 0, "atr": 0, "rsi": 50, "pdi": 0, "mdi": 0, "candle_time": None, "spread": spread,
            "swing_low": None, "swing_high": None}
    data = candles[:-1] if (drop_forming and candles) else list(candles or [])
    if len(data) < 40:
        return {**base, "reason": f"Loading candles ({len(data)}/40 closed)…"}

    closes = [c["close"] for c in data]
    last = data[-1]
    e9s, e21s = _ema_series(closes, 9), _ema_series(closes, 21)
    ema9, ema21 = e9s[-1], e21s[-1]
    rsi = _rsi(closes, 14)
    atr = _atr(data, 14)
    adx, pdi, mdi = _adx(data, 14)
    ok, session_label = _session_ok(now)
    window = data[-SWING_BARS:]
    swing_low, swing_high = min(c["low"] for c in window), max(c["high"] for c in window)
    slope = (e21s[-1] - e21s[-1 - SLOPE_BARS]) / SLOPE_BARS if len(e21s) > SLOPE_BARS else 0.0
    gap = abs(ema9 - ema21)

    out = {**base, "price": round(last["close"], 2), "rsi": round(rsi, 1), "atr": round(atr, 3),
           "adx": round(adx, 1), "pdi": round(pdi, 1), "mdi": round(mdi, 1),
           "ema9": round(ema9, 2), "ema21": round(ema21, 2), "ema_gap": round(gap, 3),
           "ema_slope": round(slope, 4), "session": session_label, "candle_time": last.get("time"),
           "swing_low": swing_low, "swing_high": swing_high}

    if session_filter and not ok:
        return {**out, "state": "PAUSED", "reason": f"⏸ {session_label} — bot paused (London+NY only)"}
    if atr <= 0:
        return {**out, "state": "WARMUP", "reason": "ATR is zero — no volatility data"}
    if gap < CHOP_ATR_FRAC * atr:
        return {**out, "state": "CHOP", "reason": f"CHOP — EMA gap {gap:.2f} < {CHOP_ATR_FRAC} × ATR {atr:.2f} • no trade"}

    # Pro Scalper Macro Trend Filter: compute EMA50 if enough candles
    ema50 = _ema(closes, 50) if len(closes) >= 50 else None
    out["ema50"] = round(ema50, 2) if ema50 else None

    if ema9 > ema21 and slope > 0:
        if ema50 and last["close"] < ema50:
            return {**out, "state": "NO_TREND", "reason": "Bullish momentum but price below EMA50 trend filter — skipping"}
        side = "BUY"
    elif ema9 < ema21 and slope < 0:
        if ema50 and last["close"] > ema50:
            return {**out, "state": "NO_TREND", "reason": "Bearish momentum but price above EMA50 trend filter — skipping"}
        side = "SELL"
    else:
        return {**out, "state": "NO_TREND", "reason": "EMAs aligned but EMA21 is not sloping with the trend — no bias"}
    out["bias"] = side

    zone_hi, zone_lo = max(ema9, ema21), min(ema9, ema21)
    if side == "BUY":
        invalid = last["close"] < zone_lo
        dist = last["low"] - zone_hi           # <= 0 => candle reached the zone
        touched = last["low"] <= zone_hi and last["high"] >= zone_lo
    else:
        invalid = last["close"] > zone_hi
        dist = zone_lo - last["high"]
        touched = last["high"] >= zone_lo and last["low"] <= zone_hi
    if invalid:
        return {**out, "state": "INVALIDATED",
                "reason": f"{side} pullback invalidated — candle closed through the whole EMA zone"}

    pb_rsi = _rsi_cooled(closes, side)
    out["pullback_rsi"] = round(pb_rsi, 1)
    if dist > APPROACH_ATR * atr:
        return {**out, "state": "WATCH", "reason": f"{side} bias — waiting for a pullback to the EMA zone ({dist:.2f} away)"}
    if not (RSI_BAND[0] <= pb_rsi <= RSI_BAND[1]):
        return {**out, "state": "WATCH",
                "reason": f"{side} bias — pullback RSI {pb_rsi:.1f} outside {RSI_BAND[0]:.0f}-{RSI_BAND[1]:.0f}"}

    rejected, quality = _rejection(side, last, ema9) if touched else (False, 0.0)
    if not rejected:
        return {**out, "state": "PLANNED_SETUP", "planned_side": side, "planned_entry_price": round(ema9, 2),
                "reason": f"PLANNED {side} — target entry @ {ema9:.2f} (EMA9) • RSI {pb_rsi:.1f} • waiting for rejection close"}

    # ---- trigger: spread gate
    sp_price = (spread or 0) / 100.0
    if spread and spread > max_spread_points:
        return {**out, "state": "BLOCKED", "reason": f"{side} trigger skipped — spread {spread:.0f} pts > {max_spread_points:.0f}"}
    if sp_price > MAX_SPREAD_ATR * atr:
        return {**out, "state": "BLOCKED", "reason": f"{side} trigger skipped — spread {sp_price:.2f} > {MAX_SPREAD_ATR} × ATR {atr:.2f}"}

    conf = int(min(95, 55 + 20 * min(1.0, gap / atr) + 20 * quality))
    return {**out, "signal": side, "state": "TRIGGERED", "setup": "EMA_PULLBACK", "confidence": conf,
            "reason": f"{side} ▶ EMA-zone rejection • RSI {pb_rsi:.1f} • ATR {atr:.2f} • spread {spread if spread is not None else '—'}"}


def plan_trade(side, entry, atr, swing_low=None, swing_high=None, sl_mult=1.2, tp_mult=1.8, min_rr=MIN_RR):
    """
    Base plan: SL = sl_mult*ATR from entry (1.2), TP = tp_mult*ATR (1.8)  -> R:R 1.5.
    The stop must sit BEYOND the pullback swing. If the swing is further away than the base stop, the stop is
    pushed past the swing (+ SWING_BUFFER_ATR) and TP is stretched to keep R:R >= min_rr.
    A stop wider than MAX_SL_ATR * ATR means the pullback was too deep -> (None, reason).
    """
    if atr <= 0 or sl_mult <= 0 or tp_mult <= 0:
        return None, "invalid ATR / multipliers"
    if tp_mult / sl_mult < min_rr - 1e-9:
        return None, f"R:R {tp_mult / sl_mult:.2f} below minimum {min_rr}"
    risk = atr * sl_mult
    if side == "BUY" and swing_low is not None:
        risk = max(risk, entry - swing_low + SWING_BUFFER_ATR * atr)
    elif side == "SELL" and swing_high is not None:
        risk = max(risk, swing_high - entry + SWING_BUFFER_ATR * atr)
    if risk > MAX_SL_ATR * atr:
        return None, f"stop beyond the swing needs {risk:.2f} (> {MAX_SL_ATR} × ATR {atr:.2f}) — pullback too deep"
    reward = max(atr * tp_mult, min_rr * risk)
    sl, tp = (entry - risk, entry + reward) if side == "BUY" else (entry + risk, entry - reward)
    return {"sl": round(sl, 2), "tp": round(tp, 2), "risk": risk, "reward": reward, "rr": round(reward / risk, 2)}, "ok"


def break_even_sl(side, entry, sl, bid, ask, trigger_r=1.0, lock_buffer=False):
    """
    Pro Scalper Auto Break-Even.
    Triggers when floating profit >= trigger_r * initial risk (default 0.8R).
    BUY -> entry + spread (+ optional micro buffer), SELL -> entry - spread.
    """
    if not sl or not entry:
        return None
    spread_px = max(ask - bid, 0.0)
    buffer_px = max(0.08, spread_px * 0.25) if lock_buffer else 0.0
    if side == "BUY":
        risk = entry - sl
        if risk <= 0:
            return None
        return round(entry + spread_px + buffer_px, 2) if (bid - entry) >= trigger_r * risk else None
    risk = sl - entry
    if risk <= 0:
        return None
    return round(entry - spread_px - buffer_px, 2) if (entry - ask) >= trigger_r * risk else None

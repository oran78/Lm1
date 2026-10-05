"""
Klop Apex — Momentum Pullback Scalper v2.6 (XAUUSD, M1/M5)

Rules (all evaluated on CLOSED candles only — nothing repaints). The constants below are the single
source of truth; CHANGES.md only describes them.
  0. Spike guard  : a closed candle with true range > 2.5 * ATR in the last 2 candles (news / stop-run)
                    -> BLOCKED, no new entries until it ages out.
  1a. H1 context  : (htf_mode) real H1 bias from market_context.htf_bias: BUY only when H1 is BULL, SELL only when BEAR
                    ("strict"); "counter" only blocks trades AGAINST H1; "off" ignores H1.
  1b. M5 structure: (structure_mode) HH+HL = BULL, LH+LL = BEAR from confirmed swings; "counter" blocks trades against it,
                    "strict" requires it to agree, "off" ignores it.
  1. Trend bias   : EMA9 > EMA21, EMA21 rising and close >= EMA50  -> BUY only
                    EMA9 < EMA21, EMA21 falling and close <= EMA50 -> SELL only
                    |EMA9 - EMA21| < 0.3 * ATR     -> CHOP, no trading
  2. Planned setup: with a bias, price pulls back into / toward the EMA9-EMA21 zone (within 0.75 ATR) while
                    RSI(14) cools to 42-58 AND the CURRENT RSI has not run away (BUY <= 65, SELL >= 35)  ->  state PLANNED_SETUP. `planned_entry_price` = EMA9 is the
                    PULLBACK ZONE shown on the chart; the actual entry is a market order on the trigger close.
  3. Trigger      : the closed candle touches the zone and closes with a rejection (bullish for BUY,
                    bearish for SELL) back beyond EMA9, AND Stochastic(5,3) confirms (BUY: K > D and K < 80,
                    SELL: K < D and K > 20)  ->  signal BUY / SELL
                    Blocked if spread > 35 points or > 0.5 * ATR.
  4. Trade plan   : SL = 1.2 * ATR from entry (pushed past the pullback swing if needed, max 2 ATR), TP = 1.8 * ATR
                    (stretched to keep R:R >= 1.5),
                    break-even at +1R -> SL = entry +/- spread.   See plan_trade() / break_even_sl().
"""
from datetime import datetime, timezone

from market_context import market_structure


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



def _stochastic(candles, k_period=5, d_period=3):
    """Fast Stochastic Oscillator (5, 3) -> (K, D)."""
    if len(candles) < k_period + d_period:
        return 50.0, 50.0
    k_vals = []
    for i in range(len(candles) - d_period, len(candles)):
        sub = candles[i - k_period + 1 : i + 1]
        c = sub[-1]["close"]
        lows = min(x["low"] for x in sub)
        highs = max(x["high"] for x in sub)
        if highs == lows:
            k_vals.append(50.0)
        else:
            k_vals.append(((c - lows) / (highs - lows)) * 100.0)
    k = k_vals[-1]
    d = sum(k_vals) / len(k_vals)
    return k, d


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
CHOP_ATR_FRAC = 0.18       # |EMA9-EMA21| below this fraction of ATR  => CHOP  (was 0.30 — looser, so weak trends still trade)
SLOPE_BARS = 3             # EMA21 angle is measured over this many closed candles
MACRO_EMA = 50             # BUY only above / SELL only below this EMA (higher-timeframe trend proxy)
RSI_BAND = (36.0, 64.0)    # RSI must cool into this band during the pullback  (was 42-58 — easier to enter)
RSI_LOOKBACK = 3           # ...measured over the last N closed candles
APPROACH_ATR = 1.20        # price within this many ATR of the zone counts as "pulling back"  (was 0.75 — fires from further out)
SWING_BARS = 3             # swing window = pullback candle(s) + trigger candle
MAX_SPREAD_ATR = 0.5       # spread veto relative to ATR
MIN_RR = 1.5
SWING_BUFFER_ATR = 0.1     # stop sits this far beyond the swing extreme
MAX_SL_ATR = 2.0           # skip the trade if the stop would need to be wider than this many ATR
SPIKE_ATR = 2.5            # a closed candle with true range above this many (pre-spike) ATR = news / stop-run
SPIKE_LOOKBACK = 2         # ...blocks entries for this many closed candles
STOCH_CONFIRM = True       # require Stochastic(5,3) to agree with the rejection candle
STOCH_EXHAUST = (20.0, 80.0)   # BUY needs K < 80, SELL needs K > 20 (don't buy an exhausted move)


RSI_NOW_LIMIT = (30.0, 70.0)   # current-candle RSI: BUY needs <= 70, SELL needs >= 30 (was 35-65)
STRUCT_N = 2                   # fractal width for M5 swings
STRUCT_WINDOW = 80             # closed M5 candles used for structure
STRUCT_MIN_MOVE_ATR = 0.1      # a "higher/lower" swing must differ by at least this many ATR
CONTEXT_MODES = ("off", "counter", "strict")


def rsi_ok(side, pb_rsi, rsi_now):
    """Pullback RSI (lowest for BUY / highest for SELL over RSI_LOOKBACK candles) must sit in RSI_BAND, AND the current closed
    candle's RSI must not be extended in the trade direction. Returns (ok, reason)."""
    lo, hi = RSI_BAND
    if not (lo <= pb_rsi <= hi):
        return False, f"pullback RSI {pb_rsi:.1f} outside {lo:.0f}-{hi:.0f}"
    nlo, nhi = RSI_NOW_LIMIT
    if side == "BUY" and rsi_now > nhi:
        return False, f"current RSI {rsi_now:.1f} > {nhi:.0f} — move already extended"
    if side == "SELL" and rsi_now < nlo:
        return False, f"current RSI {rsi_now:.1f} < {nlo:.0f} — move already extended"
    return True, ""


def _true_range(candles, i):
    h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
    return max(h - l, abs(h - pc), abs(l - pc))


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
                   max_spread_points=35.0, now=None, htf=None, htf_mode="off", structure_mode="off"):
    """
    candles : oldest -> newest. Last element is normally the still-forming candle (drop_forming=True).
    spread  : in points (price diff * 100), same unit the tick API returns.

    Returns a dict. `signal` is BUY / SELL / HOLD. `state` is one of:
      WARMUP, PAUSED, CHOP, NO_TREND, WATCH, PLANNED_SETUP, INVALIDATED, BLOCKED, TRIGGERED
    PLANNED_SETUP carries `planned_side` and `planned_entry_price` (= EMA9).
    htf : dict from market_context.htf_bias() computed on CLOSED H1 candles (or None). htf_mode / structure_mode: off | counter | strict.
          The library defaults are "off" (= the v2.6 behaviour); the bot passes its configured modes.
    """
    base = {"signal": "HOLD", "state": "WARMUP", "confidence": 0, "setup": None, "bias": None,
            "planned_side": None, "planned_entry_price": None,
            "adx": 0, "atr": 0, "rsi": 50, "pdi": 0, "mdi": 0, "candle_time": None, "spread": spread,
            "swing_low": None, "swing_high": None}
    data = candles[:-1] if (drop_forming and candles) else list(candles or [])
    if len(data) < 30:
        return {**base, "reason": f"Loading candles ({len(data)}/30 closed)…"}

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
    if SPIKE_LOOKBACK > 0 and len(data) > 14 + SPIKE_LOOKBACK:
        base_atr = _atr(data[:-SPIKE_LOOKBACK], 14)           # ATR from BEFORE the suspect candles
        spike = max(_true_range(data, len(data) - 1 - k) for k in range(SPIKE_LOOKBACK))
        if base_atr > 0 and spike > SPIKE_ATR * base_atr:
            return {**out, "state": "BLOCKED",
                    "reason": f"⚠ Volatility spike — range {spike:.2f} > {SPIKE_ATR} × ATR {base_atr:.2f} (news?) • no entries for {SPIKE_LOOKBACK} candles"}
    if gap < CHOP_ATR_FRAC * atr:
        return {**out, "state": "CHOP", "reason": f"CHOP — EMA gap {gap:.2f} < {CHOP_ATR_FRAC} × ATR {atr:.2f} • no trade"}

    # Macro trend filter: price must be on the trend side of EMA50 (when enough candles)
    ema50 = _ema(closes, MACRO_EMA) if len(closes) >= MACRO_EMA else None
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

    if htf_mode in ("counter", "strict"):
        hb = (htf or {}).get("bias", "UNKNOWN")
        out["htf_bias"] = hb
        agrees = (hb == "BULL" and side == "BUY") or (hb == "BEAR" and side == "SELL")
        opposes = (hb == "BEAR" and side == "BUY") or (hb == "BULL" and side == "SELL")
        if hb == "UNKNOWN" and htf_mode == "strict":
            return {**out, "state": "WARMUP", "reason": f"H1 context unavailable ({(htf or {}).get('reason', 'no H1 data')}) — set H1 filter to Off/Counter to trade without it"}
        if opposes or (htf_mode == "strict" and not agrees):
            return {**out, "state": "NO_TREND", "reason": f"M5 {side} setup but {(htf or {}).get('reason', 'H1 ' + hb)} — skipping"}

    ms = market_structure(data[-STRUCT_WINDOW:], STRUCT_N, STRUCT_MIN_MOVE_ATR * atr)
    out["m5_structure"] = ms["state"]
    if structure_mode in ("counter", "strict"):
        against = (ms["state"] == "BEAR" and side == "BUY") or (ms["state"] == "BULL" and side == "SELL")
        agree_s = (ms["state"] == "BULL" and side == "BUY") or (ms["state"] == "BEAR" and side == "SELL")
        if against or (structure_mode == "strict" and not agree_s):
            return {**out, "state": "NO_TREND", "reason": f"M5 structure {ms['state']} does not support {side} — skipping"}

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
    rsi_pass, rsi_why = rsi_ok(side, pb_rsi, rsi)
    if not rsi_pass:
        return {**out, "state": "WATCH", "reason": f"{side} bias — {rsi_why}"}

    rejected, quality = _rejection(side, last, ema9) if touched else (False, 0.0)
    if not rejected:
        return {**out, "state": "PLANNED_SETUP", "planned_side": side, "planned_entry_price": round(ema9, 2),
                "reason": f"PLANNED {side} — pullback zone @ {ema9:.2f} (EMA9) • RSI {pb_rsi:.1f} • waiting for rejection close, then market entry"}

    stoch_k, stoch_d = _stochastic(data, 5, 3)
    out["stoch_k"] = round(stoch_k, 1)
    out["stoch_d"] = round(stoch_d, 1)
    if STOCH_CONFIRM:
        lo, hi = STOCH_EXHAUST
        stoch_ok = (stoch_k > stoch_d and stoch_k < hi) if side == "BUY" else (stoch_k < stoch_d and stoch_k > lo)
        if not stoch_ok:
            return {**out, "state": "PLANNED_SETUP", "planned_side": side, "planned_entry_price": round(ema9, 2),
                    "reason": f"{side} rejection seen but Stochastic not confirming (K {stoch_k:.0f} / D {stoch_d:.0f}) — no entry"}

    # ---- trigger: spread gate
    sp_price = (spread or 0) / 100.0
    if spread and spread > max_spread_points:
        return {**out, "state": "BLOCKED", "reason": f"{side} trigger skipped — spread {spread:.0f} pts > {max_spread_points:.0f}"}
    if sp_price > MAX_SPREAD_ATR * atr:
        return {**out, "state": "BLOCKED", "reason": f"{side} trigger skipped — spread {sp_price:.2f} > {MAX_SPREAD_ATR} × ATR {atr:.2f}"}

    conf = int(min(98, 60 + 25 * min(1.0, gap / atr) + 15 * quality))
    setup_type = "EMA_PULLBACK"

    # explainability: why this trade exists (information only — the gates above already decided)
    swept = (ms["last_low"] is not None and last["low"] < ms["last_low"] < last["close"]) if side == "BUY" else \
            (ms["last_high"] is not None and last["high"] > ms["last_high"] > last["close"])
    reasons = []
    if htf_mode != "off":
        reasons.append(f"H1 {out.get('htf_bias', 'n/a')}")
    reasons += [f"M5 structure {ms['state']}", "EMA9/21 pullback", f"{'bullish' if side == 'BUY' else 'bearish'} rejection",
                f"RSI {pb_rsi:.0f}→{rsi:.0f}"]
    if STOCH_CONFIRM:
        reasons.append(f"Stoch {stoch_k:.0f}/{stoch_d:.0f}")
    if swept:
        reasons.append("liquidity sweep")
    out["reasons"] = reasons
    return {**out, "signal": side, "state": "TRIGGERED", "setup": setup_type, "confidence": conf,
            "reason": f"{side} ▶ Momentum Scalp (EMA Rejection + Stoch {stoch_k:.0f}) • RSI {pb_rsi:.1f} • ATR {atr:.2f} • why: {'; '.join(reasons)}"}


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
    Auto break-even. Triggers when floating profit >= trigger_r * initial risk (default 1.0R).
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

"""
Klop Apex — market context (pure functions on CLOSED candles, oldest -> newest).

* swing_points      fractal swings; a swing at index i is only reported once candle i+n has CLOSED, so a result
                    computed on candles[:k] never changes when later candles arrive (no look-ahead, no repaint).
* market_structure  BULL = higher high + higher low, BEAR = lower high + lower low, otherwise RANGE.
* htf_bias          real higher-timeframe (H1) bias from EMA20/EMA50, EMA50 slope, close vs EMA50 and H1 structure.

Nothing here knows about brokers, sessions or risk — it is deterministic and unit-tested.
"""
from typing import List, Optional


def _ema_series(values: List[float], period: int) -> List[float]:
    """EMA seeded with the SMA of the first `period` values; same length as `values`."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    if len(values) < period:
        out, start = [values[0]], 1
    else:
        out, start = [sum(values[:period]) / period] * period, period
    for v in values[start:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _atr(candles: List[dict], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def swing_points(candles: List[dict], n: int = 2) -> List[dict]:
    """Fractal swings: a high is a swing if it is strictly above the n candles before it and at least equal to the n candles after
    it (so the FIRST of two equal highs counts, and equal highs are not lost); lows are the mirror image.
    Returns [{'i': index, 'kind': 'H'|'L', 'price': float}] in time order, only swings confirmed by n later closed candles."""
    out = []
    last = len(candles) - 1
    for i in range(n, last - n + 1):                       # i + n <= last  => confirmed
        hi, lo = candles[i]["high"], candles[i]["low"]
        if all(hi > candles[j]["high"] for j in range(i - n, i)) and all(hi >= candles[j]["high"] for j in range(i + 1, i + n + 1)):
            out.append({"i": i, "kind": "H", "price": hi})
        if all(lo < candles[j]["low"] for j in range(i - n, i)) and all(lo <= candles[j]["low"] for j in range(i + 1, i + n + 1)):
            out.append({"i": i, "kind": "L", "price": lo})
    return out


def market_structure(candles: List[dict], n: int = 2, min_move: float = 0.0) -> dict:
    """Classify the last two confirmed swing highs and lows.
    `min_move` ignores a "higher/lower" that is smaller than this price distance (noise guard, e.g. 0.1 * ATR)."""
    sw = swing_points(candles, n)
    highs = [s for s in sw if s["kind"] == "H"]
    lows = [s for s in sw if s["kind"] == "L"]
    res = {"state": "RANGE", "last_high": None, "prev_high": None, "last_low": None, "prev_low": None,
           "hh": False, "hl": False, "lh": False, "ll": False}
    if highs:
        res["last_high"] = highs[-1]["price"]
    if lows:
        res["last_low"] = lows[-1]["price"]
    if len(highs) < 2 or len(lows) < 2:
        return res
    res["prev_high"], res["prev_low"] = highs[-2]["price"], lows[-2]["price"]
    res["hh"] = highs[-1]["price"] > highs[-2]["price"] + min_move
    res["lh"] = highs[-1]["price"] < highs[-2]["price"] - min_move
    res["hl"] = lows[-1]["price"] > lows[-2]["price"] + min_move
    res["ll"] = lows[-1]["price"] < lows[-2]["price"] - min_move
    if res["hh"] and res["hl"]:
        res["state"] = "BULL"
    elif res["lh"] and res["ll"]:
        res["state"] = "BEAR"
    return res


# H1 bias thresholds (in H1 ATR units) — deliberately few and coarse
HTF_FAST, HTF_SLOW = 20, 50
HTF_GAP_ATR = 0.15          # |EMA20 - EMA50| must be at least this many H1 ATR
HTF_SLOPE_BARS = 5          # EMA50 slope measured over this many closed H1 candles
HTF_MIN_CANDLES = 80        # EMA50 warm-up + a few swings


def htf_bias(h1_closed: List[dict]) -> dict:
    """Bias from CLOSED H1 candles (drop the forming one before calling).
    BULL : EMA20 > EMA50 by >= 0.15 ATR, EMA50 rising, close above EMA50 and H1 structure not BEAR.
    BEAR : the mirror image.  NEUTRAL: anything else.  UNKNOWN: not enough data."""
    if not h1_closed or len(h1_closed) < HTF_MIN_CANDLES:
        return {"bias": "UNKNOWN", "reason": f"H1 data {len(h1_closed or [])}/{HTF_MIN_CANDLES} candles"}
    closes = [c["close"] for c in h1_closed]
    atr = _atr(h1_closed, 14)
    if atr <= 0:
        return {"bias": "UNKNOWN", "reason": "H1 ATR is zero"}
    e20, e50 = _ema_series(closes, HTF_FAST), _ema_series(closes, HTF_SLOW)
    gap = (e20[-1] - e50[-1]) / atr
    slope = (e50[-1] - e50[-1 - HTF_SLOPE_BARS]) / atr / HTF_SLOPE_BARS
    struct = market_structure(h1_closed[-120:], n=2, min_move=0.1 * atr)["state"]
    info = {"gap_atr": round(gap, 2), "slope_atr": round(slope, 3), "structure": struct}
    if gap >= HTF_GAP_ATR and slope > 0 and closes[-1] > e50[-1] and struct != "BEAR":
        return {"bias": "BULL", "reason": f"H1 bullish (EMA20>EMA50 {gap:.2f} ATR, EMA50 rising, structure {struct})", **info}
    if gap <= -HTF_GAP_ATR and slope < 0 and closes[-1] < e50[-1] and struct != "BULL":
        return {"bias": "BEAR", "reason": f"H1 bearish (EMA20<EMA50 {gap:.2f} ATR, EMA50 falling, structure {struct})", **info}
    return {"bias": "NEUTRAL", "reason": f"H1 neutral (gap {gap:.2f} ATR, slope {slope:.3f}, structure {struct})", **info}

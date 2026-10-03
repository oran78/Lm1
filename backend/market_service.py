"""
Klop Apex — Real Market Data Service
No MT5 required — pulls LIVE XAUUSD/EURUSD from free public APIs
Used when Wine/MT5 not available (Railway Linux)
Fallback chain: gold-api.com -> metals API -> binance PAXG -> exchangerate
"""
import time
import random
import logging
import httpx

logger = logging.getLogger("klop.market")

# In-memory cache to avoid rate limits
_cache = {}  # symbol -> {price, time}
_cache_ttl = 3  # seconds (was 25 — far too stale for scalping)

# Last known good
_last_price = {"XAUUSD": 4141.7, "EURUSD": 1.0850, "GBPUSD": 1.2720, "USDJPY": 149.5, "BTCUSD": 68500.0}

async def fetch_xau_real():
    """Try multiple free endpoints for LIVE XAUUSD"""
    # 1. gold-api.com — free, no key, returns {price: 2650, ...}
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("https://api.gold-api.com/price/XAU", headers={"User-Agent": "Klop/2.3"})
            if r.status_code == 200:
                j = r.json()
                p = float(j.get("price") or j.get("price_gram_24k", 0) * 31.1035 if j.get("price_gram_24k") else 0)
                if p > 100:
                    return p
    except Exception as e:
        logger.debug(f"gold-api fail: {e}")
    # 2. Binance PAXGUSDT as XAU proxy (very close to spot, live)
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT")
            if r.status_code == 200:
                p = float(r.json().get("price", 0))
                if p > 100:
                    return p
    except Exception as e:
        logger.debug(f"binance PAXG fail: {e}")
    return None

async def fetch_forex_real(pair: str):
    """EURUSD etc via exchangerate-api free"""
    base = pair[:3]
    quote = pair[3:]
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"https://api.exchangerate-api.com/v4/latest/{base}")
            if r.status_code == 200:
                j = r.json()
                rate = j.get("rates", {}).get(quote)
                if rate:
                    return float(rate)
    except Exception as e:
        logger.debug(f"forex {pair} fail: {e}")
    return None

def get_live_price_sync(symbol: str) -> float:
    """
    Sync version for mt5_service fallback — uses httpx sync + cache
    Called from sync code path, so we use blocking httpx
    """
    now = time.time()
    sym = symbol.upper()
    if sym in _cache and now - _cache[sym]["t"] < _cache_ttl:
        return _cache[sym]["price"]

    price = None
    try:
        if "XAU" in sym:
            # try gold-api sync
            with httpx.Client(timeout=4) as c:
                r = c.get("https://api.gold-api.com/price/XAU", headers={"User-Agent": "Klop/2.3"})
                if r.status_code == 200:
                    j = r.json()
                    price = float(j.get("price", 0))
                    if price < 100 and j.get("price_gram_24k"):
                        price = float(j["price_gram_24k"]) * 31.1035
                if not price or price < 100:
                    # binance fallback
                    r2 = c.get("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT")
                    if r2.status_code == 200:
                        price = float(r2.json().get("price", 0))
        elif sym in ("EURUSD", "GBPUSD", "USDJPY", "BTCUSD"):
            if sym == "BTCUSD":
                with httpx.Client(timeout=4) as c:
                    r = c.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
                    if r.status_code == 200:
                        price = float(r.json().get("price", 0))
            else:
                base = sym[:3]; quote = sym[3:]
                with httpx.Client(timeout=4) as c:
                    r = c.get(f"https://api.exchangerate-api.com/v4/latest/{base}")
                    if r.status_code == 200:
                        price = float(r.json().get("rates", {}).get(quote, 0))
    except Exception as e:
        logger.warning(f"market fetch {sym} error: {e}")

    if price and price > 0:
        _last_price[sym] = price
        _cache[sym] = {"price": price, "t": now}
        return price

    # fetch failed: return last known REAL price unchanged (never fabricate noise)
    return _last_price.get(sym, 0.0)


def fetch_history_1m(limit: int = 500):
    """
    Real 1-minute history for gold from Binance PAXGUSDT (gold-backed token, tracks XAU closely).
    Returns [{time,open,high,low,close,volume}] oldest->newest, or [] if unreachable.
    The still-forming candle is the last element.
    """
    try:
        with httpx.Client(timeout=6) as c:
            r = c.get("https://api.binance.com/api/v3/klines",
                      params={"symbol": "PAXGUSDT", "interval": "1m", "limit": limit})
            if r.status_code != 200:
                return []
            return [{"time": int(k[0] // 1000), "open": float(k[1]), "high": float(k[2]),
                     "low": float(k[3]), "close": float(k[4]), "volume": float(k[5])} for k in r.json()]
    except Exception as e:
        logger.warning(f"history fetch failed: {e}")
        return []

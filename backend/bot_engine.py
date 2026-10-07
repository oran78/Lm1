"""
Klop Apex — Auto Flip Engine v2.6 (momentum pullback scalper)

v2.6: * ONE parameter set (config defaults == strategy.py == CHANGES.md): SL 1.2 / TP 1.8 ATR, BE at 1R.
      * Real P/L: closed trades are priced from the broker's deal history (floating P/L only as a fallback).
      * Scratch trades (break-even exits) are counted separately, not as wins -> honest win rate.
      * total_trades counted once (on close). First pass after start/restart never trades a stale candle.
      * Loss handling: short cooldown after a loss, a longer one after a losing streak. The bot never stops
        for the day by itself: it keeps looking for entries until max_trades_per_day or the target is hit
        (the only other stop is the optional daily-loss cap, `max_daily_loss_pct`, 0 = off).

Klop Apex — Auto Flip Engine v2.5 (momentum pullback scalper)

v2.5: strategy is the EMA-zone pullback scalper (see strategy.py). The engine publishes
  * planned_setup  — PLANNED_SETUP state with planned_entry_price (EMA9) for the chart,
  * active_trade   — ticket / entry / SL / TP / break-even flag for the chart price lines,
and moves the stop to break-even (entry +/- spread) once floating profit reaches 1R.

Klop Apex — Auto Flip Engine v2.3 (fixed)

Fixes vs v2.2:
  * ONE signal per closed candle (v2.2 re-fired the same cross every ~12s -> stacked duplicate trades).
  * Max 1 open position per symbol.
  * Real exit management: closes on opposite signal, time-stop, and detects broker SL/TP closes.
  * Real P/L is recorded (v2.2 recorded 0 on every close -> win-rate/PnL were meaningless).
  * Daily-loss limit actually enforced; lot size computed with correct XAUUSD maths.
  * Refuses to trade on missing / non-real candle data.
  * Blocking HTTP calls moved off the event loop (asyncio.to_thread).
"""
import asyncio, time, logging
from collections import deque
from datetime import datetime, timezone

from mt5_service import mt5_service
try:
    from metaapi_service import metaapi_service as _metaapi_bot
    _HAS_METAAPI_BOT = True
except Exception:
    _HAS_METAAPI_BOT = False
    _metaapi_bot = None
from risk_engine import risk_engine, RISK_CAP_PREFIX
from ownership import BOT_MAGIC, BOT_COMMENT, MANUAL_MAGIC, MANUAL_COMMENT, split_positions
from market_context import htf_bias
from strategy import analyze_symbol, plan_trade, break_even_sl, MIN_RR

logger = logging.getLogger("klop.bot")


# ------------------------------------------------------------------ broker routing
def _meta_on():
    try:
        return bool(_HAS_METAAPI_BOT and _metaapi_bot and _metaapi_bot.is_connected())
    except Exception:
        return False

def _is_any_connected(): return _meta_on() or mt5_service.is_connected()

def _any_account():
    if _meta_on():
        try:
            a = _metaapi_bot.get_account_info()
            if a: return a
        except Exception: pass
    return mt5_service.get_account_info()

def _any_tick(sym):
    if _meta_on():
        try:
            t = _metaapi_bot.get_tick(sym)
            if t and t.get("bid"): return t
        except Exception: pass
    return mt5_service.get_tick(sym)

def _any_candles(sym, tf, cnt):
    if _meta_on():
        try:
            c = _metaapi_bot.get_candles(sym, tf, cnt)
            if c: return c, "BROKER"
        except Exception: pass
    return mt5_service.get_candles(sym, tf, cnt), mt5_service.get_candle_source(sym)

def _any_positions(sym):
    try:
        ps = _metaapi_bot.get_positions() if _meta_on() else mt5_service.get_positions()
    except Exception:
        return None   # None = unknown (do NOT open new trades blind)
    return [p for p in (ps or []) if str(p.get("symbol", "")).upper() == sym.upper()]

def _any_history(days=2):
    try:
        return (_metaapi_bot.get_history(days) if _meta_on() else mt5_service.get_history(days)) or []
    except Exception:
        return None

def _realized_pnl(ticket, _fallback=None):
    """Net P/L (profit + commission + swap) of a closed position from the broker's deals, or None if not (yet) there."""
    deals = _any_history(2)
    if not deals:
        return None
    tot, found = 0.0, False
    for d in deals:
        key = d.get("position_id") if d.get("position_id") not in (None, "") else d.get("ticket")
        if str(key) == str(ticket):
            found = True
            tot += float(d.get("profit") or 0) + float(d.get("commission") or 0) + float(d.get("swap") or 0)
    return round(tot, 2) if found else None

def _any_close(ticket):
    return _metaapi_bot.close_position(ticket) if _meta_on() else mt5_service.close_position(ticket)

def _any_send_order(**kw):
    return _metaapi_bot.send_order(**kw) if _meta_on() else mt5_service.send_order(**kw)

def _any_modify(ticket, sl, tp, symbol):
    if _meta_on():
        return _metaapi_bot.modify_position(ticket, sl=sl, tp=tp, symbol=symbol)
    fn = getattr(mt5_service, "modify_position", None)
    return fn(ticket, sl=sl, tp=tp, symbol=symbol) if fn else {"status": "error", "message": "modify not supported"}

def _to_epoch(v):
    """Broker timestamps arrive as epoch ints (MT5/paper) or ISO strings (MetaApi)."""
    if v is None: return None
    if isinstance(v, (int, float)): return int(v)
    try: return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp())
    except Exception: return None


# ------------------------------------------------------------------ state
bot_config = {
    "enabled": False,
    "symbol": "XAUUSD",
    "risk_pct": 1.0,               # % of balance risked per trade
    "target_multiplier": 2.0,
    "flip_mode": True,             # 0 account flip mode: allows min lot 0.01 on micro balances
    "starting_balance": 0.0,
    "target_balance": 0.0,
    "max_trades_per_day": 12,
    "auto_lot": True,
    "fixed_lot": 0.01,
    "sl_atr_mult": 1.2,            # SL distance = 1.2 x ATR (pushed beyond the pullback swing when further away)
    "tp_atr_mult": 1.8,            # TP distance = 1.8 x ATR  -> R:R 1.5
    "timeframe": "M5",
    "session_filter": False,            # Default to False so it trades 24/7 in all sessions
    "max_hold_candles": 12,        # time-stop: close a trade that goes nowhere after N candles
    "close_on_opposite": True,
    "max_spread_points": 50,       # absolute spread cap (points = price*100) (was 35 — looser)
    "be_enabled": True,            # auto break-even
    "be_trigger_r": 1.0,           # move SL to entry +/- spread when floating profit >= 1 x initial risk
    "cooldown_candles_after_loss": 1,   # skip this many candles after a loss (was 2 — re-enter faster)
    "loss_streak_trigger": 3,           # N losses in a row -> take the longer break below (0 = off); trading then resumes
    "loss_streak_cooldown_candles": 4,  # ...skip this many candles (was 6 — M5: ~20 min, rebounded sooner)
    "htf_mode": "off",                  # H1 bias filter: default to OFF so it doesn't block trades
    "structure_mode": "off",            # M5 structure filter: default to OFF so it doesn't block trades
    "daily_loss_limit_enabled": True,   # switch for the daily-loss stop below (off = trade until max/day or target)
    "max_daily_loss_pct": 30.0,         # stop for the UTC day once today's P/L <= -X% of day-start balance (must be > risk_cap_pct or ONE loss ends the day)
    "risk_cap_pct": 25.0,               # per-trade ceiling: a trade whose real risk (min lot on a small account) exceeds this is blocked
    "tight_stop_fallback": True,        # small accounts: when the swing-based stop exceeds the cap, shrink the stop (inside the swing) until it fits
    "min_sl_atr_mult": 0.5,             # ...but never tighter than this many ATR (and never tighter than 3 x the live spread)
}

bot_stats = {
    "trades_today": 0, "wins": 0, "losses": 0, "breakevens": 0, "pnl_today": 0.0, "total_trades": 0,
    "consec_losses": 0, "cooldown_until": 0.0, "day_start_balance": None,
    "equity_curve": deque(maxlen=300), "log": deque(maxlen=100), "markers": deque(maxlen=120),
    "last_signal": "HOLD", "last_state": "WARMUP", "last_reason": "", "flip_progress": 0.0,
    "last_block": None,            # {"time","signal","reason"} - why the last TRIGGERED signal did NOT become a trade (None after a trade opens)
    "planned_setup": None,         # {"side","entry_price","symbol","timeframe","candle_time","as_of"} or None
    "active_trade": None,          # {"ticket","side","lot","entry","sl","tp","be_active","profit","opened_at"} or None
    "today_start": datetime.now(timezone.utc).date().isoformat(),
}

_task = None
_TF_SECS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}


def _log(msg, typ="info"):
    bot_stats["log"].append({"time": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"), "msg": msg, "type": typ})
    logger.info(f"[BOT] {msg}")

def _reset_daily_if_needed():
    today = datetime.now(timezone.utc).date().isoformat()
    if bot_stats["today_start"] != today:
        bot_stats.update(today_start=today, trades_today=0, pnl_today=0.0, wins=0, losses=0, breakevens=0,
                         consec_losses=0, cooldown_until=0.0, day_start_balance=None)
        risk_engine.day_start_balance = None
        _log(f"New day {today} — counters reset", "info")

BE_BAND = 0.15   # |P/L| below 15% of the initial risk = scratch (break-even exit), neither a win nor a loss

def record_close(pnl: float, risk: float = None):
    """Book a closed trade. `risk` = money risked at entry (None if unknown, e.g. after a restart). Returns WIN/LOSS/BE."""
    bot_stats["pnl_today"] += pnl
    bot_stats["total_trades"] += 1
    scratch = (abs(pnl) < BE_BAND * risk) if risk else (pnl == 0)
    if scratch:
        bot_stats["breakevens"] += 1
        return "BE"
    if pnl > 0:
        bot_stats["wins"] += 1
        bot_stats["consec_losses"] = 0
        return "WIN"
    bot_stats["losses"] += 1
    bot_stats["consec_losses"] += 1
    tf_secs = _TF_SECS.get(bot_config["timeframe"], 300)
    n = bot_config["cooldown_candles_after_loss"]
    trig = bot_config["loss_streak_trigger"]
    if trig and bot_stats["consec_losses"] >= trig:
        n = max(n, bot_config["loss_streak_cooldown_candles"])
        _log(f"{bot_stats['consec_losses']} losses in a row — taking a {n}-candle break, then searching again", "warn")
    bot_stats["cooldown_until"] = time.time() + n * tf_secs
    return "LOSS"

def get_bot_state():
    acc = _any_account()
    bal = acc["balance"] if acc else (bot_config["starting_balance"] or 0)
    tgt = bot_config["target_balance"] or (bal * bot_config["target_multiplier"] if bal else 0)
    start = bot_config["starting_balance"] or bal
    progress = max(0, min(100, ((bal - start) / (tgt - start)) * 100)) if tgt > start else 0.0
    bot_stats["flip_progress"] = round(progress, 2)
    total = bot_stats["wins"] + bot_stats["losses"]
    wr = round(bot_stats["wins"] / total * 100, 1) if total else 0
    return {"config": dict(bot_config), "enabled": bot_config["enabled"],
            "planned_setup": bot_stats["planned_setup"], "active_trade": bot_stats["active_trade"],
            "stats": {
        "trades_today": bot_stats["trades_today"], "wins": bot_stats["wins"], "losses": bot_stats["losses"],
        "breakevens": bot_stats["breakevens"], "consec_losses": bot_stats["consec_losses"],
        "day_start_balance": bot_stats["day_start_balance"],
        "pnl_today": round(bot_stats["pnl_today"], 2), "total_trades": bot_stats["total_trades"], "win_rate": wr,
        "equity_curve": list(bot_stats["equity_curve"])[-60:], "log": list(bot_stats["log"])[-40:],
        "markers": list(bot_stats["markers"])[-40:], "last_signal": bot_stats["last_signal"],
        "last_state": bot_stats["last_state"],
        "last_reason": bot_stats["last_reason"], "last_block": bot_stats["last_block"], "flip_progress": bot_stats["flip_progress"],
        "target_balance": round(tgt, 2), "starting_balance": round(start, 2), "current_balance": round(bal, 2)}}

def _sync_risk():
    """Push the user's risk settings into the risk engine (with sane bounds)."""
    bot_config["risk_pct"] = min(max(float(bot_config["risk_pct"] or 1.0), 0.05), 50.0)
    bot_config["risk_cap_pct"] = min(max(float(bot_config["risk_cap_pct"] or 10.0), 0.5), 100.0)
    bot_config["max_daily_loss_pct"] = min(max(float(bot_config["max_daily_loss_pct"] or 0.0), 0.0), 100.0)
    bot_config["min_sl_atr_mult"] = min(max(float(bot_config["min_sl_atr_mult"] or 0.5), 0.1), 5.0)
    risk_engine.max_risk_pct_hard = bot_config["risk_cap_pct"]
    risk_engine.max_daily_loss_pct = bot_config["max_daily_loss_pct"] if bot_config["daily_loss_limit_enabled"] else 0.0

def manual_trade_check(volume: float, symbol: str, action: str, sl=None):
    """Same safety gates as an automated entry, for POST /api/trade: lot bounds, hourly limit, daily-loss limit (from the fixed
    day-start balance), per-trade risk cap (when an SL is attached), margin. Returns (ok, reason). Fails closed without account data."""
    acc = _any_account()
    if not acc or float(acc.get("balance") or 0) <= 0:
        return False, "account info unavailable — cannot verify risk"
    _sync_risk()
    tick = _any_tick(symbol) or {}
    price = tick.get("ask") if str(action).upper() == "BUY" else tick.get("bid")
    sl_dist = abs(float(price) - float(sl)) if (price and sl) else None
    return risk_engine.can_trade(volume, symbol, balance=float(acc["balance"]), sl_dist=sl_dist, price=price,
                                 leverage=int(acc.get("leverage") or 2000), pnl_today=bot_stats["pnl_today"])


def update_config(patch: dict):
    for k, v in patch.items():
        if k in ("htf_mode", "structure_mode") and v not in ("off", "counter", "strict"):
            continue                                   # ignore unknown modes instead of silently disabling the filter
        if k in bot_config and k != "enabled":
            bot_config[k] = v
    if "flip_mode" in patch:
        risk_engine.flip_mode = bool(patch["flip_mode"])     # kept for the API; the cap itself is `risk_cap_pct`
    _sync_risk()
    if "target_multiplier" in patch or "starting_balance" in patch:
        sb = bot_config["starting_balance"]
        if sb: bot_config["target_balance"] = round(sb * bot_config["target_multiplier"], 2)
    return get_bot_state()


# ------------------------------------------------------------------ sizing: plan + lot that actually fit the account
ENTRY_ATTEMPTS = 3          # order/account hiccups are retried this many times within the same candle, then the candle is dropped


def _size_and_check(sig, entry, plan, balance, leverage, symbol, pnl_today):
    """Lot + money-at-risk for `plan`, then the risk-engine gate. Returns (lot, risk_money, ok, why)."""
    sl_dist = plan["risk"]
    if bot_config["auto_lot"]:
        lot, risk_money = risk_engine.calc_lot(balance, bot_config["risk_pct"], sl_dist)
    else:
        lot = float(bot_config["fixed_lot"]); risk_money = lot * risk_engine.contract_size * sl_dist
    ok, why = risk_engine.can_trade(lot, symbol, balance=balance, sl_dist=sl_dist, price=entry,
                                    leverage=leverage, pnl_today=pnl_today)
    return lot, risk_money, ok, why


def fit_plan_to_account(sig, entry, atr, swing_low, swing_high, balance, leverage, spread_px, symbol, pnl_today):
    """Build SL/TP and size the lot so the trade passes the risk gate.

    1) Normal plan: stop beyond the pullback swing (strategy.plan_trade).
    2) If ONLY the per-trade risk cap blocks it (min lot 0.01 on a small account) and `tight_stop_fallback` is on:
       shrink the stop step by step (0.1 ATR) down to `min_sl_atr_mult` (and >= 3 x live spread), IGNORING the swing
       (the old retry kept the swing, so the stop never actually got tighter and the retry was a no-op). TP keeps the
       configured R:R (>= MIN_RR) relative to the tighter stop.
    Returns dict(plan, lot, risk_money, ok, why, note).
    """
    sl_cfg, tp_cfg = float(bot_config["sl_atr_mult"]), float(bot_config["tp_atr_mult"])
    out = dict(plan=None, lot=0.0, risk_money=0.0, ok=False, why="", note=None)
    plan, why = plan_trade(sig, entry, atr, swing_low, swing_high, sl_cfg, tp_cfg)
    if not plan:
        out["why"] = why; return out
    lot, risk_money, ok, why = _size_and_check(sig, entry, plan, balance, leverage, symbol, pnl_today)
    out.update(plan=plan, lot=lot, risk_money=risk_money, ok=ok, why=why)
    if ok or not (bot_config["tight_stop_fallback"] and why.startswith(RISK_CAP_PREFIX)):
        return out

    floor = max(float(bot_config["min_sl_atr_mult"]), (3.0 * spread_px / atr) if atr > 0 else 0.0)
    if floor >= sl_cfg - 1e-9:
        out["why"] = why + f" — tight-stop fallback has no room (min stop {floor:.2f}×ATR ≥ SL×{sl_cfg})"; return out
    ratio = max(tp_cfg / sl_cfg, MIN_RR)
    mults, m = [], sl_cfg - 0.1
    while m > floor + 1e-9:
        mults.append(round(m, 3)); m -= 0.1
    mults.append(round(floor, 3))
    for mult in mults:
        tplan, _ = plan_trade(sig, entry, atr, None, None, mult, round(mult * ratio, 4))   # swing ignored on purpose
        if not tplan:
            continue
        tlot, trisk, tok, twhy = _size_and_check(sig, entry, tplan, balance, leverage, symbol, pnl_today)
        if tok:
            out.update(plan=tplan, lot=tlot, risk_money=trisk, ok=True, why="ok",
                       note=f"small-account fit: stop {mult:.2f}×ATR (inside the pullback swing) → SL {tplan['sl']:.2f} "
                            f"TP {tplan['tp']:.2f}, risk ${trisk:.2f} = {trisk / balance * 100:.1f}% of balance")
            return out
        out["why"] = twhy
    out["why"] = (out["why"] + f" — even the tightest allowed stop ({floor:.2f}×ATR) is too big for this balance. "
                  f"Raise 'Max risk cap' in the dashboard, lower 'Min stop', or add balance")
    return out


# ------------------------------------------------------------------ chart state (planned setup / active trade / markers)
def _publish_setup(result, symbol, has_position):
    """Expose PLANNED_SETUP to telemetry; cleared when a position is open, the setup invalidates or expires."""
    if has_position or result.get("state") != "PLANNED_SETUP":
        bot_stats["planned_setup"] = None
        return
    bot_stats["planned_setup"] = {"side": result["planned_side"], "entry_price": result["planned_entry_price"],
                                  "symbol": symbol, "timeframe": bot_config["timeframe"],
                                  "candle_time": result.get("candle_time"), "as_of": int(time.time())}

def _publish_trade(positions):
    if not positions:
        bot_stats["active_trade"] = None
        return
    p = positions[0]
    side, entry, sl = p["type"], float(p["price_open"]), p.get("sl")
    sl = float(sl) if sl else None
    be = bool(sl) and ((side == "BUY" and sl >= entry) or (side == "SELL" and sl <= entry))
    tp = p.get("tp")
    bot_stats["active_trade"] = {"ticket": str(p["ticket"]), "side": side, "lot": float(p.get("volume") or 0),
                                 "entry": entry, "sl": sl, "tp": float(tp) if tp else None, "be_active": be,
                                 "profit": float(p.get("profit") or 0), "opened_at": _to_epoch(p.get("time"))}

def _ensure_marker(p):
    """One persistent arrow per broker position (also rebuilt after a restart). Price = real fill price."""
    tkt = str(p["ticket"])
    for m in bot_stats["markers"]:
        if str(m.get("ticket")) == tkt:
            m["price"] = float(p["price_open"]); return
    bot_stats["markers"].append({"time": _to_epoch(p.get("time")) or int(time.time()), "price": float(p["price_open"]),
                                 "type": p["type"], "lot": float(p.get("volume") or 0), "ticket": tkt, "setup": None})


# ------------------------------------------------------------------ main loop
async def _get_htf(ctx, symbol, now_t):
    """H1 bias from CLOSED H1 candles, refreshed at most every 2 minutes. None when the H1 filter is off."""
    if bot_config["htf_mode"] == "off":
        return None
    cached = ctx.get("htf")
    if cached and now_t - cached["at"] < 120:
        return cached["bias"]
    try:
        h1, _src = await asyncio.to_thread(_any_candles, symbol, "H1", 160)
        bias = htf_bias(list(h1[:-1]) if h1 else [])        # drop the still-forming H1 candle
    except Exception as e:
        bias = {"bias": "UNKNOWN", "reason": f"H1 fetch failed: {e}"}
    ctx["htf"] = {"at": now_t, "bias": bias}
    return bias


async def _step(ctx):
    """One pass of the bot. Returns the number of seconds to sleep before the next pass."""
    _reset_daily_if_needed()
    symbol = bot_config["symbol"]
    tf_secs = _TF_SECS.get(bot_config["timeframe"], 300)
    tracked = ctx["tracked"]
    ctx.setdefault("risk", {})
    ctx.setdefault("owned", set())

    if not await asyncio.to_thread(_is_any_connected):
        _log("Not connected — waiting for broker", "warn"); return 5

    acc = await asyncio.to_thread(_any_account)
    if acc:
        bot_stats["equity_curve"].append({"t": int(time.time()), "equity": acc["equity"], "balance": acc["balance"]})
        if bot_stats["day_start_balance"] is None and acc.get("balance", 0) > 0:
            bot_stats["day_start_balance"] = float(acc["balance"])      # the daily-loss limit is measured from this, all day
        risk_engine.day_start_balance = bot_stats["day_start_balance"]

    # ---- 1. sync open positions; record P/L of anything that closed (broker SL/TP, manual, etc.)
    positions = await asyncio.to_thread(_any_positions, symbol)
    if positions is None:
        return 5                                   # unknown state: never act blind
    now_t = time.time()
    owned, unknown = split_positions(positions, ctx["owned"])       # only OUR positions are counted / managed / closed
    current = {p["ticket"]: p for p in owned}
    if unknown and not ctx.get("warned_unknown"):
        ctx["warned_unknown"] = True
        _log(f"{len(unknown)} position(s) on {symbol} carry no ownership tag — not touching them and not opening next to them", "warn")
    for t, info in list(tracked.items()):
        if t in current:
            continue
        pnl = await asyncio.to_thread(_realized_pnl, t)
        src = "broker"
        if pnl is None:
            if now_t - info.setdefault("gone_at", now_t) < 20:
                continue                           # broker history can lag a few seconds — retry next pass
            pnl, src = info["profit"], "est. from last floating P/L"
        kind = record_close(pnl, info.get("risk"))
        _log(f"Position {t} closed — {kind} P/L ${pnl:.2f} ({src})", "success" if pnl > 0 else "warn")
        del tracked[t]
    for t, p in current.items():
        tracked.setdefault(t, {"first_seen": now_t, "profit": 0.0, "risk": ctx["risk"].get(str(t))})["profit"] = float(p.get("profit") or 0)
        _ensure_marker(p)

    tick = await asyncio.to_thread(_any_tick, symbol)
    if not tick or not tick.get("bid"):
        bot_stats["last_reason"] = "No live tick"; _publish_trade(list(current.values())); return 5

    # ---- 2. auto break-even (every pass, independent of candle closes)
    if bot_config["be_enabled"]:
        for t, p in current.items():
            new_sl = break_even_sl(p["type"], float(p["price_open"]), float(p.get("sl") or 0), tick["bid"], tick["ask"],
                                   bot_config["be_trigger_r"])
            if new_sl is None or now_t < ctx["be_retry"].get(t, 0):
                continue
            r = await asyncio.to_thread(_any_modify, t, new_sl, p.get("tp"), p.get("broker_symbol") or symbol)
            if r.get("status") == "success":
                p["sl"] = new_sl
                _log(f"Break-even #{t}: SL → {new_sl:.2f} (entry {float(p['price_open']):.2f} ± spread)", "success")
            else:
                ctx["be_retry"][t] = now_t + 15
                _log(f"Break-even #{t} failed: {r.get('message')}", "warn")
    _publish_trade(list(current.values()))

    # ---- 3. analysis on CLOSED candles
    candles, source = await asyncio.to_thread(_any_candles, symbol, bot_config["timeframe"], 95)
    if not candles or len(candles) < 32:
        err = getattr(_metaapi_bot, '_last_candle_err', None) if _HAS_METAAPI_BOT else None
        bot_stats["last_reason"] = (f"Warming up candles ({len(candles or [])}/32) source={source}" +
                                     (f" — {err}" if err else ""))
        bot_stats["planned_setup"] = None
        return 10
    if source == "none":
        err = getattr(_metaapi_bot, '_last_candle_err', None) if _HAS_METAAPI_BOT else None
        bot_stats["last_reason"] = f"No candle source (all feeds empty)" + (f" — {err}" if err else "")
        return 10

    spread = tick.get("spread", 0) or 0
    htf = await _get_htf(ctx, symbol, now_t)
    result = analyze_symbol(candles, spread=spread, session_filter=bot_config["session_filter"],
                            max_spread_points=bot_config["max_spread_points"], htf=htf,
                            htf_mode=bot_config["htf_mode"], structure_mode=bot_config["structure_mode"])
    result["data_source"] = source
    sig = result["signal"]
    bot_stats["last_signal"] = sig
    bot_stats["last_state"] = result.get("state", "HOLD")
    bot_stats["last_reason"] = result.get("reason", "")
    _publish_setup(result, symbol, bool(current))

    ct = result.get("candle_time")
    if ctx["last_candle"] is None and ct is not None:
        ctx["last_candle"] = ct                    # first pass after start/restart: that candle is already old — wait for the next close
        ctx["entry_done"] = ct
        new_candle = False
    else:
        new_candle = ct is not None and ct != ctx["last_candle"]

    # ---- 4. manage open trades (opposite signal / time-stop; SL/TP/BE live on the broker)
    for t, p in list(current.items()):
        opened_at = _to_epoch(p.get("time")) or tracked[t]["first_seen"]
        age_candles = (now_t - opened_at) / tf_secs
        opposite = new_candle and sig in ("BUY", "SELL") and sig != p["type"]
        timed_out = age_candles >= bot_config["max_hold_candles"]
        if (bot_config["close_on_opposite"] and opposite) or timed_out:
            why = "opposite signal" if opposite else f"time-stop {age_candles:.0f} candles"
            r = await asyncio.to_thread(_any_close, t)
            _log(f"Close {t} ({why}): {r.get('message')}", "info" if r.get("status") == "success" else "error")
            if r.get("status") == "success":
                current.pop(t, None)               # P/L is booked by step 1 once the broker reports the deal
    if not current and bot_stats["active_trade"]:
        bot_stats["active_trade"] = None

    # ---- 5. entry: one decision per closed candle, flat only.
    # A candle is only "spent" (ctx["entry_done"]) when the decision is final: trade opened, or blocked by a real rule.
    # Transient trouble (no balance, broker order error) is retried a few times inside the same candle instead of
    # silently losing the signal.
    if new_candle:
        ctx["last_candle"] = ct
        ctx["attempts"] = 0
    if sig not in ("BUY", "SELL") or ct is None or ct == ctx.get("entry_done"):
        return 2 if current else 4

    def _skip(reason, level="warn", delay=4, retry=False):
        bot_stats["last_block"] = {"time": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"), "signal": sig, "reason": reason}
        _log(f"{sig} NOT opened — {reason}", level)
        if retry:
            ctx["attempts"] = ctx.get("attempts", 0) + 1
            if ctx["attempts"] >= ENTRY_ATTEMPTS:
                ctx["entry_done"] = ct
                _log(f"{sig} dropped after {ENTRY_ATTEMPTS} attempts on this candle — waiting for the next setup", "warn")
        else:
            ctx["entry_done"] = ct
        return delay

    if current:
        return _skip("a position is already open", "info", 2)
    if unknown:
        return _skip(f"untagged position(s) on {symbol}; cannot tell whether they are the bot's", "warn", 4)
    if bot_stats["trades_today"] >= bot_config["max_trades_per_day"]:
        return _skip(f"max trades/day reached ({bot_config['max_trades_per_day']})", "warn", 10)
    if now_t < bot_stats["cooldown_until"]:
        return _skip(f"cooling down after a loss ({int(bot_stats['cooldown_until'] - now_t)}s left)", "info", 4)

    acc = await asyncio.to_thread(_any_account)
    balance = float(acc["balance"]) if acc and acc.get("balance") else 0.0
    if balance <= 0:
        return _skip("account balance unavailable", "warn", 3, retry=True)
    leverage = int(acc.get("leverage") or 2000)
    atr = result["atr"]
    entry = tick["ask"] if sig == "BUY" else tick["bid"]
    spread_px = max(float(tick["ask"]) - float(tick["bid"]), 0.0)

    fit = fit_plan_to_account(sig, entry, atr, result.get("swing_low"), result.get("swing_high"),
                              balance, leverage, spread_px, symbol, bot_stats["pnl_today"])
    if not fit["ok"]:
        return _skip(fit["why"], "warn", 6)
    plan, lot, risk_money = fit["plan"], fit["lot"], fit["risk_money"]
    sl, tp = plan["sl"], plan["tp"]
    if fit["note"]:
        _log(f"Adjusted for account size: {fit['note']}", "success")

    eff_pct = risk_money / balance * 100.0
    if eff_pct > bot_config["risk_pct"] * 2:
        _log(f"⚠ min lot {lot} forces {eff_pct:.1f}% risk (setting is {bot_config['risk_pct']}%)", "warn")

    _log(f"{sig} [{result.get('setup')}] @ {entry:.2f} lot {lot} risk ${risk_money:.2f} "
         f"SL {sl:.2f} TP {tp:.2f} (R:R {plan['rr']}) • ATR {atr:.2f} RSI {result['rsi']} ({result['confidence']}%)", "info")
    order = await asyncio.to_thread(lambda: _any_send_order(symbol=symbol, action=sig, volume=lot, sl=sl, tp=tp,
                                                            magic=BOT_MAGIC, comment=BOT_COMMENT))
    if order.get("status") != "success":
        return _skip(f"broker rejected the order: {order.get('message')}", "error", 5, retry=True)

    ctx["entry_done"] = ct
    bot_stats["last_block"] = None
    bot_stats["trades_today"] += 1; risk_engine.register_trade(lot)
    ctx["risk"][str(order.get("ticket"))] = risk_money
    ctx["owned"].add(str(order.get("ticket")))
    bot_stats["planned_setup"] = None                # trade triggered -> planned line disappears
    bot_stats["markers"].append({"time": int(time.time()), "price": entry, "type": sig, "lot": lot,
                                 "ticket": str(order.get("ticket")), "setup": result.get("setup")})
    _log(f"Opened {sig} {lot} {symbol} ticket {order.get('ticket')}", "success")

    acc2 = await asyncio.to_thread(_any_account)
    if acc2 and bot_config["target_balance"] and acc2["balance"] >= bot_config["target_balance"]:
        _log(f"🎯 FLIP HIT! {acc2['balance']} >= {bot_config['target_balance']} — stopping", "success")
        bot_config["enabled"] = False
    return 2


async def _loop():
    _log("Pullback Scalper v2.6 started — EMA-zone rejection, 1 position max, auto break-even", "success")
    ctx = {"last_candle": None, "entry_done": None, "attempts": 0, "tracked": {}, "be_retry": {}, "risk": {}, "owned": set()}
    while bot_config["enabled"]:
        delay = 4
        try:
            delay = await _step(ctx)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("loop error")
            _log(f"Loop error: {e}", "error"); delay = 5
        await asyncio.sleep(delay)
    bot_stats["planned_setup"] = None
    _log("Auto Flip stopped", "info")


def start_bot():
    global _task
    if bot_config["enabled"] and _task and not _task.done(): return get_bot_state()
    acc = _any_account()
    if acc and not bot_config["starting_balance"]:
        bot_config["starting_balance"] = float(acc["balance"])
        bot_config["target_balance"] = round(bot_config["starting_balance"] * bot_config["target_multiplier"], 2)
    elif not bot_config["starting_balance"]:
        bot_config["starting_balance"] = 10.0
        bot_config["target_balance"] = round(10 * bot_config["target_multiplier"], 2)
    _reset_daily_if_needed()
    _sync_risk()
    bot_config["enabled"] = True
    try:
        _task = asyncio.get_running_loop().create_task(_loop())
    except RuntimeError:
        pass
    _log(f"START {bot_config['symbol']} {bot_config['timeframe']} risk {bot_config['risk_pct']}% "
         f"SL×{bot_config['sl_atr_mult']} TP×{bot_config['tp_atr_mult']} BE@{bot_config['be_trigger_r']}R max/day {bot_config['max_trades_per_day']}", "success")
    return get_bot_state()

def stop_bot():
    global _task
    bot_config["enabled"] = False
    if _task: _task.cancel(); _task = None
    bot_stats["planned_setup"] = None
    _log("STOPPED by user", "warn")
    return get_bot_state()

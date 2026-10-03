"""
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
from risk_engine import risk_engine
from strategy import analyze_symbol

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

def _any_close(ticket):
    return _metaapi_bot.close_position(ticket) if _meta_on() else mt5_service.close_position(ticket)

def _any_send_order(**kw):
    return _metaapi_bot.send_order(**kw) if _meta_on() else mt5_service.send_order(**kw)


# ------------------------------------------------------------------ state
bot_config = {
    "enabled": False,
    "symbol": "XAUUSD",
    "risk_pct": 1.0,               # % of balance risked per trade (v2.2 default 3% was never really honoured)
    "target_multiplier": 2.0,
    "starting_balance": 0.0,
    "target_balance": 0.0,
    "max_trades_per_day": 12,
    "auto_lot": True,
    "fixed_lot": 0.01,
    "sl_atr_mult": 1.6,
    "tp_atr_mult": 2.8,
    "timeframe": "M5",
    "session_filter": True,
    "max_hold_candles": 12,        # time-stop: close a trade that goes nowhere after N candles
    "close_on_opposite": True,
    "max_spread_points": 60,       # absolute spread cap (points = price*100)
}

bot_stats = {
    "trades_today": 0, "wins": 0, "losses": 0, "pnl_today": 0.0, "total_trades": 0,
    "equity_curve": deque(maxlen=300), "log": deque(maxlen=100), "markers": deque(maxlen=120),
    "last_signal": "HOLD", "last_reason": "", "flip_progress": 0.0,
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
        bot_stats.update(today_start=today, trades_today=0, pnl_today=0.0, wins=0, losses=0)
        _log(f"New day {today} — counters reset", "info")

def record_close(pnl: float):
    bot_stats["pnl_today"] += pnl
    if pnl >= 0: bot_stats["wins"] += 1
    else: bot_stats["losses"] += 1

def get_bot_state():
    acc = _any_account()
    bal = acc["balance"] if acc else (bot_config["starting_balance"] or 0)
    tgt = bot_config["target_balance"] or (bal * bot_config["target_multiplier"] if bal else 0)
    start = bot_config["starting_balance"] or bal
    progress = max(0, min(100, ((bal - start) / (tgt - start)) * 100)) if tgt > start else 0.0
    bot_stats["flip_progress"] = round(progress, 2)
    total = bot_stats["wins"] + bot_stats["losses"]
    wr = round(bot_stats["wins"] / total * 100, 1) if total else 0
    return {"config": dict(bot_config), "enabled": bot_config["enabled"], "stats": {
        "trades_today": bot_stats["trades_today"], "wins": bot_stats["wins"], "losses": bot_stats["losses"],
        "pnl_today": round(bot_stats["pnl_today"], 2), "total_trades": bot_stats["total_trades"], "win_rate": wr,
        "equity_curve": list(bot_stats["equity_curve"])[-60:], "log": list(bot_stats["log"])[-40:],
        "markers": list(bot_stats["markers"])[-40:], "last_signal": bot_stats["last_signal"],
        "last_reason": bot_stats["last_reason"], "flip_progress": bot_stats["flip_progress"],
        "target_balance": round(tgt, 2), "starting_balance": round(start, 2), "current_balance": round(bal, 2)}}

def update_config(patch: dict):
    for k, v in patch.items():
        if k in bot_config and k != "enabled":
            bot_config[k] = v
    if "target_multiplier" in patch or "starting_balance" in patch:
        sb = bot_config["starting_balance"]
        if sb: bot_config["target_balance"] = round(sb * bot_config["target_multiplier"], 2)
    return get_bot_state()


# ------------------------------------------------------------------ main loop
async def _loop():
    _log("Auto Flip v2.3 started — closed-candle signals, 1 position max, managed exits", "success")
    last_candle_handled = None
    tracked = {}        # ticket -> {"profit": float, "first_seen": ts}

    while bot_config["enabled"]:
        try:
            _reset_daily_if_needed()
            symbol = bot_config["symbol"]
            tf_secs = _TF_SECS.get(bot_config["timeframe"], 300)

            if not await asyncio.to_thread(_is_any_connected):
                _log("Not connected — waiting for broker", "warn"); await asyncio.sleep(5); continue

            acc = await asyncio.to_thread(_any_account)
            if acc:
                bot_stats["equity_curve"].append({"t": int(time.time()), "equity": acc["equity"], "balance": acc["balance"]})

            # ---- 1. sync open positions, record P/L of anything that closed (broker SL/TP, manual, etc.)
            positions = await asyncio.to_thread(_any_positions, symbol)
            if positions is None:
                await asyncio.sleep(5); continue
            now_t = time.time()
            current = {p["ticket"]: p for p in positions}
            for t, info in list(tracked.items()):
                if t not in current:
                    record_close(info["profit"])
                    _log(f"Position {t} closed — P/L ${info['profit']:.2f}", "success" if info["profit"] >= 0 else "warn")
                    del tracked[t]
            for t, p in current.items():
                tracked.setdefault(t, {"first_seen": now_t, "profit": 0.0})["profit"] = float(p.get("profit") or 0)

            # ---- 2. analysis on CLOSED candles
            candles, source = await asyncio.to_thread(_any_candles, symbol, bot_config["timeframe"], 120)
            if not candles or len(candles) < 45:
                bot_stats["last_reason"] = f"Warming up candles ({len(candles or [])}/45) source={source}"
                await asyncio.sleep(10); continue
            if source == "none":
                await asyncio.sleep(10); continue

            tick = await asyncio.to_thread(_any_tick, symbol)
            if not tick or not tick.get("bid"):
                bot_stats["last_reason"] = "No live tick"; await asyncio.sleep(5); continue
            spread = tick.get("spread", 0) or 0
            result = analyze_symbol(candles, spread=spread, session_filter=bot_config["session_filter"])
            result["data_source"] = source
            sig = result["signal"]
            bot_stats["last_signal"] = sig
            bot_stats["last_reason"] = result.get("reason", "")

            new_candle = result.get("candle_time") is not None and result["candle_time"] != last_candle_handled

            # ---- 3. manage open trades
            for t, p in list(current.items()):
                age_candles = (now_t - tracked[t]["first_seen"]) / tf_secs
                opposite = new_candle and sig in ("BUY", "SELL") and sig != p["type"]
                timed_out = age_candles >= bot_config["max_hold_candles"]
                if (bot_config["close_on_opposite"] and opposite) or timed_out:
                    why = "opposite signal" if opposite else f"time-stop {age_candles:.0f} candles"
                    r = await asyncio.to_thread(_any_close, t)
                    _log(f"Close {t} ({why}): {r.get('message')}", "info" if r.get("status") == "success" else "error")
                    if r.get("status") == "success":
                        record_close(float(r.get("profit", tracked[t]["profit"])))
                        tracked.pop(t, None); current.pop(t, None)

            # ---- 4. entries (one per closed candle, flat only)
            if not new_candle or sig not in ("BUY", "SELL"):
                if new_candle: last_candle_handled = result.get("candle_time")
                await asyncio.sleep(4); continue
            last_candle_handled = result["candle_time"]   # consume the candle, even if we end up skipping it

            if current:
                _log(f"{sig} signal skipped — position already open", "info"); await asyncio.sleep(4); continue
            if bot_stats["trades_today"] >= bot_config["max_trades_per_day"]:
                _log("Max trades/day reached", "warn"); await asyncio.sleep(10); continue
            if spread > bot_config["max_spread_points"]:
                _log(f"Spread {spread} pts too high — skip {sig}", "warn"); await asyncio.sleep(5); continue

            acc = await asyncio.to_thread(_any_account)
            balance = float(acc["balance"]) if acc else 0.0
            leverage = int(acc.get("leverage", 2000)) if acc else 2000
            atr = result["atr"]
            sl_dist, tp_dist = atr * bot_config["sl_atr_mult"], atr * bot_config["tp_atr_mult"]
            if sl_dist <= 0:
                await asyncio.sleep(4); continue

            if bot_config["auto_lot"]:
                lot, risk_money = risk_engine.calc_lot(balance, bot_config["risk_pct"], sl_dist)
            else:
                lot = float(bot_config["fixed_lot"]); risk_money = lot * risk_engine.contract_size * sl_dist

            entry = tick["ask"] if sig == "BUY" else tick["bid"]
            ok, why = risk_engine.can_trade(lot, symbol, balance=balance, sl_dist=sl_dist, price=entry,
                                            leverage=leverage, pnl_today=bot_stats["pnl_today"])
            if not ok:
                _log(f"Risk blocked {sig} {lot}: {why}", "warn"); await asyncio.sleep(6); continue

            sl = entry - sl_dist if sig == "BUY" else entry + sl_dist
            tp = entry + tp_dist if sig == "BUY" else entry - tp_dist
            _log(f"{sig} [{result.get('setup')}] @ {entry:.2f} lot {lot} risk ${risk_money:.2f} "
                 f"SL {sl:.2f} TP {tp:.2f} • ATR {atr:.2f} ADX {result['adx']} RSI {result['rsi']} ({result['confidence']}%)", "info")
            order = await asyncio.to_thread(lambda: _any_send_order(symbol=symbol, action=sig, volume=lot, sl=round(sl, 2), tp=round(tp, 2)))
            if order.get("status") == "success":
                bot_stats["trades_today"] += 1; bot_stats["total_trades"] += 1; risk_engine.register_trade(lot)
                bot_stats["markers"].append({"time": int(time.time()), "price": entry, "type": sig, "lot": lot,
                                             "rsi": result["rsi"], "atr": atr, "setup": result.get("setup")})
                _log(f"Opened {sig} {lot} {symbol} ticket {order.get('ticket')}", "success")
                await asyncio.sleep(5)
            else:
                _log(f"Order failed: {order.get('message')}", "error"); await asyncio.sleep(6)

            acc2 = await asyncio.to_thread(_any_account)
            if acc2 and bot_config["target_balance"] and acc2["balance"] >= bot_config["target_balance"]:
                _log(f"🎯 FLIP HIT! {acc2['balance']} >= {bot_config['target_balance']} — stopping", "success")
                bot_config["enabled"] = False; break
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("loop error")
            _log(f"Loop error: {e}", "error"); await asyncio.sleep(5)
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
    bot_config["enabled"] = True
    try:
        _task = asyncio.get_running_loop().create_task(_loop())
    except RuntimeError:
        pass
    _log(f"START {bot_config['symbol']} {bot_config['timeframe']} risk {bot_config['risk_pct']}% "
         f"SL×{bot_config['sl_atr_mult']} TP×{bot_config['tp_atr_mult']} max/day {bot_config['max_trades_per_day']}", "success")
    return get_bot_state()

def stop_bot():
    global _task
    bot_config["enabled"] = False
    if _task: _task.cancel(); _task = None
    _log("STOPPED by user", "warn")
    return get_bot_state()

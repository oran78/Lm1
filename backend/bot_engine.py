"""
Klop Apex — Auto Flip Engine v2.2
EMA+RSI+ATR+ADX+Session, ATR SL/TP, $10 safe
"""
import asyncio, time, logging
from collections import deque
from datetime import datetime, timezone

from mt5_service import mt5_service
from risk_engine import risk_engine
from strategy import analyze_symbol

logger = logging.getLogger("klop.bot")

bot_config = {
    "enabled": False,
    "symbol": "XAUUSD",
    "risk_pct": 3.0,               # $10: 3% => ~$0.30 risk/trade
    "target_multiplier": 2.0,      # x2 flip
    "starting_balance": 0.0,
    "target_balance": 0.0,
    "max_trades_per_day": 12,      # stricter for $10
    "auto_lot": True,
    "fixed_lot": 0.01,
    "sl_atr_mult": 1.6,
    "tp_atr_mult": 2.8,            # ~1:1.75 RR via ATR
    "timeframe": "M5",
    "session_filter": True,
}

bot_stats = {
    "trades_today": 0, "wins": 0, "losses": 0, "pnl_today": 0.0, "total_trades": 0,
    "equity_curve": deque(maxlen=300),
    "log": deque(maxlen=100),
    "markers": deque(maxlen=120),
    "last_signal": "HOLD", "last_reason": "", "flip_progress": 0.0,
    "today_start": datetime.now(timezone.utc).date().isoformat(),
}

_task = None

def _log(msg, typ="info"):
    e={"time": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"), "msg": msg, "type": typ}
    bot_stats["log"].append(e); logger.info(f"[BOT] {msg}")

def _reset_daily_if_needed():
    today=datetime.now(timezone.utc).date().isoformat()
    if bot_stats["today_start"] != today:
        bot_stats["today_start"]=today; bot_stats["trades_today"]=0; bot_stats["pnl_today"]=0.0; bot_stats["wins"]=0; bot_stats["losses"]=0
        _log(f"New day {today} — reset", "info")

def get_bot_state():
    acc=mt5_service.get_account_info()
    bal=acc["balance"] if acc else bot_config["starting_balance"] or 0
    tgt=bot_config["target_balance"] or (bal*bot_config["target_multiplier"] if bal else 0)
    start=bot_config["starting_balance"] or bal
    progress=0.0
    if tgt>start: progress=max(0,min(100,((bal-start)/(tgt-start))*100)) if tgt!=start else 0
    bot_stats["flip_progress"]=round(progress,2)
    total=bot_stats["wins"]+bot_stats["losses"]
    wr=round((bot_stats["wins"]/total*100) if total else 0,1)
    return {"config": dict(bot_config), "stats": {"trades_today":bot_stats["trades_today"],"wins":bot_stats["wins"],"losses":bot_stats["losses"],"pnl_today":round(bot_stats["pnl_today"],2),"total_trades":bot_stats["total_trades"],"win_rate":wr,"equity_curve":list(bot_stats["equity_curve"])[-60:],"log":list(bot_stats["log"])[-40:],"markers":list(bot_stats["markers"])[-40:],"last_signal":bot_stats["last_signal"],"last_reason":bot_stats["last_reason"],"flip_progress":bot_stats["flip_progress"],"target_balance":round(tgt,2),"starting_balance":round(start,2),"current_balance":round(bal,2)}, "enabled": bot_config["enabled"]}

def update_config(patch: dict):
    for k,v in patch.items():
        if k in bot_config: bot_config[k]=v
    if "target_multiplier" in patch or "starting_balance" in patch:
        sb=bot_config["starting_balance"]
        if sb: bot_config["target_balance"]=round(sb*bot_config["target_multiplier"],2)
    return get_bot_state()

async def _loop():
    _log("Auto Flip v2.2 started — ATR SL/TP + ADX + Session", "success")
    while bot_config["enabled"]:
        try:
            _reset_daily_if_needed()
            acc=mt5_service.get_account_info()
            if acc: bot_stats["equity_curve"].append({"t": int(time.time()), "equity": acc["equity"], "balance": acc["balance"]})
            if not mt5_service.is_connected():
                _log("Not connected — waiting Exness login", "warn"); await asyncio.sleep(5); continue
            if bot_stats["trades_today"] >= bot_config["max_trades_per_day"]:
                await asyncio.sleep(10); continue

            symbol=bot_config["symbol"]
            candles=mt5_service.get_candles(symbol, bot_config["timeframe"], 100)
            if not candles or len(candles)<35: await asyncio.sleep(3); continue

            tick=mt5_service.get_tick(symbol)
            spread=tick.get("spread",0) if tick else 0
            result=analyze_symbol(candles, spread=spread)
            bot_stats["last_signal"]=result.get("signal","HOLD"); bot_stats["last_reason"]=result.get("reason","")
            sig=result["signal"]
            if sig not in ("BUY","SELL"):
                await asyncio.sleep(4); continue

            # $10: spread veto stricter
            if spread and spread > 45:
                _log(f"Spread {spread} too high — skip {sig} (ATR {result.get('atr')})", "warn"); await asyncio.sleep(5); continue

            # lot calc ATR-aware
            acc=mt5_service.get_account_info(); balance=acc["balance"] if acc else 10.0
            atr=result.get("atr",0.8) or 0.8
            # convert ATR to points: atr / 0.01
            sl_points_est = max(90, min(350, int(round((atr * bot_config["sl_atr_mult"]) / 0.01))))
            if bot_config["auto_lot"]:
                lot=risk_engine.calc_lot(balance, bot_config["risk_pct"], atr=atr, sl_points=sl_points_est)
            else:
                lot=float(bot_config["fixed_lot"])

            allowed, reason=risk_engine.can_trade(lot, symbol)
            if not allowed:
                _log(f"Risk blocked {sig} {lot}: {reason}", "warn"); await asyncio.sleep(6); continue

            price=result.get("price") or (tick["ask"] if sig=="BUY" else tick["bid"])
            atr_val=atr
            sl_dist=atr_val*bot_config["sl_atr_mult"]; tp_dist=atr_val*bot_config["tp_atr_mult"]
            if sig=="BUY":
                sl=price - sl_dist; tp=price + tp_dist
            else:
                sl=price + sl_dist; tp=price - tp_dist

            _log(f"{sig} @ {price:.2f} ATR {atr_val:.2f} ADX {result.get('adx')} RSI {result.get('rsi')} lot {lot} → SL {sl:.2f} TP {tp:.2f} ({result.get('confidence',0)}%)", "info")
            order=mt5_service.send_order(symbol=symbol, action=sig, volume=lot, sl=round(sl,2), tp=round(tp,2))
            if order.get("status")=="success":
                bot_stats["trades_today"]+=1; bot_stats["total_trades"]+=1; risk_engine.register_trade(lot)
                bot_stats["markers"].append({"time": int(time.time()), "price": price, "type": sig, "lot": lot, "rsi": result.get("rsi"), "atr": atr_val})
                _log(f"Opened {sig} {lot} {symbol} ticket {order.get('ticket')} SL {sl:.2f} TP {tp:.2f}", "success")
                await asyncio.sleep(12)
            else:
                _log(f"Order failed: {order.get('message')}", "error"); await asyncio.sleep(6)

            acc2=mt5_service.get_account_info()
            if acc2 and bot_config["target_balance"] and acc2["balance"]>=bot_config["target_balance"]:
                _log(f"🎯 FLIP HIT! {acc2['balance']} >= {bot_config['target_balance']} — stopping", "success")
                bot_config["enabled"]=False; break
        except asyncio.CancelledError:
            break
        except Exception as e:
            _log(f"Loop error: {e}", "error"); await asyncio.sleep(5)
    _log("Auto Flip stopped", "info")

def start_bot():
    global _task
    if bot_config["enabled"] and _task and not _task.done(): return get_bot_state()
    acc=mt5_service.get_account_info()
    if acc and not bot_config["starting_balance"]:
        bot_config["starting_balance"]=float(acc["balance"])
        bot_config["target_balance"]=round(bot_config["starting_balance"]*bot_config["target_multiplier"],2)
    elif not bot_config["starting_balance"]:
        bot_config["starting_balance"]=10.0; bot_config["target_balance"]=round(10*bot_config["target_multiplier"],2)
    _reset_daily_if_needed()
    bot_config["enabled"]=True
    try:
        loop=asyncio.get_running_loop(); _task=loop.create_task(_loop())
    except RuntimeError:
        pass
    _log(f"START {bot_config['symbol']} M5 risk {bot_config['risk_pct']}% x{bot_config['target_multiplier']} → {bot_config['target_balance']} ATR SL×{bot_config['sl_atr_mult']} TP×{bot_config['tp_atr_mult']} max/day {bot_config['max_trades_per_day']}", "success")
    return get_bot_state()

def stop_bot():
    global _task
    bot_config["enabled"]=False
    if _task: _task.cancel(); _task=None
    _log("STOPPED by user", "warn")
    return get_bot_state()

def record_close(pnl: float):
    bot_stats["pnl_today"]+=pnl
    if pnl>=0: bot_stats["wins"]+=1
    else: bot_stats["losses"]+=1

"""v2.6 rules: spike guard, Stochastic gate, scratch trades, loss-streak pause, broker-priced P/L, stale-start seeding.
All data is SIMULATED (seeded random walk) — it only exercises the rules, it says nothing about profitability."""
import sys, os, random, asyncio, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
import strategy as st
import bot_engine as be

NOW = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)

def series(seed, n=1500, cycle=120):
    rnd = random.Random(seed); p = 4100.0; out = []; d = 0
    for i in range(n):
        if i % cycle == 0: d = rnd.choice([0.25, -0.25, 0.0, 0.35, -0.35])
        o = p; p = p + d + rnd.gauss(0, 0.9)
        out.append({"time": 1_800_000_000 + i * 300, "open": o, "high": max(o, p) + abs(rnd.gauss(0, 0.35)),
                    "low": min(o, p) - abs(rnd.gauss(0, 0.35)), "close": p, "volume": 1})
    return out

cs = series(2)
def scan(**kw):
    return [(e, st.analyze_symbol(cs[:e], spread=30, now=NOW, session_filter=False, **kw)) for e in range(60, len(cs))]

# ---- 1) one parameter set: strategy constants == bot defaults == documented values
assert (st.CHOP_ATR_FRAC, st.RSI_BAND, st.APPROACH_ATR) == (0.30, (42.0, 58.0), 0.75)
assert be.bot_config["sl_atr_mult"] == 1.2 and be.bot_config["tp_atr_mult"] == 1.8 and be.bot_config["be_trigger_r"] == 1.0
assert abs(be.bot_config["tp_atr_mult"] / be.bot_config["sl_atr_mult"] - 1.5) < 1e-9
assert not hasattr(st, "_bollinger_bands"), "dead Bollinger code should be gone"
print("single parameter set OK")

# ---- 2) Stochastic is a real gate now: every trigger is confirmed, and turning the gate off adds triggers
base = scan()
trig = [(e, r) for e, r in base if r["signal"] in ("BUY", "SELL")]
assert trig, "no triggers at all"
for e, r in trig:
    if r["signal"] == "BUY": assert r["stoch_k"] > r["stoch_d"] and r["stoch_k"] < st.STOCH_EXHAUST[1], r
    else: assert r["stoch_k"] < r["stoch_d"] and r["stoch_k"] > st.STOCH_EXHAUST[0], r
st.STOCH_CONFIRM = False
loose = [(e, r) for e, r in scan() if r["signal"] in ("BUY", "SELL")]
st.STOCH_CONFIRM = True
assert len(loose) > len(trig), (len(loose), len(trig))
print(f"stoch gate OK ({len(trig)} confirmed triggers vs {len(loose)} without the gate)")

# ---- 3) spike guard: a news-sized candle blocks entries for SPIKE_LOOKBACK candles, then releases
e0, r0 = trig[0]
data = [dict(c) for c in cs[:e0 - 1]]                      # closed candles up to (not incl.) the trigger candle
last = data[-1]
spike = dict(last, high=last["close"] + 12.0, low=last["close"] - 12.0)   # ~±12 $ range vs ATR ~1.5
for k in range(1, st.SPIKE_LOOKBACK + 1):
    d = data[:len(data) - 1] + [spike]
    window = d + [dict(cs[e0 - 1 + i]) for i in range(k - 1)]               # spike is k-1 candles old
    res = st.analyze_symbol(window + [dict(cs[e0])], spread=30, now=NOW, session_filter=False)
    assert res["state"] == "BLOCKED" and "spike" in res["reason"].lower() and res["signal"] == "HOLD", res
print("spike guard OK")

# ---- 4) scratch trades are not wins; losses -> short cooldown; a streak -> longer break, then trading RESUMES; wins reset the streak
shim = types.SimpleNamespace(time=lambda: 1_000_000.0); be.time = shim
def reset():
    be.bot_stats.update(wins=0, losses=0, breakevens=0, pnl_today=0.0, total_trades=0, consec_losses=0,
                        cooldown_until=0.0)
reset()
be.bot_config.update(loss_streak_trigger=3, loss_streak_cooldown_candles=6, cooldown_candles_after_loss=2, timeframe="M5")
assert be.record_close(0.30, risk=10.0) == "BE"            # +3% of risk -> scratch (SL moved to entry + spread)
assert be.record_close(-0.50, risk=10.0) == "BE"
assert be.bot_stats["wins"] == 0 and be.bot_stats["losses"] == 0 and be.bot_stats["breakevens"] == 2
assert be.record_close(15.0, risk=10.0) == "WIN" and be.bot_stats["consec_losses"] == 0
assert be.record_close(-10.0, risk=10.0) == "LOSS" and be.bot_stats["cooldown_until"] == 1_000_000.0 + 2 * 300
assert be.record_close(-4.0) == "LOSS"                      # unknown risk (after restart) -> sign decides
assert be.bot_stats["consec_losses"] == 2 and be.bot_stats["cooldown_until"] == 1_000_000.0 + 2 * 300
assert be.record_close(0.4, risk=10.0) == "BE" and be.bot_stats["consec_losses"] == 2     # a scratch neither breaks nor extends it
assert be.record_close(-10.0, risk=10.0) == "LOSS" and be.bot_stats["consec_losses"] == 3
assert be.bot_stats["cooldown_until"] == 1_000_000.0 + 6 * 300, "3rd loss in a row -> 6-candle break (not a day-long pause)"
assert not hasattr(be, "paused") and "paused_for_day" not in be.bot_stats
assert be.bot_stats["total_trades"] == 7 and abs(be.bot_stats["pnl_today"] - (0.3 - 0.5 + 15 - 10 - 4 + 0.4 - 10)) < 1e-9
be.bot_config["loss_streak_trigger"] = 0                    # streak break switched off -> only the short cooldown applies
be.record_close(-10.0, risk=10.0); assert be.bot_stats["cooldown_until"] == 1_000_000.0 + 2 * 300
be.bot_config["loss_streak_trigger"] = 3
be.bot_stats["today_start"] = "1970-01-01"; be._reset_daily_if_needed()
assert be.bot_stats["consec_losses"] == 0 and be.bot_stats["cooldown_until"] == 0.0
print("scratch / streak break OK")

# ---- 5) engine: only the cooldown blocks an entry (and it expires), a stale candle at start is not traded, P/L fallback after broker lag
reset()
S = {"candles": cs[:trig[0][0]], "positions": [], "history": [], "sent": [],
     "tick": {"symbol": "XAUUSD", "bid": trig[0][1]["price"] - 0.15, "ask": trig[0][1]["price"] + 0.15, "spread": 30.0}}
be._is_any_connected = lambda: True
be._any_account = lambda: {"balance": 1000.0, "equity": 1000.0, "leverage": 2000}
be._any_positions = lambda sym: list(S["positions"])
be._any_tick = lambda sym: S["tick"]
be._any_candles = lambda sym, tf, n: (S["candles"], "BROKER")
be._any_history = lambda days=2: S["history"]
be._any_modify = lambda *a, **k: {"status": "success", "message": "ok"}
def fake_send(**kw):
    S["sent"].append(kw)
    S["positions"].append({"ticket": "9", "symbol": "XAUUSD", "type": kw["action"], "volume": kw["volume"],
                           "price_open": S["tick"]["ask"], "price_current": S["tick"]["ask"], "profit": 0.0,
                           "sl": kw["sl"], "tp": kw["tp"], "time": int(shim.time())})
    return {"status": "success", "ticket": "9", "message": "ok"}
be._any_send_order = fake_send
be.bot_config.update(session_filter=False, enabled=True, risk_pct=1.0, max_trades_per_day=50, htf_mode="off", structure_mode="off")
be.risk_engine.max_trades_per_hour = 50
ctx = {"last_candle": None, "tracked": {}, "be_retry": {}, "risk": {}}
run = lambda: asyncio.run(be._step(ctx))

run()                                                       # first pass: the latest closed candle is already old
assert not S["sent"], "traded a stale candle right after start"
assert ctx["last_candle"] is not None
run(); assert not S["sent"]                                 # same candle again -> not "new", still no trade

ctx["last_candle"] = "something-else"                       # force "new candle" with the trigger candle on screen
be.bot_stats.update(consec_losses=3, cooldown_until=shim.time() + 6 * 300)     # right after a 3-loss streak
run(); assert not S["sent"], "entered during the streak break"
ctx["last_candle"] = "something-else"
be.bot_stats["cooldown_until"] = shim.time() - 1                                # break is over -> same day, search again
run(); assert len(S["sent"]) == 1, "must keep trading the same day once the break is over (no day-long pause)"
assert "9" in ctx["risk"] and ctx["risk"]["9"] > 0
run()                                                       # sync the position into `tracked`
assert be.bot_stats["total_trades"] == 0, "total_trades must count closes only"

S["positions"].clear(); S["tick"] = dict(S["tick"])         # broker closes it; deal history has NOT arrived yet
shim.time = lambda: 1_000_000.0; run()
assert be.bot_stats["total_trades"] == 0 and "9" in ctx["tracked"], "must wait for the broker deal"
shim.time = lambda: 1_000_000.0 + 25; run()                 # still nothing after 20 s -> fall back to the last floating P/L
assert be.bot_stats["total_trades"] == 1 and "9" not in ctx["tracked"]
print("engine gates / stale start / P-L fallback OK")

# ---- 6) daily-loss cap is configurable; 0 = off (the bot then trades until max_trades_per_day or the target)
from risk_engine import risk_engine as RE
RE.day_start_balance = None                                  # (engine tests above set it to $1000) -> fall back to the passed balance
be.update_config({"max_daily_loss_pct": 8.0}); ok, why = RE.can_trade(0.01, "XAUUSD", 100.0, 1.0, 4100.0, pnl_today=-9.0)
assert not ok and "Daily loss limit" in why, why
be.update_config({"max_daily_loss_pct": 0}); ok, why = RE.can_trade(0.01, "XAUUSD", 100.0, 1.0, 4100.0, pnl_today=-9.0)
assert ok, why
be.update_config({"max_daily_loss_pct": 8.0})
print("daily-loss cap configurable OK")

# ---- 7) UI settings: daily-loss switch + %, risk cap, bounds
from risk_engine import risk_engine as RE
be.update_config({"daily_loss_limit_enabled": False, "max_daily_loss_pct": 8.0})
assert RE.max_daily_loss_pct == 0.0 and RE.can_trade(0.01, "XAUUSD", 100.0, 1.0, 4100.0, pnl_today=-60.0)[0], "switch off -> no daily stop"
be.update_config({"daily_loss_limit_enabled": True, "max_daily_loss_pct": 30.0})
assert RE.max_daily_loss_pct == 30.0
assert not RE.can_trade(0.01, "XAUUSD", 100.0, 1.0, 4100.0, pnl_today=-31.0)[0]
assert RE.can_trade(0.01, "XAUUSD", 100.0, 1.0, 4100.0, pnl_today=-29.0)[0]
# per-trade cap is one explicit number (flip_mode no longer silently switches 10% / 20%)
be.update_config({"risk_cap_pct": 10.0, "flip_mode": True})
ok, why = RE.can_trade(0.01, "XAUUSD", 10.0, 2.4, 4100.0)            # $2.40 risk on $10 = 24%
assert not ok and "cap 10%" in why, why
be.update_config({"risk_cap_pct": 30.0})
assert RE.can_trade(0.01, "XAUUSD", 10.0, 2.4, 4100.0)[0], "24% risk must pass a 30% cap"
# bounds are enforced server-side too
be.update_config({"risk_pct": 500.0, "risk_cap_pct": 0.0, "max_daily_loss_pct": 900.0})
assert be.bot_config["risk_pct"] == 50.0 and be.bot_config["risk_cap_pct"] == 10.0 and be.bot_config["max_daily_loss_pct"] == 100.0, be.bot_config
be.update_config({"risk_pct": 1.0, "risk_cap_pct": 20.0, "max_daily_loss_pct": 8.0, "daily_loss_limit_enabled": True})
assert be.get_bot_state()["config"]["risk_cap_pct"] == 20.0 and be.get_bot_state()["config"]["daily_loss_limit_enabled"] is True
print("UI risk settings OK")
print("ALL v2.6 TESTS PASSED")

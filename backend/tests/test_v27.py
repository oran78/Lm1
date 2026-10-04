"""v2.7: position ownership, fixed day-start loss reference, manual-trade gate, RSI current-value rule, market structure, H1 bias.
Synthetic data is used ONLY to exercise the rules (deterministic unit tests) — it says nothing about profitability."""
import sys, os, random, asyncio, types, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
import strategy as st
import bot_engine as be
import market_context as mc
from ownership import BOT_MAGIC, MANUAL_MAGIC, split_positions
from risk_engine import risk_engine as RE

NOW = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)

# ----------------------------------------------------------------------------------------------- helpers
def candle(t, o, h, l, c): return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 1}

def path_candles(points, step=4, wick=0.1, t0=1_800_000_000, tf=300, tail=2):
    """Candles that walk linearly between turning points -> clean fractal swings at every turning point."""
    prices = []
    for a, b in zip(points, points[1:]):
        prices += [a + (b - a) * k / step for k in range(step)]
    prices.append(points[-1])
    prices += [points[-1] + (-1 if points[-1] < points[-2] else 1) * 0.3 * (i + 1) for i in range(tail)]
    out = []
    for i, p in enumerate(prices):
        o = prices[i - 1] if i else p
        out.append(candle(t0 + i * tf, o, max(o, p) + wick, min(o, p) - wick, p))
    return out

def h1_series(direction, n=160):
    out = []
    for i in range(n):
        base = 4000.0 + (2.0 * i if direction == "up" else -2.0 * i if direction == "down" else 0.0)
        wob = 3.0 * math.sin(i / 3.0) if direction != "flat" else (0.5 if i % 2 else -0.5)
        p = base + wob
        o = base + (3.0 * math.sin((i - 1) / 3.0) if direction != "flat" else (0.5 if (i - 1) % 2 else -0.5))
        out.append(candle(1_800_000_000 + i * 3600, o, max(o, p) + 1.0, min(o, p) - 1.0, p))
    return out

# ----------------------------------------------------------------------------------------------- 1) ownership
reg = {"77"}
pos = [{"ticket": 1, "magic": BOT_MAGIC}, {"ticket": 2, "magic": MANUAL_MAGIC}, {"ticket": 3, "magic": 0},
       {"ticket": 4, "magic": 999}, {"ticket": 5, "magic": None}, {"ticket": 6}, {"ticket": "77", "magic": 0},
       {"ticket": 8, "magic": str(BOT_MAGIC)}]
owned, unknown = split_positions(pos, reg)
assert sorted(str(p["ticket"]) for p in owned) == ["1", "77", "8"], owned
assert sorted(str(p["ticket"]) for p in unknown) == ["5", "6"], unknown      # no magic reported -> unknown (never touched)
print("ownership split OK")

# ----------------------------------------------------------------------------------------------- 2) market structure
bull = path_candles([100, 110, 104, 118, 108, 126, 114, 130, 120])
bear = path_candles([130, 120, 126, 112, 118, 104, 110, 96, 102])
flat = path_candles([100, 110, 100, 110, 100, 110, 100, 110, 100])
assert mc.market_structure(bull)["state"] == "BULL", mc.market_structure(bull)
assert mc.market_structure(bear)["state"] == "BEAR", mc.market_structure(bear)
assert mc.market_structure(flat)["state"] == "RANGE", mc.market_structure(flat)
assert mc.market_structure(path_candles([100, 110, 104]))["state"] == "RANGE"       # not enough swings
# no look-ahead: a swing is only reported once n later candles have closed, and it never changes afterwards
full = mc.swing_points(bull)
for k in range(8, len(bull)):
    pre = mc.swing_points(bull[:k])
    assert all(s["i"] <= k - 1 - 2 for s in pre), "swing reported before its confirmation candle closed"
    assert all(s in full for s in pre), "a confirmed swing changed / disappeared when later candles arrived"
print("market structure OK (BULL / BEAR / RANGE, no look-ahead)")

# ----------------------------------------------------------------------------------------------- 3) H1 bias
assert mc.htf_bias(h1_series("up"))["bias"] == "BULL", mc.htf_bias(h1_series("up"))
assert mc.htf_bias(h1_series("down"))["bias"] == "BEAR", mc.htf_bias(h1_series("down"))
assert mc.htf_bias(h1_series("flat"))["bias"] == "NEUTRAL", mc.htf_bias(h1_series("flat"))
assert mc.htf_bias(h1_series("up", 40))["bias"] == "UNKNOWN"
up = h1_series("up", 200)
assert all(mc.htf_bias(up[:k]) == mc.htf_bias(list(up[:k]) + [])  for k in (90, 120, 150))     # pure function of the closed prefix
print("H1 bias OK")

# ----------------------------------------------------------------------------------------------- 4) RSI: current value matters
assert st.rsi_ok("BUY", 50.0, 55.0)[0] and st.rsi_ok("SELL", 50.0, 45.0)[0]
ok, why = st.rsi_ok("BUY", 50.0, 71.0);  assert not ok and "extended" in why, why        # cooled earlier, already ran away now
ok, why = st.rsi_ok("SELL", 50.0, 28.0); assert not ok and "extended" in why, why
assert not st.rsi_ok("BUY", 38.0, 50.0)[0] and not st.rsi_ok("BUY", 63.0, 60.0)[0]       # pullback value outside the band
assert st.rsi_ok("BUY", 50.0, 65.0)[0] and not st.rsi_ok("BUY", 50.0, 65.1)[0]           # boundary
print("RSI rule OK")

# ----------------------------------------------------------------------------------------------- 5) strategy gates (H1 / structure)
def series(seed, n=1500, cycle=120):
    rnd = random.Random(seed); p = 4100.0; out = []; d = 0
    for i in range(n):
        if i % cycle == 0: d = rnd.choice([0.25, -0.25, 0.0, 0.35, -0.35])
        o = p; p = p + d + rnd.gauss(0, 0.9)
        out.append({"time": 1_800_000_000 + i * 300, "open": o, "high": max(o, p) + abs(rnd.gauss(0, 0.35)),
                    "low": min(o, p) - abs(rnd.gauss(0, 0.35)), "close": p, "volume": 1})
    return out
cs = series(2)
def an(e, **kw): return st.analyze_symbol(cs[:e], spread=30, now=NOW, session_filter=False, **kw)
trigs = [(e, an(e)) for e in range(60, len(cs))]
trigs = [(e, r) for e, r in trigs if r["signal"] in ("BUY", "SELL")]
assert len(trigs) >= 5
e0, r0 = next((e, r) for e, r in trigs if r["signal"] == "BUY")
e1, r1 = next((e, r) for e, r in trigs if r["signal"] == "SELL")
BULL, BEAR, NEUT, UNK = ({"bias": b, "reason": f"H1 {b}"} for b in ("BULL", "BEAR", "NEUTRAL", "UNKNOWN"))
assert an(e0, htf=BEAR, htf_mode="off")["signal"] == "BUY"                           # off = original v2.6 behaviour
assert an(e0, htf=BULL, htf_mode="strict")["signal"] == "BUY" and an(e1, htf=BEAR, htf_mode="strict")["signal"] == "SELL"
for mode in ("counter", "strict"):
    r = an(e0, htf=BEAR, htf_mode=mode); assert r["signal"] == "HOLD" and r["state"] == "NO_TREND", r
    r = an(e1, htf=BULL, htf_mode=mode); assert r["signal"] == "HOLD" and r["state"] == "NO_TREND", r
assert an(e0, htf=NEUT, htf_mode="counter")["signal"] == "BUY" and an(e0, htf=UNK, htf_mode="counter")["signal"] == "BUY"
r = an(e0, htf=NEUT, htf_mode="strict"); assert r["signal"] == "HOLD" and r["state"] == "NO_TREND"
r = an(e0, htf=UNK, htf_mode="strict");  assert r["signal"] == "HOLD" and r["state"] == "WARMUP" and "H1 context unavailable" in r["reason"], r
assert an(e0, htf=None, htf_mode="strict")["signal"] == "HOLD"                        # no H1 data at all in strict -> fail safe
# M5 structure gate (force the detector's answer to test the gate deterministically)
real_ms = st.market_structure
for forced, side_blocked in (("BEAR", "BUY"), ("BULL", "SELL")):
    st.market_structure = lambda *a, _s=forced, **k: {"state": _s, "last_high": None, "last_low": None}
    e = e0 if side_blocked == "BUY" else e1
    assert an(e, structure_mode="off")["signal"] == side_blocked
    for mode in ("counter", "strict"):
        r = an(e, structure_mode=mode); assert r["signal"] == "HOLD" and r["state"] == "NO_TREND", (forced, mode, r)
st.market_structure = lambda *a, **k: {"state": "RANGE", "last_high": None, "last_low": None}
assert an(e0, structure_mode="counter")["signal"] == "BUY" and an(e0, structure_mode="strict")["signal"] == "HOLD"
st.market_structure = real_ms
# explainable trades
r = an(e0, htf=BULL, htf_mode="strict", structure_mode="off")
assert r["signal"] == "BUY" and "H1 BULL" in r["reasons"] and any("rejection" in x for x in r["reasons"]) and "why:" in r["reason"], r
print("strategy gates OK (H1 + structure + reasons)")

# ----------------------------------------------------------------------------------------------- 6) risk: fixed day-start reference, min-lot rejection
RE.max_daily_loss_pct = 8.0; RE.day_start_balance = 1000.0; RE.max_risk_pct_hard = 20.0
assert RE.can_trade(0.01, "XAUUSD", 920.0, 1.0, 4100.0, pnl_today=-79.0)[0], "limit is 8% of the DAY-START balance (=$80)"
ok, why = RE.can_trade(0.01, "XAUUSD", 920.0, 1.0, 4100.0, pnl_today=-81.0)
assert not ok and "day-start balance $1000.00" in why, why
RE.day_start_balance = None
assert not RE.can_trade(0.01, "XAUUSD", 920.0, 1.0, 4100.0, pnl_today=-75.0)[0], "without a reference it falls back to the current balance"
ok, why = RE.can_trade(0.01, "XAUUSD", 10.0, 2.4, 4100.0)                               # min lot would risk 24% > 20% cap
assert not ok and "Account too small" in why, why
assert RE.can_trade(0.01, "XAUUSD", 20.0, 2.4, 4100.0)[0]                               # 12% -> fine
print("risk reference + min-lot rejection OK")

# ----------------------------------------------------------------------------------------------- 7) engine harness
shim = types.SimpleNamespace(time=lambda: 1_000_000.0); be.time = shim
trig_e, trig_r = trigs[0]
side = trig_r["signal"]
S = {"candles": cs[:trig_e], "positions": [], "history": [], "sent": [], "modified": [], "closed": [],
     "acct": {"balance": 1000.0, "equity": 1000.0, "leverage": 2000},
     "tick": {"symbol": "XAUUSD", "bid": trig_r["price"] - 0.15, "ask": trig_r["price"] + 0.15, "spread": 30.0},
     "h1": h1_series("up"), "h1_calls": 0}
def candles_stub(sym, tf, n):
    if tf == "H1":
        S["h1_calls"] += 1; return S["h1"] + [candle(0, 0, 0, 0, 0)], "BROKER"       # last candle = still forming (dropped by the engine)
    return S["candles"], "BROKER"
be._is_any_connected = lambda: True
be._any_account = lambda: dict(S["acct"])
be._any_positions = lambda sym: [dict(p) for p in S["positions"]]
be._any_tick = lambda sym: S["tick"]
be._any_candles = candles_stub
be._any_history = lambda days=2: S["history"]
def fake_modify(t, sl, tp, sym): S["modified"].append(str(t)); return {"status": "success", "message": "ok"}
def fake_close(t): S["closed"].append(str(t)); return {"status": "success", "message": "closed"}
def fake_send(**kw):
    S["sent"].append(kw)
    S["positions"].append({"ticket": "B9", "symbol": "XAUUSD", "type": kw["action"], "volume": kw["volume"], "price_open": S["tick"]["ask"],
                           "price_current": S["tick"]["ask"], "profit": 0.0, "sl": kw["sl"], "tp": kw["tp"], "time": int(shim.time()),
                           "magic": kw.get("magic")})
    return {"status": "success", "ticket": "B9", "message": "ok"}
be._any_modify, be._any_close, be._any_send_order = fake_modify, fake_close, fake_send
be.bot_config.update(session_filter=False, enabled=True, risk_pct=1.0, max_trades_per_day=50, htf_mode="off", structure_mode="off",
                     be_enabled=True, be_trigger_r=1.0, close_on_opposite=True, max_hold_candles=12, cooldown_candles_after_loss=0)
be.risk_engine.max_trades_per_hour = 50
be._sync_risk()
def fresh():
    S.update(sent=[], modified=[], closed=[], positions=[], h1_calls=0)
    S["tick"].update(bid=trig_r["price"] - 0.15, ask=trig_r["price"] + 0.15)      # price back at the trigger candle's close
    be.bot_stats.update(wins=0, losses=0, breakevens=0, pnl_today=0.0, total_trades=0, consec_losses=0, cooldown_until=0.0,
                        trades_today=0, day_start_balance=None)
    be.bot_stats["today_start"] = datetime.now(timezone.utc).strftime("%Y-%m-%d") if hasattr(be.bot_stats.get("today_start"), "lower") else be.bot_stats.get("today_start")
    return {"last_candle": "seed", "tracked": {}, "be_retry": {}, "risk": {}, "owned": set()}
run = lambda ctx: asyncio.run(be._step(ctx))
opp = "SELL" if side == "BUY" else "BUY"
profitable = lambda typ, e: dict(price_open=e, sl=e - 2.4 if typ == "BUY" else e + 2.4, tp=e + 4.3 if typ == "BUY" else e - 4.3)

# 7a) a MANUAL position (same symbol, opposite direction, ancient, in profit) is never touched and does not block the bot's entry
ctx = fresh()
px = trig_r["price"]
S["positions"] = [{"ticket": "M1", "symbol": "XAUUSD", "type": opp, "volume": 0.05, "profit": 40.0, "price_current": px,
                   "time": int(shim.time()) - 40 * 300, "magic": MANUAL_MAGIC, **profitable(opp, px + (3.0 if opp == "SELL" else -3.0))}]
S["tick"].update(bid=px - 0.15, ask=px + 0.15)
run(ctx)
assert len(S["sent"]) == 1, "a manual trade must not stop the bot from entering"
assert S["sent"][0]["magic"] == BOT_MAGIC and S["sent"][0]["comment"].startswith("KlopApex"), S["sent"][0]
assert "M1" not in S["modified"] and "M1" not in S["closed"], (S["modified"], S["closed"])
assert "M1" not in ctx["tracked"] and "B9" in ctx["owned"]
print("manual position isolated; bot entry tagged with its magic")

# 7b) the bot's OWN position is managed: break-even moves it, the time-stop closes it; the manual one still isn't touched
ctx = fresh(); S["positions"] = []
S["candles"] = cs[:trig_e]; ctx["last_candle"] = "x"; run(ctx)                              # bot opens B9
assert len(S["sent"]) == 1
own = S["positions"][0]; entry = own["price_open"]
risk = abs(entry - own["sl"])
S["positions"].append({"ticket": "M2", "symbol": "XAUUSD", "type": own["type"], "volume": 0.05, "profit": 0.0, "price_current": entry,
                       "time": int(shim.time()) - 40 * 300, "magic": 0, "price_open": entry, "sl": own["sl"], "tp": own["tp"]})
mv = (risk + 0.4) * (1 if own["type"] == "BUY" else -1)
S["tick"].update(bid=entry + mv - 0.15, ask=entry + mv + 0.15)                               # +1.1R floating
S["candles"] = cs[:trig_e]; run(ctx)
assert S["modified"] == ["B9"], S["modified"]                                                # BE applied to ours only
shim.time = lambda: 1_000_000.0 + 14 * 300                                                   # beyond max_hold_candles
S["positions"][0]["time"] = int(1_000_000.0)
run(ctx)
assert S["closed"] == ["B9"], S["closed"]                                                    # time-stop closes ours only (M2 is 40 candles old but foreign)
shim.time = lambda: 1_000_000.0
print("bot position managed (BE / time-stop); foreign positions untouched")

# 7c) a position whose layer reports NO ownership tag is left alone AND blocks new entries (fail safe)
ctx = fresh()
S["positions"] = [{"ticket": "U1", "symbol": "XAUUSD", "type": opp, "volume": 0.01, "profit": 1.0, "price_current": px,
                   "time": int(shim.time()) - 40 * 300, "price_open": px, "sl": 0, "tp": 0}]      # no 'magic' key at all
run(ctx)
assert not S["sent"] and not S["modified"] and not S["closed"], (S["sent"], S["modified"], S["closed"])
print("untagged position: untouched, no entry beside it")

# 7d) fixed day-start reference inside the engine; reset on a new day
ctx = fresh(); S["acct"].update(balance=1000.0); S["candles"] = cs[:trig_e]
run(ctx); assert be.bot_stats["day_start_balance"] == 1000.0 and RE.day_start_balance == 1000.0
S["acct"].update(balance=905.0); ctx["last_candle"] = "x"; run(ctx)
assert be.bot_stats["day_start_balance"] == 1000.0, "must not follow the shrinking balance"
assert be.get_bot_state()["stats"]["day_start_balance"] == 1000.0
be.bot_stats["today_start"] = "1970-01-01"; be._reset_daily_if_needed()
assert be.bot_stats["day_start_balance"] is None and RE.day_start_balance is None
S["acct"].update(balance=1000.0)
print("day-start reference OK")

# 7e) H1 filter inside the engine: fetched once per 2 minutes, drops the forming candle, blocks entries against H1
be.bot_config.update(htf_mode="counter")
for h1dir, expect_entry in (("up" if side == "BUY" else "down", True), ("down" if side == "BUY" else "up", False)):
    S["h1"] = h1_series(h1dir); ctx = fresh(); S["candles"] = cs[:trig_e]; ctx["last_candle"] = "x"
    run(ctx)
    assert (len(S["sent"]) == 1) == expect_entry, (h1dir, side, S["sent"], [l["msg"] for l in list(be.bot_stats["log"])[-4:]])
    if not expect_entry:
        assert "H1" in be.bot_stats["last_reason"], be.bot_stats["last_reason"]
S["h1_calls"] = 0; ctx = fresh(); S["candles"] = cs[:trig_e]
run(ctx); run(ctx); run(ctx); assert S["h1_calls"] == 1, S["h1_calls"]                       # cached
be.bot_config.update(htf_mode="off"); S["h1_calls"] = 0; ctx = fresh(); run(ctx); assert S["h1_calls"] == 0     # off = no H1 requests
print("engine H1 filter OK")

# ----------------------------------------------------------------------------------------------- 8) manual /api/trade gate
be._any_account = lambda: dict(S["acct"]); be._any_tick = lambda sym: {"bid": 4100.0, "ask": 4100.3, "spread": 30}
be.bot_config["risk_cap_pct"] = 20.0; be.bot_stats["pnl_today"] = 0.0; RE.day_start_balance = None
S["acct"].update(balance=1000.0)
assert be.manual_trade_check(0.01, "XAUUSD", "BUY", 4097.0)[0]                                # $3.3 risk on $1000
ok, why = be.manual_trade_check(0.01, "XAUUSD", "BUY", None); assert ok                       # no SL attached -> cap cannot be computed, other gates still run
S["acct"].update(balance=10.0)
ok, why = be.manual_trade_check(0.01, "XAUUSD", "BUY", 4098.0); assert not ok and "Account too small" in why, why   # $2.3 on $10 = 23% > cap
S["acct"].update(balance=1000.0); RE.day_start_balance = 1000.0; be.bot_stats["pnl_today"] = -81.0
ok, why = be.manual_trade_check(0.01, "XAUUSD", "SELL", 4103.0); assert not ok and "Daily loss limit" in why, why  # same daily stop as the bot
be.bot_stats["pnl_today"] = 0.0
ok, why = be.manual_trade_check(0.5, "XAUUSD", "BUY", 4097.0); assert not ok and "Lot" in why, why
be._any_account = lambda: None
ok, why = be.manual_trade_check(0.01, "XAUUSD", "BUY", 4097.0); assert not ok and "unavailable" in why, why            # fails closed
print("manual trade gate OK")

# ----------------------------------------------------------------------------------------------- 9) config hygiene
be.update_config({"htf_mode": "bogus", "structure_mode": "STRICT"})
assert be.bot_config["htf_mode"] in ("off", "counter", "strict") and be.bot_config["structure_mode"] != "STRICT"
be.update_config({"htf_mode": "strict", "structure_mode": "off"}); assert (be.bot_config["htf_mode"], be.bot_config["structure_mode"]) == ("strict", "off")
be.update_config({"htf_mode": "counter", "structure_mode": "counter"})
print("ALL v2.7 TESTS PASSED")

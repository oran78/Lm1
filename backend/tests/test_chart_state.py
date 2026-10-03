"""Engine -> chart contract: planned_setup / active_trade / markers / auto break-even, with the broker layer faked."""
import sys, os, asyncio, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot_engine as be
from strategy import analyze_symbol

def series(seed, n=1500, cycle=120):          # seeded random walk, only used to drive the rules
    rnd = random.Random(seed); p = 4100.0; out = []; d = 0
    for i in range(n):
        if i % cycle == 0: d = rnd.choice([0.25, -0.25, 0.0, 0.35, -0.35])
        o = p; p = p + d + rnd.gauss(0, 0.9)
        out.append({"time": 1_800_000_000 + i * 300, "open": o, "high": max(o, p) + abs(rnd.gauss(0, 0.35)),
                    "low": min(o, p) - abs(rnd.gauss(0, 0.35)), "close": p, "volume": 1})
    return out

cs = series(2)
def first(pred):
    for end in range(60, len(cs)):
        r = analyze_symbol(cs[:end], spread=30, session_filter=False)
        if pred(r): return end, r
planned_end, planned = first(lambda r: r["state"] == "PLANNED_SETUP")
trig_end, trig = first(lambda r: r["signal"] == "BUY")

S = {"candles": cs[:planned_end], "positions": [], "tick": {"symbol": "XAUUSD", "bid": 4100.0, "ask": 4100.3, "spread": 30.0},
     "modify": [], "sent": []}
be._is_any_connected = lambda: True
be._any_account = lambda: {"balance": 1000.0, "equity": 1000.0, "leverage": 2000}
be._any_positions = lambda sym: list(S["positions"])
be._any_tick = lambda sym: S["tick"]
be._any_candles = lambda sym, tf, n: (S["candles"], "BROKER")
def fake_modify(t, sl, tp, sym):
    S["modify"].append((t, sl, tp)); 
    for p in S["positions"]:
        if p["ticket"] == t: p["sl"] = sl
    return {"status": "success", "message": "ok"}
be._any_modify = fake_modify
def fake_send(**kw):
    S["sent"].append(kw)
    S["positions"].append({"ticket": "501", "symbol": "XAUUSD", "type": kw["action"], "volume": kw["volume"],
                           "price_open": S["tick"]["ask"], "price_current": S["tick"]["ask"], "profit": 0.0, "sl": kw["sl"], "tp": kw["tp"], "time": 1_800_000_000 + trig_end * 300})
    return {"status": "success", "ticket": "501", "message": "ok"}
be._any_send_order = fake_send
be.bot_config.update(session_filter=False, enabled=True, risk_pct=1.0)
ctx = {"last_candle": None, "tracked": {}, "be_retry": {}}
run = lambda: asyncio.run(be._step(ctx))

# 1) PLANNED_SETUP is published with the EMA9 target price and the side
run()
ps = be.get_bot_state()["planned_setup"]
assert ps and ps["side"] == planned["planned_side"] and ps["entry_price"] == planned["planned_entry_price"], ps
print("planned_setup emitted:", ps["side"], "@", ps["entry_price"])

# 2) the trigger candle opens ONE trade with SL+TP, clears the planned line, adds a marker
S["candles"] = cs[:trig_end]
S["tick"] = {"symbol": "XAUUSD", "bid": trig["price"] - 0.15, "ask": trig["price"] + 0.15, "spread": 30.0}
run()
assert len(S["sent"]) == 1, S["sent"]
o = S["sent"][0]; o_entry = S["tick"]["ask"]; assert o["action"] == "BUY" and o["sl"] < S["tick"]["ask"] < o["tp"], o
assert be.get_bot_state()["planned_setup"] is None
run()                                                       # next pass: position synced -> active_trade + marker
at = be.get_bot_state()["active_trade"]
assert at and at["side"] == "BUY" and at["sl"] == o["sl"] and at["tp"] == o["tp"] and not at["be_active"], at
mk = be.get_bot_state()["stats"]["markers"]; assert len(mk) == 1 and mk[0]["type"] == "BUY" and mk[0]["price"] == o_entry, mk
print("trade opened, active_trade + marker OK:", at["entry"], at["sl"], at["tp"])

# 3) +1R -> SL moves to entry + spread exactly once; TP untouched
risk = o_entry - o["sl"]
S["tick"] = {"symbol": "XAUUSD", "bid": o_entry + risk + 0.05, "ask": o_entry + risk + 0.35, "spread": 30.0}
run()
assert len(S["modify"]) == 1 and S["modify"][0] == ("501", round(o_entry + 0.30, 2), o["tp"]), S["modify"]
at = be.get_bot_state()["active_trade"]; assert at["be_active"] and at["sl"] == round(o_entry + 0.30, 2), at
run(); run(); assert len(S["modify"]) == 1, "break-even repeated"
print("auto break-even OK ->", S["modify"][0])

# 4) position gone (SL/TP hit on the broker) -> active_trade cleared, P/L recorded
S["positions"].clear(); run()
assert be.get_bot_state()["active_trade"] is None and be.bot_stats["wins"] + be.bot_stats["losses"] == 1
print("CHART STATE TEST PASSED")

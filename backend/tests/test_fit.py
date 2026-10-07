"""Small-account sizing: the old 'tighter stop' retry kept the swing, so the stop never shrank and valid signals died on 'Account too small'.
These tests lock in the fix (fit_plan_to_account) and the one-decision-per-candle entry logic."""
import sys, os, asyncio, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot_engine as be

def cfg(**kw):
    be.bot_config.update(dict(sl_atr_mult=1.2, tp_atr_mult=1.8, risk_pct=1.0, auto_lot=True, fixed_lot=0.01,
                              risk_cap_pct=25.0, tight_stop_fallback=True, min_sl_atr_mult=0.5, max_daily_loss_pct=30.0,
                              daily_loss_limit_enabled=True))
    be.bot_config.update(kw); be._sync_risk(); be.risk_engine.day_start_balance = None; be.risk_engine._trades.clear()

ENTRY, ATR = 4000.0, 3.0
SWING_LOW = ENTRY - 4.0          # pullback swing 4$ below entry -> swing stop ~4.30$

# 1) $10 account: swing stop = 43% risk -> blocked before; now fitted with a tighter stop
cfg()
f = be.fit_plan_to_account("BUY", ENTRY, ATR, SWING_LOW, None, 10.0, 2000, 0.2, "XAUUSD", 0.0)
assert f["ok"] and f["note"], f
assert f["plan"]["risk"] < 4.30 and f["plan"]["risk"] >= 0.5 * ATR - 1e-9, f["plan"]
assert f["risk_money"] / 10.0 * 100 <= 25.0 + 1e-9, f
assert f["plan"]["rr"] >= 1.5 - 1e-9, f["plan"]
print("1) $10 account fits:", f["note"])

# 2) fallback OFF -> clear block reason, no tight stop
cfg(tight_stop_fallback=False)
f = be.fit_plan_to_account("BUY", ENTRY, ATR, SWING_LOW, None, 10.0, 2000, 0.2, "XAUUSD", 0.0)
assert not f["ok"] and "Account too small" in f["why"], f
print("2) fallback off -> blocked:", f["why"][:70])

# 3) bigger account: normal swing stop, no fallback used
cfg()
f = be.fit_plan_to_account("SELL", ENTRY, ATR, None, ENTRY + 4.0, 1000.0, 2000, 0.2, "XAUUSD", 0.0)
assert f["ok"] and f["note"] is None and f["plan"]["risk"] >= 4.0, f
print("3) $1000 account keeps the swing stop (lot %.2f)" % f["lot"])

# 4) impossible even at the tightest stop (balance $2) -> blocked with an actionable message
cfg()
f = be.fit_plan_to_account("BUY", ENTRY, ATR, SWING_LOW, None, 2.0, 2000, 0.2, "XAUUSD", 0.0)
assert not f["ok"] and "Raise 'Max risk cap'" in f["why"], f
print("4) $2 account blocked with advice")

# 5) wide spread raises the stop floor (3 x spread)
cfg(min_sl_atr_mult=0.2)
f = be.fit_plan_to_account("BUY", ENTRY, ATR, SWING_LOW, None, 10.0, 2000, 0.5, "XAUUSD", 0.0)
assert (not f["ok"]) or f["plan"]["risk"] >= 3 * 0.5 - 1e-9, f
print("5) spread floor respected")

# 6) daily-loss default no longer ends the day after ONE loss on a micro account
cfg(); assert be.bot_config["max_daily_loss_pct"] > be.bot_config["risk_cap_pct"]
ok, why = be.risk_engine.can_trade(0.01, "XAUUSD", balance=10.0, sl_dist=1.5, price=ENTRY, leverage=2000, pnl_today=-1.5)
assert ok, why
print("6) one 15% loss does not trip the daily limit")

print("FIT TESTS PASSED")

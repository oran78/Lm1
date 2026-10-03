import sys, random, math
import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
from strategy import analyze_symbol, _rsi, _atr, _adx, _ema_series
from risk_engine import risk_engine

def mk(prices, t0=1_800_000_000, step=300, noise=0.6, seed=1):
    rnd=random.Random(seed); out=[]
    for i,p in enumerate(prices):
        o=prices[i-1] if i else p
        h=max(o,p)+rnd.uniform(0,noise); l=min(o,p)-rnd.uniform(0,noise)
        out.append({"time":t0+i*step,"open":o,"high":h,"low":l,"close":p,"volume":100})
    return out

NOW=datetime(2026,10,6,14,0,tzinfo=timezone.utc)  # Tuesday 14:00 UTC (in session)

# --- indicator sanity
flat=[100.0]*60; c=mk(flat,noise=0.0)
assert abs(_rsi([c_["close"] for c_ in c])-50)<1e-6, "flat RSI should be 50"
up=mk([100+i for i in range(80)],noise=0.2)
adx,pdi,mdi=_adx(up); print("uptrend ADX/+DI/-DI",round(adx,1),round(pdi,1),round(mdi,1)); assert adx>40 and pdi>mdi
rng=mk([100+math.sin(i/1.5)*0.8 for i in range(120)],noise=0.2)
adx_r,_,_=_adx(rng); print("range ADX",round(adx_r,1)); assert adx_r<adx
print("ATR trend",round(_atr(up),2))

# --- deterministic regime-switching series (seeded random walk, NOT market data: only used to exercise the rules)
import random as _r
def series(seed, n=1500, cycle=120):
    rnd=_r.Random(seed); p=4100.0; out=[]; d=0
    for i in range(n):
        if i%cycle==0: d=rnd.choice([0.25,-0.25,0.0,0.35,-0.35])
        o=p; p=p+d+rnd.gauss(0,0.9)
        out.append({"time":1_800_000_000+i*300,"open":o,"high":max(o,p)+abs(rnd.gauss(0,0.35)),"low":min(o,p)-abs(rnd.gauss(0,0.35)),"close":p,"volume":1})
    return out
cs=series(2)
states={}; trig=[]
for end in range(60,len(cs)):
    r=analyze_symbol(cs[:end],spread=30,now=NOW,session_filter=False)
    states.setdefault(r["state"],[]).append(end)
    if r["signal"] in ("BUY","SELL"): trig.append((end,r))
print({k:len(v) for k,v in states.items()})
for need in ("CHOP","WATCH","PLANNED_SETUP","TRIGGERED","INVALIDATED"): assert need in states, f"state {need} never produced"

# every trigger obeys the written rules
from strategy import RSI_BAND, CHOP_ATR_FRAC
for end,r in trig:
    assert r["state"]=="TRIGGERED" and r["setup"]=="EMA_PULLBACK"
    assert r["ema_gap"]>=CHOP_ATR_FRAC*r["atr"]-1e-6, "traded inside CHOP"
    assert RSI_BAND[0]<=r["pullback_rsi"]<=RSI_BAND[1], "RSI not cooled"
    if r["signal"]=="BUY": assert r["ema9"]>r["ema21"] and r["ema_slope"]>0 and r["bias"]=="BUY"
    else: assert r["ema9"]<r["ema21"] and r["ema_slope"]<0 and r["bias"]=="SELL"
# PLANNED_SETUP carries EMA9 as the target entry and a side matching the bias
for end in states["PLANNED_SETUP"][:50]:
    r=analyze_symbol(cs[:end],spread=30,now=NOW,session_filter=False)
    assert r["planned_entry_price"]==r["ema9"] and r["planned_side"]==r["bias"] and r["signal"]=="HOLD"
print("trend / chop / planned / trigger rules OK")

# no repaint: the forming (last) candle must not change a decision on closed candles
end,r0=trig[0]
a=analyze_symbol(cs[:end]+[dict(cs[end],close=cs[end]["close"]+9)],spread=30,now=NOW,session_filter=False)
b=analyze_symbol(cs[:end]+[dict(cs[end],close=cs[end]["close"]-9)],spread=30,now=NOW,session_filter=False)
assert a["signal"]==b["signal"]==r0["signal"] and a["candle_time"]==b["candle_time"]; print("no-repaint OK")

# session filter
off=datetime(2026,10,6,2,0,tzinfo=timezone.utc); assert analyze_symbol(cs[:end],now=off)["signal"]=="HOLD"
assert analyze_symbol(cs[:end],now=datetime(2026,10,3,14,0,tzinfo=timezone.utc))["state"]=="PAUSED"  # Saturday
print("session filter OK")

# spread gates: > 35 points and > 0.5*ATR both block a trigger (planned state is unaffected)
v=analyze_symbol(cs[:end],spread=36,now=NOW,session_filter=False); assert v["signal"]=="HOLD" and v["state"]=="BLOCKED", v["reason"]
ok_=analyze_symbol(cs[:end],spread=35,now=NOW,session_filter=False); assert ok_["signal"]==r0["signal"]
atr_cap=r0["atr"]*0.5*100                                              # 0.5*ATR expressed in points
v2=analyze_symbol(cs[:end],spread=atr_cap+1,max_spread_points=10_000,now=NOW,session_filter=False); assert v2["state"]=="BLOCKED" and "ATR" in v2["reason"]
print("spread veto OK")

# chop: flat market never trades
flat=mk([4100+((-1)**i)*0.05 for i in range(120)],noise=0.05)
assert analyze_symbol(flat,now=NOW,session_filter=False)["state"] in ("CHOP","NO_TREND","WATCH") and analyze_symbol(flat,now=NOW,session_filter=False)["signal"]=="HOLD"

# --- trade plan: SL 1.2*ATR, TP 1.8*ATR, R:R 1.5, stop must sit beyond the swing
from strategy import plan_trade, break_even_sl
pl,_=plan_trade("BUY",4100.0,2.0,swing_low=4098.0); assert pl["sl"]==4097.6 and pl["tp"]==4103.6 and pl["rr"]==1.5, pl
pl,_=plan_trade("SELL",4100.0,2.0,swing_high=4102.0); assert pl["sl"]==4102.4 and pl["tp"]==4096.4, pl
pl,_=plan_trade("BUY",4100.0,2.0,swing_low=4097.0)          # swing 3.0 away -> stop pushed beyond it, TP keeps 1.5R
assert pl["sl"]==4096.8 and pl["sl"]<4097.0 and pl["rr"]>=1.5 and pl["tp"]>=4103.6, pl
assert plan_trade("BUY",4100.0,2.0,swing_low=4095.0)[0] is None       # needs 5.2 > 2 ATR -> too deep
assert plan_trade("BUY",4100.0,2.0,sl_mult=1.6,tp_mult=1.8)[0] is None  # R:R 1.125 < 1.5
n_ok=0
for end,r in trig[:40]:
    p,_=plan_trade(r["signal"],r["price"],r["atr"],r["swing_low"],r["swing_high"])
    if p:
        n_ok+=1; assert p["rr"]>=1.5-1e-6 and p["risk"]<=2.0*r["atr"]+1e-9
        if r["signal"]=="BUY": assert p["sl"]<r["swing_low"]<r["price"]<p["tp"]
        else: assert p["sl"]>r["swing_high"]>r["price"]>p["tp"]
assert n_ok>=len(trig[:40])*0.6, "trade-plan filter rejects too many triggers"
print("trade plan OK")

# --- break-even: +1R -> SL = entry +/- spread, exactly once
assert break_even_sl("BUY",4100.0,4097.6,4102.3,4102.6)is None            # +2.3 < 1R (2.4)
assert break_even_sl("BUY",4100.0,4097.6,4102.4,4102.7)==4100.3           # +1R reached
assert break_even_sl("BUY",4100.0,4100.3,4104.0,4104.3)is None            # already moved
assert break_even_sl("SELL",4100.0,4102.4,4097.4,4097.6)==4099.8          # entry - spread
assert break_even_sl("SELL",4100.0,4102.4,4098.0,4098.2)is None
assert break_even_sl("BUY",4100.0,0,4110,4110.3)is None                   # no SL -> nothing to move
print("break-even OK")

# --- risk maths
assert risk_engine.calc_lot(10,3,2.4)==(0.01,2.4)
ok,why=risk_engine.can_trade(0.01,"XAUUSD",10,2.4,4100); assert not ok; print("$10 acct:",why)
lot,rm=risk_engine.calc_lot(1000,1,3.0); print("$1000 @1%, SL $3 ->",lot,"lot risk $",rm); assert lot==0.03 and rm<=10
ok,why=risk_engine.can_trade(0.03,"XAUUSD",1000,3.0,4100,pnl_today=-85); assert not ok and "Daily" in why; print("daily limit OK")
print("ALL STRATEGY/RISK TESTS PASSED")

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

# --- signals: down then sharp up -> must produce BUY at the cross candle, never repaint
prices=[200-i*0.5 for i in range(60)]+[170+i*1.2 for i in range(40)]
cs=mk(prices,noise=0.3)
fired=[]
for end in range(45,len(cs)+1):
    r=analyze_symbol(cs[:end],now=NOW)          # last candle = forming, dropped
    if r["signal"] in("BUY","SELL"): fired.append((end,r["signal"],r["setup"],r["candle_time"]))
print("signals:",fired[:6]); assert any(f[1]=="BUY" for f in fired), "no BUY on reversal"
# same closed candle -> identical signal regardless of the forming candle's value (no repaint)
a=analyze_symbol(cs[:70]+[dict(cs[70],close=cs[70]["close"]+5)],now=NOW)
b=analyze_symbol(cs[:70]+[dict(cs[70],close=cs[70]["close"]-5)],now=NOW)
assert a["signal"]==b["signal"] and a["candle_time"]==b["candle_time"]; print("no-repaint OK")
# session filter
off=datetime(2026,10,6,2,0,tzinfo=timezone.utc); assert analyze_symbol(cs[:70],now=off)["signal"]=="HOLD"
assert analyze_symbol(cs[:70],now=datetime(2026,10,3,14,0,tzinfo=timezone.utc))["signal"]=="HOLD"  # Saturday
print("session filter OK")
# spread veto
big=analyze_symbol(cs[:70],spread=500,now=NOW); assert big["signal"]=="HOLD" and "Spread" in big["reason"]; print("spread veto OK")

# --- risk maths
assert risk_engine.calc_lot(10,3,2.4)==(0.01,2.4)
ok,why=risk_engine.can_trade(0.01,"XAUUSD",10,2.4,4100); assert not ok; print("$10 acct:",why)
lot,rm=risk_engine.calc_lot(1000,1,3.0); print("$1000 @1%, SL $3 ->",lot,"lot risk $",rm); assert lot==0.03 and rm<=10
ok,why=risk_engine.can_trade(0.03,"XAUUSD",1000,3.0,4100,pnl_today=-85); assert not ok and "Daily" in why; print("daily limit OK")
print("ALL STRATEGY/RISK TESTS PASSED")

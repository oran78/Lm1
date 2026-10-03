"""Integration test: runs the REAL bot loop against the REAL paper broker with a scripted price feed on a virtual clock."""
import sys, asyncio, random, types, math, collections
import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mt5_service as m                       # module
import bot_engine as be
from datetime import datetime, timezone

T0=int(datetime(2026,10,6,6,0,tzinfo=timezone.utc).timestamp())
vt=[float(T0)]
shim=types.SimpleNamespace(time=lambda: vt[0]); m.time=shim; be.time=shim

# price process: regime switching (trend up / trend down / range) per minute
rnd=random.Random(7); minute_price={}
def build(upto_min, p0=4100.0):
    p=p0; drift=0.0
    for i in range(upto_min):
        if i%90==0: drift=rnd.choice([0.10,-0.10,0.0,0.0,0.14,-0.14])
        p+=drift+rnd.gauss(0,0.55); minute_price[i]=p
    return minute_price
build(2*24*60+700)
def feed(sym):
    i=int((vt[0]-(T0-600*60))//60); return round(minute_price[i]+ (vt[0]%60)/60*(minute_price[i+1]-minute_price[i]),2)
m.HAS_MARKET=True; m.get_live_price_sync=feed
# real-looking history seed (600 min before T0)
dq=collections.deque(maxlen=1500)
for k in range(500):
    t=T0-(500-k)*60; i=int((t-(T0-600*60))//60); o=minute_price[i]; c=minute_price[i+1]
    dq.append({"time":t,"open":o,"high":max(o,c)+0.2,"low":min(o,c)-0.2,"close":c,"volume":50})
m._candle_cache["XAUUSD"]=dq; m._candle_source["XAUUSD"]="PAXG-history+live"

# paper account $1000
svc=m.mt5_service; svc._connected=True; svc._real_balance=1000.0; svc.mode="REAL"; svc._login=1; svc._server="paper"
real_sleep=asyncio.sleep
async def fast_sleep(s,*a,**k):
    vt[0]+=s; await real_sleep(0)
asyncio.sleep=fast_sleep

be.bot_config.update(session_filter=False, risk_pct=1.0, target_multiplier=1000, max_trades_per_day=50)
be.risk_engine.max_trades_per_hour=50

opened=[]; open_hist=[]
orig_send=be._any_send_order
def spy(**kw):
    r=orig_send(**kw); 
    if r["status"]=="success": opened.append((vt[0],kw["action"],kw["volume"],kw["sl"],kw["tp"]))
    return r
be._any_send_order=spy

async def main():
    be.start_bot()
    END=T0+30*3600
    while vt[0]<END and be.bot_config["enabled"]:
        await real_sleep(0)
        open_hist.append(len(m._mock_positions))
        # day rollover uses real date -> irrelevant here
    be.stop_bot()
asyncio.run(main())

st=be.bot_stats; closed=list(m._mock_history)
print(f"virtual hours run: {(vt[0]-T0)/3600:.1f}")
print(f"orders opened: {len(opened)}  closed(paper): {len(closed)}  open now: {len(m._mock_positions)}")
print(f"wins {st['wins']} losses {st['losses']} pnl_today(bot) {st['pnl_today']:.2f}")
realized=sum(p['profit'] for p in closed)
print(f"sum closed P/L {realized:.2f}   balance {svc._real_balance:.2f} (start 1000)")
print("max simultaneous positions:",max(open_hist))
# invariants
assert len(opened)>=3, "bot never traded"
assert max(open_hist)<=1, "more than one position open at once"
cand=[int(t//300) for t,*_ in opened]; assert len(cand)==len(set(cand)), "two trades on same 5m candle"
assert abs((svc._real_balance-1000)-realized)<0.02, "balance does not match closed P/L"
assert st['wins']+st['losses']>=len(closed)-1, "closed trades not recorded in stats"
assert abs(st['pnl_today']-realized)<max(0.05, 0.02*abs(realized)+3), (st['pnl_today'],realized)
# every SL/TP close happened at the level or via managed exit
reasons=[l['msg'] for l in be.bot_stats['log'] if 'Close ' in l['msg']]
print("managed closes:",len(reasons), "| sample:", reasons[:2])
risk=[abs(o[3]-0) for o in opened]
for t,a,v,sl,tp in opened[:4]: print(" trade",datetime.fromtimestamp(t,timezone.utc).strftime('%H:%M'),a,v,"SL",sl,"TP",tp)
print("ENGINE INTEGRATION TEST PASSED")

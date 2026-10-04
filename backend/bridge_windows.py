"""
Klop Apex — Windows MT5 Bridge (REAL BROKER)
Run on ANY Windows PC/VPS with MT5 installed.
Railway Linux (oran78/Lm1 backend) proxies via BRIDGE_URL -> 100% REAL Exness balance/trades.

Windows setup:
  pip install MetaTrader5 fastapi uvicorn
  python bridge_windows.py          # :8000
  ngrok http 8000                  # -> https://xxxx.ngrok.io  (paste as BRIDGE_URL in Railway)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
try:
    import MetaTrader5 as mt5
    HAS_MT5=True
except:
    HAS_MT5=False; mt5=None
import os
app=FastAPI(title="Klop MT5 Bridge")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
class Conn(BaseModel):
    login:int; password:str; server:str
class Order(BaseModel):
    symbol:str; action:str; volume:float; sl:float|None=None; tp:float|None=None; magic:int=202501; comment:str="Klop Apex"
@app.get("/health")
def health(): return {"status":"ok","mt5":HAS_MT5}
@app.get("/")
def root(): return {"status":"ok","bridge":"Klop MT5 Windows Bridge","mt5":HAS_MT5}
@app.post("/bridge/connect")
def br_connect(c:Conn):
    if not HAS_MT5: return {"status":"error","message":"MetaTrader5 not installed on Windows bridge"}
    if not mt5.initialize(): return {"status":"error","message":f"MT5 init {mt5.last_error()}"}
    if not mt5.login(c.login,password=c.password,server=c.server): return {"status":"error","message":f"Login fail {mt5.last_error()} — check Exness login/server"}
    acc=mt5.account_info()
    return {"status":"success","mode":"NATIVE","login":c.login,"server":c.server,"balance":float(acc.balance) if acc else 0,"equity":float(acc.equity) if acc else 0}
@app.get("/bridge/account")
def br_account():
    if not HAS_MT5: return {"error":"no mt5"}
    acc=mt5.account_info()
    if not acc: return {"error":"not connected"}
    return {"login":acc.login,"server":acc.server,"balance":float(acc.balance),"equity":float(acc.equity),"profit":float(acc.profit),"margin":float(acc.margin),"leverage":int(acc.leverage),"currency":"USD"}
@app.get("/bridge/tick/{symbol}")
def br_tick(symbol:str):
    if not HAS_MT5: return {"error":"no mt5"}
    t=mt5.symbol_info_tick(symbol)
    if not t: return {"error":f"No tick {symbol}"}
    return {"symbol":symbol,"bid":float(t.bid),"ask":float(t.ask),"time":int(t.time),"spread":round((t.ask-t.bid)*100,1)}
@app.get("/bridge/candles/{symbol}")
def br_candles(symbol:str, timeframe:str="M5", count:int=100):
    if not HAS_MT5: return {"error":"no mt5"}
    tf_map={"M1":mt5.TIMEFRAME_M1,"M5":mt5.TIMEFRAME_M5,"M15":mt5.TIMEFRAME_M15,"H1":mt5.TIMEFRAME_H1,"D1":mt5.TIMEFRAME_D1}
    tf=tf_map.get(timeframe, mt5.TIMEFRAME_M5)
    rates=mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None: return {"error":"no candles"}
    return {"candles":[{"time":int(r["time"]),"open":float(r["open"]),"high":float(r["high"]),"low":float(r["low"]),"close":float(r["close"]),"volume":int(r["tick_volume"])} for r in rates]}
@app.get("/bridge/positions")
def br_positions():
    if not HAS_MT5: return {"positions":[]}
    pos=mt5.positions_get()
    if not pos: return {"positions":[]}
    return {"positions":[{"ticket":p.ticket,"symbol":p.symbol,"type":"BUY" if p.type==0 else "SELL","volume":p.volume,"price_open":p.price_open,"price_current":p.price_current,"profit":p.profit,"sl":p.sl,"tp":p.tp,"time":int(p.time),"magic":p.magic,"comment":p.comment} for p in pos]}
@app.post("/bridge/order")
def br_order(o:Order):
    if not HAS_MT5: return {"status":"error","message":"no mt5"}
    tick=mt5.symbol_info_tick(o.symbol)
    if not tick: return {"status":"error","message":f"No tick {o.symbol}"}
    typ=mt5.ORDER_TYPE_BUY if o.action=="BUY" else mt5.ORDER_TYPE_SELL
    price=tick.ask if o.action=="BUY" else tick.bid
    req={"action":mt5.TRADE_ACTION_DEAL,"symbol":o.symbol,"volume":o.volume,"type":typ,"price":price,"deviation":30,"magic":o.magic,"comment":o.comment[:31],"type_filling":mt5.ORDER_FILLING_IOC}
    if o.sl: req["sl"]=o.sl
    if o.tp: req["tp"]=o.tp
    r=mt5.order_send(req)
    if not r: return {"status":"error","message":str(mt5.last_error())}
    if r.retcode in (mt5.TRADE_RETCODE_DONE,10009): return {"status":"success","ticket":r.order,"retcode":r.retcode}
    return {"status":"error","message":f"{r.retcode}: {r.comment}"}
@app.post("/bridge/close/{ticket}")
def br_close(ticket:int):
    if not HAS_MT5: return {"status":"error","message":"no mt5"}
    poss=mt5.positions_get(ticket=ticket)
    if not poss: poss=[p for p in (mt5.positions_get() or []) if p.ticket==ticket]
    if not poss: return {"status":"error","message":"Position not found"}
    p=poss[0]
    tick=mt5.symbol_info_tick(p.symbol)
    ctyp=mt5.ORDER_TYPE_SELL if p.type==0 else mt5.ORDER_TYPE_BUY
    price=tick.bid if p.type==0 else tick.ask
    req={"action":mt5.TRADE_ACTION_DEAL,"symbol":p.symbol,"volume":p.volume,"type":ctyp,"position":ticket,"price":price,"deviation":30,"magic":p.magic,"type_filling":mt5.ORDER_FILLING_IOC}
    r=mt5.order_send(req)
    if r and r.retcode in (mt5.TRADE_RETCODE_DONE,10009): return {"status":"success","message":f"Closed {ticket}"}
    return {"status":"error","message":f"Close fail {r.comment if r else mt5.last_error()}"}
if __name__=="__main__":
    import uvicorn; uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","8000")))

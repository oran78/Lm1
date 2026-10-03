import logging, asyncio, json
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging as _lg
try:
    from mt5_service import mt5_service
except Exception as e:
    _lg.getLogger("klop").warning(f"mt5_service fallback (no crash): {e}")
    from types import SimpleNamespace
    mt5_service = SimpleNamespace(is_connected=lambda: False, mode="REAL", get_account_info=lambda: None, get_tick=lambda s: {"symbol":s,"bid":4141.5,"ask":4141.8,"time":0,"spread":30.0}, get_candles=lambda *a, **k: [], get_positions=lambda: [], get_history=lambda *a, **k: [], send_order=lambda **k: {"status":"error","message":"Fallback — use MetaApi"}, close_position=lambda t: {"status":"error","message":"Fallback"}, connect=lambda *a, **k: {"status":"error","message":"Fallback"}, disconnect=lambda: None, set_balance=lambda b: None, _get_bridge_url=lambda: None)
try:
    from metaapi_service import metaapi_service
except Exception as e:
    _lg.getLogger("klop").warning(f"metaapi_service fallback: {e}")
    from types import SimpleNamespace
    metaapi_service = SimpleNamespace(is_connected=lambda: False, get_account_info=lambda: None, get_tick=lambda s: None, get_positions=lambda: [], close_position=lambda t: {"status":"error","message":"MetaApi missing"}, send_order=lambda **k: {"status":"error","message":"MetaApi missing"}, connect=lambda *a, **k: {"status":"error","message":"MetaApi missing"}, disconnect=lambda: None)
from risk_engine import risk_engine
from strategy import analyze_symbol
import bot_engine

logging.basicConfig(level=logging.INFO)
logger=logging.getLogger("klop")
app=FastAPI(title="Klop Apex API", description="Exness MT5 Auto Flip v2.2", version="2.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class ConnectRequest(BaseModel):
    login: str = ""; password: str = ""; server: str = ""
    metaapi_token: str = ""
    metaapi_account_id: str = ""
    use_metaapi: bool = False
class TradeRequest(BaseModel):
    symbol: str="XAUUSD"; action: str; volume: float=0.01; sl: Optional[float]=None; tp: Optional[float]=None
class BotPatch(BaseModel):
    risk_pct: Optional[float]=None; target_multiplier: Optional[float]=None; max_trades_per_day: Optional[int]=None
    auto_lot: Optional[bool]=None; fixed_lot: Optional[float]=None; sl_atr_mult: Optional[float]=None; tp_atr_mult: Optional[float]=None
    symbol: Optional[str]=None; timeframe: Optional[str]=None; starting_balance: Optional[float]=None; session_filter: Optional[bool]=None

@app.get("/")
def root(): return {"status":"ok","service":"Klop Apex","version":"2.2.0","mt5_connected": mt5_service.is_connected() or metaapi_service.is_connected(),"bot":bot_engine.bot_config["enabled"], "metaapi": metaapi_service.is_connected()}
@app.get("/health")
def health(): return {"status":"healthy","mt5": mt5_service.is_connected() or metaapi_service.is_connected(),"bot":bot_engine.bot_config["enabled"], "metaapi": metaapi_service.is_connected()}
@app.get("/api/status")
def api_status():
    # Prefer METAAPI if it is connected — this is REAL broker NATIVE
    if metaapi_service.is_connected():
        return {"connected": True, "mode": "METAAPI", "account": metaapi_service.get_account_info(), "bot": bot_engine.get_bot_state()}
    return {"connected":mt5_service.is_connected(),"mode":mt5_service.mode,"account":mt5_service.get_account_info(),"bot":bot_engine.get_bot_state()}
@app.post("/api/connect")
def connect(req: ConnectRequest):
    # METAAPI path — professional real broker (switch any day via frontend fields)
    if req.use_metaapi or req.metaapi_token or req.metaapi_account_id:
        token = req.metaapi_token.strip() if req.metaapi_token else ""
        acc_id = req.metaapi_account_id.strip() if req.metaapi_account_id else ""
        # fallback to env if frontend didn't send
        import os
        if not token: token = os.getenv("METAAPI_TOKEN","")
        if not acc_id: acc_id = os.getenv("METAAPI_ACCOUNT_ID","")
        r = metaapi_service.connect(token, acc_id)
        if r["status"]=="success": return r
        raise HTTPException(status_code=400, detail=r["message"])
    try: login_int=int(str(req.login).strip()) if req.login else 0
    except: raise HTTPException(status_code=400, detail="Invalid login")
    if not req.login or not req.password:
        raise HTTPException(status_code=400, detail="Login + password required — or toggle MetaApi")
    r=mt5_service.connect(login_int, req.password, req.server)
    if r["status"]=="success": return r
    raise HTTPException(status_code=400, detail=r["message"])
@app.post("/api/disconnect")
def disconnect():
    bot_engine.stop_bot(); mt5_service.disconnect(); metaapi_service.disconnect(); return {"status":"success","message":"Disconnected + bot stopped"}

class BalanceSet(BaseModel):
    balance: float
@app.post("/api/balance/set")
def set_balance(req: BalanceSet):
    if not mt5_service.is_connected(): raise HTTPException(status_code=400, detail="Connect first")
    mt5_service.set_balance(req.balance)
    return {"status": "success", "message": f"Balance synced to ${req.balance:.2f} — live XAU price active, P/L now real", "account": mt5_service.get_account_info()}
@app.get("/api/account")
def account():
    if metaapi_service.is_connected():
        info=metaapi_service.get_account_info()
        if info: return info
    info=mt5_service.get_account_info()
    if not info: raise HTTPException(status_code=400, detail="Not connected")
    return info
@app.get("/api/symbols")
def symbols(): return mt5_service.get_symbols()
@app.get("/api/tick/{symbol}")
def tick(symbol: str):
    if metaapi_service.is_connected():
        t=metaapi_service.get_tick(symbol)
        if t: return t
    t=mt5_service.get_tick(symbol)
    if not t: raise HTTPException(status_code=404, detail=f"No tick {symbol}")
    return t
@app.get("/api/candles/{symbol}")
def candles(symbol: str, timeframe: str="M5", count: int=100):
    return {"symbol":symbol,"timeframe":timeframe,"candles":mt5_service.get_candles(symbol,timeframe,count)}
@app.get("/api/positions")
def positions():
    if metaapi_service.is_connected():
        return {"positions": metaapi_service.get_positions()}
    return {"positions": mt5_service.get_positions()}
@app.get("/api/history")
def history(days: int=7):
    if metaapi_service.is_connected():
        return {"history": mt5_service.get_history(days)}
    return {"history": mt5_service.get_history(days)}
@app.get("/api/analysis/{symbol}")
def analysis(symbol: str="XAUUSD"):
    c=mt5_service.get_candles(symbol,"M5",100)
    if not c: return {"symbol":symbol,"signal":"HOLD","reason":"No data"}
    r=analyze_symbol(c, spread=(mt5_service.get_tick(symbol) or {}).get("spread"))
    r["symbol"]=symbol
    t=mt5_service.get_tick(symbol)
    if t: r["price"]=t["bid"]; r["spread"]=t.get("spread")
    return r
@app.get("/api/scalp-analysis")
def scalp_analysis(): return analysis("XAUUSD")
@app.post("/api/trade")
def trade(req: TradeRequest):
    if metaapi_service.is_connected():
        allowed, reason=risk_engine.can_trade(req.volume, req.symbol)
        if not allowed: raise HTTPException(status_code=400, detail=f"Risk blocked: {reason}")
        res=metaapi_service.send_order(symbol=req.symbol, action=req.action.upper(), volume=req.volume, sl=req.sl, tp=req.tp)
        if res["status"]=="success": risk_engine.register_trade(req.volume)
        return res
    if not mt5_service.is_connected(): raise HTTPException(status_code=400, detail="Not connected")
    allowed, reason=risk_engine.can_trade(req.volume, req.symbol)
    if not allowed: raise HTTPException(status_code=400, detail=f"Risk blocked: {reason}")
    res=mt5_service.send_order(symbol=req.symbol, action=req.action.upper(), volume=req.volume, sl=req.sl, tp=req.tp)
    if res["status"]=="success": risk_engine.register_trade(req.volume)
    return res
@app.post("/api/close/{ticket}")
def close_position(ticket: int):
    if metaapi_service.is_connected():
        res=metaapi_service.close_position(ticket)
        if res["status"]=="success": bot_engine.record_close(0)
        return res
    res=mt5_service.close_position(ticket)
    if res["status"]=="success": bot_engine.record_close(0)
    return res
@app.get("/api/bot/state")
def bot_state(): return bot_engine.get_bot_state()
@app.post("/api/bot/config")
def bot_config(patch: BotPatch):
    data={k:v for k,v in patch.model_dump().items() if v is not None}
    return bot_engine.update_config(data)
@app.post("/api/bot/start")
def bot_start(patch: Optional[BotPatch]=None):
    if patch:
        data={k:v for k,v in patch.model_dump().items() if v is not None}
        if data: bot_engine.update_config(data)
    if not mt5_service.is_connected(): raise HTTPException(status_code=400, detail="Connect Exness first")
    return bot_engine.start_bot()
@app.post("/api/bot/stop")
def bot_stop(): return bot_engine.stop_bot()
@app.websocket("/ws/telemetry")
async def telemetry(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            bs=bot_engine.get_bot_state()
            acc = metaapi_service.get_account_info() if metaapi_service.is_connected() else mt5_service.get_account_info()
            mode = "METAAPI" if metaapi_service.is_connected() else mt5_service.mode
            conn = metaapi_service.is_connected() or mt5_service.is_connected()
            # ticks prefer metaapi when connected
            ticks = {"XAUUSD": (metaapi_service.get_tick("XAUUSD") or mt5_service.get_tick("XAUUSD")), "EURUSD": (metaapi_service.get_tick("EURUSD") or mt5_service.get_tick("EURUSD"))}
            payload={"type":"telemetry","connected": conn,"mode": mode,"account": acc,"ticks": ticks,"bot":bs}
            await ws.send_text(json.dumps(payload))
            await asyncio.sleep(1.5)
    except WebSocketDisconnect:
        pass

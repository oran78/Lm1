"""Logic test for metaapi_service against a SIMULATED MetaApi (no network, no live account).
Endpoint names/paths mirror the official docs; this proves our handling, not the broker itself."""
import sys, os, types, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CALLS = []
ROUTES = {}      # (method, path-suffix) -> (status, json)

class FakeResp:
    def __init__(self, status, data): self.status_code, self._d = status, data; self.text = json.dumps(data)
    def json(self): return self._d

class FakeClient:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def _go(self, method, url, **kw):
        CALLS.append((method, url, kw.get("json"), kw.get("params")))
        for (m, suffix), resp in ROUTES.items():
            if m == method and url.split("?")[0].endswith(suffix): return FakeResp(*resp)
        return FakeResp(404, {"message": "not found"})
    def get(self, url, **kw): return self._go("GET", url, **kw)
    def post(self, url, **kw): return self._go("POST", url, **kw)

sys.modules["httpx"] = types.SimpleNamespace(Client=FakeClient)
import metaapi_service as ms
from risk_engine import risk_engine

def setup(symbols):
    CALLS.clear(); ROUTES.clear()
    ROUTES[("GET", "/accounts/ACC")] = (200, {"state": "DEPLOYED", "connectionStatus": "CONNECTED", "region": "london", "login": "123", "server": "Exness-MT5Trial9"})
    ROUTES[("GET", "/accountInformation")] = (200, {"balance": 10.0, "equity": 10.2, "profit": 0.2, "leverage": 2000, "currency": "USD"})
    ROUTES[("GET", "/symbols")] = (200, symbols)
    ROUTES[("GET", "/specification")] = (200, {"contractSize": 100, "minVolume": 0.01, "maxVolume": 200, "volumeStep": 0.01, "digits": 3})
    svc = ms.MetaApiService(); r = svc.connect("tok", "ACC"); return svc, r

# 1) symbol resolution for the different Exness account types
for syms, expect in [(["EURUSD", "XAUUSDm", "XAGUSDm"], "XAUUSDm"), (["XAUUSD", "EURUSD"], "XAUUSD"), (["XAUUSDc"], "XAUUSDc")]:
    svc, r = setup(syms)
    assert r["status"] == "success" and svc.resolve("XAUUSD") == expect, (syms, r)
    assert svc.canonical(expect) == "XAUUSD"
print("symbol resolution OK (m / plain / c)")

# 2) tick uses current-price on the RESOLVED symbol
svc, _ = setup(["XAUUSDm"])
ROUTES[("GET", "/symbols/XAUUSDm/current-price")] = (200, {"bid": 4140.10, "ask": 4140.40})
t = svc.get_tick("XAUUSD")
assert t and t["bid"] == 4140.10 and t["spread"] == 30.0 and t["broker_symbol"] == "XAUUSDm", t
assert any(u.endswith("/symbols/XAUUSDm/current-price") for _, u, _, _ in CALLS)
print("tick OK ->", t["bid"], "spread", t["spread"])

# 3) candles: sorted oldest->newest, ISO times parsed, correct host/timeframe
base = int(time.time()) // 300 * 300
ROUTES[("GET", "/symbols/XAUUSDm/timeframes/5m/candles")] = (200, [
    {"time": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(base - 300 * i)), "open": 1, "high": 2, "low": .5, "close": 1.5, "tickVolume": 10} for i in range(60)])
c = svc.get_candles("XAUUSD", "M5", 50)
assert len(c) == 50 and c[0]["time"] < c[-1]["time"], len(c)
assert any("mt-market-data-client-api-v1.london" in u for _, u, _, _ in CALLS)
print("candles OK", len(c))

# 4) order: broker symbol, SL/TP, retcode checked
ROUTES[("POST", "/trade")] = (200, {"numericCode": 10009, "stringCode": "TRADE_RETCODE_DONE", "orderId": "9", "positionId": "77"})
r = svc.send_order("XAUUSD", "BUY", 0.01, sl=4138.123456, tp=4144)
body = [b for m, u, b, _ in CALLS if m == "POST" and u.endswith("/trade")][-1]
assert r["status"] == "success" and r["ticket"] == "77", r
assert body["symbol"] == "XAUUSDm" and body["actionType"] == "ORDER_TYPE_BUY" and body["stopLoss"] == 4138.123 and body["takeProfit"] == 4144, body
ROUTES[("POST", "/trade")] = (200, {"numericCode": 10018, "stringCode": "TRADE_RETCODE_MARKET_CLOSED", "message": "Market is closed"})
r = svc.send_order("XAUUSD", "SELL", 0.01)
assert r["status"] == "error" and "MARKET_CLOSED" in r["message"], r     # HTTP 200 but NOT filled
print("order OK (and rejected-with-200 is reported as error)")

# 5) positions -> canonical symbol; close -> POSITION_CLOSE_ID
ROUTES[("GET", "/positions")] = (200, [{"id": "77", "symbol": "XAUUSDm", "type": "POSITION_TYPE_BUY", "volume": 0.01, "openPrice": 4140.4, "currentPrice": 4141, "profit": 0.6}])
ps = svc.get_positions()
assert ps[0]["symbol"] == "XAUUSD" and ps[0]["type"] == "BUY" and ps[0]["ticket"] == "77", ps
ROUTES[("POST", "/trade")] = (200, {"numericCode": 10009, "stringCode": "TRADE_RETCODE_DONE"})
r = svc.close_position("77")
cb = [b for m, u, b, _ in CALLS if m == "POST"][-1]
assert r["status"] == "success" and r["profit"] == 0.6 and cb == {"actionType": "POSITION_CLOSE_ID", "positionId": "77"}, (r, cb)
print("positions/close OK")

# 5b) break-even: POSITION_MODIFY keeps TP, rounds to the symbol digits, reports broker rejections
ROUTES[("POST", "/trade")] = (200, {"numericCode": 10009, "stringCode": "TRADE_RETCODE_DONE"})
r = svc.modify_position("77", sl=4140.45678, tp=4144.0, symbol="XAUUSD")
mb = [b for m, u, b, _ in CALLS if m == "POST"][-1]
assert r["status"] == "success" and mb == {"actionType": "POSITION_MODIFY", "positionId": "77", "stopLoss": 4140.457, "takeProfit": 4144.0}, (r, mb)
ROUTES[("POST", "/trade")] = (200, {"numericCode": 10016, "stringCode": "TRADE_RETCODE_INVALID_STOPS", "message": "Invalid stops"})
assert svc.modify_position("77", sl=4140.4, tp=4144.0, symbol="XAUUSD")["status"] == "error"
print("modify (break-even) OK")

# 5c) SL/TP on the wrong side never reach the broker; volume is floored to the lot step (risk is never rounded UP)
n_before = len(CALLS)
assert svc.send_order("XAUUSD", "BUY", 0.01, sl=4150.0, tp=4140.0)["status"] == "error" and len(CALLS) == n_before
ROUTES[("POST", "/trade")] = (200, {"numericCode": 10009, "stringCode": "TRADE_RETCODE_DONE", "positionId": "78"})
svc.send_order("XAUUSD", "SELL", 0.039, sl=4145.0, tp=4135.0)
sb = [b for m, u, b, _ in CALLS if m == "POST"][-1]
assert sb["volume"] == 0.03 and sb["stopLoss"] == 4145.0 and sb["takeProfit"] == 4135.0 and sb["actionType"] == "ORDER_TYPE_SELL", sb
print("order SL/TP validation + lot floor OK")

# 6) positions failure must raise (engine then refuses to open blind)
ROUTES[("GET", "/positions")] = (500, {})
try: svc.get_positions(); raise SystemExit("should raise")
except RuntimeError: pass
print("positions error propagates OK")

# 7) risk engine adopts broker contract spec
assert risk_engine.contract_size == 100 and risk_engine.min_lot == 0.01
st = svc.xau_status("M5")
keys = {k["key"]: k["ok"] for k in st["checks"]}
assert keys["account"] and keys["symbol"] and keys["tick"] and keys["candles"] and keys["fresh"], keys
print("xau_status OK ->", keys, "ready:", st["ready"])

# 8) missing gold symbol gives a clear message instead of a 404 loop
svc, r = setup(["EURUSD", "GBPUSD"])
assert svc.resolve("XAUUSD") is None and "not found" in svc.send_order("XAUUSD", "BUY", 0.01)["message"]
print("missing symbol message OK")
print("ALL METAAPI LOGIC TESTS PASSED")

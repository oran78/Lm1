"""
MetaApi Cloud — REAL Exness bridge (no Wine)
Professional: uses deployed AccountID + Token (from app.metaapi.cloud)
Works on Railway: HTTPS REST to mt-client-api-v1 / metaApi
Stores credentials per-connect for frontend switch-anytime.
"""
import os, time, logging
import httpx
logger = logging.getLogger("klop.metaapi")

REGION = os.getenv("METAAPI_REGION", "https://mt-client-api-v1")  # or london/new-york
DOMAIN = os.getenv("METAAPI_DOMAIN", "agiliumtrade.agiliumtrade.ai")  # default

class MetaApiService:
    def __init__(self):
        self.token = os.getenv("METAAPI_TOKEN", "").strip()
        self.account_id = os.getenv("METAAPI_ACCOUNT_ID", "").strip()
        self._connected = False
        self._account = None  # {login, server, balance...}
        self._mode = "METAAPI"
        self._last_err = None

    def configure(self, token: str, account_id: str):
        self.token = (token or "").strip()
        self.account_id = (account_id or "").strip()
        if token: os.environ["METAAPI_TOKEN"] = self.token
        if account_id: os.environ["METAAPI_ACCOUNT_ID"] = self.account_id

    def is_connected(self): return self._connected

    def _headers(self):
        return {"auth-token": self.token, "Content-Type": "application/json"}

    def connect(self, token: str = None, account_id: str = None):
        # token/account_id from frontend allows switch any day without Railway vars
        if token: self.token = token.strip()
        if account_id: self.account_id = account_id.strip()
        if token: os.environ["METAAPI_TOKEN"] = self.token
        if account_id: os.environ["METAAPI_ACCOUNT_ID"] = self.account_id
        if not self.token or not self.account_id:
            return {"status": "error", "message": "METAAPI_TOKEN + ACCOUNT_ID required. Create at app.metaapi.cloud/token + copy AccountID from deployed account."}
        # verify deployed
        try:
            with httpx.Client(timeout=8) as c:
                # metaapi provisioning: GET /users/current/accounts/:id
                r = c.get(f"https://mt-provisioning-api-v1.{DOMAIN}/users/current/accounts/{self.account_id}", headers=self._headers())
                if r.status_code == 401:
                    return {"status": "error", "message": "MetaApi token invalid (401) — recreate token at app.metaapi.cloud/token"}
                if r.status_code == 404:
                    return {"status": "error", "message": f"AccountID not found (404): {self.account_id} — check ID from screenshot"}
                if r.status_code != 200:
                    return {"status": "error", "message": f"MetaApi provisioning {r.status_code}: {r.text[:300]}"}
                j = r.json()
                state = j.get("state")
                conn = j.get("connectionStatus")
                login = j.get("login") or j.get("account", {}).get("login")
                server = j.get("server") or j.get("account", {}).get("server")
                if state not in ("DEPLOYED",):
                    logger.warning(f"MetaApi state {state} conn {conn}")
                    # still try RPC if deployed
                # Now try RPC: GET accountInformation
                # Choose region from account
                region = j.get("region") or "london"
                host = f"https://mt-client-api-v1.{region}.agiliumtrade.ai"
                # connection still deploying? allow
                # fetch account info via RPC
                r2 = c.get(f"{host}/users/current/accounts/{self.account_id}/accountInformation", headers=self._headers())
                bal = None
                acc_info = {}
                if r2.status_code == 200:
                    acc_info = r2.json()
                    bal = acc_info.get("balance")
                    logger.info(f"MetaApi NATIVE balance ${bal} login {login}@{server}")
                else:
                    # account not connected yet — try POST deploy or wait
                    logger.warning(f"MetaApi accountInformation {r2.status_code}: {r2.text[:400]}")
                self._connected = True
                self._account = {"login": login, "server": server, "balance": float(bal) if bal is not None else 0.0, "equity": float(acc_info.get("equity", bal or 0)), "profit": float(acc_info.get("profit", 0)), "mode": "METAAPI", "leverage": int(acc_info.get("leverage", 2000)), "currency": acc_info.get("currency","USD")}
                bal_txt = f"${self._account['balance']:.2f}" if bal is not None else "deploying (wait 30s then retry)"
                return {"status": "success", "message": f"\u2705 LIVE MetaApi NATIVE — {server} {login} — Balance {bal_txt} (REAL broker)", "mode": "METAAPI", "account": self._account, "balance": bal}
        except Exception as e:
            logger.exception("MetaApi connect fail")
            return {"status": "error", "message": f"MetaApi error: {e}"}

    def get_account_info(self):
        if not self._connected or not self.token: return None
        # refresh balance from RPC
        try:
            import httpx
            # need region — fetch provisioning once
            with httpx.Client(timeout=6) as c:
                r = c.get(f"https://mt-provisioning-api-v1.{DOMAIN}/users/current/accounts/{self.account_id}", headers=self._headers(), timeout=6)
                if r.status_code == 200:
                    region = r.json().get("region") or "london"
                    host = f"https://mt-client-api-v1.{region}.agiliumtrade.ai"
                    r2 = c.get(f"{host}/users/current/accounts/{self.account_id}/accountInformation", headers=self._headers(), timeout=6)
                    if r2.status_code == 200:
                        j = r2.json()
                        bal = float(j.get("balance", self._account.get("balance",0)))
                        return {"login": self._account.get("login"), "server": self._account.get("server"), "balance": bal, "equity": float(j.get("equity", bal)), "profit": float(j.get("profit",0)), "margin": float(j.get("margin",0)), "leverage": int(j.get("leverage",2000)), "currency": j.get("currency","USD"), "mode": "METAAPI"}
        except: pass
        return self._account

    def get_tick(self, symbol: str):
        # try MetaApi symbolPrice
        try:
            with httpx.Client(timeout=6) as c:
                r = c.get(f"https://mt-provisioning-api-v1.{DOMAIN}/users/current/accounts/{self.account_id}", headers=self._headers(), timeout=6)
                region = r.json().get("region") if r.status_code==200 else "london"
                host = f"https://mt-client-api-v1.{region}.agiliumtrade.ai"
                sym = symbol.upper()
                r2 = c.get(f"{host}/users/current/accounts/{self.account_id}/symbols/{sym}/currentPrice", headers=self._headers(), timeout=6)
                if r2.status_code==200:
                    j=r2.json(); return {"symbol": sym, "bid": float(j.get("bid",0)), "ask": float(j.get("ask",0)), "time": int(time.time()), "spread": round((j.get("ask",0)-j.get("bid",0))*100,1)}
        except: pass
        return None

    def send_order(self, symbol, action, volume, sl=None, tp=None):
        try:
            with httpx.Client(timeout=10) as c:
                r = c.get(f"https://mt-provisioning-api-v1.{DOMAIN}/users/current/accounts/{self.account_id}", headers=self._headers(), timeout=6)
                region = r.json().get("region") if r.status_code==200 else "london"
                host = f"https://mt-client-api-v1.{region}.agiliumtrade.ai"
                payload={"symbol": symbol.upper(), "volume": float(volume), "actionType": "ORDER_TYPE_BUY" if action=="BUY" else "ORDER_TYPE_SELL"}
                # SL/TP via price not supported here — backend will manage via close
                rr=c.post(f"{host}/users/current/accounts/{self.account_id}/trade", headers=self._headers(), json=payload, timeout=10)
                if rr.status_code in (200,201):
                    j=rr.json()
                    return {"status":"success","message": f"\u2705 LIVE MetaApi {action} {volume} {symbol} (REAL broker)", "ticket": j.get("orderId") or j.get("positionId"), "mode":"METAAPI"}
                return {"status":"error","message": f"MetaApi trade {rr.status_code}: {rr.text[:400]}"}
        except Exception as e:
            return {"status":"error","message": str(e)}

    def get_positions(self):
        try:
            with httpx.Client(timeout=8) as c:
                r=c.get(f"https://mt-provisioning-api-v1.{DOMAIN}/users/current/accounts/{self.account_id}", headers=self._headers(), timeout=6)
                region=r.json().get("region") if r.status_code==200 else "london"
                host=f"https://mt-client-api-v1.{region}.agiliumtrade.ai"
                r2=c.get(f"{host}/users/current/accounts/{self.account_id}/positions", headers=self._headers(), timeout=8)
                if r2.status_code==200:
                    arr=r2.json()
                    if isinstance(arr, list):
                        return [{"ticket": p.get("id") or p.get("positionId"), "symbol": p.get("symbol"), "type": "BUY" if str(p.get("type")).lower().find("buy")>=0 else "SELL", "volume": float(p.get("volume",0)), "price_open": float(p.get("openPrice",0)), "price_current": float(p.get("currentPrice",0)), "profit": float(p.get("profit",0)), "sl": p.get("stopLoss"), "tp": p.get("takeProfit"), "time": p.get("time")} for p in arr]
        except: pass
        return []

    def close_position(self, ticket):
        try:
            with httpx.Client(timeout=10) as c:
                r=c.get(f"https://mt-provisioning-api-v1.{DOMAIN}/users/current/accounts/{self.account_id}", headers=self._headers(), timeout=6)
                region=r.json().get("region") if r.status_code==200 else "london"
                host=f"https://mt-client-api-v1.{region}.agiliumtrade.ai"
                rr=c.post(f"{host}/users/current/accounts/{self.account_id}/positions/{ticket}/close", headers=self._headers(), json={}, timeout=10)
                if rr.status_code in (200,201): return {"status":"success","message": f"Closed LIVE {ticket} on broker"}
                return {"status":"error","message": f"Close {rr.status_code}: {rr.text[:300]}"}
        except Exception as e:
            return {"status":"error","message": str(e)}

    def disconnect(self):
        self._connected=False
        self._account=None

metaapi_service = MetaApiService()

"""
MetaApi Cloud bridge for Exness (REST, no Wine) — v2.4

What changed vs v2.3 (why XAUUSD never went "active"):
  * Price endpoint was `/symbols/X/currentPrice` (404). The real one is `/symbols/X/current-price`.
  * Exness names gold per account type (XAUUSD, XAUUSDm, XAUUSDc, XAUUSDz ...). The bot asked for plain
    "XAUUSD" and got 404 on Standard/Cent accounts. Symbols are now resolved from the broker's own list.
  * A provisioning call was repeated before EVERY tick/position/order. Region host is now cached.
  * Close used a non-existent `/positions/{id}/close`; now POST /trade {POSITION_CLOSE_ID}.
  * HTTP 200 does not mean the order filled: `stringCode` is now checked (TRADE_RETCODE_DONE...).
  * Positions come back with the canonical symbol (XAUUSD) so the bot's "1 position max" check works.
  * `xau_status()` gives a readiness checklist for the frontend.
"""
import os, time, logging, threading
from datetime import datetime, timezone
import httpx

logger = logging.getLogger("klop.metaapi")

DOMAIN = os.getenv("METAAPI_DOMAIN", "agiliumtrade.agiliumtrade.ai")       # provisioning host domain
CLIENT_DOMAIN = os.getenv("METAAPI_CLIENT_DOMAIN", "agiliumtrade.ai")        # client / market-data domain
PROVISIONING = f"https://mt-provisioning-api-v1.{DOMAIN}"

_TF = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m", "H1": "1h", "H4": "4h"}
_OK_CODES = {"TRADE_RETCODE_DONE", "TRADE_RETCODE_PLACED", "TRADE_RETCODE_DONE_PARTIAL", "ERR_NO_ERROR"}
# Exness gold name variants, most common first (standard=XAUUSDm, pro/zero/raw=XAUUSD, cent=XAUUSDc)
_SUFFIXES = ["", "m", "c", "z", "r", "pro", ".", "#", "_i", ".a", "-"]


class MetaApiService:
    def __init__(self):
        self.token = os.getenv("METAAPI_TOKEN", "").strip()
        self.account_id = os.getenv("METAAPI_ACCOUNT_ID", "").strip()
        self._connected = False
        self._account = None
        self._mode = "METAAPI"
        self._last_err = None
        self._region = None
        self._lock = threading.Lock()
        self._sym_map = {}          # canonical (XAUUSD) -> broker symbol (XAUUSDm)
        self._rev_map = {}          # broker symbol -> canonical
        self._broker_symbols = []
        self._spec = {}             # broker symbol -> specification dict
        self._acc_cache = (0.0, None)
        self._tick_cache = {}       # broker symbol -> (t, tick)
        self._last_tick_ok = 0.0
        self._last_candle_ok = 0.0
        self._last_candle_count = 0
        self._last_candle_err = None

    # ------------------------------------------------------------------ plumbing
    def configure(self, token, account_id):
        if token: self.token = token.strip()
        if account_id: self.account_id = account_id.strip()

    def is_connected(self): return self._connected

    def _h(self):
        return {"auth-token": self.token, "Accept": "application/json", "Content-Type": "application/json"}

    def _client_host(self):
        return f"https://mt-client-api-v1.{self._region or 'london'}.{CLIENT_DOMAIN}"

    def _market_host(self):
        return f"https://mt-market-data-client-api-v1.{self._region or 'london'}.{CLIENT_DOMAIN}"

    def _acc_url(self, host, path=""):
        return f"{host}/users/current/accounts/{self.account_id}{path}"

    def _provision(self, c):
        r = c.get(f"{PROVISIONING}/users/current/accounts/{self.account_id}", headers=self._h())
        return r

    # ------------------------------------------------------------------ connect
    def connect(self, token=None, account_id=None):
        if token: self.token = token.strip()
        if account_id: self.account_id = account_id.strip()
        if not self.token or not self.account_id:
            return {"status": "error", "message": "MetaApi Token + Account ID required (app.metaapi.cloud/token, Account ID from the account card)"}
        try:
            with httpx.Client(timeout=12) as c:
                r = self._provision(c)
                if r.status_code == 401:
                    return {"status": "error", "message": "MetaApi token invalid (401) — create a new token at app.metaapi.cloud/token"}
                if r.status_code in (403, 404):
                    return {"status": "error", "message": f"Account ID not found / no access ({r.status_code}) — copy the ID from the account card"}
                if r.status_code != 200:
                    return {"status": "error", "message": f"MetaApi provisioning {r.status_code}: {r.text[:200]}"}
                j = r.json()
                self._region = j.get("region") or "london"
                state, conn = j.get("state"), j.get("connectionStatus")
                login, server = j.get("login"), j.get("server")
                if state != "DEPLOYED":
                    return {"status": "error", "message": f"Account state is {state} — press Deploy in app.metaapi.cloud and wait until CONNECTED, then retry"}
                if conn != "CONNECTED":
                    logger.warning(f"MetaApi deployed but broker connection is {conn}")
                r2 = c.get(self._acc_url(self._client_host(), "/accountInformation"), headers=self._h())
                if r2.status_code != 200:
                    return {"status": "error", "message": f"Deployed but broker not reachable yet (connection {conn}, HTTP {r2.status_code}). Wait ~30s and retry. {r2.text[:150]}"}
                info = r2.json()
            self._connected = True
            self._account = self._mk_account(info, login, server)
            self._load_symbols()
            xau = self.resolve("XAUUSD")
            self._apply_spec_to_risk(xau)
            note = f"XAUUSD → {xau}" if xau else "⚠ gold symbol not found in this account's Market Watch"
            return {"status": "success", "mode": "METAAPI", "account": self._account, "balance": self._account["balance"],
                    "xau_symbol": xau,
                    "message": f"✅ MetaApi connected — {server} {login} • Balance ${self._account['balance']:.2f} • {note}"}
        except Exception as e:
            logger.exception("MetaApi connect failed")
            return {"status": "error", "message": f"MetaApi error: {e}"}

    def _mk_account(self, j, login=None, server=None):
        bal = float(j.get("balance", 0) or 0)
        return {"login": login or (self._account or {}).get("login"), "server": server or (self._account or {}).get("server"),
                "balance": bal, "equity": float(j.get("equity", bal) or bal), "profit": float(j.get("profit", 0) or 0),
                "margin": float(j.get("margin", 0) or 0), "leverage": int(j.get("leverage", 2000) or 2000),
                "currency": j.get("currency", "USD"), "mode": "METAAPI"}

    def disconnect(self):
        self._connected = False
        self._account = None
        self._sym_map.clear(); self._rev_map.clear(); self._broker_symbols = []; self._spec.clear(); self._tick_cache.clear()

    # ------------------------------------------------------------------ symbols
    def _load_symbols(self):
        try:
            with httpx.Client(timeout=10) as c:
                r = c.get(self._acc_url(self._client_host(), "/symbols"), headers=self._h())
                if r.status_code == 200 and isinstance(r.json(), list):
                    self._broker_symbols = [str(s) for s in r.json()]
                else:
                    logger.warning(f"symbols list {r.status_code}: {r.text[:150]}")
        except Exception as e:
            logger.warning(f"symbols list failed: {e}")

    def resolve(self, symbol):
        """Canonical name (XAUUSD) -> the broker's real symbol (XAUUSDm / XAUUSD / XAUUSDc ...). None if absent."""
        canon = (symbol or "").upper().replace("/", "")
        if canon in self._sym_map: return self._sym_map[canon]
        if not self._broker_symbols: self._load_symbols()
        syms = self._broker_symbols
        by_upper = {s.upper(): s for s in syms}
        found = None
        for suf in _SUFFIXES:                     # exact variants first
            cand = (canon + suf).upper()
            if cand in by_upper: found = by_upper[cand]; break
        if not found:                              # any symbol that starts with the canonical name
            starts = sorted([s for s in syms if s.upper().startswith(canon)], key=len)
            if starts: found = starts[0]
        if not found and not syms:                 # list unavailable: fall back to the plain name
            found = canon
        if found:
            self._sym_map[canon] = found
            self._rev_map[found.upper()] = canon
        return found

    def canonical(self, broker_symbol):
        b = str(broker_symbol or "").upper()
        return self._rev_map.get(b, b)

    def symbols(self):
        return self._broker_symbols

    def get_spec(self, broker_symbol):
        if not broker_symbol: return {}
        if broker_symbol in self._spec: return self._spec[broker_symbol]
        try:
            with httpx.Client(timeout=8) as c:
                r = c.get(self._acc_url(self._client_host(), f"/symbols/{broker_symbol}/specification"), headers=self._h())
                if r.status_code == 200:
                    self._spec[broker_symbol] = r.json()
                    return self._spec[broker_symbol]
        except Exception as e:
            logger.debug(f"spec fail {e}")
        return {}

    def _apply_spec_to_risk(self, broker_symbol):
        """Use the broker's real contract size / lot limits for risk maths (cent accounts differ!)."""
        try:
            from risk_engine import risk_engine
            s = self.get_spec(broker_symbol)
            if s.get("contractSize"): risk_engine.contract_size = float(s["contractSize"])
            if s.get("minVolume"): risk_engine.min_lot = float(s["minVolume"])
            if s.get("volumeStep"): risk_engine.lot_step = float(s["volumeStep"])
            if s.get("maxVolume"): risk_engine.max_lot = min(risk_engine.max_lot, float(s["maxVolume"]))
            logger.info(f"risk spec {broker_symbol}: contract={risk_engine.contract_size} min={risk_engine.min_lot} step={risk_engine.lot_step}")
        except Exception as e:
            logger.debug(f"apply spec failed: {e}")

    # ------------------------------------------------------------------ account
    def get_account_info(self):
        if not self._connected: return None
        t, cached = self._acc_cache
        if cached and time.time() - t < 5: return cached
        try:
            with httpx.Client(timeout=6) as c:
                r = c.get(self._acc_url(self._client_host(), "/accountInformation"), headers=self._h())
                if r.status_code == 200:
                    acc = self._mk_account(r.json())
                    self._acc_cache = (time.time(), acc); self._account = acc
                    return acc
        except Exception as e:
            logger.debug(f"account info fail {e}")
        return self._account

    # ------------------------------------------------------------------ market data
    def get_tick(self, symbol):
        if not self._connected: return None
        canon = symbol.upper()
        bsym = self.resolve(canon)
        if not bsym: return None
        t, cached = self._tick_cache.get(bsym, (0.0, None))
        if cached and time.time() - t < 1.0: return cached
        try:
            with httpx.Client(timeout=6) as c:
                r = c.get(self._acc_url(self._client_host(), f"/symbols/{bsym}/current-price"),
                          headers=self._h(), params={"keepSubscription": "true"})
                if r.status_code == 200:
                    j = r.json()
                    bid, ask = float(j.get("bid") or 0), float(j.get("ask") or 0)
                    if bid <= 0 or ask <= 0: return cached
                    tick = {"symbol": canon, "broker_symbol": bsym, "bid": bid, "ask": ask, "time": int(time.time()),
                            "spread": round((ask - bid) * 100, 1), "source": "BROKER"}
                    self._tick_cache[bsym] = (time.time(), tick)
                    self._last_tick_ok = time.time()
                    return tick
                logger.warning(f"current-price {bsym} {r.status_code}: {r.text[:150]}")
        except Exception as e:
            logger.debug(f"tick fail {e}")
        return cached if cached and time.time() - t < 10 else None

    def get_candles(self, symbol, timeframe="M5", count=100):
        """Real broker candles (oldest->newest). Last element is the still-forming candle. [] on failure."""
        if not self._connected: return []
        bsym = self.resolve(symbol)
        if not bsym: return []
        tf = _TF.get(timeframe, "5m")
        try:
            with httpx.Client(timeout=15) as c:
                r = c.get(self._acc_url(self._market_host(), f"/historical-market-data/symbols/{bsym}/timeframes/{tf}/candles"),
                          headers=self._h(), params={"limit": min(int(count), 1000)})
                if r.status_code != 200:
                    self._last_candle_err = f"HTTP {r.status_code}: {r.text[:120]}"
                    logger.warning(f"candles {bsym} {tf} {self._last_candle_err}")
                    return []
                out = []
                for k in r.json():
                    t = k.get("time")
                    ts = int(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()) if isinstance(t, str) else int(t)
                    out.append({"time": ts, "open": float(k["open"]), "high": float(k["high"]), "low": float(k["low"]),
                                "close": float(k["close"]), "volume": int(k.get("tickVolume", 0) or 0)})
                out.sort(key=lambda x: x["time"])
                out = out[-count:]
                self._last_candle_ok = time.time(); self._last_candle_count = len(out); self._last_candle_err = None
                return out
        except Exception as e:
            self._last_candle_err = str(e)
            logger.warning(f"candles error: {e}")
            return []

    # ------------------------------------------------------------------ trading
    def _trade_post(self, c, body, timeout=15):
        return c.post(self._acc_url(self._client_host(), "/trade"), headers=self._h(), json=body, timeout=timeout)

    def send_order(self, symbol, action, volume, sl=None, tp=None, magic=None, comment=None):
        bsym = self.resolve(symbol)
        if not bsym:
            return {"status": "error", "message": f"{symbol} not found in this MetaApi account's symbols (Market Watch). Available e.g.: {', '.join(self._broker_symbols[:8])}"}
        spec = self.get_spec(bsym)
        step, vmin, vmax = float(spec.get("volumeStep") or 0.01), float(spec.get("minVolume") or 0.01), float(spec.get("maxVolume") or 100)
        vol = round(max(vmin, min(vmax, int(float(volume) / step + 1e-9) * step)), 2)   # floor to the lot step, never round UP the risk
        is_buy = action.upper() == "BUY"
        body = {"symbol": bsym, "volume": vol, "actionType": "ORDER_TYPE_BUY" if is_buy else "ORDER_TYPE_SELL"}
        digits = int(spec.get("digits") or 2)
        if magic is not None: body["magic"] = int(magic)           # ownership tag: the bot only manages its own magic
        if comment: body["comment"] = str(comment)[:31]
        if sl and float(sl) > 0: body["stopLoss"] = round(float(sl), digits)
        if tp and float(tp) > 0: body["takeProfit"] = round(float(tp), digits)
        s_, t_ = body.get("stopLoss"), body.get("takeProfit")
        if s_ and t_ and ((is_buy and not s_ < t_) or (not is_buy and not t_ < s_)):
            return {"status": "error", "message": f"Invalid SL/TP for {action.upper()}: SL {s_} / TP {t_}"}
        try:
            with httpx.Client(timeout=15) as c:
                rr = self._trade_post(c, body)
                try: j = rr.json()
                except Exception: j = {}
                code = j.get("stringCode") or ""
                if rr.status_code in (200, 201) and (code in _OK_CODES or not code):
                    tid = j.get("positionId") or j.get("orderId") or "pending"
                    logger.info(f"MetaApi {action} {bsym} {vol} -> {j}")
                    return {"status": "success", "ticket": tid, "mode": "METAAPI", "symbol": bsym, "volume": vol, "raw": j,
                            "message": f"✅ {action.upper()} {vol} {bsym} filled on broker (#{tid})"}
                msg = j.get("message") or rr.text[:300]
                logger.warning(f"MetaApi trade rejected {rr.status_code} {code}: {msg}")
                return {"status": "error", "message": f"Broker rejected: {code or rr.status_code} — {msg}"}
        except Exception as e:
            logger.exception("send_order failed")
            return {"status": "error", "message": f"MetaApi error: {e}"}

    def modify_position(self, ticket, sl=None, tp=None, symbol=None):
        """Move SL/TP of an open position (used for auto break-even). Sends POSITION_MODIFY to MetaApi."""
        if not self._connected: return {"status": "error", "message": "MetaApi not connected"}
        bsym = self.resolve(symbol) if symbol else None
        digits = int((self.get_spec(bsym) or {}).get("digits") or 2) if bsym else 2
        body = {"actionType": "POSITION_MODIFY", "positionId": str(ticket)}
        if sl and float(sl) > 0: body["stopLoss"] = round(float(sl), digits)
        if tp and float(tp) > 0: body["takeProfit"] = round(float(tp), digits)
        try:
            with httpx.Client(timeout=12) as c:
                rr = self._trade_post(c, body, timeout=12)
                try: j = rr.json()
                except Exception: j = {}
                code = j.get("stringCode") or ""
                if rr.status_code in (200, 201) and (code in _OK_CODES or not code):
                    return {"status": "success", "message": f"Modified #{ticket}: SL {body.get('stopLoss')} TP {body.get('takeProfit')}"}
                return {"status": "error", "message": f"Modify rejected: {code or rr.status_code} — {j.get('message') or rr.text[:200]}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_positions(self):
        if not self._connected: return []
        try:
            with httpx.Client(timeout=8) as c:
                r = c.get(self._acc_url(self._client_host(), "/positions"), headers=self._h())
                if r.status_code != 200: raise RuntimeError(f"positions HTTP {r.status_code}")
                arr = r.json()
                return [{"ticket": str(p.get("id")), "symbol": self.canonical(p.get("symbol")), "broker_symbol": p.get("symbol"),
                         "type": "BUY" if "BUY" in str(p.get("type", "")).upper() else "SELL",
                         "volume": float(p.get("volume", 0)), "price_open": float(p.get("openPrice", 0)),
                         "price_current": float(p.get("currentPrice", 0)), "profit": float(p.get("profit", 0)),
                         "sl": p.get("stopLoss"), "tp": p.get("takeProfit"), "time": p.get("time"),
                         "magic": p.get("magic"), "comment": p.get("comment") or p.get("brokerComment")} for p in arr]
        except Exception as e:
            logger.warning(f"positions failed: {e}")
            raise            # the engine treats an exception as "unknown" and will not open blind trades

    def close_position(self, ticket):
        try:
            profit = 0.0
            try:
                for p in self.get_positions():
                    if str(p["ticket"]) == str(ticket): profit = p["profit"]
            except Exception: pass
            with httpx.Client(timeout=12) as c:
                rr = self._trade_post(c, {"actionType": "POSITION_CLOSE_ID", "positionId": str(ticket)}, timeout=12)
                try: j = rr.json()
                except Exception: j = {}
                code = j.get("stringCode") or ""
                if rr.status_code in (200, 201) and (code in _OK_CODES or not code):
                    return {"status": "success", "message": f"Closed #{ticket} on broker", "profit": profit}
                return {"status": "error", "message": f"Close rejected: {code or rr.status_code} — {j.get('message') or rr.text[:200]}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_history(self, days=7):
        """Closed deals (last N days) from the broker."""
        if not self._connected: return []
        try:
            end = datetime.now(timezone.utc); start = datetime.fromtimestamp(end.timestamp() - days * 86400, timezone.utc)
            f = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            with httpx.Client(timeout=12) as c:
                r = c.get(self._acc_url(self._client_host(), f"/history-deals/time/{f(start)}/{f(end)}"), headers=self._h())
                if r.status_code != 200: return []
                deals = r.json()
                deals = deals.get("deals", deals) if isinstance(deals, dict) else deals
                out = [{"ticket": d.get("id"), "symbol": self.canonical(d.get("symbol")), "type": str(d.get("type", "")).replace("DEAL_TYPE_", ""),
                        "volume": d.get("volume"), "profit": round(float(d.get("profit", 0) or 0), 2), "time": d.get("time"),
                        "position_id": d.get("positionId"), "commission": round(float(d.get("commission", 0) or 0), 2),
                        "swap": round(float(d.get("swap", 0) or 0), 2)}
                       for d in deals if d.get("symbol") and str(d.get("entryType", "")).endswith("OUT")]
                return out[-40:]
        except Exception as e:
            logger.debug(f"history fail {e}")
            return []

    # ------------------------------------------------------------------ XAUUSD readiness (for the UI)
    def xau_status(self, timeframe="M5"):
        bsym = self.resolve("XAUUSD") if self._connected else None
        tick = self.get_tick("XAUUSD") if bsym else None
        candles = self.get_candles("XAUUSD", timeframe, 120) if bsym else []
        age = (time.time() - candles[-1]["time"]) if candles else None
        from strategy import _session_ok
        sess_ok, sess_label = _session_ok()
        tf_secs = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}.get(timeframe, 300)
        market_open = bool(tick) and (age is None or age < tf_secs * 4)
        checks = [
            {"key": "account", "label": "MetaApi account connected", "ok": self._connected},
            {"key": "symbol", "label": f"Gold symbol found ({bsym})" if bsym else "Gold symbol found in broker list", "ok": bool(bsym)},
            {"key": "tick", "label": "Live bid/ask streaming" + (f" ({tick['bid']:.2f}/{tick['ask']:.2f})" if tick else ""), "ok": bool(tick)},
            {"key": "candles", "label": f"{timeframe} history loaded ({len(candles)}/45+)", "ok": len(candles) >= 45},
            {"key": "fresh", "label": "Market open / candles fresh", "ok": market_open},
            {"key": "session", "label": f"Trading session — {sess_label}", "ok": sess_ok},
        ]
        return {"connected": self._connected, "symbol": "XAUUSD", "broker_symbol": bsym, "tick": tick, "candles": len(candles),
                "candle_age_s": round(age) if age is not None else None, "session": sess_label, "checks": checks,
                "ready": all(c["ok"] for c in checks[:5]), "last_error": self._last_candle_err}


metaapi_service = MetaApiService()

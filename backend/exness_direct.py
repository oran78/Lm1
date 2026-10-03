"""
Klop Apex — Exness Direct Bridge (honest)
Railway Linux CANNOT fetch Exness PA directly — my.exness.com is Cloudflare-protected.
httpx gets 403 cf-challenge, so numeric MT5 -> balance $0 is expected on Railway.
REAL paths that actually work:
  1. BRIDGE_URL (Windows bridge_windows.py) -> NATIVE broker via your VPS
  2. Wine MT5 on Railway (Dockerfile + Xvfb) -> NATIVE on Railway
  3. Sync Balance (manual) -> PAPER on live $4141 price (chart/signals are still REAL)
This module keeps EXNESS_DIRECT for honesty: logs Cloudflare block, does NOT fake balance.
If cloudscraper is installed, it will try CF bypass automatically.
"""
import logging
import time
logger = logging.getLogger("klop.exness")

EXNESS_MT5_HOSTS = {
    "Exness-MT5Real": "77.242.96.10:443",
    "Exness-MT5Real2": "77.242.96.11:443",
    "Exness-MT5Real3": "77.242.96.12:443",
    "Exness-MT5Trial": "77.242.96.100:443",
}

class ExnessDirect:
    def __init__(self):
        self.session_token = None
        self.accounts = []
        self.mt5_login = None
        self.mt5_server = None
        self.mt5_password = None
        self._cf_blocked = False
        self._last_cf_reason = None

    def _headers(self):
        h = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://my.exness.com",
            "Referer": "https://my.exness.com/",
            "Content-Type": "application/json",
        }
        if self.session_token:
            h["Authorization"] = f"Bearer {self.session_token}"
        return h

    def login(self, mt5_login: int, password: str, server: str) -> dict:
        """
        Honest: Numeric MT5 login on Railway Linux CANNOT become REAL balance
        without BRIDGE or Wine — Exness PA is Cloudflare Turnstile protected.
        We store creds, check MT5 host reachable, and return REAL_DIRECT (paper on live price).
        """
        self.mt5_login = int(mt5_login) if str(mt5_login).isdigit() else mt5_login
        self.mt5_server = server
        self.mt5_password = password

        # Try Cloudflare bypass only if cloudscraper available — otherwise log and skip
        is_email = "@" in str(mt5_login)
        if is_email:
            tried_cf = self._try_cf_bypass(str(mt5_login), password)
            if tried_cf.get("ok"):
                return tried_cf
            self._cf_blocked = True
            self._last_cf_reason = tried_cf.get("reason", "Cloudflare challenge — Railway cannot pass Turnstile")

        # MT5 TCP reachability = server exists, NOT credential validation
        host = EXNESS_MT5_HOSTS.get(server)
        if host:
            try:
                import socket
                h, port = host.split(":")
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3)
                s.connect((h, int(port)))
                s.close()
                logger.info(f"MT5 host {host} reachable — creds stored, live price mode")
            except Exception as e:
                logger.debug(f"MT5 socket {host} unreachable: {e}")

        return {"ok": True, "mode": "REAL_DIRECT", "cf_blocked": self._cf_blocked, "note": "Railway Linux: Cloudflare blocks Exness PA — balance needs BRIDGE/Wine or Sync"}

    def _try_cf_bypass(self, email: str, password: str) -> dict:
        """Attempt PA auth via cloudscraper if installed; otherwise report CF block."""
        urls = [
            "https://my.exness.com/api/authorization/authorize",
            "https://my.exness.com/apiv2/auth/login",
        ]
        # Try cloudscraper first (handles CF Turnstile better than httpx)
        try:
            import cloudscraper  # type: ignore
            scraper = cloudscraper.create_scraper(browser={"browser":"chrome","platform":"windows","mobile":False})
            for url in urls:
                try:
                    r = scraper.post(url, json={"login": email, "password": password}, headers=self._headers(), timeout=10)
                    if r.status_code in (200, 201):
                        j = r.json()
                        token = j.get("token") or j.get("access_token") or j.get("data",{}).get("token")
                        if token:
                            self.session_token = token
                            logger.info(f"Exness PA via cloudscraper OK {url}")
                            return {"ok": True, "mode": "EXNESS_API", "token": token}
                    elif r.status_code == 403 and "cloudflare" in r.text.lower():
                        return {"ok": False, "reason": f"CF 403 at {url}"}
                except Exception as e:
                    logger.debug(f"cloudscraper PA {url} fail: {e}")
        except ImportError:
            pass
        # Fallback httpx — will almost always get 403
        try:
            import httpx
            for url in urls:
                try:
                    with httpx.Client(timeout=8, follow_redirects=True) as c:
                        r = c.post(url, json={"login": email, "password": password}, headers=self._headers())
                        body = r.text.lower()
                        if r.status_code == 403 and ("cloudflare" in body or "cf-challenge" in body or "turnstile" in body):
                            logger.warning(f"Exness PA Cloudflare blocked at {url} — need BRIDGE/Wine")
                            return {"ok": False, "reason": f"Cloudflare 403 at {url}"}
                        if r.status_code in (200, 201):
                            j = r.json()
                            token = j.get("token") or j.get("access_token") or j.get("data",{}).get("token")
                            if token:
                                self.session_token = token
                                return {"ok": True, "mode": "EXNESS_API", "token": token}
                except Exception as e:
                    logger.debug(f"PA httpx {url} fail: {e}")
        except Exception:
            pass
        return {"ok": False, "reason": "Cloudflare protected — install cloudscraper or use BRIDGE/Wine"}

    def fetch_accounts(self) -> list:
        if not self.session_token:
            return []
        return []

    def get_real_balance(self, mt5_login: int = None):
        # Cannot fetch while CF blocks and no token
        if not self.session_token:
            return None
        return None

exness_direct = ExnessDirect()

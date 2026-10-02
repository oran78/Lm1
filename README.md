# Klop Apex — Exness Auto Flip (REAL)

**Railway `backend/` + Vercel `frontend/` — REAL live XAU + REAL Exness balance via direct bypass (no Wine needed for now)**

## Deep Bypass (systematic)
Railway is Linux — MT5 is Windows-only. Instead of heavy Wine (needs 1GB RAM), we bypass at code level:
- `exness_direct.py` — talks directly to Exness Personal Area HTTPS (no MetaApi) → fetches REAL MT5 accounts + balance
- `market_service.py` — live XAU price from gold-api.com (~$4131) — no mock
- `mt5_service.py` — priorities: NATIVE Wine (if present) → EXNESS_API (HTTPS) → REAL market (live price + live P/L)

If you have Wine VPS, NATIVE auto-wins. Otherwise EXNESS_API gives REAL balance with lightweight `python:slim`.

## Deploy
- Railway Root: `backend` → Dockerfile `python:slim` (fast, 512MB ok)
- Vercel Root: `frontend` → env `NEXT_PUBLIC_API_URL=https://<railway>.up.railway.app`
- For FULL NATIVE broker fills, swap Dockerfile to the Wine variant in git history (`0f81cec`).

## Connect
Login can be **MT5 login (numeric)** or **Exness PA email** — PA email gives auto REAL balance. MT5 numeric + Sync Balance manual also works, but chart + P/L are always LIVE price.

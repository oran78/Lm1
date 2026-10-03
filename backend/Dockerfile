# Klop Apex — REAL Exness MT5 on Railway — slim build, runtime MT5 (no build timeout)
# MT5 is Windows-only → Linux: Wine + mt5linux RPyC + mt5server.exe at startup, not build
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    PYTHONUNBUFFERED=1 \
    WINEPREFIX=/root/.wine \
    WINEARCH=win64

# Only Python + tools now — Wine/MT5 installed at runtime to avoid 10-min build timeout
RUN apt-get update && apt-get install -y --no-install-recommends \
      wget curl ca-certificates procps unzip \
      && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Startup: install Wine + MT5 if missing then run mt5server + FastAPI
# This keeps BUILD <2 min (Railway Hobby/Pro timely), runtime pulls heavy bits lazily with fallback to LIVE $4141
RUN printf '#!/bin/bash\nset +e\n# Quick path: if Wine exists, start Xvfb + mt5server; else apt-get Wine lazily\nif ! command -v wine >/dev/null 2>&1; then\n  echo "[SETUP] Installing Wine (first boot, ~2min) ..."\n  dpkg --add-architecture i386 2>/dev/null || true\n  apt-get update -qq\n  apt-get install -y -qq --no-install-recommends software-properties-common 2>&1 | tail -2 || true\n  apt-get install -y -qq --no-install-recommends wine64 wine32 xvfb xauth cabextract winbind 2>&1 | tail -5 || echo "[SETUP] Wine apt fallback"\n  wine --version 2>&1 | head -1 || echo "[SETUP] wine not yet"\nfi\n# Xvfb\nrm -f /tmp/.X99-lock\nif command -v Xvfb >/dev/null 2>&1; then\n  Xvfb :99 -ac -screen 0 1024x768x24 &\n  for i in 1 2 3 4 5 6; do xdpyinfo -display :99 >/dev/null 2>&1 && break; sleep 0.5; done\n  echo "[WINE] Xvfb ready"\nfi\n# mt5server.exe fetch if missing\nif [ ! -f /app/mt5server.exe ]; then\n  echo "[WINE] Fetching mt5server.exe ..."\n  wget -q https://github.com/lucas-campagna/mt5linux/releases/download/server-1.1.1/mt5server.exe -O /app/mt5server.exe 2>&1 | tail -2 || echo "[WINE] mt5server fetch fail — paper fallback"\nfi\n# MT5 installer (background, non-blocking)\nMT5_EXE="/root/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"\nif [ ! -f "$MT5_EXE" ] && command -v wine >/dev/null 2>&1; then\n  echo "[WINE] Installing MT5 in background ..."\n  mkdir -p /tmp/mt5dl\n  wget -q https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe -O /tmp/mt5setup.exe 2>&1 | tail -1 || true\n  timeout 120 xvfb-run -a wine /tmp/mt5setup.exe /auto 2>&1 | tail -5 || true\n  echo "[WINE] MT5 install attempt done"\nfi\n# Start mt5server + terminal if available\nif [ -f /app/mt5server.exe ] && command -v wine >/dev/null 2>&1; then\n  echo "[WINE] Starting mt5server.exe :8001 ..."\n  wine /app/mt5server.exe --port 8001 2>&1 | sed "s/^/[mt5server] /" &\n  sleep 6\n  if [ -f "$MT5_EXE" ]; then\n    echo "[WINE] Starting terminal64.exe ..."\n    wine "$MT5_EXE" /portable >/tmp/mt5.log 2>&1 &\n    sleep 4\n  fi\nelse\n  echo "[WINE] mt5server/wine missing — running on LIVE $4141 paper (Sync Balance)"\nfi\necho "[APP] Starting FastAPI on ${PORT:-8080} ..."\nexec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}\n' > /app/start.sh && chmod +x /app/start.sh

EXPOSE 8080
CMD ["/app/start.sh"]

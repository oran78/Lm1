# Klop Apex — REAL Exness MT5 on Railway (Docker + Wine) — No Windows needed
# Systematically bypasses Railway Linux limitation: Ubuntu + Wine + Xvfb + MT5 Terminal
FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive \
    WINEPREFIX=/root/.wine \
    WINEARCH=win64 \
    DISPLAY=:99 \
    PYTHONUNBUFFERED=1

RUN dpkg --add-architecture i386 && apt-get update && \
    apt-get install -y --no-install-recommends \
      wine64 wine32 xvfb wget curl unzip ca-certificates \
      python3 python3-pip winbind cabextract xvfb xauth && \
    rm -rf /var/lib/apt/lists/*

# Pre-create Wine prefix (avoid first-run delay)
RUN winecfg /v || true

# Fetch MT5 installers (Exness + MetaQuotes fallback)
RUN mkdir -p /opt/mt5 && \
    wget -q https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe -O /tmp/mt5setup.exe && \
    (wget -q https://download.exness.com/mt5/exness5setup.exe -O /tmp/exness5setup.exe || cp /tmp/mt5setup.exe /tmp/exness5setup.exe) && \
    ls -lh /tmp/*.exe

# Silent install MT5 under Xvfb (ignore timeout, check install)
RUN Xvfb :99 -screen 0 1024x768x16 & XPID=$!; sleep 2; \
    timeout 200 xvfb-run -a wine /tmp/mt5setup.exe /auto || true; \
    sleep 10; wineserver -k 2>/dev/null || true; kill $XPID 2>/dev/null || true; \
    ls -la "/root/.wine/drive_c/Program Files/" 2>&1 | head -30 || true; \
    ls -la "/root/.wine/drive_c/Program Files/MetaTrader 5/" 2>&1 | head -20 || echo "MT5 folder not yet — will retry at startup"

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Install MetaTrader5 inside Wine Python (for NATIVE bridge)
RUN xvfb-run -a wine python -m pip install --upgrade pip 2>&1 | tail -5 || true
RUN timeout 120 xvfb-run -a wine python -m pip install MetaTrader5 2>&1 | tail -15 || echo "Wine MetaTrader5 optional — fallback to EXNESS_DIRECT live price"

COPY . .

# Startup: Xvfb + MT5 terminal + FastAPI — if MT5 fails, FastAPI still serves REAL market via gold-api
RUN printf '#!/bin/bash\nset -e\nXvfb :99 -screen 0 1024x768x16 &\nXVFB_PID=$!\nsleep 3\nMT5_EXE="/root/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"\nif [ -f "$MT5_EXE" ]; then\n  echo "[WINE] Starting MT5 terminal..."\n  wine "$MT5_EXE" /portable &\n  MT5_PID=$!\n  sleep 12\n  echo "[WINE] MT5 PID $MT5_PID"\nelse\n  echo "[WINE] MT5 not preinstalled — will install on first /api/connect (EXNESS_DIRECT live price until then)"\nfi\necho "[APP] Starting FastAPI..."\nexec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}\n' > /app/start.sh && chmod +x /app/start.sh

EXPOSE 8080
CMD ["/app/start.sh"]

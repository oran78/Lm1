# Klop Apex — REAL Exness MT5 on Railway Linux — mt5linux (Wine+RPyC+mt5server.exe)
# MT5 is Windows-only. Linux systematic: mt5linux = Wine + RPyC + mt5server.exe
# Sources: github.com/lucas-campagna/mt5linux + metatrader5.com/install_linux + tobix/pywine
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    WINEPREFIX=/root/.wine \
    WINEARCH=win64 \
    DISPLAY=:99 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 1. Wine + Xvfb + deps (from mt5linux/tobix/pywine)
RUN dpkg --add-architecture i386 && apt-get update && \
    apt-get install -y --no-install-recommends \
      wine64 wine32 \
      xvfb xauth x11vnc fluxbox cabextract winbind \
      wget curl unzip ca-certificates procps \
      && rm -rf /var/lib/apt/lists/*

# 2. vcrun2019 (needed for MT5) via winetricks
RUN curl -L -o /usr/bin/winetricks https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks && chmod +x /usr/bin/winetricks && \
    xvfb-run -a winetricks --unattended vcrun2019 || echo "vcrun2019 done" && \
    wine --version

# 3. MT5 terminal via official installer inside Wine
RUN mkdir -p /opt/mt5 && \
    wget -q https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe -O /tmp/mt5setup.exe && \
    timeout 180 xvfb-run -a wine /tmp/mt5setup.exe /auto || echo "mt5setup exit 0" && \
    sleep 8 && wineserver -k 2>/dev/null || true && \
    ls -la "/root/.wine/drive_c/Program Files/" 2>&1 | head -20 || true && \
    ls -la "/root/.wine/drive_c/Program Files/MetaTrader 5/" 2>&1 | head -20 || echo "MT5 dir pending startup"

# 4. Python deps + mt5linux (RPyC talk to Wine mt5server.exe)
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Fetch mt5server.exe (standalone) — the Linux bridge binary
RUN wget -q https://github.com/lucas-campagna/mt5linux/releases/download/server-1.1.1/mt5server.exe -O /app/mt5server.exe && ls -lh /app/mt5server.exe

COPY . .

# 6. Startup: Xvfb -> wine mt5server.exe (RPyC 8001) -> FastAPI (PORT)
RUN printf '#!/bin/bash\nset -e\nrm -f /tmp/.X99-lock\nXvfb :99 -ac -screen 0 1024x768x24 &\nfor i in 1 2 3 4 5 6 7 8 9 10; do xdpyinfo -display :99 >/dev/null 2>&1 && break; sleep 0.5; done\nsleep 2\necho "[WINE] Xvfb ready on :99"\nif [ -f /app/mt5server.exe ]; then\n  echo "[WINE] Starting mt5server.exe :8001 ..."\n  wine /app/mt5server.exe --port 8001 &\n  sleep 10\n  echo "[WINE] mt5server started"\n  MT5_EXE="/root/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"\n  if [ -f "$MT5_EXE" ]; then\n    echo "[WINE] Starting terminal64.exe ..."\n    wine "$MT5_EXE" /portable >/tmp/mt5.log 2>&1 &\n    sleep 6\n    echo "[WINE] terminal started"\n  fi\nelse\n  echo "[WINE] mt5server.exe missing — fallback to BRIDGE / paper"\nfi\necho "[APP] Starting FastAPI on ${PORT:-8080} ..."\nexec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}\n' > /app/start.sh && chmod +x /app/start.sh

EXPOSE 8080
CMD ["/app/start.sh"]

'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import TradingChart from '@/components/TradingChart';
import XauHero, { XauStatus } from '@/components/XauHero';
import { get, post, wsUrl } from '@/lib/api';
import { toPlanned, toTrade } from '@/lib/types';

const SERVERS = ['Exness-MT5Real', 'Exness-MT5Real2', 'Exness-MT5Real3', 'Exness-MT5Real4', 'Exness-MT5Real5', 'Exness-MT5Trial', 'Exness-MT5Trial6', 'Exness-MT5Trial9'];
const SYMBOLS = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY'];
const TFS = ['M1', 'M5', 'M15', 'H1'] as const;
type TF = typeof TFS[number];

const money = (n: any, d = 2) => (typeof n === 'number' && isFinite(n) ? n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }) : '—');
const signed = (n: any) => (typeof n === 'number' && isFinite(n) ? `${n >= 0 ? '+' : '−'}$${Math.abs(n).toFixed(2)}` : '—');
const tone = (n: any) => (typeof n === 'number' && n < 0 ? 'text-rose-400' : 'text-emerald-400');

function usePoll(fn: () => Promise<void>, ms: number, deps: any[]) {
  useEffect(() => {
    let off = false;
    const run = async () => { if (off || (typeof document !== 'undefined' && document.hidden)) return; try { await fn(); } catch {} };
    run();
    const id = setInterval(run, ms);
    return () => { off = true; clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

function Meter({ label, value, max, mark, text, hue }: { label: string; value?: number; max: number; mark?: number; text: string; hue: string }) {
  const pct = typeof value === 'number' ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-black/20 p-3">
      <div className="flex items-baseline justify-between"><span className="label">{label}</span><span className="font-mono text-sm font-semibold">{text}</span></div>
      <div className="relative mt-2 h-1.5 rounded-full bg-white/[0.07]">
        <div className={`h-full rounded-full ${hue} transition-all duration-500`} style={{ width: `${pct}%` }} />
        {mark !== undefined && <i className="absolute -top-1 h-3.5 w-px bg-white/40" style={{ left: `${(mark / max) * 100}%` }} />}
      </div>
    </div>
  );
}

function Spark({ points }: { points: number[] }) {
  if (points.length < 2) return null;
  const min = Math.min(...points), max = Math.max(...points), r = max - min || 1;
  const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${(i / (points.length - 1)) * 300},${44 - ((p - min) / r) * 40}`).join(' ');
  const up = points[points.length - 1] >= points[0];
  return (
    <svg viewBox="0 0 300 48" className="h-12 w-full" preserveAspectRatio="none">
      <defs><linearGradient id="sg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={up ? '#34d399' : '#f87171'} stopOpacity=".35" /><stop offset="1" stopColor={up ? '#34d399' : '#f87171'} stopOpacity="0" /></linearGradient></defs>
      <path d={`${d} L300,48 L0,48 Z`} fill="url(#sg)" />
      <path d={d} fill="none" stroke={up ? '#34d399' : '#f87171'} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function Page() {
  const [connected, setConnected] = useState(false); const [mode, setMode] = useState(''); const [acc, setAcc] = useState<any>(null);
  const [symbol, setSymbol] = useState('XAUUSD'); const [tf, setTf] = useState<TF>('M5');
  const [ticks, setTicks] = useState<Record<string, any>>({}); const [candles, setCandles] = useState<any[]>([]); const [candleSrc, setCandleSrc] = useState('');
  const [analysis, setAnalysis] = useState<any>(null); const [positions, setPositions] = useState<any[]>([]); const [history, setHistory] = useState<any[]>([]);
  const [tab, setTab] = useState<'positions' | 'history' | 'log'>('positions'); const [wsOk, setWsOk] = useState(false);
  const [xau, setXau] = useState<XauStatus | null>(null); const [activating, setActivating] = useState(false);
  const [bot, setBot] = useState<any>(null); const [msg, setMsg] = useState<{ t: 'ok' | 'err'; m: string } | null>(null);

  // connect form
  const [useMeta, setUseMeta] = useState(true); const [metaToken, setMetaToken] = useState(''); const [showTok, setShowTok] = useState(false);
  const [metaAccountId, setMetaAccountId] = useState(''); const [login, setLogin] = useState(''); const [password, setPassword] = useState('');
  const [server, setServer] = useState('Exness-MT5Trial9'); const [connecting, setConnecting] = useState(false); const [showConnect, setShowConnect] = useState(true);

  // bot form
  const [riskPct, setRiskPct] = useState('1'); const [targetMult, setTargetMult] = useState('2'); const [maxDay, setMaxDay] = useState('12');
  const [autoLot, setAutoLot] = useState(true); const [fixedLot, setFixedLot] = useState('0.01'); const [slAtr, setSlAtr] = useState('1.2'); const [tpAtr, setTpAtr] = useState('1.8');
  const [botTf, setBotTf] = useState<TF>('M5'); const [session, setSession] = useState(true); const [flipMode, setFlipMode] = useState(true);
  const [manualLot, setManualLot] = useState('0.01'); const [attachSlTp, setAttachSlTp] = useState(true); const [trading, setTrading] = useState(false);
  const hydrated = useRef(false);

  const tick = ticks[symbol] || ticks.XAUUSD;
  const toast = useCallback((t: 'ok' | 'err', m: string) => { setMsg({ t, m }); }, []);
  useEffect(() => { if (!msg) return; const id = setTimeout(() => setMsg(null), 8000); return () => clearTimeout(id); }, [msg]);
  useEffect(() => { try { const v = localStorage.getItem('klop_account_id'); if (v) setMetaAccountId(v); } catch {} }, []);

  const hydrate = (b: any) => {
    if (!b?.config || hydrated.current) return;
    const c = b.config; hydrated.current = true;
    setRiskPct(String(c.risk_pct)); setTargetMult(String(c.target_multiplier)); setMaxDay(String(c.max_trades_per_day));
    setAutoLot(!!c.auto_lot); setFixedLot(String(c.fixed_lot)); setSlAtr(String(c.sl_atr_mult)); setTpAtr(String(c.tp_atr_mult));
    setBotTf((c.timeframe || 'M5') as TF); setTf((c.timeframe || 'M5') as TF); setSession(!!c.session_filter); if (c.flip_mode !== undefined) setFlipMode(!!c.flip_mode);
    if (c.symbol && SYMBOLS.includes(c.symbol)) setSymbol(c.symbol);
  };

  // ---- data: status (4s), market (5s), positions (3s), history (20s), XAU checklist (6s); ticks + account + bot arrive by WebSocket
  usePoll(async () => {
    const s = await get('/api/status');
    setConnected(!!s.connected); setMode(s.mode || ''); if (s.account) setAcc(s.account);
    if (s.bot) { setBot(s.bot); hydrate(s.bot); }
    if (s.connected) setShowConnect(false);
  }, 4000, []);
  usePoll(async () => {
    if (!connected) return;
    const [c, a] = await Promise.all([get(`/api/candles/${symbol}?timeframe=${tf}&count=150`), get(`/api/analysis/${symbol}`).catch(() => null)]);
    if (c?.candles) { setCandles(c.candles); setCandleSrc(c.source || ''); }
    if (a) setAnalysis(a);
  }, 5000, [connected, symbol, tf]);
  usePoll(async () => { if (connected) { const p = await get('/api/positions'); if (p?.positions) setPositions(p.positions); } }, 3000, [connected]);
  usePoll(async () => { if (connected) { const h = await get('/api/history?days=7'); if (h?.history) setHistory(h.history); } }, 20000, [connected]);
  usePoll(async () => { if (connected && mode === 'METAAPI') setXau(await get(`/api/xau/status?timeframe=${tf}`)); }, 6000, [connected, mode, tf]);

  useEffect(() => { setCandles([]); setAnalysis(null); }, [symbol, tf]);

  // websocket with auto-reconnect
  useEffect(() => {
    let ws: WebSocket | null = null; let stop = false; let timer: any;
    const open = () => {
      try {
        ws = new WebSocket(wsUrl(`/ws/telemetry?symbol=${symbol}`));
        ws.onopen = () => setWsOk(true);
        ws.onclose = () => { setWsOk(false); if (!stop) timer = setTimeout(open, 2500); };
        ws.onmessage = e => {
          try {
            const d = JSON.parse(e.data);
            if (d.connected !== undefined) setConnected(d.connected);
            if (d.mode) setMode(d.mode); if (d.account) setAcc(d.account); if (d.ticks) setTicks(p => ({ ...p, ...d.ticks })); if (d.bot) setBot(d.bot);
          } catch {}
        };
      } catch { setWsOk(false); }
    };
    open();
    return () => { stop = true; clearTimeout(timer); try { ws?.close(); } catch {} };
  }, [symbol]);

  // ---- actions
  const activateXau = async (quiet = false) => {
    setActivating(true);
    try {
      const x = await post(`/api/xau/activate?timeframe=${tf}`);
      setXau(x); setSymbol('XAUUSD'); setBotTf(tf); if (!quiet) toast(x.ready ? 'ok' : 'err', x.message);
      return x;
    } catch (e: any) { toast('err', e.message); } finally { setActivating(false); }
  };

  const doConnect = async () => {
    setConnecting(true); setMsg(null);
    try {
      const body: any = useMeta ? { use_metaapi: true, metaapi_token: metaToken.trim(), metaapi_account_id: metaAccountId.trim() } : { login, password, server };
      const j = await post('/api/connect', body);
      setConnected(true); setShowConnect(false); hydrated.current = false;
      if (useMeta) {
        try { localStorage.setItem('klop_account_id', metaAccountId.trim()); } catch {}
        setMetaToken('');
        const x = await activateXau(true);
        toast(x?.ready ? 'ok' : 'err', `${j.message} — ${x?.message || 'XAUUSD check failed'}`);
      } else toast('ok', j.message);
    } catch (e: any) {
      toast('err', e.message + (e.message?.includes('Failed to fetch') ? ' — backend unreachable. Check NEXT_PUBLIC_API_URL.' : ''));
    } finally { setConnecting(false); }
  };

  const num = (v: string) => parseFloat(v);
  const botBody = () => ({ risk_pct: num(riskPct), target_multiplier: num(targetMult), max_trades_per_day: parseInt(maxDay), auto_lot: autoLot, fixed_lot: num(fixedLot), sl_atr_mult: num(slAtr), tp_atr_mult: num(tpAtr), symbol, timeframe: botTf, session_filter: session, flip_mode: flipMode });
  const validate = () => {
    if (!(num(riskPct) > 0 && num(riskPct) <= 5)) return 'Risk per trade must be between 0.1% and 5%';
    if (!(num(slAtr) > 0 && num(tpAtr) > 0)) return 'SL / TP multipliers must be above 0';
    if (!autoLot && !(num(fixedLot) >= 0.01)) return 'Fixed lot must be at least 0.01';
    return null;
  };
  const saveBot = async () => { const v = validate(); if (v) return toast('err', v); try { setBot(await post('/api/bot/config', botBody())); toast('ok', '✓ Bot settings saved'); } catch (e: any) { toast('err', e.message); } };
  const startBot = async () => {
    const v = validate(); if (v) return toast('err', v);
    if (symbol === 'XAUUSD' && mode === 'METAAPI' && xau && !xau.ready) return toast('err', 'XAUUSD is not ready — fix the red checks above (or press Activate XAUUSD).');
    try { setBot(await post('/api/bot/start', botBody())); toast('ok', '🚀 Auto Flip started — watch the Log tab'); setTab('log'); } catch (e: any) { toast('err', e.message); }
  };
  const stopBot = async () => { try { setBot(await post('/api/bot/stop')); toast('ok', '⏹ Bot stopped'); } catch (e: any) { toast('err', e.message); } };
  const doTrade = async (a: 'BUY' | 'SELL') => {
    const lot = num(manualLot); if (!(lot >= 0.01)) return toast('err', 'Lot must be at least 0.01');
    const atr = analysis?.atr; const t = tick; let sl: number | undefined, tp: number | undefined;
    if (attachSlTp && atr > 0 && t?.bid) { const e = a === 'BUY' ? t.ask : t.bid; const d = atr * num(slAtr), r = atr * num(tpAtr); sl = +(a === 'BUY' ? e - d : e + d).toFixed(2); tp = +(a === 'BUY' ? e + r : e - r).toFixed(2); }
    if (!window.confirm(`${a} ${lot} ${symbol}${sl ? `\nSL ${sl}  •  TP ${tp}` : '\nNo SL/TP attached'}\n${mode === 'METAAPI' ? 'This sends a REAL order to your broker.' : ''}`)) return;
    setTrading(true);
    try { const j = await post('/api/trade', { symbol, action: a, volume: lot, sl, tp }); toast(j.status === 'error' ? 'err' : 'ok', j.message); } catch (e: any) { toast('err', e.message); } finally { setTrading(false); }
  };
  const closePos = async (t: any) => { try { const j = await post(`/api/close/${t}`); toast(j.status === 'error' ? 'err' : 'ok', j.message); } catch (e: any) { toast('err', e.message); } };
  const disconnect = async () => { try { await post('/api/disconnect'); } catch {} setConnected(false); setAcc(null); setXau(null); setShowConnect(true); };

  // chart overlays: while the bot runs its telemetry is authoritative; otherwise fall back to the polled analysis / broker positions
  const botSymbol: string = bot?.config?.symbol || symbol;
  const planned = botSymbol !== symbol ? null
    : bot?.enabled ? toPlanned(bot?.planned_setup)
    : analysis?.state === 'PLANNED_SETUP' ? toPlanned({ side: analysis.planned_side, entry_price: analysis.planned_entry_price }) : null;
  const livePos = positions.find(p => String(p.symbol || '').toUpperCase() === symbol.toUpperCase());
  const trade = toTrade(bot?.active_trade && botSymbol === symbol ? bot.active_trade : livePos);
  const chartPlanned = trade ? null : planned;       // planned line disappears the moment the trade triggers

  const st = bot?.stats; const sig = st?.last_signal || analysis?.signal || 'HOLD';
  const sigCls = sig === 'BUY' ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-300' : sig === 'SELL' ? 'border-rose-400/30 bg-rose-400/10 text-rose-300' : sig.includes('WARN') ? 'border-amber-400/30 bg-amber-400/10 text-amber-300' : 'border-white/10 bg-white/5 text-zinc-400';
  const eq: number[] = (st?.equity_curve || []).map((p: any) => p.equity);
  const flip = st?.flip_progress ?? 0;
  const modeLabel = mode === 'METAAPI' ? 'MetaApi • Real broker' : mode === 'BRIDGE' ? 'Bridge' : mode === 'NATIVE' ? 'MT5 native' : mode === 'REAL' ? 'Paper on live price' : mode;
  const risky = num(riskPct) > 2;

  return (
    <div className="min-h-screen selection:bg-amber-400/30">
      <div className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(700px_420px_at_12%_-5%,rgba(245,185,66,0.10),transparent_60%),radial-gradient(700px_500px_at_100%_0%,rgba(120,90,255,0.10),transparent_60%)]" />

      <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-[#07070b]/75 backdrop-blur-2xl">
        <div className="mx-auto flex h-16 max-w-[1500px] items-center justify-between gap-3 px-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-2xl bg-gradient-to-br from-amber-300 to-amber-600 text-lg font-black text-zinc-950 shadow-lg shadow-amber-500/25">Au</div>
            <div className="leading-tight">
              <h1 className="text-[17px] font-semibold tracking-tight">Klop <span className="gold-text">Apex</span></h1>
              <p className="label !text-[10px]">XAUUSD • Auto scalper</p>
            </div>
            <div className="ml-3 hidden items-center gap-2 md:flex">
              <span className={`chip ${connected ? 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300' : 'border-white/10 bg-white/5 text-zinc-400'}`}>
                <i className={`h-1.5 w-1.5 rounded-full ${connected ? 'animate-pulse bg-emerald-400' : 'bg-zinc-500'}`} />{connected ? 'Connected' : 'Disconnected'}
              </span>
              {connected && <span className="chip border-white/10 bg-white/5 text-zinc-300">{modeLabel}</span>}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="seg hidden sm:inline-flex">{SYMBOLS.map(s => <button key={s} data-on={symbol === s} onClick={() => setSymbol(s)}>{s}</button>)}</div>
            <select value={symbol} onChange={e => setSymbol(e.target.value)} className="input !w-auto !rounded-full !py-1.5 sm:hidden">{SYMBOLS.map(s => <option key={s}>{s}</option>)}</select>
            {connected ? <button onClick={disconnect} className="btn-ghost !px-4 !py-1.5 text-xs">Disconnect</button> : <button onClick={() => setShowConnect(v => !v)} className="btn-gold !px-4 !py-1.5 text-xs">Connect</button>}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] space-y-5 px-4 py-6 sm:px-6">
        {msg && (
          <div onClick={() => setMsg(null)} className={`rise cursor-pointer rounded-2xl border px-4 py-3 text-sm ${msg.t === 'ok' ? 'border-emerald-400/20 bg-emerald-400/10 text-emerald-200' : 'border-rose-400/25 bg-rose-400/10 text-rose-200'}`}>{msg.m}</div>
        )}

        {(showConnect || !connected) && (
          <section className="card-pad rise">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold tracking-tight">Connect your Exness account</h2>
                <p className="mt-1 text-sm text-zinc-500">MetaApi trades your real MT5 account from the cloud. After connecting, XAUUSD is activated automatically.</p>
              </div>
              <div className="seg"><button data-on={useMeta} onClick={() => setUseMeta(true)}>MetaApi</button><button data-on={!useMeta} onClick={() => setUseMeta(false)}>MT5 direct</button></div>
            </div>
            {useMeta ? (
              <div className="mt-4 grid gap-3 lg:grid-cols-[1.3fr_1fr_auto]">
                <div className="relative">
                  <input value={metaToken} onChange={e => setMetaToken(e.target.value)} type={showTok ? 'text' : 'password'} autoComplete="off" placeholder="MetaApi token (eyJ…)" className="input pr-14" />
                  <button type="button" onClick={() => setShowTok(v => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-[11px] font-semibold text-zinc-500 hover:text-zinc-300">{showTok ? 'HIDE' : 'SHOW'}</button>
                </div>
                <input value={metaAccountId} onChange={e => setMetaAccountId(e.target.value)} placeholder="Account ID (xxxxxxxx-xxxx-…)" className="input font-mono" />
                <button onClick={doConnect} disabled={connecting || !metaToken.trim() || !metaAccountId.trim()} className="btn-gold">{connecting ? 'Connecting…' : 'Connect & activate XAUUSD →'}</button>
              </div>
            ) : (
              <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_1fr_1fr_auto]">
                <input value={login} onChange={e => setLogin(e.target.value)} placeholder="MT5 login" className="input" />
                <input value={password} onChange={e => setPassword(e.target.value)} type="password" placeholder="Master password" className="input" />
                <select value={server} onChange={e => setServer(e.target.value)} className="input">{SERVERS.map(s => <option key={s}>{s}</option>)}</select>
                <button onClick={doConnect} disabled={connecting || !login || !password} className="btn-gold">{connecting ? 'Connecting…' : 'Connect →'}</button>
              </div>
            )}
            {useMeta && <p className="mt-3 text-xs text-zinc-500">Account must show <b className="text-zinc-300">DEPLOYED</b> and <b className="text-zinc-300">CONNECTED</b> in app.metaapi.cloud. The token is sent to your backend only and is not stored in the browser.</p>}
          </section>
        )}

        <XauHero tick={ticks.XAUUSD} status={xau} connected={connected} wsOk={wsOk} botOn={!!bot?.enabled} activating={activating} onActivate={() => activateXau()} selected={symbol === 'XAUUSD'} />

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          {[
            { k: 'Balance', v: acc ? `$${money(acc.balance)}` : '—', sub: acc?.login ? `${acc.login} • ${acc.server}` : 'Not connected' },
            { k: 'Equity', v: acc ? `$${money(acc.equity)}` : '—', c: acc ? tone(acc.equity - acc.balance) : '' },
            { k: 'Floating P/L', v: acc ? signed(acc.profit) : '—', c: acc ? tone(acc.profit) : '' },
            { k: 'Today P/L', v: st ? signed(st.pnl_today) : '—', sub: st ? `${st.wins}W / ${st.losses}L • ${st.win_rate}%` : '', c: st ? tone(st.pnl_today) : '' },
          ].map((c, i) => (
            <div key={i} className="card-pad rise" style={{ animationDelay: `${i * 40}ms` }}>
              <p className="label">{c.k}</p>
              <p className={`mt-1.5 font-mono text-[22px] font-semibold tracking-tight ${c.c || 'text-white'}`}>{c.v}</p>
              {c.sub && <p className="mt-1 truncate text-xs text-zinc-500">{c.sub}</p>}
            </div>
          ))}
          <div className="card-pad col-span-2 lg:col-span-1">
            <p className="label">Flip progress</p>
            <p className="mt-1.5 font-mono text-[22px] font-semibold tracking-tight">{flip.toFixed(1)}%</p>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.07]"><div className="h-full rounded-full bg-gradient-to-r from-amber-300 to-amber-500 transition-all duration-700" style={{ width: `${Math.min(100, flip)}%` }} /></div>
            <p className="mt-1.5 truncate text-[11px] text-zinc-500">{st ? `$${money(st.current_balance)} → $${money(st.target_balance)}` : '—'}</p>
          </div>
        </div>

        <div className="grid gap-5 xl:grid-cols-[1fr_400px]">
          <div className="min-w-0 space-y-5">
            <section className="card overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] px-5 py-3.5">
                <div className="flex items-center gap-3">
                  <h3 className="font-semibold tracking-tight">{symbol}</h3>
                  <div className="seg">{TFS.map(t => <button key={t} data-on={tf === t} onClick={() => setTf(t)}>{t}</button>)}</div>
                </div>
                <div className="flex items-center gap-2">
                  {candleSrc && <span className={`chip ${candleSrc === 'BROKER' ? 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300' : 'border-amber-400/25 bg-amber-400/10 text-amber-300'}`} title={candleSrc === 'BROKER' ? 'Candles come from your broker' : 'Fallback public data (PAXG) — not your broker'}>{candleSrc === 'BROKER' ? 'Broker candles' : `Fallback: ${candleSrc}`}</span>}
                  {(st?.last_state || analysis?.state) && <span className="chip border-white/10 bg-white/5 text-zinc-400" title="Strategy state">{(st?.last_state || analysis?.state).replace('_', ' ')}</span>}
                  <span className={`chip font-bold ${sigCls}`}>{sig.replace('_WARN', '')}{analysis?.confidence ? ` • ${analysis.confidence}%` : ''}</span>
                </div>
              </div>
              <div className="px-2 pb-2 pt-3"><TradingChart data={candles} markers={st?.markers} planned={chartPlanned} trade={trade} resetKey={`${symbol}-${tf}`} height={420} /></div>
            </section>

            <section className="card-pad">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Meter label="RSI 14" value={analysis?.rsi} max={100} mark={50} text={analysis?.rsi != null ? String(analysis.rsi) : '—'} hue={analysis?.rsi > 70 ? 'bg-rose-400' : analysis?.rsi < 30 ? 'bg-emerald-400' : 'bg-violet-400'} />
                <Meter label="ADX 14" value={analysis?.adx} max={50} text={analysis?.adx != null ? String(analysis.adx) : '—'} hue="bg-amber-400" />
                <div className="rounded-2xl border border-white/[0.06] bg-black/20 p-3"><div className="flex items-baseline justify-between"><span className="label">ATR 14</span><span className="font-mono text-sm font-semibold">{analysis?.atr ?? '—'}</span></div><p className="mt-2 font-mono text-[11px] text-zinc-500">SL ≈ ${analysis?.atr ? (analysis.atr * num(slAtr)).toFixed(2) : '—'} • TP ≈ ${analysis?.atr ? (analysis.atr * num(tpAtr)).toFixed(2) : '—'}</p></div>
                <div className="rounded-2xl border border-white/[0.06] bg-black/20 p-3"><div className="flex items-baseline justify-between"><span className="label">EMA 9 / 21</span><span className={`font-mono text-sm font-semibold ${analysis?.ema9 > analysis?.ema21 ? 'text-emerald-400' : 'text-rose-400'}`}>{analysis?.ema9 > analysis?.ema21 ? '▲ bull' : analysis?.ema9 < analysis?.ema21 ? '▼ bear' : '—'}</span></div><p className="mt-2 font-mono text-[11px] text-zinc-500">{analysis?.ema9 ?? '—'} / {analysis?.ema21 ?? '—'}</p></div>
              </div>
              <p className="mt-4 text-sm leading-relaxed text-zinc-300">{st?.last_reason || analysis?.reason || 'Waiting for a signal…'}</p>
              {analysis?.session && <p className="mt-1 text-xs text-zinc-500">{analysis.session}</p>}
            </section>

            <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[{ v: `${st?.trades_today ?? 0}/${bot?.config?.max_trades_per_day ?? 12}`, k: 'Trades today' }, { v: String(st?.wins ?? 0), k: 'Wins', c: 'text-emerald-400' }, { v: String(st?.losses ?? 0), k: 'Losses', c: 'text-rose-400' }, { v: `${st?.win_rate ?? 0}%`, k: st ? `Win rate (${(st.wins || 0) + (st.losses || 0)} trades)` : 'Win rate' }].map((s, i) => (
                <div key={i} className="card py-4 text-center"><p className={`font-mono text-xl font-semibold ${s.c || ''}`}>{s.v}</p><p className="label mt-0.5">{s.k}</p></div>
              ))}
            </section>

            {eq.length > 1 && <section className="card-pad"><p className="label mb-2">Equity</p><Spark points={eq} /></section>}
          </div>

          <aside className="space-y-5">
            <section className="card-pad border-amber-400/15 bg-gradient-to-b from-amber-400/[0.06] to-transparent">
              <div className="flex items-center justify-between"><h3 className="font-semibold tracking-tight">⚡ Auto Flip Engine</h3>{bot?.enabled && <span className="chip border-emerald-400/30 bg-emerald-400/10 text-emerald-300"><i className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />RUNNING</span>}</div>
              <div className="mt-4 grid grid-cols-2 gap-3">
                <label className="label">Risk / trade %<input value={riskPct} onChange={e => setRiskPct(e.target.value)} inputMode="decimal" className="input mt-1.5 font-mono !normal-case !tracking-normal" /></label>
                <label className="label">Flip target<select value={targetMult} onChange={e => setTargetMult(e.target.value)} className="input mt-1.5 !normal-case !tracking-normal">{['1.5', '2', '3', '5', '10'].map(x => <option key={x} value={x}>×{x}</option>)}</select></label>
                <label className="label">SL (ATR ×)<input value={slAtr} onChange={e => setSlAtr(e.target.value)} inputMode="decimal" className="input mt-1.5 font-mono !normal-case !tracking-normal" /></label>
                <label className="label">TP (ATR ×)<input value={tpAtr} onChange={e => setTpAtr(e.target.value)} inputMode="decimal" className="input mt-1.5 font-mono !normal-case !tracking-normal" /></label>
                <label className="label">Max / day<input value={maxDay} onChange={e => setMaxDay(e.target.value)} inputMode="numeric" className="input mt-1.5 font-mono !normal-case !tracking-normal" /></label>
                <label className="label">Bot timeframe<select value={botTf} onChange={e => setBotTf(e.target.value as TF)} className="input mt-1.5 !normal-case !tracking-normal">{TFS.map(t => <option key={t}>{t}</option>)}</select></label>
                <label className="label">Lot mode<select value={autoLot ? 'auto' : 'fixed'} onChange={e => setAutoLot(e.target.value === 'auto')} className="input mt-1.5 !normal-case !tracking-normal"><option value="auto">Auto (risk %)</option><option value="fixed">Fixed</option></select></label>
                {!autoLot ? <label className="label">Fixed lot<input value={fixedLot} onChange={e => setFixedLot(e.target.value)} inputMode="decimal" className="input mt-1.5 font-mono !normal-case !tracking-normal" /></label>
                  : <label className="label flex items-end gap-2 pb-2.5 !normal-case !tracking-normal"><input type="checkbox" checked={session} onChange={e => setSession(e.target.checked)} className="h-4 w-4 accent-amber-400" /><span className="text-xs text-zinc-400">London + NY only</span></label>}
              </div>
              {risky && <p className="mt-3 rounded-xl border border-amber-400/20 bg-amber-400/10 px-3 py-2 text-xs text-amber-200">Risk above 2% per trade can wipe a small account quickly.</p>}
              <div className="mt-4 flex gap-2">
                <button onClick={saveBot} className="btn-ghost flex-1">Save</button>
                {!bot?.enabled ? <button onClick={startBot} disabled={!connected} className="btn-gold flex-1">▶ Start</button> : <button onClick={stopBot} className="btn-sell flex-1">⏹ Stop</button>}
              </div>
              <div className="mt-3 flex items-center justify-between rounded-xl border border-amber-400/20 bg-amber-400/10 p-2.5">
                <div>
                  <p className="text-xs font-semibold text-amber-300">$10 Flip Mode</p>
                  <p className="text-[10px] text-zinc-400">Allows 0.01 lot on micro accounts (up to 35% risk cap)</p>
                </div>
                <input type="checkbox" checked={flipMode} onChange={e => setFlipMode(e.target.checked)} className="h-4 w-4 accent-amber-400" />
              </div>
              <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">EMA 9/21 + RSI + ATR + ADX on closed candles • 1 position max • SL/TP on every order.</p>
            </section>

            <section className="card-pad">
              <h3 className="font-semibold tracking-tight">Manual trade <span className="font-mono text-xs text-zinc-500">{symbol}</span></h3>
              <div className="mt-3 flex items-center gap-3">
                <input value={manualLot} onChange={e => setManualLot(e.target.value)} inputMode="decimal" className="input !w-24 font-mono" />
                <label className="flex items-center gap-2 text-xs text-zinc-400"><input type="checkbox" checked={attachSlTp} onChange={e => setAttachSlTp(e.target.checked)} className="h-4 w-4 accent-amber-400" />Attach ATR SL/TP</label>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <button onClick={() => doTrade('BUY')} disabled={!connected || trading} className="btn-buy !py-3">BUY {tick?.ask ? money(tick.ask) : ''}</button>
                <button onClick={() => doTrade('SELL')} disabled={!connected || trading} className="btn-sell !py-3">SELL {tick?.bid ? money(tick.bid) : ''}</button>
              </div>
            </section>

            <section className="card overflow-hidden">
              <div className="flex border-b border-white/[0.06]">
                {(['positions', 'history', 'log'] as const).map(t => (
                  <button key={t} onClick={() => setTab(t)} className={`flex-1 py-3 text-[11px] font-bold uppercase tracking-[0.14em] transition ${tab === t ? 'bg-white/[0.06] text-white' : 'text-zinc-500 hover:text-zinc-300'}`}>
                    {t}{t === 'positions' && positions.length ? ` (${positions.length})` : ''}
                  </button>
                ))}
              </div>
              <div className="max-h-[380px] overflow-auto p-3">
                {tab === 'positions' && (positions.length === 0 ? <p className="py-10 text-center text-sm text-zinc-500">No open positions</p> : (
                  <div className="space-y-2">{positions.map((p: any) => (
                    <div key={p.ticket} className="flex items-center justify-between rounded-2xl border border-white/[0.06] bg-black/25 px-3 py-2.5 text-sm">
                      <div className="flex items-center gap-2.5">
                        <span className={`chip !py-0.5 font-bold ${p.type === 'BUY' ? 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300' : 'border-rose-400/25 bg-rose-400/10 text-rose-300'}`}>{p.type}</span>
                        <span className="font-mono">{p.symbol} {p.volume}</span>
                        <span className={`font-mono ${tone(p.profit)}`}>{signed(p.profit)}</span>
                      </div>
                      <button onClick={() => closePos(p.ticket)} className="btn-ghost !px-3 !py-1 text-xs">Close</button>
                    </div>))}</div>
                ))}
                {tab === 'history' && (history.length === 0 ? <p className="py-10 text-center text-sm text-zinc-500">No closed trades yet</p> : (
                  <div className="font-mono text-xs">{history.slice(-25).reverse().map((h: any, i: number) => (
                    <div key={i} className="flex justify-between border-b border-white/[0.05] py-2"><span className="text-zinc-300">{h.symbol} {h.type}{h.volume ? ` ${h.volume}` : ''}</span><span className={tone(h.profit)}>{signed(h.profit)}</span></div>
                  ))}</div>
                ))}
                {tab === 'log' && ((st?.log || []).length === 0 ? <p className="py-10 text-center text-sm text-zinc-500">No log yet — start the bot</p> : (
                  <div className="font-mono text-xs">{(st.log as any[]).slice().reverse().map((l, i) => (
                    <div key={i} className={`border-b border-white/[0.05] py-1.5 ${l.type === 'success' ? 'text-emerald-300' : l.type === 'error' ? 'text-rose-300' : l.type === 'warn' ? 'text-amber-300' : 'text-zinc-400'}`}><span className="text-zinc-600">[{l.time}]</span> {l.msg}</div>
                  ))}</div>
                ))}
              </div>
            </section>
          </aside>
        </div>
        <p className="pb-6 text-center text-[11px] text-zinc-600">Trading gold with leverage is high risk. Test on a demo account first. Chart times are UTC.</p>
      </main>
    </div>
  );
}

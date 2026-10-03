/** Shapes shared between the bot telemetry (backend/bot_engine.py) and the chart. */
export type Side = 'BUY' | 'SELL';

export type Candle = { time: number; open: number; high: number; low: number; close: number };

/** Executed order → arrow on the candle it happened in. */
export type TradeMarker = { time: number; type: string; lot?: number; price?: number; ticket?: string };

/** PLANNED_SETUP: price level the bot is waiting to enter at (EMA9). */
export type PlannedSetup = { side: Side; price: number };

/** Open position drawn as TP / SL / break-even lines. */
export type ActiveTrade = {
  ticket: string; side: Side; lot: number; entry: number;
  sl: number | null; tp: number | null; beActive: boolean;
};

const isSide = (v: unknown): v is Side => v === 'BUY' || v === 'SELL';
const finite = (v: unknown): v is number => typeof v === 'number' && isFinite(v);

/** backend `planned_setup` ({side, entry_price}) → chart prop. */
export function toPlanned(raw: any): PlannedSetup | null {
  if (!raw || !isSide(raw.side) || !finite(raw.entry_price)) return null;
  return { side: raw.side, price: raw.entry_price };
}

/** backend `active_trade` (bot) or a broker position (`/api/positions`) → chart prop. */
export function toTrade(raw: any): ActiveTrade | null {
  if (!raw) return null;
  const side = raw.side ?? raw.type;
  const entry = raw.entry ?? raw.price_open;
  if (!isSide(side) || !finite(entry)) return null;
  const sl = finite(+raw.sl) && +raw.sl > 0 ? +raw.sl : null;
  const tp = finite(+raw.tp) && +raw.tp > 0 ? +raw.tp : null;
  const be = typeof raw.be_active === 'boolean'
    ? raw.be_active
    : sl !== null && (side === 'BUY' ? sl >= entry : sl <= entry);
  return { ticket: String(raw.ticket), side, lot: Number(raw.lot ?? raw.volume ?? 0), entry, sl, tp, beActive: be };
}

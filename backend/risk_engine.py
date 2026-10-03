"""
Klop Apex — Risk Engine v2.3 (fixed)

v2.2 lot maths was wrong for XAUUSD: 1 lot = 100 oz, so 0.01 lot = 1 oz and a $1 move = $1.
The old code assumed ~$0.01 per point per 0.01 lot and then forced 0.01 lot for small balances,
which on a $10 account risked $2-5 per trade (20-50%) while the log claimed 3%.

Now:
  lot  = floor_to_0.01( balance * risk% / (sl_distance * contract_size) )
  if even 0.01 lot risks more than `max_risk_pct_hard` of balance -> trade is BLOCKED (not forced).
"""
import time
from collections import deque


class RiskEngine:
    def __init__(self):
        self.max_daily_loss_pct = 8.0
        self.min_lot = 0.01
        self.max_lot = 0.20
        self.lot_step = 0.01
        self.contract_size = 100.0     # XAUUSD: 100 oz per 1.00 lot
        self.max_trades_per_hour = 12
        self.max_risk_pct_hard = 10.0  # absolute per-trade ceiling even when min-lot forces more risk
        self.max_margin_use_pct = 50.0 # margin for the new trade must stay under 50% of balance
        self._trades = deque(maxlen=50)

    # ---- sizing
    def calc_lot(self, balance: float, risk_pct: float, sl_dist: float):
        """Returns (lot, risk_money). sl_dist is in PRICE units (e.g. 2.4 = $2.40 on gold)."""
        if balance <= 0 or sl_dist <= 0:
            return 0.0, 0.0
        risk_value = balance * risk_pct / 100.0
        raw = risk_value / (sl_dist * self.contract_size)
        steps = int(raw / self.lot_step + 1e-9)
        lot = max(self.min_lot, min(steps * self.lot_step, self.max_lot))
        lot = round(lot, 2)
        return lot, round(lot * self.contract_size * sl_dist, 2)

    # ---- gate
    def can_trade(self, volume: float, symbol: str, balance: float = None, sl_dist: float = None,
                  price: float = None, leverage: int = 2000, pnl_today: float = 0.0):
        if volume < self.min_lot - 1e-9 or volume > self.max_lot + 1e-9:
            return False, f"Lot {volume} outside {self.min_lot}-{self.max_lot}"
        now = time.time()
        if sum(1 for t in self._trades if now - t < 3600) >= self.max_trades_per_hour:
            return False, f"Hourly limit ({self.max_trades_per_hour}/h) — cooling"
        if balance is not None:
            if balance <= 0:
                return False, "Balance is 0 — connect broker or Sync Balance first"
            if pnl_today <= -balance * self.max_daily_loss_pct / 100.0:
                return False, f"Daily loss limit {self.max_daily_loss_pct}% hit — trading paused until tomorrow"
            if sl_dist:
                risk_money = volume * self.contract_size * sl_dist
                risk_pct = risk_money / balance * 100.0
                if risk_pct > self.max_risk_pct_hard:
                    return False, (f"Account too small: min lot {volume} with SL ${sl_dist:.2f} risks "
                                   f"${risk_money:.2f} = {risk_pct:.0f}% of balance (cap {self.max_risk_pct_hard:.0f}%)")
            if price:
                margin = volume * self.contract_size * price / max(leverage, 1)
                if margin > balance * self.max_margin_use_pct / 100.0:
                    return False, f"Margin ${margin:.2f} > {self.max_margin_use_pct:.0f}% of balance"
        return True, "ok"

    def register_trade(self, volume: float = 0.0):
        self._trades.append(time.time())


risk_engine = RiskEngine()

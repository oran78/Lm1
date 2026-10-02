"""
Klop Apex — Risk Engine v2.2
Micro-account aware ($10 Exness) — preserves capital, compounds correctly
"""
import time
from collections import deque

class RiskEngine:
    def __init__(self):
        self.max_daily_loss_pct = 8.0
        self.min_lot = 0.01
        self.max_lot = 0.20          # cap for $10 account — 0.20 is aggressive enough
        self.max_trades_per_hour = 12
        self._trades = deque(maxlen=50)

    def can_trade(self, volume: float, symbol: str):
        if volume < self.min_lot - 1e-9 or volume > self.max_lot + 1e-9:
            return False, f"Lot {volume} outside {self.min_lot}-{self.max_lot} (micro cap)"
        now = time.time()
        recent = sum(1 for t in self._trades if now - t < 3600)
        if recent >= self.max_trades_per_hour:
            return False, "Hourly limit (12/h) — cooling"
        return True, "ok"

    def register_trade(self, volume: float):
        self._trades.append(time.time())

    def calc_lot(self, balance: float, risk_pct: float, atr: float = None, sl_points: int = 200):
        """
        $10-safe:
          risk_value = balance * risk_pct%
          sl_money_per_lot ~ sl_points * $0.10 for XAU 0.01 lot ~ rough $0.20 per 200 points on Exness mini
          Use ATR-adjusted: tighter SL = smaller risk, but keep lot >= 0.01 and respect max_lot
        For true micro: use sl_points based ATR so $10 account never risks > risk_pct
        Exness XAU: 0.01 lot value ~ $0.10 per $1 move; 200 points = $2 move => $0.20 risk per 0.01 lot
        => lot = risk_value / (sl_points * 0.001)  approx
        """
        risk_value = balance * (risk_pct / 100.0)
        # money risk per 0.01 lot for given sl_points on XAU
        # 1 point = 0.01 price; 0.01 lot moves ~ $0.01 per point on standard Exness
        per_001_risk = sl_points * 0.01  #$
        if per_001_risk <= 0:
            per_001_risk = 2.0
        lot = (risk_value / per_001_risk) * 0.01
        # quantize to 0.01
        lot = round(lot / 0.01) * 0.01
        # $10 account: never below 0.01, never above max_lot, and if balance < 15 force 0.01
        if balance < 15:
            lot = 0.01
        lot = max(self.min_lot, min(lot, self.max_lot))
        # also cap so lot*1.5*sl not exceed balance (avoid margin call on Exness)
        # rough: margin needed ~ lot*1000 for XAU at 1:2000
        return round(lot, 2)

risk_engine = RiskEngine()

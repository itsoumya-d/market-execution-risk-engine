from dataclasses import dataclass, field
from enum import Enum
import time
from typing import List, Optional, Tuple, Dict


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(Enum):
    NEW = "NEW"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass
class Order:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: float
    quantity: float
    filled_qty: float = 0.0
    status: OrderStatus = OrderStatus.NEW
    timestamp: float = field(default_factory=time.time)

    @property
    def remaining_qty(self) -> float:
        return self.quantity - self.filled_qty

    @property
    def notional(self) -> float:
        return self.price * self.quantity


@dataclass
class Trade:
    trade_id: str
    symbol: str
    price: float
    quantity: float
    buy_order_id: str
    sell_order_id: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class RiskLimits:
    max_order_qty: float = 1000.0
    max_order_notional: float = 100_000.0
    max_position_notional: float = 250_000.0
    price_collar_pct: float = 0.05  # 5% max deviation from reference price


class PreTradeRiskValidator:
    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def validate(
        self, order: Order, reference_price: float, current_notional: float
    ) -> Tuple[bool, str]:
        if order.quantity <= 0:
            return False, "Order quantity must be positive"

        if order.quantity > self.limits.max_order_qty:
            return False, f"Order quantity {order.quantity} exceeds max limit {self.limits.max_order_qty}"

        notional = order.notional
        if notional > self.limits.max_order_notional:
            return False, f"Order notional {notional:.2f} exceeds max limit {self.limits.max_order_notional:.2f}"

        if current_notional + notional > self.limits.max_position_notional:
            return (
                False,
                f"Projected portfolio notional {current_notional + notional:.2f} exceeds limit {self.limits.max_position_notional:.2f}",
            )

        if reference_price > 0 and order.order_type == OrderType.LIMIT:
            diff = abs(order.price - reference_price) / reference_price
            if diff > self.limits.price_collar_pct:
                return (
                    False,
                    f"Price collar breach: price {order.price} deviates {diff*100:.1f}% from reference {reference_price}",
                )

        return True, "Passed"


class OrderBook:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: List[Order] = []  # descending by price, ascending by time
        self.asks: List[Order] = []  # ascending by price, ascending by time
        self.orders: Dict[str, Order] = {}
        self._trade_seq = 0

    def add_order(self, order: Order) -> List[Trade]:
        self.orders[order.order_id] = order
        trades: List[Trade] = []

        if order.side == OrderSide.BUY:
            while self.asks and order.remaining_qty > 0:
                best_ask = self.asks[0]
                if order.price >= best_ask.price:
                    match_qty = min(order.remaining_qty, best_ask.remaining_qty)
                    match_price = best_ask.price
                    self._trade_seq += 1
                    trades.append(
                        Trade(
                            trade_id=f"T-{self._trade_seq}",
                            symbol=self.symbol,
                            price=match_price,
                            quantity=match_qty,
                            buy_order_id=order.order_id,
                            sell_order_id=best_ask.order_id,
                        )
                    )
                    order.filled_qty += match_qty
                    best_ask.filled_qty += match_qty
                    if best_ask.remaining_qty == 0:
                        best_ask.status = OrderStatus.FILLED
                        self.asks.pop(0)
                    else:
                        best_ask.status = OrderStatus.PARTIALLY_FILLED
                else:
                    break

            if order.remaining_qty > 0:
                order.status = (
                    OrderStatus.PARTIALLY_FILLED
                    if order.filled_qty > 0
                    else OrderStatus.NEW
                )
                self.bids.append(order)
                self.bids.sort(key=lambda o: (-o.price, o.timestamp))
            else:
                order.status = OrderStatus.FILLED

        elif order.side == OrderSide.SELL:
            while self.bids and order.remaining_qty > 0:
                best_bid = self.bids[0]
                if order.price <= best_bid.price:
                    match_qty = min(order.remaining_qty, best_bid.remaining_qty)
                    match_price = best_bid.price
                    self._trade_seq += 1
                    trades.append(
                        Trade(
                            trade_id=f"T-{self._trade_seq}",
                            symbol=self.symbol,
                            price=match_price,
                            quantity=match_qty,
                            buy_order_id=best_bid.order_id,
                            sell_order_id=order.order_id,
                        )
                    )
                    order.filled_qty += match_qty
                    best_bid.filled_qty += match_qty
                    if best_bid.remaining_qty == 0:
                        best_bid.status = OrderStatus.FILLED
                        self.bids.pop(0)
                    else:
                        best_bid.status = OrderStatus.PARTIALLY_FILLED
                else:
                    break

            if order.remaining_qty > 0:
                order.status = (
                    OrderStatus.PARTIALLY_FILLED
                    if order.filled_qty > 0
                    else OrderStatus.NEW
                )
                self.asks.append(order)
                self.asks.sort(key=lambda o: (o.price, o.timestamp))
            else:
                order.status = OrderStatus.FILLED

        return trades

    def cancel_order(self, order_id: str) -> bool:
        if order_id not in self.orders:
            return False
        order = self.orders[order_id]
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELLED):
            return False
        order.status = OrderStatus.CANCELLED
        self.bids = [o for o in self.bids if o.order_id != order_id]
        self.asks = [o for o in self.asks if o.order_id != order_id]
        return True


class ExecutionEngine:
    def __init__(self, limits: Optional[RiskLimits] = None):
        self.limits = limits or RiskLimits()
        self.validator = PreTradeRiskValidator(self.limits)
        self.books: Dict[str, OrderBook] = {}
        self.portfolio_notional = 0.0

    def submit_order(
        self, order: Order, reference_price: float = 0.0
    ) -> Tuple[Optional[List[Trade]], Optional[str]]:
        passed, reason = self.validator.validate(
            order, reference_price, self.portfolio_notional
        )
        if not passed:
            order.status = OrderStatus.REJECTED
            return None, reason

        if order.symbol not in self.books:
            self.books[order.symbol] = OrderBook(order.symbol)

        trades = self.books[order.symbol].add_order(order)
        self.portfolio_notional += order.notional
        return trades, None

import pytest
from market_risk.engine import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    RiskLimits,
    PreTradeRiskValidator,
    OrderBook,
    ExecutionEngine,
)


def test_risk_order_size_limit():
    limits = RiskLimits(max_order_qty=500.0)
    validator = PreTradeRiskValidator(limits)

    order_ok = Order("O1", "BHP", OrderSide.BUY, OrderType.LIMIT, 45.0, 400.0)
    passed, reason = validator.validate(order_ok, reference_price=45.0, current_notional=0.0)
    assert passed
    assert reason == "Passed"

    order_breach = Order("O2", "BHP", OrderSide.BUY, OrderType.LIMIT, 45.0, 600.0)
    passed, reason = validator.validate(order_breach, reference_price=45.0, current_notional=0.0)
    assert not passed
    assert "exceeds max limit" in reason


def test_risk_price_collar():
    limits = RiskLimits(price_collar_pct=0.05)  # 5% collar
    validator = PreTradeRiskValidator(limits)

    # Reference = 100.0. Order at 104.0 (4% diff) -> passes
    order_in = Order("O3", "CBA", OrderSide.BUY, OrderType.LIMIT, 104.0, 10.0)
    passed, _ = validator.validate(order_in, reference_price=100.0, current_notional=0.0)
    assert passed

    # Order at 108.0 (8% diff) -> rejected
    order_out = Order("O4", "CBA", OrderSide.BUY, OrderType.LIMIT, 108.0, 10.0)
    passed, reason = validator.validate(order_out, reference_price=100.0, current_notional=0.0)
    assert not passed
    assert "Price collar breach" in reason


def test_order_book_crossing_execution():
    book = OrderBook("RIO")

    # Place resting sell order: 100 shares @ $120.0
    sell_order = Order("S1", "RIO", OrderSide.SELL, OrderType.LIMIT, 120.0, 100.0)
    trades = book.add_order(sell_order)
    assert len(trades) == 0
    assert sell_order.status == OrderStatus.NEW

    # Incoming crossing buy order: 60 shares @ $120.5
    buy_order = Order("B1", "RIO", OrderSide.BUY, OrderType.LIMIT, 120.5, 60.0)
    trades = book.add_order(buy_order)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.price == 120.0  # Executed at resting ask price
    assert trade.quantity == 60.0
    assert buy_order.status == OrderStatus.FILLED
    assert sell_order.status == OrderStatus.PARTIALLY_FILLED
    assert sell_order.remaining_qty == 40.0


def test_order_cancellation():
    book = OrderBook("ANZ")
    order = Order("O5", "ANZ", OrderSide.BUY, OrderType.LIMIT, 28.0, 100.0)
    book.add_order(order)
    assert len(book.bids) == 1

    cancelled = book.cancel_order("O5")
    assert cancelled
    assert len(book.bids) == 0
    assert order.status == OrderStatus.CANCELLED


def test_execution_engine_end_to_end():
    engine = ExecutionEngine(limits=RiskLimits(max_order_notional=50_000.0))

    # Order 1: 100 shares @ $10.0 ($1,000 notional) -> Accepted
    o1 = Order("E1", "MQG", OrderSide.SELL, OrderType.LIMIT, 10.0, 100.0)
    trades, err = engine.submit_order(o1, reference_price=10.0)
    assert err is None
    assert len(trades) == 0

    # Order 2: 100 shares @ $10.0 -> Matches
    o2 = Order("E2", "MQG", OrderSide.BUY, OrderType.LIMIT, 10.0, 100.0)
    trades, err = engine.submit_order(o2, reference_price=10.0)
    assert err is None
    assert len(trades) == 1
    assert trades[0].quantity == 100.0

# Market Execution Risk Engine

High-throughput pre-trade risk validation and execution engine in Python. Enforces deterministic pre-trade risk limits (fat-finger price collars, order size limits, notional exposure caps, and rate limits) before orders route to market matching venues.

## Features

- **Pre-Trade Risk Checks**: Price collar verification, maximum order quantity, and portfolio-level notional exposure tracking.
- **In-Memory Order Matching**: Deterministic limit order book with price-time priority (FIFO).
- **Audit & Metrics**: Real-time position tracking, trade execution logs, and risk breach rejections.
- **Pure Python**: Zero third-party runtime dependencies, fully tested with `pytest`.

## Usage

```bash
pip install -e .
pytest
```

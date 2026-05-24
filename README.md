# Yield Pilot

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](#testing)
[![DeFi](https://img.shields.io/badge/DeFi-Yield%20Optimizer-purple.svg)]()

**Multi-chain yield optimizer with automated rebalancing engine.**

Yield Pilot scans yield opportunities across Aave, Compound, and Yearn on Ethereum, Arbitrum, and Base. It uses Welford's online algorithm for real-time yield statistics, computes risk-adjusted scores (Sharpe-like ratios), and triggers auto-rebalancing when thresholds are met.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      YIELD PILOT                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   │
│  │ YieldScanner │──▶│YieldOptimizer│──▶│  Rebalancer  │   │
│  │  (Protocol   │   │  (Welford's  │   │  (Threshold  │   │
│  │   Scanner)   │   │   Algorithm) │   │   Trigger)   │   │
│  └──────────────┘   └──────────────┘   └──────────────┘   │
│         │                  │                    │           │
│         ▼                  ▼                    ▼           │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   │
│  │   RiskEngine │   │  Portfolio   │   │ GasOptimizer │   │
│  │  (Composite  │   │  (Multi-Chain│   │  (Batch TX   │   │
│  │   Scoring)   │   │   Tracking)  │   │   Savings)   │   │
│  └──────────────┘   └──────────────┘   └──────────────┘   │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  Supported: Aave · Compound · Yearn                        │
│  Chains:    Ethereum · Arbitrum · Base                      │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# Clone
git clone https://github.com/yourorg/yield-pilot.git
cd yield-pilot

# Install
pip install -e ".[dev]"

# Run demo
python -m src.main

# Run tests
python -m pytest tests/ -v

# Scan opportunities
python -m src.main --scan
```

## Modules

### `src/yield_pilot.py` — Core Engine

- **`WelfordStats`** — Online algorithm for mean, variance, z-score without storing all values
- **`YieldOptimizer`** — Risk-adjusted scoring with `score = (yield - benchmark) / volatility`
- **`YieldScanner`** — Scans Aave, Compound, Yearn across 3 chains
- **`should_rebalance()`** — Threshold-based rebalance trigger

### `src/risk_engine.py` — Risk Assessment

- **`RiskEngine`** — Composite risk scoring (TVL, audit, age, incidents, utilization)
- **`ImpermanentLossCalculator`** — IL formula for constant-product AMMs + break-even APY
- **`SmartContractRiskHeuristics`** — Signal-based risk estimation

### `src/portfolio.py` — Portfolio Management

- **`Portfolio`** — Position tracking with realized/unrealized PnL split
- **`GasOptimizer`** — Transaction batching for gas savings
- **`Position`** — Full lifecycle tracking (entry, yield, gas, exit)

### `demo/index.html` — Interactive Dashboard

- Real-time yield dashboard with animated charts
- Portfolio allocation donut chart
- Historical yield line chart with moving averages
- Risk heatmap (protocols × chains)
- Simulated live metrics

## API Reference

### YieldOptimizer

```python
from src.yield_pilot import YieldOptimizer, YieldScanner

optimizer = YieldOptimizer(
    benchmark_rate=0.04,       # Risk-free benchmark (4%)
    rebalance_threshold=0.02,  # Min APY improvement to rebalance
    min_tvl=1_000_000,         # Minimum TVL filter
)

# Scan and score
scanner = YieldScanner()
opportunities = scanner.scan()
for opp in opportunities:
    optimizer.record_yield(opp)

scored = optimizer.find_best_opportunities(opportunities, top_n=5)

# Check rebalance
should = optimizer.should_rebalance(current_pos, candidate_pos)
```

### RiskEngine

```python
from src.risk_engine import RiskEngine, ProtocolProfile, AuditStatus

engine = RiskEngine()
profile = ProtocolProfile(
    protocol=Protocol.AAVE,
    chain=Chain.ETHEREUM,
    tvl_current=12_000_000_000,
    tvl_peak=18_000_000_000,
    age_days=1500,
    audit_status=AuditStatus.FORMALLY_VERIFIED,
    num_audits=8,
    has_bug_bounty=True,
    has_insurance=True,
    incident_count=0,
    total_borrowed=4_000_000_000,
)
risk = engine.compute_composite_risk(profile)  # 0.0 (safe) to 1.0 (risky)
```

### ImpermanentLossCalculator

```python
from src.risk_engine import ImpermanentLossCalculator

il = ImpermanentLossCalculator.calculate_il(2.0)  # -0.0572 (5.72% IL for 2x price move)
breakeven = ImpermanentLossCalculator.breakeven_apy(2.0, 365)  # APY needed to offset IL
```

### Portfolio

```python
from src.portfolio import Portfolio, GasOptimizer

portfolio = Portfolio("my-vault")
pos = portfolio.open_position(
    Protocol.AAVE, Chain.ETHEREUM, "USDC",
    amount=50000, price=1.0, apy=0.045, gas_cost=12.50,
)

print(portfolio.total_value)
print(portfolio.chain_allocation)
```

## Testing

```bash
python -m pytest tests/ -v
```

Expected output: all tests passing with coverage of:
- Welford's algorithm (mean, variance, z-score, sample variance)
- Yield optimizer (scoring, filtering, rebalance logic)
- Risk engine (TVL, audit, incidents, composite)
- Impermanent loss (IL calculation, symmetry, break-even)
- Portfolio (positions, PnL, allocation, gas)

## Risk Disclaimer

This software is for **educational and research purposes only**. It does not constitute financial advice. DeFi protocols carry inherent risks including but not limited to:

- Smart contract vulnerabilities
- Impermanent loss
- Protocol insolvency
- Oracle manipulation
- Regulatory changes

Always do your own research. Never invest more than you can afford to lose.

## License

MIT

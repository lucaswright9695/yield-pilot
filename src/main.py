#!/usr/bin/env python3
"""
Yield Pilot — CLI entry point with demo mode.

Usage:
    python -m src.main                  # Run interactive demo
    python -m src.main --scan           # Scan current opportunities
    python -m src.main --portfolio      # Show portfolio summary
    python -m src.main --risk <proto>   # Assess protocol risk
"""

from __future__ import annotations

import argparse
import random
import sys
import time

from .yield_pilot import (
    Chain,
    Protocol,
    WelfordStats,
    YieldOptimizer,
    YieldScanner,
)
from .risk_engine import (
    AuditStatus,
    ImpermanentLossCalculator,
    ProtocolProfile,
    RiskEngine,
)
from .portfolio import GasOptimizer, Portfolio


def print_header(title: str) -> None:
    """Print a formatted section header."""
    width = 60
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def run_demo() -> None:
    """Run the interactive demo showcasing all features."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║                    YIELD PILOT v0.1.0                       ║
║           Multi-Chain Yield Optimizer & Rebalancer          ║
╚══════════════════════════════════════════════════════════════╝
    """)

    # --- 1. Yield Scanning ---
    print_header("1. YIELD SCANNING — Live Opportunities")
    scanner = YieldScanner()
    optimizer = YieldOptimizer(benchmark_rate=0.04, rebalance_threshold=0.02)

    opportunities = scanner.scan()
    for opp in opportunities:
        optimizer.record_yield(opp)

    # Score opportunities
    scored = optimizer.find_best_opportunities(opportunities, top_n=8)

    print(f"\n  {'Protocol':<12} {'Chain':<12} {'Asset':<8} {'APY':>8} {'TVL':>14} {'Score':>8}")
    print("  " + "-" * 66)
    for opp, score in scored:
        tvl_str = f"${opp.tvl / 1e6:.1f}M" if opp.tvl >= 1e6 else f"${opp.tvl / 1e3:.0f}K"
        print(f"  {opp.protocol.value:<12} {opp.chain.value:<12} {opp.asset:<8} {opp.apy * 100:>7.2f}% {tvl_str:>14} {score:>8.3f}")

    # --- 2. Welford Statistics ---
    print_header("2. WELFORD ONLINE STATISTICS — Yield Tracking")
    stats = WelfordStats()
    simulated_ys = [0.038, 0.041, 0.039, 0.043, 0.037, 0.045, 0.042, 0.040, 0.044, 0.036]
    for y in simulated_ys:
        stats.update(y)

    print(f"\n  Observations:  {stats.n}")
    print(f"  Mean APY:      {stats.mean * 100:.4f}%")
    print(f"  Std Deviation: {stats.std_dev * 100:.4f}%")
    print(f"  Variance:      {stats.variance * 10000:.4f} (×10⁴)")
    print(f"  Z-score(4.5%): {stats.z_score(0.045):>+.3f}")

    # --- 3. Risk Assessment ---
    print_header("3. RISK ASSESSMENT — Protocol Risk Scoring")
    risk_engine = RiskEngine()

    profiles = [
        ProtocolProfile(
            protocol=Protocol.AAVE, chain=Chain.ETHEREUM,
            tvl_current=12_000_000_000, tvl_peak=18_000_000_000,
            age_days=1500, audit_status=AuditStatus.FORMALLY_VERIFIED,
            num_audits=8, has_bug_bounty=True, has_insurance=True,
            incident_count=0, total_borrowed=4_000_000_000,
        ),
        ProtocolProfile(
            protocol=Protocol.COMPOUND, chain=Chain.ETHEREUM,
            tvl_current=3_500_000_000, tvl_peak=5_000_000_000,
            age_days=1800, audit_status=AuditStatus.MULTI_AUDIT,
            num_audits=5, has_bug_bounty=True, has_insurance=True,
            incident_count=1, total_borrowed=1_200_000_000,
        ),
        ProtocolProfile(
            protocol=Protocol.YEARN, chain=Chain.ETHEREUM,
            tvl_current=800_000_000, tvl_peak=1_500_000_000,
            age_days=1200, audit_status=AuditStatus.MULTI_AUDIT,
            num_audits=6, has_bug_bounty=True, has_insurance=False,
            incident_count=0, total_borrowed=0,
        ),
        ProtocolProfile(
            protocol=Protocol.AAVE, chain=Chain.ARBITRUM,
            tvl_current=450_000_000, tvl_peak=600_000_000,
            age_days=600, audit_status=AuditStatus.MULTI_AUDIT,
            num_audits=4, has_bug_bounty=True, has_insurance=True,
            incident_count=0, total_borrowed=120_000_000,
        ),
    ]

    print(f"\n  {'Protocol':<12} {'Chain':<12} {'Risk Score':>10} {'TVL Risk':>10} {'Audit':>10} {'Age':>8}")
    print("  " + "-" * 66)
    for p in profiles:
        composite = risk_engine.compute_composite_risk(p)
        tvl_r = risk_engine.compute_tvl_risk(p)
        audit_r = risk_engine.compute_audit_risk(p)
        age_r = risk_engine.compute_age_risk(p)
        print(f"  {p.protocol.value:<12} {p.chain.value:<12} {composite:>10.3f} {tvl_r:>10.3f} {audit_r:>10.3f} {age_r:>8.3f}")

    # --- 4. Impermanent Loss ---
    print_header("4. IMPERMANENT LOSS — LP Risk Analysis")
    il_calc = ImpermanentLossCalculator()

    price_changes = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 5.0]
    print(f"\n  {'Price Ratio':>12} {'IL %':>10} {'Break-even APY':>16}")
    print("  " + "-" * 42)
    for r in price_changes:
        il = il_calc.calculate_il(r)
        be = il_calc.breakeven_apy(r)
        print(f"  {r:>12.2f}x {il * 100:>9.2f}% {be * 100:>15.2f}%")

    # --- 5. Portfolio Management ---
    print_header("5. PORTFOLIO — Position Tracking & PnL")
    portfolio = Portfolio("demo-user")

    # Open sample positions
    positions_data = [
        (Protocol.AAVE, Chain.ETHEREUM, "USDC", 50000, 1.0, 0.038, 12.50),
        (Protocol.YEARN, Chain.ETHEREUM, "ETH", 10, 2500, 0.032, 18.00),
        (Protocol.COMPOUND, Chain.ETHEREUM, "DAI", 30000, 1.0, 0.039, 14.00),
        (Protocol.AAVE, Chain.ARBITRUM, "USDC", 20000, 1.0, 0.045, 0.45),
        (Protocol.YEARN, Chain.ARBITRUM, "ETH", 5, 2500, 0.038, 0.55),
    ]

    for proto, chain, asset, amt, price, apy, gas in positions_data:
        pos = portfolio.open_position(proto, chain, asset, amt, price, apy, gas)

    # Simulate some price changes
    time.sleep(0.01)  # Small delay for realistic timestamps
    for pos in portfolio.active_positions:
        if pos.asset == "ETH":
            pos.current_price = pos.entry_price * random.uniform(1.02, 1.15)
        else:
            pos.current_price = pos.entry_price * random.uniform(0.998, 1.005)
        pos.current_apy = pos.entry_apy * random.uniform(0.95, 1.08)

    print(f"\n  Active Positions: {len(portfolio.active_positions)}")
    print(f"  Total Value:      ${portfolio.total_value:,.2f}")
    print(f"  Unrealized PnL:   ${portfolio.total_unrealized_pnl:+,.2f}")
    print(f"  Yield Earned:     ${portfolio.total_yield_earned:,.2f}")
    print(f"  Gas Spent:        ${portfolio.total_gas_spent:,.2f}")

    print(f"\n  {'ID':<14} {'Protocol':<10} {'Chain':<10} {'Asset':<6} {'Value':>12} {'PnL':>10} {'APY':>8}")
    print("  " + "-" * 74)
    for pos in portfolio.active_positions:
        print(f"  {pos.id:<14} {pos.protocol.value:<10} {pos.chain.value:<10} {pos.asset:<6} "
              f"${pos.current_value:>10,.2f} ${pos.unrealized_pnl:>+9,.2f} {pos.current_apy * 100:>7.2f}%")

    print(f"\n  Chain Allocation:")
    for chain, pct in portfolio.chain_allocation.items():
        bar = "█" * int(pct * 30)
        print(f"    {chain:<12} {pct * 100:>5.1f}% {bar}")

    # --- 6. Gas Optimization ---
    print_header("6. GAS OPTIMIZATION — Batch Savings")
    gas_opt = GasOptimizer()
    savings = gas_opt.compare_gas_costs([Chain.ETHEREUM, Chain.ARBITRUM, Chain.BASE], 5)

    print(f"\n  Cost for 5 transactions:")
    for chain, cost in savings.items():
        print(f"    {chain:<12} ${cost:>8.2f}")

    print(f"\n  L2 Savings vs Ethereum:")
    eth_cost = savings["ethereum"]
    for chain, cost in savings.items():
        if chain != "ethereum":
            saving_pct = (1 - cost / eth_cost) * 100
            print(f"    {chain:<12} {saving_pct:>5.1f}% cheaper")

    print("\n" + "=" * 60)
    print("  Demo complete. Run with --scan for live scan,")
    print("  --portfolio for portfolio view.")
    print("=" * 60 + "\n")


def run_scan() -> None:
    """Run a yield scan and display results."""
    scanner = YieldScanner()
    optimizer = YieldOptimizer()

    opportunities = scanner.scan()
    for opp in opportunities:
        optimizer.record_yield(opp)

    scored = optimizer.find_best_opportunities(opportunities, top_n=10)

    print_header("YIELD SCAN — Top Opportunities")
    print(f"\n  {'#':<4} {'Protocol':<12} {'Chain':<12} {'Asset':<8} {'APY':>8} {'TVL':>14} {'Score':>8}")
    print("  " + "-" * 68)
    for i, (opp, score) in enumerate(scored, 1):
        tvl_str = f"${opp.tvl / 1e6:.1f}M"
        print(f"  {i:<4} {opp.protocol.value:<12} {opp.chain.value:<12} {opp.asset:<8} {opp.apy * 100:>7.2f}% {tvl_str:>14} {score:>8.3f}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Yield Pilot — Multi-chain yield optimizer",
    )
    parser.add_argument("--scan", action="store_true", help="Scan current yield opportunities")
    parser.add_argument("--portfolio", action="store_true", help="Show portfolio summary")
    parser.add_argument("--risk", type=str, help="Assess risk for a protocol")
    parser.add_argument("--demo", action="store_true", help="Run full interactive demo")

    args = parser.parse_args()

    if args.scan:
        run_scan()
    elif args.demo or (not args.portfolio and not args.risk):
        run_demo()
    else:
        run_demo()


if __name__ == "__main__":
    main()

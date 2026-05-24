"""
Tests for Yield Pilot — yield optimizer, risk engine, and portfolio.

Run with: python -m pytest tests/ -v
"""

import math
import time
import pytest

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.yield_pilot import (
    Chain,
    Protocol,
    WelfordStats,
    YieldOptimizer,
    YieldOpportunity,
    YieldScanner,
)
from src.risk_engine import (
    AuditStatus,
    ImpermanentLossCalculator,
    ProtocolProfile,
    RiskEngine,
    SmartContractRiskHeuristics,
)
from src.portfolio import (
    GasOptimizer,
    Portfolio,
    PositionStatus,
)


# ── Welford Stats Tests ──────────────────────────────────────────

class TestWelfordStats:
    """Tests for Welford's online algorithm."""

    def test_single_observation(self):
        """Single observation should have mean equal to value, zero variance."""
        stats = WelfordStats()
        stats.update(5.0)
        assert stats.n == 1
        assert stats.mean == 5.0
        assert stats.variance == 0.0
        assert stats.std_dev == 0.0

    def test_multiple_observations_mean(self):
        """Mean should converge to correct value."""
        stats = WelfordStats()
        values = [2.0, 4.0, 6.0, 8.0, 10.0]
        for v in values:
            stats.update(v)
        assert stats.n == 5
        assert stats.mean == pytest.approx(6.0)

    def test_multiple_observations_variance(self):
        """Variance should match manual calculation."""
        stats = WelfordStats()
        values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        for v in values:
            stats.update(v)

        expected_mean = sum(values) / len(values)
        expected_var = sum((v - expected_mean) ** 2 for v in values) / len(values)

        assert stats.mean == pytest.approx(expected_mean)
        assert stats.variance == pytest.approx(expected_var)

    def test_z_score(self):
        """Z-score should correctly standardize values."""
        stats = WelfordStats()
        values = [10.0, 10.0, 10.0, 10.0, 10.0]
        for v in values:
            stats.update(v)
        # All same values → std_dev = 0 → z_score = 0
        assert stats.z_score(10.0) == 0.0

        stats2 = WelfordStats()
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            stats2.update(v)
        # z-score of the mean should be 0
        assert stats2.z_score(3.0) == pytest.approx(0.0)
        # z-score of 5 should be positive
        assert stats2.z_score(5.0) > 0
        # z-score of 1 should be negative
        assert stats2.z_score(1.0) < 0

    def test_sample_variance(self):
        """Sample variance should use Bessel's correction."""
        stats = WelfordStats()
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        for v in values:
            stats.update(v)

        expected_mean = 3.0
        expected_sample_var = sum((v - expected_mean) ** 2 for v in values) / (len(values) - 1)

        assert stats.sample_variance == pytest.approx(expected_sample_var)
        # Sample variance > population variance for n > 1
        assert stats.sample_variance > stats.variance


# ── Yield Optimizer Tests ────────────────────────────────────────

class TestYieldOptimizer:
    """Tests for the yield optimizer engine."""

    def _make_opportunity(self, apy=0.05, tvl=10_000_000, protocol=Protocol.AAVE, chain=Chain.ETHEREUM, asset="USDC"):
        return YieldOpportunity(
            protocol=protocol,
            chain=chain,
            asset=asset,
            apy=apy,
            tvl=tvl,
        )

    def test_risk_adjusted_score_positive(self):
        """Opportunity above benchmark should have positive score."""
        opt = YieldOptimizer(benchmark_rate=0.04)
        opp = self._make_opportunity(apy=0.06)
        score = opt.compute_risk_adjusted_score(opp)
        assert score > 0

    def test_risk_adjusted_score_negative(self):
        """Opportunity below benchmark should have negative score."""
        opt = YieldOptimizer(benchmark_rate=0.04)
        opp = self._make_opportunity(apy=0.02)
        score = opt.compute_risk_adjusted_score(opp)
        assert score < 0

    def test_risk_adjusted_score_with_risk_penalty(self):
        """Higher risk score should reduce the adjusted score."""
        opt = YieldOptimizer(benchmark_rate=0.04)
        opp = self._make_opportunity(apy=0.06)
        score_low_risk = opt.compute_risk_adjusted_score(opp, risk_score=0.1)
        score_high_risk = opt.compute_risk_adjusted_score(opp, risk_score=0.9)
        assert score_low_risk > score_high_risk

    def test_find_best_opportunities_filters_tvl(self):
        """Opportunities below min_tvl should be filtered out."""
        opt = YieldOptimizer(min_tvl=5_000_000)
        opps = [
            self._make_opportunity(apy=0.10, tvl=1_000_000),   # Below threshold
            self._make_opportunity(apy=0.05, tvl=10_000_000),  # Above threshold
        ]
        scored = opt.find_best_opportunities(opps)
        # Only the high-TVL one should appear
        assert len(scored) == 1
        assert scored[0][0].tvl >= 5_000_000

    def test_should_rebalance_positive(self):
        """Should rebalance when candidate is significantly better."""
        opt = YieldOptimizer(rebalance_threshold=0.02)
        current = self._make_opportunity(apy=0.04)
        candidate = self._make_opportunity(apy=0.07)
        assert opt.should_rebalance(current, candidate) is True

    def test_should_rebalance_negative(self):
        """Should not rebalance when improvement is below threshold."""
        opt = YieldOptimizer(rebalance_threshold=0.05)
        current = self._make_opportunity(apy=0.04)
        candidate = self._make_opportunity(apy=0.05)  # Only 1% improvement
        assert opt.should_rebalance(current, candidate) is False

    def test_record_yield_updates_stats(self):
        """Recording yield should update internal statistics."""
        opt = YieldOptimizer()
        opp = self._make_opportunity(apy=0.05)
        opt.record_yield(opp)
        stats = opt.get_yield_stats(opp.identifier)
        assert stats is not None
        assert stats.n == 1
        assert stats.mean == pytest.approx(0.05)

    def test_scanner_returns_opportunities(self):
        """Scanner should return a non-empty list of opportunities."""
        scanner = YieldScanner()
        opps = scanner.scan()
        assert len(opps) > 0
        assert all(isinstance(o, YieldOpportunity) for o in opps)
        assert all(o.apy > 0 for o in opps)


# ── Risk Engine Tests ────────────────────────────────────────────

class TestRiskEngine:
    """Tests for the risk assessment engine."""

    def _make_profile(self, **kwargs):
        defaults = dict(
            protocol=Protocol.AAVE,
            chain=Chain.ETHEREUM,
            tvl_current=1_000_000_000,
            tvl_peak=1_500_000_000,
            age_days=1000,
            audit_status=AuditStatus.MULTI_AUDIT,
            num_audits=3,
            has_bug_bounty=True,
            has_insurance=True,
            incident_count=0,
            total_borrowed=300_000_000,
        )
        defaults.update(kwargs)
        return ProtocolProfile(**defaults)

    def test_high_tvl_lower_risk(self):
        """Higher TVL should produce lower risk score."""
        engine = RiskEngine()
        high_tvl = self._make_profile(tvl_current=10_000_000_000)
        low_tvl = self._make_profile(tvl_current=1_000_000)
        assert engine.compute_tvl_risk(high_tvl) < engine.compute_tvl_risk(low_tvl)

    def test_audit_status_affects_risk(self):
        """More audits should reduce risk."""
        engine = RiskEngine()
        unaudited = self._make_profile(audit_status=AuditStatus.UNAUDITED)
        verified = self._make_profile(audit_status=AuditStatus.FORMALLY_VERIFIED)
        assert engine.compute_audit_risk(unaudited) > engine.compute_audit_risk(verified)

    def test_incidents_increase_risk(self):
        """Past incidents should increase risk score."""
        engine = RiskEngine()
        clean = self._make_profile(incident_count=0)
        hacked = self._make_profile(incident_count=3)
        assert engine.compute_incident_risk(clean) < engine.compute_incident_risk(hacked)

    def test_composite_risk_bounded(self):
        """Composite risk should be between 0 and 1."""
        engine = RiskEngine()
        profile = self._make_profile()
        risk = engine.compute_composite_risk(profile)
        assert 0.0 <= risk <= 1.0


# ── Impermanent Loss Tests ──────────────────────────────────────

class TestImpermanentLoss:
    """Tests for impermanent loss calculations."""

    def test_no_price_change(self):
        """No price change should result in zero IL."""
        il = ImpermanentLossCalculator.calculate_il(1.0)
        assert il == pytest.approx(0.0)

    def test_price_doubles(self):
        """Price doubling should produce ~5.7% IL."""
        il = ImpermanentLossCalculator.calculate_il(2.0)
        # Expected: 2*sqrt(2)/(1+2) - 1 ≈ -0.0572
        assert il == pytest.approx(-0.0572, abs=0.001)

    def test_price_quadruples(self):
        """Price 4x should produce ~25% IL (no — actually ~20%)."""
        il = ImpermanentLossCalculator.calculate_il(4.0)
        # 2*sqrt(4)/(1+4) - 1 = 4/5 - 1 = -0.2
        assert il == pytest.approx(-0.2, abs=0.001)

    def test_il_is_symmetric(self):
        """IL for price going up 2x should equal IL for price going down 0.5x."""
        il_up = ImpermanentLossCalculator.calculate_il(2.0)
        il_down = ImpermanentLossCalculator.calculate_il(0.5)
        assert il_up == pytest.approx(il_down)

    def test_breakeven_apy(self):
        """Break-even APY should cover the IL."""
        il = ImpermanentLossCalculator.calculate_il(2.0)
        be_apy = ImpermanentLossCalculator.breakeven_apy(2.0, holding_period_days=365)
        # Break-even APY should equal |IL| when period = 1 year
        assert be_apy == pytest.approx(abs(il), abs=0.001)


# ── Portfolio Tests ──────────────────────────────────────────────

class TestPortfolio:
    """Tests for portfolio management."""

    def test_open_position(self):
        """Opening a position should create an active position."""
        portfolio = Portfolio("test")
        pos = portfolio.open_position(
            Protocol.AAVE, Chain.ETHEREUM, "USDC",
            amount=10000, price=1.0, apy=0.05, gas_cost=10.0,
        )
        assert len(portfolio.active_positions) == 1
        assert pos.amount == 10000
        assert pos.entry_apy == 0.05

    def test_close_position_realized_pnl(self):
        """Closing a position should record realized PnL."""
        portfolio = Portfolio("test")
        pos = portfolio.open_position(
            Protocol.AAVE, Chain.ETHEREUM, "USDC",
            amount=10000, price=1.0, apy=0.05, gas_cost=10.0,
        )
        trade = portfolio.close_position(pos.id, exit_price=1.02, gas_cost=8.0)
        assert len(portfolio.active_positions) == 0
        assert len(portfolio._realized_trades) == 1
        assert trade.exit_value > trade.entry_value

    def test_chain_allocation(self):
        """Chain allocation should sum to ~1.0."""
        portfolio = Portfolio("test")
        portfolio.open_position(Protocol.AAVE, Chain.ETHEREUM, "USDC", 50000, 1.0, 0.05, 10)
        portfolio.open_position(Protocol.AAVE, Chain.ARBITRUM, "USDC", 30000, 1.0, 0.06, 0.5)
        allocation = portfolio.chain_allocation
        total = sum(allocation.values())
        assert total == pytest.approx(1.0, abs=0.01)

    def test_gas_optimizer_savings(self):
        """Batching should save gas compared to individual transactions."""
        optimizer = GasOptimizer()
        savings = optimizer.compare_gas_costs(
            [Chain.ETHEREUM, Chain.ARBITRUM, Chain.BASE],
            num_transactions=10,
        )
        # Ethereum should be most expensive
        assert savings["ethereum"] > savings["arbitrum"]
        assert savings["arbitrum"] > savings["base"]


# ── Smart Contract Risk Heuristics ──────────────────────────────

class TestSmartContractRisk:
    """Tests for smart contract risk heuristics."""

    def test_high_risk_signals(self):
        """High-risk signals should increase the risk score."""
        high = SmartContractRiskHeuristics.assess_from_signals(
            ["upgradeable_proxy", "single_owner", "no_timelock"],
        )
        low = SmartContractRiskHeuristics.assess_from_signals(
            ["immutable", "timelock_governance", "multi_sig"],
        )
        assert high > low

    def test_tvl_modifies_risk(self):
        """Higher TVL should slightly reduce risk."""
        high_tvl = SmartContractRiskHeuristics.assess_from_signals(
            signals=["immutable"], tvl=2_000_000_000, age_days=1000,
        )
        low_tvl = SmartContractRiskHeuristics.assess_from_signals(
            signals=["immutable"], tvl=500_000, age_days=1000,
        )
        assert high_tvl < low_tvl

    def test_tvl_history_risk(self):
        """Sudden TVL drops should increase risk score."""
        stable = SmartContractRiskHeuristics.estimate_risk_from_tvl_history(
            [100, 102, 105, 108, 110, 112, 115]
        )
        crashed = SmartContractRiskHeuristics.estimate_risk_from_tvl_history(
            [100, 102, 105, 80, 50, 45, 40]
        )
        assert crashed > stable

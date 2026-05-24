"""
Yield Pilot — Multi-chain yield optimizer with rebalancing engine.

Core module implementing Welford's online algorithm for yield statistics,
risk-adjusted scoring, and auto-rebalancing logic.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Protocol(Enum):
    """Supported DeFi protocols."""
    AAVE = "aave"
    COMPOUND = "compound"
    YEARN = "yearn"


class Chain(Enum):
    """Supported blockchain networks."""
    ETHEREUM = "ethereum"
    ARBITRUM = "arbitrum"
    BASE = "base"


@dataclass
class YieldOpportunity:
    """Represents a single yield opportunity."""
    protocol: Protocol
    chain: Chain
    asset: str
    apy: float
    tvl: float
    pool_address: str = ""
    risk_score: float = 0.0

    @property
    def identifier(self) -> str:
        """Unique identifier for this opportunity."""
        return f"{self.protocol.value}:{self.chain.value}:{self.asset}"


@dataclass
class WelfordStats:
    """Online statistics using Welford's algorithm.

    Tracks mean and variance incrementally without storing all values.
    """
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0  # Sum of squares of differences from the current mean

    def update(self, value: float) -> None:
        """Add a new observation and update statistics."""
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        delta2 = value - self.mean
        self.m2 += delta * delta2

    @property
    def variance(self) -> float:
        """Population variance (returns 0.0 if fewer than 2 observations)."""
        if self.n < 2:
            return 0.0
        return self.m2 / self.n

    @property
    def sample_variance(self) -> float:
        """Sample variance (Bessel's correction)."""
        if self.n < 2:
            return 0.0
        return self.m2 / (self.n - 1)

    @property
    def std_dev(self) -> float:
        """Population standard deviation."""
        return math.sqrt(self.variance)

    def z_score(self, value: float) -> float:
        """Compute z-score for a given value relative to observed distribution."""
        if self.std_dev == 0:
            return 0.0
        return (value - self.mean) / self.std_dev


@dataclass
class YieldRecord:
    """A single yield observation with timestamp."""
    timestamp: float
    apy: float
    protocol: Protocol
    chain: Chain
    asset: str


class YieldOptimizer:
    """Multi-chain yield optimizer with rebalancing engine.

    Scans yield opportunities across Aave, Compound, and Yearn,
    computes risk-adjusted scores, and triggers rebalancing when
    thresholds are met.
    """

    def __init__(
        self,
        benchmark_rate: float = 0.04,
        rebalance_threshold: float = 0.02,
        min_tvl: float = 1_000_000.0,
    ):
        """Initialize the yield optimizer.

        Args:
            benchmark_rate: Risk-free benchmark rate (default 4%).
            rebalance_threshold: Minimum APY improvement to trigger rebalance.
            min_tvl: Minimum TVL filter for opportunities.
        """
        self.benchmark_rate = benchmark_rate
        self.rebalance_threshold = rebalance_threshold
        self.min_tvl = min_tvl

        # Per-opportunity yield statistics (keyed by identifier)
        self._yield_stats: Dict[str, WelfordStats] = {}
        # Historical records
        self._history: List[YieldRecord] = []
        # Current best opportunities cache
        self._best_opportunities: List[YieldOpportunity] = []

    def _get_stats(self, identifier: str) -> WelfordStats:
        """Get or create Welford stats for an opportunity."""
        if identifier not in self._yield_stats:
            self._yield_stats[identifier] = WelfordStats()
        return self._yield_stats[identifier]

    def record_yield(self, opportunity: YieldOpportunity) -> None:
        """Record a yield observation and update statistics.

        Args:
            opportunity: The yield opportunity to record.
        """
        stats = self._get_stats(opportunity.identifier)
        stats.update(opportunity.apy)

        self._history.append(YieldRecord(
            timestamp=time.time(),
            apy=opportunity.apy,
            protocol=opportunity.protocol,
            chain=opportunity.chain,
            asset=opportunity.asset,
        ))

    def compute_risk_adjusted_score(
        self,
        opportunity: YieldOpportunity,
        risk_score: float = 0.0,
    ) -> float:
        """Compute Sharpe-like risk-adjusted score.

        score = (yield - benchmark) / volatility

        Higher is better. Penalizes high volatility and low yields.

        Args:
            opportunity: The yield opportunity to score.
            risk_score: Additional risk penalty (0-1 scale, higher = riskier).

        Returns:
            Risk-adjusted score (higher is better).
        """
        stats = self._get_stats(opportunity.identifier)

        # Use historical std_dev if available, otherwise estimate from APY
        volatility = stats.std_dev if stats.n >= 3 else max(opportunity.apy * 0.1, 0.001)

        # Blend historical volatility with protocol risk
        effective_vol = volatility * (1.0 + risk_score)

        if effective_vol == 0:
            effective_vol = 0.001  # Avoid division by zero

        excess_yield = opportunity.apy - self.benchmark_rate
        return excess_yield / effective_vol

    def find_best_opportunities(
        self,
        opportunities: List[YieldOpportunity],
        risk_scores: Optional[Dict[str, float]] = None,
        top_n: int = 5,
    ) -> List[Tuple[YieldOpportunity, float]]:
        """Find the best risk-adjusted yield opportunities.

        Args:
            opportunities: List of available yield opportunities.
            risk_scores: Optional risk scores keyed by opportunity identifier.
            top_n: Number of top opportunities to return.

        Returns:
            List of (opportunity, score) tuples, sorted by score descending.
        """
        if risk_scores is None:
            risk_scores = {}

        # Filter by minimum TVL
        filtered = [o for o in opportunities if o.tvl >= self.min_tvl]

        # Score each opportunity
        scored: List[Tuple[YieldOpportunity, float]] = []
        for opp in filtered:
            risk = risk_scores.get(opp.identifier, 0.0)
            score = self.compute_risk_adjusted_score(opp, risk)
            scored.append((opp, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        self._best_opportunities = [opp for opp, _ in scored[:top_n]]
        return scored[:top_n]

    def should_rebalance(
        self,
        current_opportunity: YieldOpportunity,
        candidate_opportunity: YieldOpportunity,
        current_risk: float = 0.0,
        candidate_risk: float = 0.0,
    ) -> bool:
        """Determine if rebalancing is warranted.

        Rebalances when the APY improvement exceeds the threshold,
        accounting for risk adjustments.

        Args:
            current_opportunity: Currently held position.
            candidate_opportunity: Potential new position.
            current_risk: Risk score of current position.
            candidate_risk: Risk score of candidate position.

        Returns:
            True if rebalancing is recommended.
        """
        current_score = self.compute_risk_adjusted_score(current_opportunity, current_risk)
        candidate_score = self.compute_risk_adjusted_score(candidate_opportunity, candidate_risk)

        score_improvement = candidate_score - current_score

        # Also check raw APY improvement
        apy_improvement = candidate_opportunity.apy - current_opportunity.apy

        return score_improvement > 0 and apy_improvement >= self.rebalance_threshold

    def get_yield_stats(self, identifier: str) -> Optional[WelfordStats]:
        """Get yield statistics for an opportunity.

        Args:
            identifier: The opportunity identifier.

        Returns:
            WelfordStats if available, None otherwise.
        """
        return self._yield_stats.get(identifier)

    @property
    def history_count(self) -> int:
        """Total number of recorded observations."""
        return len(self._history)

    @property
    def tracked_opportunities(self) -> int:
        """Number of unique opportunities being tracked."""
        return len(self._yield_stats)


class YieldScanner:
    """Scans and aggregates yield data from multiple protocols.

    Provides a unified interface for querying yield opportunities
    across Aave, Compound, and Yearn on multiple chains.
    """

    # Simulated baseline APYs by protocol/chain
    BASELINE_APYS: Dict[Tuple[Protocol, Chain], Dict[str, float]] = {
        (Protocol.AAVE, Chain.ETHEREUM): {"USDC": 0.038, "ETH": 0.025, "DAI": 0.036, "WBTC": 0.012},
        (Protocol.AAVE, Chain.ARBITRUM): {"USDC": 0.045, "ETH": 0.030, "DAI": 0.042},
        (Protocol.AAVE, Chain.BASE): {"USDC": 0.052, "ETH": 0.035},
        (Protocol.COMPOUND, Chain.ETHEREUM): {"USDC": 0.041, "ETH": 0.022, "DAI": 0.039},
        (Protocol.COMPOUND, Chain.BASE): {"USDC": 0.048, "ETH": 0.028},
        (Protocol.YEARN, Chain.ETHEREUM): {"USDC": 0.055, "ETH": 0.032, "DAI": 0.050, "WBTC": 0.018},
        (Protocol.YEARN, Chain.ARBITRUM): {"USDC": 0.062, "ETH": 0.038, "DAI": 0.058},
    }

    def scan(
        self,
        volatility_factor: float = 0.1,
    ) -> List[YieldOpportunity]:
        """Scan all known yield opportunities.

        Args:
            volatility_factor: Random-ish variation factor for realistic data.

        Returns:
            List of yield opportunities with simulated APYs.
        """
        import random

        opportunities: List[YieldOpportunity] = []

        for (protocol, chain), assets in self.BASELINE_APYS.items():
            for asset, base_apy in assets.items():
                # Add realistic variation
                variation = random.gauss(0, base_apy * volatility_factor)
                apy = max(base_apy + variation, 0.001)

                # Simulate TVL (higher for Ethereum, lower for L2s)
                base_tvl = random.uniform(10_000_000, 500_000_000)
                if chain == Chain.ETHEREUM:
                    tvl = base_tvl * 2.0
                else:
                    tvl = base_tvl * 0.5

                opportunities.append(YieldOpportunity(
                    protocol=protocol,
                    chain=chain,
                    asset=asset,
                    apy=round(apy, 6),
                    tvl=round(tvl, 2),
                    pool_address=f"0x{''.join(random.choices('0123456789abcdef', k=40))}",
                ))

        return opportunities

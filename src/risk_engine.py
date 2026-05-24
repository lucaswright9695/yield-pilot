"""
Yield Pilot — Risk assessment module.

Protocol risk scoring, impermanent loss calculator,
and smart contract risk heuristics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .yield_pilot import Chain, Protocol


class AuditStatus(Enum):
    """Protocol audit status."""
    UNAUDITED = "unaudited"
    SINGLE_AUDIT = "single_audit"
    MULTI_AUDIT = "multi_audit"
    FORMALLY_VERIFIED = "formally_verified"


@dataclass
class ProtocolProfile:
    """Risk profile for a DeFi protocol."""
    protocol: Protocol
    chain: Chain
    tvl_current: float
    tvl_peak: float
    age_days: int
    audit_status: AuditStatus
    num_audits: int = 0
    has_bug_bounty: bool = False
    has_insurance: bool = False
    incident_count: int = 0
    total_borrowed: float = 0.0


class RiskEngine:
    """Assesses risk across DeFi protocols.

    Combines multiple risk factors into a composite score (0-1 scale,
    where 0 is safest and 1 is riskiest).
    """

    # Weight factors for composite risk
    WEIGHTS = {
        "tvl_risk": 0.25,
        "audit_risk": 0.20,
        "age_risk": 0.15,
        "incident_risk": 0.20,
        "utilization_risk": 0.10,
        "insurance_benefit": 0.10,
    }

    def compute_tvl_risk(self, profile: ProtocolProfile) -> float:
        """Compute TVL-based risk score.

        Considers absolute TVL and drawdown from peak.
        Lower TVL and higher drawdown = higher risk.

        Args:
            profile: Protocol profile with TVL data.

        Returns:
            Risk score from 0 (safe) to 1 (risky).
        """
        if profile.tvl_current <= 0:
            return 1.0

        # Absolute TVL risk (log scale)
        # > $1B: ~0.0, $100M: ~0.3, $10M: ~0.6, $1M: ~0.9
        log_tvl = math.log10(max(profile.tvl_current, 1))
        tvl_score = max(0.0, min(1.0, 1.0 - (log_tvl - 6) / 4))

        # Drawdown risk
        if profile.tvl_peak > 0:
            drawdown = 1.0 - (profile.tvl_current / profile.tvl_peak)
            drawdown_score = min(drawdown * 2.0, 1.0)  # 50% drawdown = max risk
        else:
            drawdown_score = 0.5

        return tvl_score * 0.6 + drawdown_score * 0.4

    def compute_audit_risk(self, profile: ProtocolProfile) -> float:
        """Compute audit-based risk score.

        More audits and bug bounties = lower risk.

        Args:
            profile: Protocol profile with audit data.

        Returns:
            Risk score from 0 (safe) to 1 (risky).
        """
        base_risk = {
            AuditStatus.UNAUDITED: 1.0,
            AuditStatus.SINGLE_AUDIT: 0.6,
            AuditStatus.MULTI_AUDIT: 0.3,
            AuditStatus.FORMALLY_VERIFIED: 0.1,
        }.get(profile.audit_status, 0.8)

        # Reduce risk for bug bounty programs
        if profile.has_bug_bounty:
            base_risk *= 0.8

        # Additional audits reduce risk
        if profile.num_audits > 1:
            base_risk *= max(0.5, 1.0 - (profile.num_audits - 1) * 0.1)

        return min(max(base_risk, 0.0), 1.0)

    def compute_age_risk(self, profile: ProtocolProfile) -> float:
        """Compute age-based risk score.

        Older protocols with good track records = lower risk.

        Args:
            profile: Protocol profile with age data.

        Returns:
            Risk score from 0 (safe) to 1 (risky).
        """
        if profile.age_days <= 0:
            return 1.0

        # Logarithmic decay: 30 days = 0.8, 180 days = 0.5, 730 days = 0.2, 1460+ days = ~0.05
        log_age = math.log10(max(profile.age_days, 1))
        return max(0.0, min(1.0, 1.0 - (log_age - 1.5) / 2.0))

    def compute_incident_risk(self, profile: ProtocolProfile) -> float:
        """Compute incident-based risk score.

        Past security incidents increase risk.

        Args:
            profile: Protocol profile with incident data.

        Returns:
            Risk score from 0 (safe) to 1 (risky).
        """
        if profile.incident_count == 0:
            return 0.0

        # Each incident adds risk, diminishing returns
        return min(1.0, 1.0 - math.exp(-profile.incident_count * 0.8))

    def compute_utilization_risk(self, profile: ProtocolProfile) -> float:
        """Compute utilization-based risk score.

        High borrow utilization = higher risk (liquidity crunch).

        Args:
            profile: Protocol profile with utilization data.

        Returns:
            Risk score from 0 (safe) to 1 (risky).
        """
        if profile.tvl_current <= 0:
            return 1.0

        utilization = profile.total_borrowed / profile.tvl_current

        # Utilization > 90% is dangerous, < 50% is safe
        if utilization > 0.95:
            return 1.0
        elif utilization > 0.80:
            return 0.5 + (utilization - 0.80) * 3.33
        elif utilization > 0.50:
            return (utilization - 0.50) * 1.67
        else:
            return utilization * 0.6

    def compute_composite_risk(self, profile: ProtocolProfile) -> float:
        """Compute composite risk score using weighted factors.

        Args:
            profile: Complete protocol risk profile.

        Returns:
            Composite risk score from 0 (safest) to 1 (riskiest).
        """
        factors = {
            "tvl_risk": self.compute_tvl_risk(profile),
            "audit_risk": self.compute_audit_risk(profile),
            "age_risk": self.compute_age_risk(profile),
            "incident_risk": self.compute_incident_risk(profile),
            "utilization_risk": self.compute_utilization_risk(profile),
        }

        # Insurance benefit (reduces overall risk)
        insurance_discount = 0.15 if profile.has_insurance else 0.0

        composite = sum(
            factors[k] * self.WEIGHTS[k]
            for k in factors
        )

        # Apply insurance discount
        composite *= (1.0 - insurance_discount)

        return min(max(composite, 0.0), 1.0)


class ImpermanentLossCalculator:
    """Calculates impermanent loss for LP positions.

    Uses the standard IL formula for constant-product AMMs.
    """

    @staticmethod
    def calculate_il(price_ratio: float) -> float:
        """Calculate impermanent loss given a price change ratio.

        IL = 2 * sqrt(r) / (1 + r) - 1

        Args:
            price_ratio: New price / initial price of one asset relative to the other.
                        E.g., if ETH doubles relative to USDC, price_ratio = 2.0.

        Returns:
            Impermanent loss as a negative fraction (e.g., -0.057 = 5.7% IL).
        """
        if price_ratio <= 0:
            return -1.0

        sqrt_r = math.sqrt(price_ratio)
        il = 2 * sqrt_r / (1 + price_ratio) - 1
        return il

    @staticmethod
    def calculate_il_pair(
        price_a_change: float,
        price_b_change: float,
    ) -> float:
        """Calculate IL for a pair of price changes.

        Args:
            price_a_change: Price multiplier for asset A (1.0 = no change).
            price_b_change: Price multiplier for asset B (1.0 = no change).

        Returns:
            Impermanent loss as a negative fraction.
        """
        if price_b_change <= 0:
            return -1.0

        ratio = price_a_change / price_b_change
        return ImpermanentLossCalculator.calculate_il(ratio)

    @staticmethod
    def il_to_yield_loss(il_fraction: float, position_value: float) -> float:
        """Convert IL fraction to dollar loss.

        Args:
            il_fraction: IL as a fraction (negative).
            position_value: Total position value in dollars.

        Returns:
            Dollar loss (positive number).
        """
        return abs(il_fraction) * position_value

    @staticmethod
    def breakeven_apy(
        price_ratio: float,
        holding_period_days: int = 365,
    ) -> float:
        """Calculate the APY needed to offset impermanent loss.

        Args:
            price_ratio: Expected price change ratio.
            holding_period_days: Holding period in days.

        Returns:
            Required APY (as a decimal, e.g., 0.15 = 15%).
        """
        il = ImpermanentLossCalculator.calculate_il(price_ratio)
        annualized_il = abs(il) * (365 / max(holding_period_days, 1))
        return annualized_il


class SmartContractRiskHeuristics:
    """Heuristic-based smart contract risk assessment.

    Uses observable signals to estimate smart contract risk
    without requiring source code access.
    """

    # Known high-risk patterns
    HIGH_RISK_INDICATORS = [
        "upgradeable_proxy",
        "unlimited_mint",
        "centralized_pause",
        "no_timelock",
        "single_owner",
    ]

    # Known low-risk indicators
    LOW_RISK_INDICATORS = [
        "immutable",
        "timelock_governance",
        "multi_sig",
        "frozen_code",
        "formal_verification",
    ]

    @staticmethod
    def assess_from_signals(
        signals: List[str],
        tvl: float = 0.0,
        age_days: int = 0,
    ) -> float:
        """Assess risk from observable smart contract signals.

        Args:
            signals: List of risk signal strings.
            tvl: Protocol TVL for scaling.
            age_days: Protocol age in days.

        Returns:
            Risk score from 0 (safe) to 1 (risky).
        """
        high_count = sum(1 for s in signals if s in SmartContractRiskHeuristics.HIGH_RISK_INDICATORS)
        low_count = sum(1 for s in signals if s in SmartContractRiskHeuristics.LOW_RISK_INDICATORS)

        # Base score from signals
        base = 0.5
        base -= low_count * 0.1
        base += high_count * 0.15

        # TVL modifier (higher TVL = more battle-tested)
        if tvl > 1_000_000_000:
            base -= 0.1
        elif tvl < 1_000_000:
            base += 0.1

        # Age modifier
        if age_days > 730:
            base -= 0.05
        elif age_days < 90:
            base += 0.1

        return min(max(base, 0.0), 1.0)

    @staticmethod
    def estimate_risk_from_tvl_history(
        tvl_history: List[float],
    ) -> float:
        """Estimate risk from TVL volatility.

        Sudden drops may indicate exploits or loss of confidence.

        Args:
            tvl_history: List of historical TVL values (oldest first).

        Returns:
            Risk score from 0 (stable) to 1 (volatile).
        """
        if len(tvl_history) < 2:
            return 0.5

        # Calculate max drawdown
        peak = tvl_history[0]
        max_drawdown = 0.0

        for tvl in tvl_history:
            if tvl > peak:
                peak = tvl
            drawdown = (peak - tvl) / peak if peak > 0 else 0
            max_drawdown = max(max_drawdown, drawdown)

        # Convert drawdown to risk score
        # 10% drawdown = 0.2 risk, 30% = 0.6, 50%+ = 1.0
        return min(max_drawdown * 2.0, 1.0)

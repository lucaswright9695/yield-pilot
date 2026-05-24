"""
Yield Pilot — Portfolio management module.

Position tracking across chains, gas cost optimization,
and PnL tracking with realized/unrealized split.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .yield_pilot import Chain, Protocol


class PositionStatus(Enum):
    """Position lifecycle status."""
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"
    MIGRATING = "migrating"


@dataclass
class Position:
    """A yield farming position."""
    id: str
    protocol: Protocol
    chain: Chain
    asset: str
    amount: float
    entry_price: float
    current_price: float
    entry_apy: float
    current_apy: float
    entry_timestamp: float
    status: PositionStatus = PositionStatus.ACTIVE
    gas_cost_entry: float = 0.0
    gas_cost_exit: float = 0.0
    rewards_claimed: float = 0.0

    @property
    def current_value(self) -> float:
        """Current value of the position."""
        return self.amount * self.current_price

    @property
    def entry_value(self) -> float:
        """Value at entry."""
        return self.amount * self.entry_price

    @property
    def unrealized_pnl(self) -> float:
        """Unrealized PnL (price appreciation only)."""
        return self.current_value - self.entry_value

    @property
    def yield_earned(self) -> float:
        """Estimated yield earned based on APY and time held."""
        elapsed_years = (time.time() - self.entry_timestamp) / (365.25 * 86400)
        return self.entry_value * self.entry_apy * elapsed_years

    @property
    def total_gas_cost(self) -> float:
        """Total gas costs for this position."""
        return self.gas_cost_entry + self.gas_cost_exit

    @property
    def net_pnl(self) -> float:
        """Net PnL including yield and gas costs."""
        return self.unrealized_pnl + self.yield_earned + self.rewards_claimed - self.total_gas_cost

    @property
    def holding_days(self) -> float:
        """Days since position was opened."""
        return (time.time() - self.entry_timestamp) / 86400


@dataclass
class RealizedTrade:
    """Record of a closed trade."""
    position_id: str
    protocol: Protocol
    chain: Chain
    asset: str
    entry_value: float
    exit_value: float
    yield_earned: float
    gas_costs: float
    close_timestamp: float

    @property
    def realized_pnl(self) -> float:
        """Realized PnL for this trade."""
        return (self.exit_value - self.entry_value) + self.yield_earned - self.gas_costs


@dataclass
class PendingTransaction:
    """A batched transaction waiting to be executed."""
    action: str  # "deposit", "withdraw", "swap", "claim"
    protocol: Protocol
    chain: Chain
    asset: str
    amount: float
    gas_estimate: float
    priority: int = 0  # Higher = more urgent


class Portfolio:
    """Multi-chain portfolio manager.

    Tracks positions across chains, optimizes gas costs via batching,
    and maintains PnL history with realized/unrealized split.
    """

    def __init__(self, owner: str = "default"):
        """Initialize the portfolio.

        Args:
            owner: Portfolio owner identifier.
        """
        self.owner = owner
        self._positions: Dict[str, Position] = {}
        self._realized_trades: List[RealizedTrade] = []
        self._pending_transactions: List[PendingTransaction] = []
        self._position_counter: int = 0

    def _next_position_id(self) -> str:
        """Generate next position ID."""
        self._position_counter += 1
        return f"pos-{self._position_counter:06d}"

    def open_position(
        self,
        protocol: Protocol,
        chain: Chain,
        asset: str,
        amount: float,
        price: float,
        apy: float,
        gas_cost: float = 0.0,
    ) -> Position:
        """Open a new yield farming position.

        Args:
            protocol: DeFi protocol to use.
            chain: Blockchain network.
            asset: Asset symbol.
            amount: Amount to deposit.
            price: Entry price per unit.
            apy: Current APY.
            gas_cost: Gas cost for the deposit transaction.

        Returns:
            The newly created position.
        """
        position = Position(
            id=self._next_position_id(),
            protocol=protocol,
            chain=chain,
            asset=asset,
            amount=amount,
            entry_price=price,
            current_price=price,
            entry_apy=apy,
            current_apy=apy,
            entry_timestamp=time.time(),
            gas_cost_entry=gas_cost,
        )
        self._positions[position.id] = position
        return position

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        gas_cost: float = 0.0,
    ) -> RealizedTrade:
        """Close a position and record the realized trade.

        Args:
            position_id: ID of the position to close.
            exit_price: Price at exit.
            gas_cost: Gas cost for the withdrawal transaction.

        Returns:
            The realized trade record.

        Raises:
            KeyError: If position_id not found.
        """
        if position_id not in self._positions:
            raise KeyError(f"Position {position_id} not found")

        pos = self._positions[position_id]
        pos.current_price = exit_price
        pos.gas_cost_exit = gas_cost
        pos.status = PositionStatus.CLOSED

        trade = RealizedTrade(
            position_id=pos.id,
            protocol=pos.protocol,
            chain=pos.chain,
            asset=pos.asset,
            entry_value=pos.entry_value,
            exit_value=pos.current_value,
            yield_earned=pos.yield_earned,
            gas_costs=pos.total_gas_cost,
            close_timestamp=time.time(),
        )
        self._realized_trades.append(trade)

        # Remove from active positions
        del self._positions[position_id]
        return trade

    def update_position(
        self,
        position_id: str,
        current_price: Optional[float] = None,
        current_apy: Optional[float] = None,
    ) -> Position:
        """Update position with current market data.

        Args:
            position_id: ID of the position to update.
            current_price: New price (if changed).
            current_apy: New APY (if changed).

        Returns:
            Updated position.

        Raises:
            KeyError: If position_id not found.
        """
        if position_id not in self._positions:
            raise KeyError(f"Position {position_id} not found")

        pos = self._positions[position_id]
        if current_price is not None:
            pos.current_price = current_price
        if current_apy is not None:
            pos.current_apy = current_apy
        return pos

    def claim_rewards(self, position_id: str, amount: float) -> None:
        """Record claimed rewards for a position.

        Args:
            position_id: Position to credit.
            amount: Amount of rewards claimed.

        Raises:
            KeyError: If position_id not found.
        """
        if position_id not in self._positions:
            raise KeyError(f"Position {position_id} not found")
        self._positions[position_id].rewards_claimed += amount

    def get_positions_by_chain(self, chain: Chain) -> List[Position]:
        """Get all active positions on a specific chain.

        Args:
            chain: The chain to filter by.

        Returns:
            List of positions on the specified chain.
        """
        return [p for p in self._positions.values() if p.chain == chain and p.status == PositionStatus.ACTIVE]

    def get_positions_by_protocol(self, protocol: Protocol) -> List[Position]:
        """Get all active positions for a specific protocol.

        Args:
            protocol: The protocol to filter by.

        Returns:
            List of positions on the specified protocol.
        """
        return [p for p in self._positions.values() if p.protocol == protocol and p.status == PositionStatus.ACTIVE]

    @property
    def active_positions(self) -> List[Position]:
        """All active positions."""
        return [p for p in self._positions.values() if p.status == PositionStatus.ACTIVE]

    @property
    def total_value(self) -> float:
        """Total portfolio value across all active positions."""
        return sum(p.current_value for p in self.active_positions)

    @property
    def total_unrealized_pnl(self) -> float:
        """Total unrealized PnL."""
        return sum(p.unrealized_pnl for p in self.active_positions)

    @property
    def total_yield_earned(self) -> float:
        """Total yield earned across all positions."""
        return sum(p.yield_earned for p in self.active_positions) + sum(t.yield_earned for t in self._realized_trades)

    @property
    def total_realized_pnl(self) -> float:
        """Total realized PnL from closed trades."""
        return sum(t.realized_pnl for t in self._realized_trades)

    @property
    def total_gas_spent(self) -> float:
        """Total gas spent across all positions and trades."""
        active_gas = sum(p.total_gas_cost for p in self.active_positions)
        realized_gas = sum(t.gas_costs for t in self._realized_trades)
        return active_gas + realized_gas

    @property
    def chain_allocation(self) -> Dict[str, float]:
        """Portfolio allocation by chain (as fraction of total)."""
        total = self.total_value
        if total == 0:
            return {}

        allocation: Dict[str, float] = {}
        for pos in self.active_positions:
            chain_name = pos.chain.value
            allocation[chain_name] = allocation.get(chain_name, 0) + pos.current_value / total
        return allocation

    @property
    def protocol_allocation(self) -> Dict[str, float]:
        """Portfolio allocation by protocol (as fraction of total)."""
        total = self.total_value
        if total == 0:
            return {}

        allocation: Dict[str, float] = {}
        for pos in self.active_positions:
            proto_name = pos.protocol.value
            allocation[proto_name] = allocation.get(proto_name, 0) + pos.current_value / total
        return allocation


class GasOptimizer:
    """Optimizes gas costs by batching transactions."""

    # Estimated gas costs by chain (in USD)
    GAS_ESTIMATES: Dict[Chain, float] = {
        Chain.ETHEREUM: 15.0,
        Chain.ARBITRUM: 0.50,
        Chain.BASE: 0.30,
    }

    def __init__(self):
        """Initialize the gas optimizer."""
        self._pending: List[PendingTransaction] = []

    def add_transaction(self, tx: PendingTransaction) -> None:
        """Add a transaction to the pending queue.

        Args:
            tx: Transaction to queue.
        """
        self._pending.append(tx)

    def get_batchable_transactions(self, chain: Chain) -> List[PendingTransaction]:
        """Get pending transactions that can be batched on a chain.

        Transactions on the same chain can be batched to save gas.

        Args:
            chain: The chain to batch for.

        Returns:
            List of batchable transactions.
        """
        return sorted(
            [tx for tx in self._pending if tx.chain == chain],
            key=lambda t: t.priority,
            reverse=True,
        )

    def estimate_batch_savings(self, chain: Chain) -> float:
        """Estimate gas savings from batching transactions.

        Batching N transactions saves approximately (N-1) * base_gas * 0.6.

        Args:
            chain: The chain to estimate for.

        Returns:
            Estimated gas savings in USD.
        """
        txs = self.get_batchable_transactions(chain)
        if len(txs) < 2:
            return 0.0

        base_gas = self.GAS_ESTIMATES.get(chain, 1.0)
        # Each additional tx in a batch saves ~60% of its individual gas
        savings = (len(txs) - 1) * base_gas * 0.6
        return round(savings, 2)

    def execute_batch(self, chain: Chain) -> Tuple[List[PendingTransaction], float]:
        """Execute a batch of transactions on a chain.

        Args:
            chain: The chain to execute on.

        Returns:
            Tuple of (executed transactions, gas savings).
        """
        txs = self.get_batchable_transactions(chain)
        savings = self.estimate_batch_savings(chain)

        # Remove executed transactions from pending
        executed_ids = {id(tx) for tx in txs}
        self._pending = [tx for tx in self._pending if id(tx) not in executed_ids]

        return txs, savings

    @property
    def pending_count(self) -> int:
        """Number of pending transactions."""
        return len(self._pending)

    @staticmethod
    def compare_gas_costs(
        chains: List[Chain],
        num_transactions: int = 1,
    ) -> Dict[str, float]:
        """Compare gas costs across chains.

        Args:
            chains: Chains to compare.
            num_transactions: Number of transactions.

        Returns:
            Dict mapping chain name to total gas cost.
        """
        return {
            chain.value: GasOptimizer.GAS_ESTIMATES.get(chain, 1.0) * num_transactions
            for chain in chains
        }

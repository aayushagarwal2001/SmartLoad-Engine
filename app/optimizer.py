from dataclasses import dataclass
from typing import List, Dict

import numpy as np

from app.models import Order, Truck


@dataclass(frozen=True)
class _GroupKey:
    origin: str
    destination: str
    is_hazmat: bool


@dataclass
class OptimizationResult:
    selected_orders: List[Order]
    total_payout_cents: int
    total_weight_lbs: int
    total_volume_cuft: int


_EMPTY_RESULT = OptimizationResult(
    selected_orders=[],
    total_payout_cents=0,
    total_weight_lbs=0,
    total_volume_cuft=0,
)


def optimize(truck: Truck, orders: List[Order]) -> OptimizationResult:
    """
    Entry point. Groups orders by compatibility, runs bitmask DP per group,
    returns the globally best result.
    """
    if not orders:
        return _EMPTY_RESULT

    groups = _group_by_compatibility(orders)
    best = _EMPTY_RESULT

    for group_orders in groups.values():
        result = _bitmask_dp(truck, group_orders)
        if result.total_payout_cents > best.total_payout_cents:
            best = result

    return best


def best_per_group(truck: Truck, orders: List[Order]) -> List[OptimizationResult]:
    """Returns the best feasible result for each compatibility group."""
    if not orders:
        return []
    results = []
    for group_orders in _group_by_compatibility(orders).values():
        result = _bitmask_dp(truck, group_orders)
        if result.selected_orders:
            results.append(result)
    return results


def pareto_optimize(truck: Truck, orders: List[Order]) -> List[OptimizationResult]:
    """
    Returns Pareto-optimal solutions across all compatible groups:
    solutions where no other solution is strictly better in both
    payout and combined utilization.
    """
    if not orders:
        return [_EMPTY_RESULT]

    groups = _group_by_compatibility(orders)
    candidates: List[OptimizationResult] = []

    for group_orders in groups.values():
        candidates.extend(_all_feasible(truck, group_orders))

    return _pareto_front(truck, candidates) or [_EMPTY_RESULT]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _group_by_compatibility(orders: List[Order]) -> Dict[_GroupKey, List[Order]]:
    groups: Dict[_GroupKey, List[Order]] = {}
    for order in orders:
        key = _GroupKey(
            origin=order.origin.strip().lower(),
            destination=order.destination.strip().lower(),
            is_hazmat=order.is_hazmat,
        )
        groups.setdefault(key, []).append(order)
    return groups


# Cache precomputed index arrays keyed by n — they depend only on group size.
_dp_index_cache: Dict[int, tuple] = {}


def _get_dp_indices(n: int) -> tuple:
    if n not in _dp_index_cache:
        total_states = 1 << n
        masks = np.arange(1, total_states, dtype=np.int64)
        lsbs = masks & (-masks)
        bit_idx = np.log2(lsbs.astype(np.float64)).astype(np.int64)
        prevs = masks ^ lsbs
        temp = masks.copy()
        popcounts = np.zeros(len(masks), dtype=np.int64)
        while np.any(temp):
            popcounts += temp & 1
            temp >>= 1
        # Pre-partition indices by popcount level for fast lookup
        levels = [np.where(popcounts == lvl)[0] for lvl in range(1, n + 1)]
        _dp_index_cache[n] = (masks, bit_idx, prevs, levels)
    return _dp_index_cache[n]


def _bitmask_dp(truck: Truck, orders: List[Order]) -> OptimizationResult:
    n = len(orders)
    max_w = truck.max_weight_lbs
    max_v = truck.max_volume_cuft
    total_states = 1 << n

    w_arr = np.array([o.weight_lbs for o in orders], dtype=np.int64)
    v_arr = np.array([o.volume_cuft for o in orders], dtype=np.int64)
    p_arr = np.array([o.payout_cents for o in orders], dtype=np.int64)

    w_sum = np.zeros(total_states, dtype=np.int64)
    v_sum = np.zeros(total_states, dtype=np.int64)
    p_sum = np.zeros(total_states, dtype=np.int64)

    masks, bit_idx, prevs, levels = _get_dp_indices(n)

    # Fill DP level by level — all masks within a level are independent
    for idx in levels:
        lm = masks[idx]
        lp = prevs[idx]
        lb = bit_idx[idx]
        w_sum[lm] = w_sum[lp] + w_arr[lb]
        v_sum[lm] = v_sum[lp] + v_arr[lb]
        p_sum[lm] = p_sum[lp] + p_arr[lb]

    feasible = (w_sum[1:] <= max_w) & (v_sum[1:] <= max_v)
    if not feasible.any():
        return _EMPTY_RESULT

    best_rel = int(np.argmax(np.where(feasible, p_sum[1:], np.int64(-1))))
    best_mask = best_rel + 1

    selected = [orders[i] for i in range(n) if best_mask & (1 << i)]
    return OptimizationResult(
        selected_orders=selected,
        total_payout_cents=int(p_sum[best_mask]),
        total_weight_lbs=int(w_sum[best_mask]),
        total_volume_cuft=int(v_sum[best_mask]),
    )


def _all_feasible(truck: Truck, orders: List[Order]) -> List[OptimizationResult]:
    n = len(orders)
    max_w = truck.max_weight_lbs
    max_v = truck.max_volume_cuft

    weights = [o.weight_lbs for o in orders]
    volumes = [o.volume_cuft for o in orders]
    payouts = [o.payout_cents for o in orders]

    total_states = 1 << n
    w_sum = [0] * total_states
    v_sum = [0] * total_states
    p_sum = [0] * total_states

    results = []
    for mask in range(1, total_states):
        lsb = mask & (-mask)
        bit = lsb.bit_length() - 1
        prev = mask ^ lsb

        w_sum[mask] = w_sum[prev] + weights[bit]
        v_sum[mask] = v_sum[prev] + volumes[bit]
        p_sum[mask] = p_sum[prev] + payouts[bit]

        if w_sum[mask] <= max_w and v_sum[mask] <= max_v:
            selected = [orders[i] for i in range(n) if mask & (1 << i)]
            results.append(OptimizationResult(
                selected_orders=selected,
                total_payout_cents=p_sum[mask],
                total_weight_lbs=w_sum[mask],
                total_volume_cuft=v_sum[mask],
            ))

    return results


def _pareto_front(truck: Truck, candidates: List[OptimizationResult]) -> List[OptimizationResult]:
    """
    Returns solutions where no other candidate dominates on BOTH
    payout_cents AND combined utilization score.
    """
    def utilization(r: OptimizationResult) -> float:
        w_pct = r.total_weight_lbs / truck.max_weight_lbs
        v_pct = r.total_volume_cuft / truck.max_volume_cuft
        return (w_pct + v_pct) / 2.0

    pareto = []
    for candidate in candidates:
        dominated = False
        for other in candidates:
            if other is candidate:
                continue
            if (other.total_payout_cents >= candidate.total_payout_cents and
                    utilization(other) >= utilization(candidate) and
                    (other.total_payout_cents > candidate.total_payout_cents or
                     utilization(other) > utilization(candidate))):
                dominated = True
                break
        if not dominated:
            pareto.append(candidate)

    return pareto

"""Graph query helpers over the NetworkX relationship graph."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

GraphT = Any


def shared_device(graph: GraphT, *, seed_customer_ids: list[str] | None = None) -> dict[str, Any]:
    """Devices used by more than one distinct customer (via owned accounts)."""
    account_to_customer: dict[str, str] = {}
    for u, v, data in graph.edges(data=True):
        if data.get("edge_type") == "owns" and str(u).startswith("customer:"):
            account_to_customer[str(v)] = str(u)

    device_customers: dict[str, set[str]] = defaultdict(set)
    for u, v, data in graph.edges(data=True):
        if data.get("edge_type") != "used_device":
            continue
        account = str(u)
        device = str(v)
        customer = account_to_customer.get(account)
        if customer:
            device_customers[device].add(customer)

    seed = {f"customer:{cid}" for cid in (seed_customer_ids or [])}
    findings: list[dict[str, Any]] = []
    for device, customers in sorted(device_customers.items()):
        if len(customers) < 2:
            continue
        if seed and customers.isdisjoint(seed):
            continue
        findings.append(
            {
                "device_id": device.removeprefix("device:"),
                "customer_ids": sorted(c.removeprefix("customer:") for c in customers),
            }
        )
    return {"findings": findings, "count": len(findings)}


def circular_transfers(graph: GraphT, *, max_cycle_length: int = 4) -> dict[str, Any]:
    """Simple directed cycles among accounts connected by transferred_to edges."""
    import networkx as nx  # type: ignore[import-untyped]

    transfer = nx.DiGraph()
    for u, v, data in graph.edges(data=True):
        if data.get("edge_type") != "transferred_to":
            continue
        if str(u).startswith("account:") and str(v).startswith("account:"):
            transfer.add_edge(u, v, transaction_id=data.get("transaction_id"))

    cycles: list[list[str]] = []
    try:
        raw = nx.simple_cycles(transfer, length_bound=max_cycle_length)
        for cycle in raw:
            if 2 <= len(cycle) <= max_cycle_length:
                cycles.append([node.removeprefix("account:") for node in cycle])
            if len(cycles) >= 50:
                break
    except TypeError:
        # networkx < 3.2 may not support length_bound
        for cycle in nx.simple_cycles(transfer):
            if 2 <= len(cycle) <= max_cycle_length:
                cycles.append([node.removeprefix("account:") for node in cycle])
            if len(cycles) >= 50:
                break

    return {"cycles": cycles, "count": len(cycles)}


def two_hop_exposure(
    graph: GraphT,
    *,
    seed_account_ids: list[str] | None = None,
    seed_customer_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Accounts/counterparties reachable within two hops from seed accounts."""
    seeds: set[str] = {f"account:{aid}" for aid in (seed_account_ids or [])}
    if seed_customer_ids:
        for u, v, data in graph.edges(data=True):
            if data.get("edge_type") == "owns" and str(u).removeprefix("customer:") in set(
                seed_customer_ids
            ):
                seeds.add(str(v))

    if not seeds:
        # Use all account nodes as seeds when none provided (scoped graph already small).
        seeds = {n for n, attrs in graph.nodes(data=True) if attrs.get("kind") == "account"}

    exposed: set[str] = set()
    paths: list[dict[str, Any]] = []
    for seed in sorted(seeds):
        if seed not in graph:
            continue
        # one hop
        for _, nbr, data in graph.out_edges(seed, data=True):
            exposed.add(str(nbr))
            paths.append(
                {
                    "from": seed.split(":", 1)[-1],
                    "to": str(nbr).split(":", 1)[-1],
                    "hops": 1,
                    "via": data.get("edge_type"),
                }
            )
            # two hop
            for _, nbr2, data2 in graph.out_edges(nbr, data=True):
                if str(nbr2) == seed:
                    continue
                exposed.add(str(nbr2))
                paths.append(
                    {
                        "from": seed.split(":", 1)[-1],
                        "to": str(nbr2).split(":", 1)[-1],
                        "hops": 2,
                        "via": f"{data.get('edge_type')}->{data2.get('edge_type')}",
                    }
                )

    return {
        "seed_accounts": sorted(s.removeprefix("account:") for s in seeds),
        "exposed_nodes": sorted(exposed),
        "paths": paths[:200],
        "count": len(exposed),
    }


def connected_accounts(
    graph: GraphT,
    *,
    seed_account_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Accounts sharing a device or transfer path with seed accounts."""
    import networkx as nx

    undirected = graph.to_undirected()
    seeds = {f"account:{aid}" for aid in (seed_account_ids or [])}
    if not seeds:
        seeds = {n for n, attrs in graph.nodes(data=True) if attrs.get("kind") == "account"}

    connected: set[str] = set()
    for seed in seeds:
        if seed not in undirected:
            continue
        for node in nx.node_connected_component(undirected, seed):
            if str(node).startswith("account:") and node != seed:
                connected.add(str(node).removeprefix("account:"))

    return {
        "seed_accounts": sorted(s.removeprefix("account:") for s in seeds),
        "connected_account_ids": sorted(connected),
        "count": len(connected),
    }

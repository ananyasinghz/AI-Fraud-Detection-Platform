"""Build an in-memory NetworkX relationship graph from scoped SQL rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.data.models.tables import Account, Transaction
from backend.app.domain.filters import NormalizedFilters

# Lazy import keeps app cold-start free of networkx until graph tools run.
GraphT = Any


def build_relationship_graph(
    session: Session,
    filters: NormalizedFilters,
    *,
    allow_unscoped: bool = False,
    max_transactions: int = 5000,
) -> tuple[GraphT, list[str]]:
    """Return (MultiDiGraph, warnings). Nodes are typed ids: customer:/account:/device:/cp:."""
    import networkx as nx  # type: ignore[import-untyped]

    warnings: list[str] = []
    graph: GraphT = nx.MultiDiGraph()

    customer_ids = list(filters.customer_ids)
    account_ids = list(filters.account_ids)
    has_scope = bool(customer_ids or account_ids or filters.transaction_ids)
    if not has_scope and not allow_unscoped:
        warnings.append("EMPTY_GRAPH_SCOPE")
        return graph, warnings

    stmt = select(Transaction)
    clauses = []
    if customer_ids:
        clauses.append(Transaction.customer_id.in_(customer_ids))
    if account_ids:
        clauses.append(Transaction.account_id.in_(account_ids))
    if filters.transaction_ids:
        clauses.append(Transaction.transaction_id.in_(list(filters.transaction_ids)))
    if clauses:
        stmt = stmt.where(or_(*clauses))
    stmt = stmt.limit(max_transactions)
    transactions = list(session.scalars(stmt))

    if not transactions and has_scope:
        # Still load owns edges for requested customers/accounts.
        _add_ownership_edges(session, graph, customer_ids, account_ids)
        warnings.append("NO_TRANSACTIONS_IN_SCOPE")
        return graph, warnings

    scoped_customers = set(customer_ids)
    scoped_accounts = set(account_ids)
    for txn in transactions:
        scoped_customers.add(txn.customer_id)
        scoped_accounts.add(txn.account_id)

    _add_ownership_edges(session, graph, list(scoped_customers), list(scoped_accounts))

    known_accounts = {
        row.account_id
        for row in session.scalars(
            select(Account).where(Account.account_id.in_(list(scoped_accounts)))
        )
    }
    # Expand known accounts for counterparty_account_id matching within loaded set.
    cp_account_candidates = {
        txn.counterparty_account_id for txn in transactions if txn.counterparty_account_id
    }
    if cp_account_candidates:
        known_accounts.update(
            session.scalars(
                select(Account.account_id).where(
                    Account.account_id.in_(list(cp_account_candidates))
                )
            )
        )

    for txn in transactions:
        acct = f"account:{txn.account_id}"
        if txn.device_id:
            device = f"device:{txn.device_id}"
            graph.add_node(device, kind="device")
            graph.add_edge(
                acct,
                device,
                key=f"used_device:{txn.transaction_id}",
                edge_type="used_device",
                transaction_id=txn.transaction_id,
            )
        if txn.counterparty_id:
            cp = f"counterparty:{txn.counterparty_id}"
            graph.add_node(cp, kind="counterparty")
            graph.add_edge(
                acct,
                cp,
                key=f"contacted:{txn.transaction_id}",
                edge_type="contacted_counterparty",
                transaction_id=txn.transaction_id,
            )
        if txn.counterparty_account_id and txn.counterparty_account_id in known_accounts:
            other = f"account:{txn.counterparty_account_id}"
            graph.add_node(other, kind="account")
            graph.add_edge(
                acct,
                other,
                key=f"transfer:{txn.transaction_id}",
                edge_type="transferred_to",
                transaction_id=txn.transaction_id,
                direction=txn.direction,
                amount_minor=txn.amount_minor,
            )

    if len(transactions) >= max_transactions:
        warnings.append(f"TRANSACTION_CAP:{max_transactions}")
    return graph, warnings


def _add_ownership_edges(
    session: Session,
    graph: GraphT,
    customer_ids: list[str],
    account_ids: list[str],
) -> None:
    stmt = select(Account)
    clauses = []
    if customer_ids:
        clauses.append(Account.customer_id.in_(customer_ids))
    if account_ids:
        clauses.append(Account.account_id.in_(account_ids))
    if not clauses:
        return
    stmt = stmt.where(or_(*clauses))
    for account in session.scalars(stmt):
        cust = f"customer:{account.customer_id}"
        acct = f"account:{account.account_id}"
        graph.add_node(cust, kind="customer")
        graph.add_node(acct, kind="account")
        graph.add_edge(
            cust,
            acct,
            key=f"owns:{account.account_id}",
            edge_type="owns",
        )

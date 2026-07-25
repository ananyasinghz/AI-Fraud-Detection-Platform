"""Typed repository exports."""

from backend.app.data.repositories.customers import CustomerRepository
from backend.app.data.repositories.transactions import TransactionRepository

__all__ = ["CustomerRepository", "TransactionRepository"]

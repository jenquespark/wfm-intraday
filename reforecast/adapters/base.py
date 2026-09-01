"""Input adapter base class and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Type

import pandas as pd


class InputAdapter(ABC):
    """Abstract base for WFM data input adapters.

    An adapter is responsible for reading source files and returning
    DataFrames with canonical column names so the engine never needs
    to know the original vendor format.
    """

    name: str = "base"

    @classmethod
    @abstractmethod
    def can_handle(cls, source_hint: str) -> bool:
        """Return True if this adapter can handle the given source."""
        ...

    @abstractmethod
    def load_forecast(self, path: str) -> pd.DataFrame:
        """Return DataFrame with canonical forecast columns."""
        ...

    @abstractmethod
    def load_actuals(self, path: str) -> pd.DataFrame:
        """Return DataFrame with canonical actuals columns."""
        ...

    @abstractmethod
    def load_staffing(self, path: str) -> pd.DataFrame:
        """Return DataFrame with canonical staffing columns."""
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_adapters: List[Type[InputAdapter]] = []


def register_adapter(adapter_cls: Type[InputAdapter]) -> Type[InputAdapter]:
    """Register an adapter class so it can be auto-detected."""
    _adapters.append(adapter_cls)
    return adapter_cls


def get_adapter(source_hint: str = "") -> InputAdapter:
    """Return the first adapter that claims it can handle *source_hint*.

    Falls back to GenericCSVAdapter (which always returns True).
    """
    for cls in _adapters:
        if cls.can_handle(source_hint):
            return cls()
    # Fallback to generic CSV
    from reforecast.adapters.generic_csv import GenericCSVAdapter
    return GenericCSVAdapter()
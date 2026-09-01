# WFM Intraday adapters
from wfm_intraday.adapters.base import InputAdapter, register_adapter, get_adapter
from wfm_intraday.adapters.generic_csv import GenericCSVAdapter

__all__ = ["InputAdapter", "register_adapter", "get_adapter", "GenericCSVAdapter"]

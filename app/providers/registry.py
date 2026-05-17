from __future__ import annotations

from app.providers.akshare_csindex import AkshareCsindexProvider
from app.providers.base import HistoricalValuationProvider


def default_provider_registry() -> dict[str, HistoricalValuationProvider]:
    return {
        "akshare_csindex": AkshareCsindexProvider(),
    }

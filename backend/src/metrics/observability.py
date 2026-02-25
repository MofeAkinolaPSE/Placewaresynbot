from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class MetricsCollector:
    query_count: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_latency_ms: int = 0
    extra: Dict[str, int] = field(default_factory=dict)

    def record_query(self, n: int = 1) -> None:
        self.query_count += n

    def record_cache_hit(self, n: int = 1) -> None:
        self.cache_hits += n

    def record_cache_miss(self, n: int = 1) -> None:
        self.cache_misses += n

    def add_latency(self, ms: int) -> None:
        self.total_latency_ms += ms

    def as_dict(self) -> Dict[str, int]:
        d = {
            "query_count": self.query_count,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "total_latency_ms": self.total_latency_ms,
        }
        d.update(self.extra)
        return d


__all__ = ["MetricsCollector"]

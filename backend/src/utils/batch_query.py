from __future__ import annotations
from typing import Callable, Iterable, Any, List, Dict, Tuple
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def batch_query(executor: Callable[[Any], Any], query_specs: Iterable[Any], parallel: bool = False, max_workers: int = 4) -> Dict[str, Any]:
    """Execute grouped queries using the provided `executor` callable.

    - `executor` is a callable that accepts a single `query_spec` and returns a result.
    - `query_specs` is an iterable of query descriptions (SQL strings, dicts, or callables).
    - If `parallel` is True, queries run in a ThreadPool.

    Returns a dict with `results` (list), `query_count`, and `total_latency_ms`.
    """

    start = time.time()
    results: List[Tuple[Any, Any]] = []

    if parallel:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(executor, spec): spec for spec in query_specs}
            for fut in as_completed(futures):
                spec = futures[fut]
                try:
                    res = fut.result()
                except Exception as e:
                    res = {"error": str(e)}
                results.append((spec, res))
    else:
        for spec in query_specs:
            try:
                res = executor(spec)
            except Exception as e:
                res = {"error": str(e)}
            results.append((spec, res))

    total_latency_ms = int((time.time() - start) * 1000)
    return {
        "results": results,
        "query_count": len(results),
        "total_latency_ms": total_latency_ms,
    }


__all__ = ["batch_query"]

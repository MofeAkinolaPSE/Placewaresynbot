from __future__ import annotations

from typing import Iterable


def _response_details(response) -> str:
    request = getattr(response, "request", None)
    method = getattr(request, "method", "?")
    url = getattr(request, "url", "?")
    body = getattr(response, "text", "")
    return f"{method} {url} -> {response.status_code}. Body: {body}"


def assert_status(response, expected: int | Iterable[int]) -> None:
    if isinstance(expected, int):
        assert response.status_code == expected, _response_details(response)
        return
    allowed = tuple(expected)
    assert response.status_code in allowed, _response_details(response)

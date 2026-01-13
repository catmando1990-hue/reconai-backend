# BUILD 12E — Outbound Timeout Defaults (httpx helper)
# Use for Plaid/any outbound HTTP. Keeps latency trust.
from __future__ import annotations

import httpx

DEFAULT_CONNECT_TIMEOUT_S = 5.0
DEFAULT_READ_TIMEOUT_S = 15.0


def build_httpx_client(
    connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
    read_timeout_s: float = DEFAULT_READ_TIMEOUT_S,
) -> httpx.Client:
    timeout = httpx.Timeout(connect=connect_timeout_s, read=read_timeout_s, write=read_timeout_s, pool=connect_timeout_s)
    return httpx.Client(timeout=timeout)


def build_httpx_async_client(
    connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
    read_timeout_s: float = DEFAULT_READ_TIMEOUT_S,
) -> httpx.AsyncClient:
    timeout = httpx.Timeout(connect=connect_timeout_s, read=read_timeout_s, write=read_timeout_s, pool=connect_timeout_s)
    return httpx.AsyncClient(timeout=timeout)

"""Test package for Stock AI Assistant.

Network guard: outbound connections to non-local addresses are blocked unless
ALLOW_LIVE_NETWORK=1 is set in the environment.  This prevents accidental
yfinance / external API calls during unit tests while allowing localhost
connections (TestClient, SQLite, etc.).
"""
from __future__ import annotations

import os
import socket


def _install_network_guard() -> None:
    """Patch socket.create_connection to block external addresses.

    Localhost (127.0.0.1, ::1, localhost) is always allowed so TestClient
    and SQLite keep working.  All other outbound connections raise an error
    unless ALLOW_LIVE_NETWORK=1.
    """
    if os.environ.get("ALLOW_LIVE_NETWORK") == "1":
        return

    _real_create_connection = socket.create_connection

    def _guarded_create_connection(
        address: tuple[str, int],
        *args: object,
        **kwargs: object,
    ) -> socket.socket:
        host, port = address
        # Allow localhost connections (TestClient, SQLite, etc.)
        if host in ("127.0.0.1", "::1", "localhost", "0.0.0.0"):
            return _real_create_connection(address, *args, **kwargs)
        raise RuntimeError(
            f"Network access blocked in unit tests (tried to connect to {host}:{port}). "
            "Set ALLOW_LIVE_NETWORK=1 for live smoke tests."
        )

    socket.create_connection = _guarded_create_connection


_install_network_guard()

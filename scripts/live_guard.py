from __future__ import annotations

import os
import sys


_TRUTHY = {"1", "true", "yes", "on"}


def require_live_network(label: str) -> bool:
    value = os.getenv("ALLOW_LIVE_NETWORK", "").strip().lower()
    if value in _TRUTHY:
        return True

    print(
        f"{label} requires ALLOW_LIVE_NETWORK=1 to run live network checks.",
        file=sys.stderr,
    )
    return False

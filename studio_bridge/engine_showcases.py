"""Lab / catalog showcase attachments (optional enrichment).

If preview textures are missing, catalog rows still work without them.
"""

from __future__ import annotations

from typing import Any


def attach_showcases(engines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pass-through for now — keeps /api/engines usable without local preview packs."""
    return engines

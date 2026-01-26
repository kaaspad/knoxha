"""Data models for Knox Chameleon64i."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ZoneState:
    """Represents the current state of a zone."""

    zone_id: int
    input_id: Optional[int] = None
    volume: Optional[int] = None  # 0-63, where 0=loudest, 63=quietest
    is_muted: Optional[bool] = None

    # Optional audio controls (not yet implemented)
    bass: Optional[int] = None  # -7 to +7
    treble: Optional[int] = None  # -7 to +7
    balance: Optional[int] = None  # -32 to +32
    loudness: Optional[bool] = None

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"ZoneState(zone={self.zone_id}, input={self.input_id}, "
            f"volume={self.volume}, muted={self.is_muted})"
        )

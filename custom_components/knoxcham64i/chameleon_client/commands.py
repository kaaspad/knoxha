"""Knox Chameleon64i protocol command definitions.

Based on Knox Chameleon64i User Manual.

Command Format:
- All commands end with \r (carriage return)
- Zone numbers: 01-64 (two digits, zero-padded)
- Input numbers: 01-64 (two digits, zero-padded)
- Volume: 00-63 (two digits, 00=loudest, 63=quietest)

Response Format:
- Success: <data>\r\nDONE\r\n
- Failure: ERROR\r\n
"""

from typing import Optional


class ChameleonCommands:
    """Knox Chameleon64i protocol commands."""

    # ========================================================================
    # ROUTING COMMANDS (Section 3.4 of manual)
    # ========================================================================

    @staticmethod
    def set_input(zone: int, input_id: int) -> str:
        """Set both video and audio input for a zone.

        Command: Bxxyy
        - B = Both (video and audio)
        - xx = zone number (01-64)
        - yy = input number (01-64)

        Example: B0102 = Route input 2 to zone 1
        """
        return f"B{zone:02d}{input_id:02d}"

    @staticmethod
    def set_video_input(zone: int, input_id: int) -> str:
        """Set video input only for a zone.

        Command: Vxxyy
        - V = Video only
        - xx = zone number (01-64)
        - yy = input number (01-64)
        """
        return f"V{zone:02d}{input_id:02d}"

    @staticmethod
    def set_audio_input(zone: int, input_id: int) -> str:
        """Set audio input only for a zone.

        Command: Axxyy
        - A = Audio only
        - xx = zone number (01-64)
        - yy = input number (01-64)
        """
        return f"A{zone:02d}{input_id:02d}"

    @staticmethod
    def get_crosspoint(zone: int) -> str:
        """Get current crosspoint (input routing) for a zone.

        Command: Dxx
        - D = Display/Dump crosspoint
        - xx = zone number (01-64)

        Response format varies - see manual page 20
        """
        return f"D{zone:02d}"

    # ========================================================================
    # VOLUME, TONE, BALANCE (VTB) COMMANDS (Section 3.4, page 17)
    # ========================================================================

    @staticmethod
    def set_volume(zone: int, volume: int) -> str:
        """Set volume for a zone.

        Command: $Vxxyy
        - $V = Volume command
        - xx = zone number (01-64)
        - yy = volume (00-63, where 00=loudest, 63=quietest)

        Note: Knox uses inverted scale compared to most systems
        """
        return f"$V{zone:02d}{volume:02d}"

    @staticmethod
    def volume_up(zone: int, steps: int = 1) -> str:
        """Increase volume (decrease Knox value).

        Command: $Vxx+ or $Vxxn+ (n=steps)
        """
        if steps == 1:
            return f"$V{zone:02d}+"
        return f"$V{zone:02d}{steps}+"

    @staticmethod
    def volume_down(zone: int, steps: int = 1) -> str:
        """Decrease volume (increase Knox value).

        Command: $Vxx- or $Vxxn- (n=steps)
        """
        if steps == 1:
            return f"$V{zone:02d}-"
        return f"$V{zone:02d}{steps}-"

    @staticmethod
    def set_mute(zone: int, mute: bool) -> str:
        """Set mute state for a zone.

        Command: $Mxx{0|1}
        - $M = Mute command
        - xx = zone number (01-64)
        - 0 = unmuted, 1 = muted
        """
        return f"$M{zone:02d}{'1' if mute else '0'}"

    @staticmethod
    def get_vtb(zone: int) -> str:
        """Get volume, tone, and balance for a zone.

        Command: $Dxx
        - $D = Dump VTB settings
        - xx = zone number (01-64)

        Response format: "V:xx  M:x  L:x  BL:xx BR:xx B: x T: x"
        - V = volume (00-63)
        - M = mute (0=unmuted, 1=muted)
        - L = loudness (0=off, 1=on)
        - BL/BR = balance left/right
        - B = bass (-7 to +7)
        - T = treble (-7 to +7)
        """
        return f"$D{zone:02d}"

    # ========================================================================
    # TONE CONTROLS (Optional - not yet implemented in integration)
    # ========================================================================

    @staticmethod
    def set_bass(zone: int, value: int) -> str:
        """Set bass for a zone.

        Command: $Bxxyy where yy is -7 to +7
        Or: $Bxx+ / $Bxx- to increment/decrement
        """
        if isinstance(value, int):
            return f"$B{zone:02d}{value:+d}"
        raise ValueError("Bass must be integer -7 to +7")

    @staticmethod
    def set_treble(zone: int, value: int) -> str:
        """Set treble for a zone.

        Command: $Txxyy where yy is -7 to +7
        Or: $Txx+ / $Txx- to increment/decrement
        """
        if isinstance(value, int):
            return f"$T{zone:02d}{value:+d}"
        raise ValueError("Treble must be integer -7 to +7")

    @staticmethod
    def set_balance(zone: int, direction: Optional[str] = None) -> str:
        """Set balance for a zone.

        Command: $Sxx{+|-|0}
        - + = decrease left channel (shift right)
        - - = decrease right channel (shift left)
        - 0 = reset to center

        Range: -32 to +32
        """
        if direction == "left":
            return f"$S{zone:02d}-"
        elif direction == "right":
            return f"$S{zone:02d}+"
        elif direction == "center":
            return f"$S{zone:02d}0"
        else:
            raise ValueError("Balance direction must be 'left', 'right', or 'center'")

    # ========================================================================
    # PATTERN STORAGE/RECALL (Section 3.4, page 19)
    # ========================================================================

    @staticmethod
    def store_pattern(pattern_number: int) -> str:
        """Store current crosspoint pattern.

        Command: Snn (nn = 01-20)
        """
        if not 1 <= pattern_number <= 20:
            raise ValueError("Pattern number must be 1-20")
        return f"S{pattern_number:02d}"

    @staticmethod
    def recall_pattern(pattern_number: int) -> str:
        """Recall a stored crosspoint pattern.

        Command: Rnn (nn = 01-20)
        """
        if not 1 <= pattern_number <= 20:
            raise ValueError("Pattern number must be 1-20")
        return f"R{pattern_number:02d}"

    # ========================================================================
    # INTERROGATION COMMANDS (Section 3.4, page 20)
    # ========================================================================

    @staticmethod
    def get_all_crosspoints() -> str:
        """Get full crosspoint map for all zones.

        Command: M

        Returns complete routing table.
        """
        return "M"

    @staticmethod
    def get_firmware_version() -> str:
        """Get device firmware version and info.

        Command: I

        Returns signon message with firmware revision.
        """
        return "I"

    @staticmethod
    def list_cards() -> str:
        """List installed crosspoint cards.

        Command: W

        Returns list of active audio/video cards.
        """
        return "W"

    @staticmethod
    def get_help() -> str:
        """Get command help from device.

        Command: H

        Returns list of available commands.
        """
        return "H"

    # ========================================================================
    # VALIDATION HELPERS
    # ========================================================================

    @staticmethod
    def validate_zone(zone: int) -> None:
        """Validate zone number is in valid range."""
        if not 1 <= zone <= 64:
            raise ValueError(f"Zone must be 1-64, got {zone}")

    @staticmethod
    def validate_input(input_id: int) -> None:
        """Validate input number is in valid range."""
        if not 1 <= input_id <= 64:
            raise ValueError(f"Input must be 1-64, got {input_id}")

    @staticmethod
    def validate_volume(volume: int) -> None:
        """Validate volume is in valid range."""
        if not 0 <= volume <= 63:
            raise ValueError(f"Volume must be 0-63, got {volume}")

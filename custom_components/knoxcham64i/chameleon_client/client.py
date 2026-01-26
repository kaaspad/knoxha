"""Knox Chameleon64i async client."""

import asyncio
import logging
import re
from typing import Dict, List, Optional

from .commands import ChameleonCommands
from .connection import ChameleonConnection
from .exceptions import ChameleonCommandError, ChameleonProtocolError
from .models import ZoneState

_LOGGER = logging.getLogger(__name__)


class ChameleonClient:
    """Async client for Knox Chameleon64i video routing switcher."""

    def __init__(
        self,
        host: str,
        port: int = 8899,
        timeout: float = 5.0,
        max_retries: int = 3,
    ) -> None:
        """Initialize client.

        Args:
            host: Device IP address or hostname
            port: TCP port (default 8899)
            timeout: Command timeout in seconds
            max_retries: Maximum retry attempts
        """
        self.host = host
        self.port = port
        self._connection = ChameleonConnection(
            host=host,
            port=port,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._commands = ChameleonCommands()

    @property
    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connection.is_connected

    async def connect(self) -> None:
        """Connect to device."""
        await self._connection.connect()

    async def disconnect(self) -> None:
        """Disconnect from device."""
        await self._connection.disconnect()

    async def health_check(self) -> bool:
        """Check if connection is healthy."""
        return await self._connection.health_check()

    # ========================================================================
    # LOW-LEVEL COMMAND EXECUTION
    # ========================================================================

    async def _send_command(self, command: str) -> str:
        """Send command and get raw response.

        Args:
            command: Knox command string

        Returns:
            Raw response from device

        Raises:
            ChameleonCommandError: Command failed
            ChameleonProtocolError: Invalid response
        """
        response = await self._connection.send_command(command)
        return response

    def _parse_response(self, response: str) -> Dict[str, any]:
        """Parse device response.

        Args:
            response: Raw response from device

        Returns:
            Parsed response dict with 'success', 'data', 'error' keys

        Raises:
            ChameleonProtocolError: Invalid response format
        """
        if not response or not response.strip():
            raise ChameleonProtocolError("Empty response from device")

        # Split into lines and clean
        lines = [line.strip() for line in response.replace('\r', '\n').split('\n') if line.strip()]

        if not lines:
            raise ChameleonProtocolError("No data in response")

        # Check for status indicators
        status_line = lines[-1].upper() if lines else ""

        if status_line == "ERROR":
            error_msg = lines[-2] if len(lines) > 1 else "Unknown error"
            return {"success": False, "error": error_msg}

        if status_line == "DONE":
            # Success with possible data
            data_lines = lines[:-1] if len(lines) > 1 else []
            if data_lines:
                return {"success": True, "data": "\n".join(data_lines)}
            return {"success": True}

        # No explicit status - assume success if we got data
        return {"success": True, "data": "\n".join(lines)}

    # ========================================================================
    # ZONE ROUTING COMMANDS
    # ========================================================================

    async def set_input(self, zone: int, input_id: int) -> bool:
        """Set input for a zone.

        Args:
            zone: Zone number (1-64)
            input_id: Input number (1-64)

        Returns:
            True if successful

        Raises:
            ValueError: Invalid zone or input number
            ChameleonCommandError: Command failed
        """
        self._commands.validate_zone(zone)
        self._commands.validate_input(input_id)

        command = self._commands.set_input(zone, input_id)
        response = await self._send_command(command)
        result = self._parse_response(response)

        if not result.get("success"):
            raise ChameleonCommandError(
                f"Failed to set input {input_id} for zone {zone}: "
                f"{result.get('error', 'Unknown error')}"
            )

        _LOGGER.debug("Set zone %d to input %d", zone, input_id)
        return True

    async def get_input(self, zone: int) -> Optional[int]:
        """Get current input for a zone.

        Args:
            zone: Zone number (1-64)

        Returns:
            Current input number, or None if unavailable

        Raises:
            ValueError: Invalid zone number
        """
        self._commands.validate_zone(zone)

        command = self._commands.get_crosspoint(zone)
        response = await self._send_command(command)
        result = self._parse_response(response)

        if not result.get("success") or "data" not in result:
            _LOGGER.warning("Failed to get input for zone %d", zone)
            return None

        data = result["data"]

        # Parse crosspoint data
        # Format: "OUTPUT   XX   VIDEO   YY   AUDIO   ZZ" (multi-line for range query)
        # Or: Single zone query may return different format

        lines = data.split('\n')
        for line in lines:
            if line.strip().startswith("OUTPUT"):
                parts = line.split()
                if len(parts) >= 6:
                    try:
                        output_num = int(parts[1])
                        video_input = int(parts[3])

                        if output_num == zone:
                            _LOGGER.debug("Zone %d input: %d", zone, video_input)
                            return video_input
                    except (ValueError, IndexError) as err:
                        _LOGGER.debug("Failed to parse output line '%s': %s", line, err)
                        continue

        _LOGGER.debug("No input found for zone %d in response", zone)
        return None

    # ========================================================================
    # VOLUME COMMANDS
    # ========================================================================

    async def set_volume(self, zone: int, volume: int) -> bool:
        """Set volume for a zone.

        Args:
            zone: Zone number (1-64)
            volume: Volume (0-63, where 0=loudest, 63=quietest)

        Returns:
            True if successful

        Raises:
            ValueError: Invalid zone or volume
            ChameleonCommandError: Command failed
        """
        self._commands.validate_zone(zone)
        self._commands.validate_volume(volume)

        command = self._commands.set_volume(zone, volume)
        response = await self._send_command(command)
        result = self._parse_response(response)

        if not result.get("success"):
            raise ChameleonCommandError(
                f"Failed to set volume {volume} for zone {zone}: "
                f"{result.get('error', 'Unknown error')}"
            )

        _LOGGER.debug("Set zone %d volume to %d", zone, volume)
        return True

    async def get_volume(self, zone: int) -> Optional[int]:
        """Get current volume for a zone.

        Args:
            zone: Zone number (1-64)

        Returns:
            Current volume (0-63), or None if unavailable

        Raises:
            ValueError: Invalid zone number
        """
        self._commands.validate_zone(zone)

        command = self._commands.get_vtb(zone)
        response = await self._send_command(command)
        result = self._parse_response(response)

        if not result.get("success") or "data" not in result:
            _LOGGER.warning("Failed to get volume for zone %d", zone)
            return None

        data = result["data"]

        # Parse VTB data: "V:XX  M:X  L:X  BL:XX BR:XX B: X T: X"
        volume_match = re.search(r'V:(-?\d+)', data)
        if volume_match:
            volume = int(volume_match.group(1))
            if 0 <= volume <= 63:
                _LOGGER.debug("Zone %d volume: %d", zone, volume)
                return volume
            else:
                _LOGGER.debug(
                    "Zone %d volume invalid (%d), device may not be configured",
                    zone,
                    volume,
                )
                return None

        _LOGGER.debug("No volume found for zone %d in response", zone)
        return None

    # ========================================================================
    # MUTE COMMANDS
    # ========================================================================

    async def set_mute(self, zone: int, mute: bool) -> bool:
        """Set mute state for a zone.

        Args:
            zone: Zone number (1-64)
            mute: True to mute, False to unmute

        Returns:
            True if successful

        Raises:
            ValueError: Invalid zone number
            ChameleonCommandError: Command failed
        """
        self._commands.validate_zone(zone)

        command = self._commands.set_mute(zone, mute)
        response = await self._send_command(command)
        result = self._parse_response(response)

        if not result.get("success"):
            raise ChameleonCommandError(
                f"Failed to {'mute' if mute else 'unmute'} zone {zone}: "
                f"{result.get('error', 'Unknown error')}"
            )

        _LOGGER.debug("Zone %d %s", zone, "muted" if mute else "unmuted")
        return True

    async def get_mute(self, zone: int) -> Optional[bool]:
        """Get current mute state for a zone.

        Args:
            zone: Zone number (1-64)

        Returns:
            True if muted, False if unmuted, None if unavailable

        Raises:
            ValueError: Invalid zone number
        """
        self._commands.validate_zone(zone)

        command = self._commands.get_vtb(zone)
        response = await self._send_command(command)
        result = self._parse_response(response)

        if not result.get("success") or "data" not in result:
            _LOGGER.warning("Failed to get mute state for zone %d", zone)
            return None

        data = result["data"]

        # Parse VTB data: "V:XX  M:X  L:X  BL:XX BR:XX B: X T: X"
        mute_match = re.search(r'M:(\d+)', data)
        if mute_match:
            mute_val = int(mute_match.group(1))
            is_muted = mute_val == 1
            _LOGGER.debug("Zone %d mute: %s", zone, is_muted)
            return is_muted

        _LOGGER.debug("No mute state found for zone %d in response", zone)
        return None

    # ========================================================================
    # ZONE STATE QUERIES
    # ========================================================================

    async def get_zone_state(self, zone: int) -> ZoneState:
        """Get complete state for a zone.

        Args:
            zone: Zone number (1-64)

        Returns:
            ZoneState object with current state

        Raises:
            ValueError: Invalid zone number
        """
        self._commands.validate_zone(zone)

        # Fetch VTB data (volume, mute, tone, balance)
        vtb_command = self._commands.get_vtb(zone)
        vtb_response = await self._send_command(vtb_command)
        vtb_result = self._parse_response(vtb_response)

        # Fetch crosspoint data (input routing)
        cp_command = self._commands.get_crosspoint(zone)
        cp_response = await self._send_command(cp_command)
        cp_result = self._parse_response(cp_response)

        # Create state object
        state = ZoneState(zone_id=zone)

        # Parse VTB data
        if vtb_result.get("success") and "data" in vtb_result:
            vtb_data = vtb_result["data"]
            _LOGGER.debug("Parsing VTB data for zone %d: %s", zone, repr(vtb_data))

            # Volume - handle format like "V:+4" or "V:-5" or "V:32"
            # Note: Knox may return negative values for some configurations
            volume_match = re.search(r'V:([+-]?\d+)', vtb_data)
            if volume_match:
                volume = int(volume_match.group(1))
                _LOGGER.debug("Found volume: %d", volume)
                if 0 <= volume <= 63:
                    state.volume = volume
                else:
                    # CRITICAL: Knox reports V:-1 or other invalid values
                    # Use zone number as fallback to ensure audible audio
                    # This matches old working code behavior
                    fallback_volume = min(zone, 40)
                    _LOGGER.debug("Zone %d has invalid volume %d, using fallback: %d",
                                  zone, volume, fallback_volume)
                    state.volume = fallback_volume
            else:
                # No volume found in response, use fallback
                fallback_volume = min(zone, 40)
                _LOGGER.debug("Zone %d has no volume in response, using fallback: %d",
                              zone, fallback_volume)
                state.volume = fallback_volume

            # Mute
            mute_match = re.search(r'M:(\d+)', vtb_data)
            if mute_match:
                mute_val = int(mute_match.group(1))
                state.is_muted = (mute_val == 1)
                _LOGGER.debug("Found mute: %d -> is_muted=%s", mute_val, state.is_muted)
            else:
                # Default to unmuted if mute state not reported
                state.is_muted = False
                _LOGGER.debug("No mute state found, defaulting to unmuted")

        # Parse crosspoint data
        if cp_result.get("success") and "data" in cp_result:
            cp_data = cp_result["data"]
            lines = cp_data.split('\n')

            for line in lines:
                if line.strip().startswith("OUTPUT"):
                    parts = line.split()
                    if len(parts) >= 6:
                        try:
                            output_num = int(parts[1])
                            if output_num == zone:
                                state.input_id = int(parts[3])
                                break
                        except (ValueError, IndexError):
                            continue

        _LOGGER.debug("Zone %d state: %s", zone, state)
        return state

    async def get_all_zones_state(self, zones: List[int]) -> Dict[int, ZoneState]:
        """Get state for multiple zones efficiently.

        Args:
            zones: List of zone numbers to query

        Returns:
            Dict mapping zone number to ZoneState

        Note: Currently fetches zones individually. Could be optimized
              with batch queries using get_crosspoint("D0164") for range.
        """
        states = {}

        # Fetch all zone states concurrently
        tasks = [self.get_zone_state(zone) for zone in zones]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for zone, result in zip(zones, results):
            if isinstance(result, Exception):
                _LOGGER.warning("Failed to get state for zone %d: %s", zone, result)
                # Create empty state
                states[zone] = ZoneState(zone_id=zone)
            else:
                states[zone] = result

        return states

    # ========================================================================
    # DEVICE INFORMATION
    # ========================================================================

    async def get_firmware_version(self) -> Optional[str]:
        """Get device firmware version.

        Returns:
            Firmware version string, or None if unavailable
        """
        try:
            command = self._commands.get_firmware_version()
            response = await self._send_command(command)
            result = self._parse_response(response)

            if result.get("success") and "data" in result:
                return result["data"]
        except Exception as err:
            _LOGGER.debug("Failed to get firmware version: %s", err)

        return None

    async def test_connection(self) -> bool:
        """Test connection to device.

        Returns:
            True if connection is working
        """
        try:
            # Just verify connection is established
            # The connection itself is the test - if connect() succeeded, we're good
            # Some Knox devices reject certain commands (D01 returns ERROR on some models)
            # So don't test with a command, just verify we can connect
            if not self._connection.is_connected:
                await self._connection.connect()

            return self._connection.is_connected
        except Exception as err:
            _LOGGER.debug("Connection test failed: %s", err)
            return False

"""Knox Chameleon64i async client."""

import asyncio
import logging
import re
from typing import Dict, List, Optional

from .commands import ChameleonCommands
from .connection_blocking import ChameleonConnectionBlocking
from .exceptions import ChameleonCommandError, ChameleonProtocolError
from .models import ZoneState

_LOGGER = logging.getLogger(__name__)


class ChameleonClient:
    """Async client for Knox Chameleon64i video routing switcher."""

    def __init__(
        self,
        host: str,
        port: int = 8899,
        timeout: float = 3.0,  # Optimized for balance between reliability and speed
        max_retries: int = 3,
    ) -> None:
        """Initialize client.

        Args:
            host: Device IP address or hostname
            port: TCP port (default 8899)
            timeout: Socket timeout in seconds (default 3.0 - balanced for HF2211A)
            max_retries: Maximum retry attempts
        """
        self.host = host
        self.port = port
        self._connection = ChameleonConnectionBlocking(
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

    @property
    def is_lock_available(self) -> bool:
        """Check if the connection lock is available.

        Used by coordinator to skip refresh if a command is pending.
        """
        return self._connection.is_lock_available

    @property
    def priority_command_waiting(self) -> bool:
        """Check if a priority command (user action) is waiting.

        Coordinator should yield refresh if this is True.
        """
        return self._connection.priority_command_waiting

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
        """Send command and get raw response (for polling/queries).

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

    async def _send_command_priority(self, command: str) -> str:
        """Send priority command with timeout on lock acquisition.

        Use this for user-initiated commands (mute, volume, source) that
        should fail fast rather than wait behind coordinator refresh.

        Args:
            command: Knox command string

        Returns:
            Raw response from device

        Raises:
            ChameleonTimeoutError: If lock not acquired within timeout
        """
        response = await self._connection.send_command_priority(command)
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
        """Set input for a zone (user action - uses priority command).

        Args:
            zone: Zone number (1-64)
            input_id: Input number (1-64)

        Returns:
            True if successful

        Raises:
            ValueError: Invalid zone or input number
            ChameleonCommandError: Command failed
            ChameleonTimeoutError: Lock acquisition timeout (coordinator blocking)
        """
        self._commands.validate_zone(zone)
        self._commands.validate_input(input_id)

        command = self._commands.set_input(zone, input_id)
        # Use priority command - fails fast if coordinator is blocking
        response = await self._send_command_priority(command)
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
        """Set volume for a zone (user action - uses priority command).

        Args:
            zone: Zone number (1-64)
            volume: Volume (0-63, where 0=loudest, 63=quietest)

        Returns:
            True if successful

        Raises:
            ValueError: Invalid zone or volume
            ChameleonCommandError: Command failed
            ChameleonTimeoutError: Lock acquisition timeout (coordinator blocking)
        """
        self._commands.validate_zone(zone)
        self._commands.validate_volume(volume)

        command = self._commands.set_volume(zone, volume)
        # Use priority command - fails fast if coordinator is blocking
        response = await self._send_command_priority(command)
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
        """Set mute state for a zone (user action - uses priority command).

        Args:
            zone: Zone number (1-64)
            mute: True to mute, False to unmute

        Returns:
            True if successful

        Raises:
            ValueError: Invalid zone number
            ChameleonCommandError: Command failed
            ChameleonTimeoutError: Lock acquisition timeout (coordinator blocking)
        """
        self._commands.validate_zone(zone)

        command = self._commands.set_mute(zone, mute)
        # Use priority command - fails fast if coordinator is blocking
        response = await self._send_command_priority(command)
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

        Optimized approach:
        1. Fetch crosspoint data ONCE for all zones (D0136)
        2. Parse to get input_id for all zones
        3. Fetch VTB data concurrently for each zone ($Dxx)
        This reduces from 2N commands to 1 + N commands.
        """
        states = {}

        # Step 1: Fetch crosspoint data for all zones 1-36 with a single command
        crosspoint_map = {}  # zone_id -> input_id
        try:
            cp_command = self._commands.get_crosspoint(1)  # Returns D0136
            cp_response = await self._send_command(cp_command)
            cp_result = self._parse_response(cp_response)

            if cp_result.get("success") and "data" in cp_result:
                cp_data = cp_result["data"]
                lines = cp_data.split('\n')

                for line in lines:
                    if line.strip().startswith("OUTPUT"):
                        parts = line.split()
                        if len(parts) >= 6:
                            try:
                                output_num = int(parts[1])
                                video_input = int(parts[3])
                                crosspoint_map[output_num] = video_input
                            except (ValueError, IndexError):
                                continue

                _LOGGER.debug("Fetched crosspoint data for %d zones in one command", len(crosspoint_map))
        except Exception as err:
            _LOGGER.warning("Failed to fetch crosspoint data: %s", err)

        # Step 2: Fetch VTB data concurrently for each requested zone
        async def get_vtb_for_zone(zone: int) -> tuple[int, Optional[dict]]:
            """Fetch VTB data for a single zone."""
            try:
                vtb_command = self._commands.get_vtb(zone)
                vtb_response = await self._send_command(vtb_command)
                vtb_result = self._parse_response(vtb_response)

                if vtb_result.get("success") and "data" in vtb_result:
                    return zone, vtb_result["data"]
            except Exception as err:
                _LOGGER.debug("Failed to get VTB for zone %d: %s", zone, err)

            return zone, None

        # Fetch VTB data for all zones concurrently
        vtb_tasks = [get_vtb_for_zone(zone) for zone in zones]
        vtb_results = await asyncio.gather(*vtb_tasks, return_exceptions=True)

        # Step 3: Build ZoneState objects combining crosspoint + VTB data
        for zone in zones:
            state = ZoneState(zone_id=zone)

            # Add crosspoint data (input_id) if available
            if zone in crosspoint_map:
                state.input_id = crosspoint_map[zone]

            # Add VTB data (volume, mute) if available
            vtb_data = None
            for result in vtb_results:
                if isinstance(result, Exception):
                    continue
                if result[0] == zone and result[1] is not None:
                    vtb_data = result[1]
                    break

            if vtb_data:
                # Parse volume
                volume_match = re.search(r'V:([+-]?\d+)', vtb_data)
                if volume_match:
                    volume = int(volume_match.group(1))
                    if 0 <= volume <= 63:
                        state.volume = volume
                    else:
                        # Invalid volume, use fallback
                        state.volume = min(zone, 40)
                else:
                    state.volume = min(zone, 40)

                # Parse mute
                mute_match = re.search(r'M:(\d+)', vtb_data)
                if mute_match:
                    state.is_muted = (int(mute_match.group(1)) == 1)
                else:
                    state.is_muted = False
            else:
                # No VTB data, use defaults
                state.volume = min(zone, 40)
                state.is_muted = False

            states[zone] = state

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

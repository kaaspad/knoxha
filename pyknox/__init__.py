"""Python library for controlling Knox Chameleon64i devices."""
import logging
import socket
import time
from typing import Optional, Dict, Any

_LOGGER = logging.getLogger(__name__)

class Knox:
    """Class for controlling a Knox Chameleon64i device."""

    def __init__(self, host: str, port: int = 8899) -> None:
        """Initialize the Knox device."""
        self._host = host
        self._port = port
        self._socket = None
        self._connected = False
        self._max_retries = 3
        self._retry_delay = 1  # seconds

    def connect(self) -> None:
        """Connect to the Knox device."""
        if self._connected:
            return

        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(10)  # Increased timeout
            self._socket.connect((self._host, self._port))
            self._connected = True
            _LOGGER.debug("Connected to Knox device at %s:%s", self._host, self._port)
        except Exception as err:
            _LOGGER.error("Failed to connect to Knox device: %s", err)
            self._connected = False
            raise

    def disconnect(self) -> None:
        """Disconnect from the Knox device."""
        if self._socket:
            try:
                self._socket.close()
            except Exception as err:
                _LOGGER.error("Error closing socket: %s", err)
            finally:
                self._socket = None
                self._connected = False

    def _send_command(self, command: str) -> str:
        """Send a command to the Knox device and return the response."""
        if not self._connected:
            self.connect()

        for attempt in range(self._max_retries):
            try:
                self._socket.sendall(f"{command}\r".encode())
                response = self._socket.recv(1024).decode().strip()
                _LOGGER.debug("Sent command: %s, Received response: %s", command, response)
                time.sleep(0.9) # Add a 0.9-second delay after sending/receiving a command
                return response
            except socket.timeout:
                _LOGGER.warning("Timeout on attempt %d for command %s", attempt + 1, command)
                if attempt < self._max_retries - 1:
                    time.sleep(self._retry_delay)
                    continue
                raise
            except Exception as err:
                _LOGGER.error("Error sending command %s: %s", command, err)
                self._connected = False
                raise

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """Parse the response from the Knox device."""
        try:
            # Split response into lines and remove empty lines
            lines = [line.strip() for line in response.split("\n") if line.strip()]

            # Look for a specific data line (not DONE or ERROR)
            actual_data_line = None
            for line in lines:
                if line and "DONE" not in line and "ERROR" not in line:
                    actual_data_line = line
                    break # Found the data, no need to check further

            # Check for DONE and ERROR statuses
            is_done = any("DONE" in line for line in lines)
            is_error = any("ERROR" in line for line in lines)

            if is_done and not is_error:
                if actual_data_line:
                    _LOGGER.debug("Response contains DONE and data: %s", actual_data_line)
                    return {"success": True, "data": actual_data_line}
                else:
                    _LOGGER.debug("Response contains DONE but no specific data line. Returning success without data key.")
                    return {"success": True} # Only DONE, no specific data
            elif is_error:
                _LOGGER.debug("Response contains ERROR: %s", response)
                return {"success": False, "error": "Device returned error"}
            elif actual_data_line: # If no DONE/ERROR, but we found a data line
                _LOGGER.debug("Response considered success with data: %s", actual_data_line)
                return {"success": True, "data": actual_data_line}
            else: # No DONE, no ERROR, no data lines
                _LOGGER.debug("No response or empty response after stripping.")
                return {"success": False, "error": "No response from device"}

        except Exception as err:
            _LOGGER.error("Error parsing response '%s': %s", response, err)
            return {"success": False, "error": str(err)}

    def set_input(self, zone: int, input_id: int) -> bool:
        """Set the input for a zone."""
        command = f"B{zone:02d}{input_id:02d}"
        response = self._send_command(command)
        result = self._parse_response(response)
        _LOGGER.debug("set_input (B%02d%02d) response result: %s", zone, input_id, result)
        return result["success"]

    def get_input(self, zone: int) -> Optional[int]:
        """Get the current input for a zone."""
        # The device does not provide direct feedback for GET commands.
        # This method will always return None, relying on optimistic updates.
        _LOGGER.debug("Knox device does not support direct state queries for input. Returning None.")
        return None

    def set_volume(self, zone: int, volume: int) -> bool:
        """Set the volume for a zone (0-63)."""
        if not 0 <= volume <= 63:
            raise ValueError("Volume must be between 0 and 63")
        command = f"$V{zone:02d}{volume:02d}"
        response = self._send_command(command)
        result = self._parse_response(response)
        _LOGGER.debug("set_volume ($V%02d%02d) response result: %s", zone, volume, result)
        return result["success"]

    def get_volume(self, zone: int) -> Optional[int]:
        """Get the current volume for a zone."""
        # The device does not provide direct feedback for GET commands.
        # This method will always return None, relying on optimistic updates.
        _LOGGER.debug("Knox device does not support direct state queries for volume. Returning None.")
        return None

    def set_mute(self, zone: int, mute: bool) -> bool:
        """Set the mute state for a zone."""
        command = f"$M{zone:02d}{'1' if mute else '0'}"
        response = self._send_command(command)
        result = self._parse_response(response)
        _LOGGER.debug("set_mute ($M%02d%s) response result: %s", zone, '1' if mute else '0', result)
        return result["success"]

    def get_mute(self, zone: int) -> Optional[bool]:
        """Get the current mute state for a zone."""
        # The device does not provide direct feedback for GET commands.
        # This method will always return None, relying on optimistic updates.
        _LOGGER.debug("Knox device does not support direct state queries for mute. Returning None.")
        return None

    def get_zone_state(self, zone: int) -> Dict[str, Any]:
        """Get the current state of a zone.
        Since the device does not provide state feedback, this method
        will return an empty dictionary, relying on optimistic updates in HA.
        """
        _LOGGER.debug("Knox device does not provide state feedback. Returning empty state.")
        return {}

def get_knox(host: str, port: int = 8899) -> Knox:
    """Get a Knox instance."""
    knox = Knox(host, port)
    knox.connect()
    return knox 
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
            if not response or not response.strip():
                _LOGGER.debug("Empty response received")
                return {"success": False, "error": "No response from device"}

            # Split response into lines and remove empty lines
            lines = [line.strip() for line in response.split("\r\n") if line.strip()]
            if not lines:
                lines = [line.strip() for line in response.split("\n") if line.strip()]
            
            _LOGGER.debug("Parsed response lines: %s", lines)

            # Check for explicit DONE/ERROR responses (case insensitive)
            done_line = None
            error_line = None
            data_lines = []

            for line in lines:
                line_upper = line.upper()
                if line_upper == "DONE":
                    done_line = line
                elif line_upper == "ERROR":
                    error_line = line
                elif line_upper.startswith("ERROR"):
                    error_line = line  # Handle "ERROR: message" format
                else:
                    data_lines.append(line)

            # Process the response based on status
            if error_line:
                _LOGGER.debug("Device returned ERROR: %s", error_line)
                return {"success": False, "error": f"Device error: {error_line}"}
            elif done_line:
                if data_lines:
                    # Successful command with data
                    data = "\n".join(data_lines)
                    _LOGGER.debug("Successful response with data: %s", data)
                    return {"success": True, "data": data}
                else:
                    # Successful command without data
                    _LOGGER.debug("Successful response without data")
                    return {"success": True}
            elif data_lines:
                # Response with data but no explicit DONE/ERROR
                # Some commands might not return explicit status
                data = "\n".join(data_lines)
                _LOGGER.debug("Response with data but no status: %s", data)
                return {"success": True, "data": data}
            else:
                # No meaningful response
                _LOGGER.debug("No meaningful response received: %s", response)
                return {"success": False, "error": "Invalid response from device"}

        except Exception as err:
            _LOGGER.error("Error parsing response '%s': %s", response, err)
            return {"success": False, "error": f"Parse error: {str(err)}"}

    def set_input(self, zone: int, input_id: int) -> bool:
        """Set the input for a zone."""
        command = f"B{zone:02d}{input_id:02d}"
        response = self._send_command(command)
        result = self._parse_response(response)
        _LOGGER.debug("set_input (B%02d%02d) response result: %s", zone, input_id, result)
        return result["success"]

    def get_input(self, zone: int) -> Optional[int]:
        """Get the current input for a zone."""
        try:
            command = f"D{zone:02d}"
            response = self._send_command(command)
            result = self._parse_response(response)
            if result["success"] and "data" in result:
                # Parse the crosspoint data to extract input number
                # Response format is typically "OUTPUT XX INPUT YY" 
                data = result["data"]
                if "INPUT" in data:
                    input_part = data.split("INPUT")[1].strip()
                    input_num = int(input_part.split()[0])
                    return input_num
            return None
        except Exception as err:
            _LOGGER.error("Error getting input for zone %s: %s", zone, err)
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
        try:
            command = f"$D{zone:02d}"
            response = self._send_command(command)
            result = self._parse_response(response)
            if result["success"] and "data" in result:
                # Parse VTB dump data to extract volume
                # Response format includes volume information
                data = result["data"]
                # Look for volume value in the response
                if "VOLUME" in data.upper():
                    # Extract volume number from response
                    parts = data.split()
                    for i, part in enumerate(parts):
                        if "VOLUME" in part.upper() and i + 1 < len(parts):
                            try:
                                volume = int(parts[i + 1])
                                return volume
                            except ValueError:
                                continue
                # Alternative parsing if format is different
                lines = data.split('\n')
                for line in lines:
                    if 'volume' in line.lower():
                        # Try to extract number from the line
                        import re
                        numbers = re.findall(r'\d+', line)
                        if numbers:
                            return int(numbers[0])
            return None
        except Exception as err:
            _LOGGER.error("Error getting volume for zone %s: %s", zone, err)
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
        try:
            command = f"$D{zone:02d}"
            response = self._send_command(command)
            result = self._parse_response(response)
            if result["success"] and "data" in result:
                # Parse VTB dump data to extract mute status
                data = result["data"]
                # Look for mute status in the response
                if "MUTE" in data.upper():
                    # Extract mute value from response
                    parts = data.split()
                    for i, part in enumerate(parts):
                        if "MUTE" in part.upper() and i + 1 < len(parts):
                            try:
                                mute_val = parts[i + 1]
                                return mute_val == "1" or mute_val.upper() == "ON"
                            except ValueError:
                                continue
                # Alternative parsing if format is different
                lines = data.split('\n')
                for line in lines:
                    if 'mute' in line.lower():
                        return '1' in line or 'on' in line.lower()
            return None
        except Exception as err:
            _LOGGER.error("Error getting mute for zone %s: %s", zone, err)
            return None

    def get_zone_state(self, zone: int) -> Dict[str, Any]:
        """Get the current state of a zone.
        Returns a dictionary with current input, volume, and mute state.
        """
        state = {}
        try:
            # Get current input
            current_input = self.get_input(zone)
            if current_input is not None:
                state["input"] = current_input
            
            # Get current volume
            current_volume = self.get_volume(zone)
            if current_volume is not None:
                state["volume"] = current_volume
            
            # Get current mute state
            current_mute = self.get_mute(zone)
            if current_mute is not None:
                state["mute"] = current_mute
                
            _LOGGER.debug("Retrieved zone %s state: %s", zone, state)
            return state
        except Exception as err:
            _LOGGER.error("Error getting zone %s state: %s", zone, err)
            return {}

def get_knox(host: str, port: int = 8899) -> Knox:
    """Get a Knox instance."""
    knox = Knox(host, port)
    knox.connect()
    return knox 
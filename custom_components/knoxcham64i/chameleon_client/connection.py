"""Persistent async TCP connection for Knox Chameleon64i."""

import asyncio
import logging
import random
from typing import Optional

from .exceptions import (
    ChameleonConnectionError,
    ChameleonTimeoutError,
)

_LOGGER = logging.getLogger(__name__)


class ChameleonConnection:
    """Manages persistent async TCP connection to Knox device."""

    def __init__(
        self,
        host: str,
        port: int = 8899,
        timeout: float = 5.0,
        max_retries: int = 3,
    ) -> None:
        """Initialize connection.

        Args:
            host: Device IP address or hostname
            port: TCP port (default 8899 for serial-to-ethernet)
            timeout: Command timeout in seconds
            max_retries: Maximum retry attempts
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.max_retries = max_retries

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._lock = asyncio.Lock()  # Serialize commands

        # Reconnection backoff
        self._reconnect_delay = 1.0  # Start with 1 second
        self._max_reconnect_delay = 60.0  # Max 60 seconds

    @property
    def is_connected(self) -> bool:
        """Check if connection is active."""
        return self._connected and self._writer is not None

    async def connect(self) -> None:
        """Establish connection to device."""
        if self.is_connected:
            _LOGGER.debug("Already connected to %s:%d", self.host, self.port)
            return

        try:
            _LOGGER.info("Connecting to Knox device at %s:%d", self.host, self.port)
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
            self._connected = True
            self._reconnect_delay = 1.0  # Reset backoff on successful connect
            _LOGGER.info("Connected to Knox device at %s:%d", self.host, self.port)

            # Small delay and clear any initialization bytes from serial adapter
            await asyncio.sleep(0.2)
            try:
                # Non-blocking read to clear any startup noise (e.g., 0xFF from HF2211A)
                leftover = await asyncio.wait_for(self._reader.read(1024), timeout=0.1)
                if leftover:
                    _LOGGER.debug("Cleared %d initialization bytes from adapter", len(leftover))
            except asyncio.TimeoutError:
                # No initialization bytes, this is fine
                pass

        except asyncio.TimeoutError as err:
            _LOGGER.error(
                "Timeout connecting to Knox device at %s:%d", self.host, self.port
            )
            raise ChameleonTimeoutError(f"Connection timeout: {err}") from err

        except OSError as err:
            _LOGGER.error(
                "Failed to connect to Knox device at %s:%d: %s",
                self.host,
                self.port,
                err,
            )
            raise ChameleonConnectionError(f"Connection failed: {err}") from err

    async def disconnect(self) -> None:
        """Close connection to device."""
        if not self._writer:
            return

        try:
            _LOGGER.info("Disconnecting from Knox device at %s:%d", self.host, self.port)
            self._writer.close()
            await self._writer.wait_closed()
        except Exception as err:
            _LOGGER.warning("Error closing connection: %s", err)
        finally:
            self._reader = None
            self._writer = None
            self._connected = False

    async def _reconnect_with_backoff(self) -> None:
        """Reconnect with exponential backoff + jitter."""
        await self.disconnect()

        # Exponential backoff with jitter
        delay = min(self._reconnect_delay, self._max_reconnect_delay)
        jitter = random.uniform(0, delay * 0.1)  # 10% jitter
        total_delay = delay + jitter

        _LOGGER.info(
            "Reconnecting to %s:%d in %.1f seconds", self.host, self.port, total_delay
        )
        await asyncio.sleep(total_delay)

        # Increase backoff for next time (exponential)
        self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)

        await self.connect()

    async def send_command(self, command: str) -> str:
        """Send command and receive response.

        Args:
            command: Knox command string (without \\r terminator)

        Returns:
            Device response string (without terminators)

        Raises:
            ChameleonConnectionError: Connection failed
            ChameleonTimeoutError: Command timed out
        """
        async with self._lock:  # Serialize commands
            for attempt in range(self.max_retries):
                try:
                    # Ensure connected
                    if not self.is_connected:
                        _LOGGER.warning("Not connected, attempting to connect...")
                        await self.connect()

                    # Send command
                    command_bytes = f"{command}\r".encode("utf-8")
                    _LOGGER.debug("Sending command: %s", command)
                    self._writer.write(command_bytes)
                    await self._writer.drain()

                    # Small delay for device to process (per old working code)
                    await asyncio.sleep(0.1)

                    # Receive response with timeout
                    # Knox sends multi-line responses ending with DONE/ERROR
                    # Use read() with limit like old code's recv(1024)
                    response_bytes = await asyncio.wait_for(
                        self._reader.read(1024),
                        timeout=self.timeout,
                    )

                    # Decode with error handling for serial adapter noise (0xFF bytes)
                    response = response_bytes.decode("utf-8", errors="ignore").strip()
                    _LOGGER.debug("Received response: %s", response)

                    return response

                except asyncio.TimeoutError:
                    _LOGGER.warning(
                        "Timeout on attempt %d/%d for command: %s",
                        attempt + 1,
                        self.max_retries,
                        command,
                    )

                    if attempt < self.max_retries - 1:
                        # Try to reconnect before retrying
                        await self._reconnect_with_backoff()
                    else:
                        raise ChameleonTimeoutError(
                            f"Command timed out after {self.max_retries} attempts"
                        )

                except (OSError, ConnectionResetError, BrokenPipeError) as err:
                    _LOGGER.warning(
                        "Connection error on attempt %d/%d: %s",
                        attempt + 1,
                        self.max_retries,
                        err,
                    )

                    if attempt < self.max_retries - 1:
                        await self._reconnect_with_backoff()
                    else:
                        raise ChameleonConnectionError(
                            f"Connection failed after {self.max_retries} attempts: {err}"
                        ) from err

                except UnicodeDecodeError as err:
                    _LOGGER.error("UTF-8 decode error (serial noise?): %s", err)
                    if attempt < self.max_retries - 1:
                        await self._reconnect_with_backoff()
                    else:
                        raise ChameleonConnectionError(
                            f"Decode error after {self.max_retries} attempts: {err}"
                        ) from err

                except Exception as err:
                    _LOGGER.error("Unexpected error sending command: %s", err)
                    raise ChameleonConnectionError(f"Command failed: {err}") from err

            # Should never reach here
            raise ChameleonConnectionError("Max retries exceeded")

    async def health_check(self) -> bool:
        """Check if connection is healthy by sending a simple command.

        Returns:
            True if connection is healthy, False otherwise
        """
        try:
            # Try to get firmware version (simple read-only command)
            response = await asyncio.wait_for(
                self.send_command("I"), timeout=2.0
            )
            return bool(response)
        except Exception as err:
            _LOGGER.debug("Health check failed: %s", err)
            return False

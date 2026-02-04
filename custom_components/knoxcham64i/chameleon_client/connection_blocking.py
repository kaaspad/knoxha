"""Blocking socket connection for Knox Chameleon64i with priority scheduling.

FIX for Issue A & B: Replaced Semaphore(1) with a priority command scheduler.
User commands (HIGH) always preempt refresh queries (LOW), ensuring UI
responsiveness even during coordinator refresh.
"""

import asyncio
import logging
import socket
import time
from typing import Optional

from .exceptions import (
    ChameleonConnectionError,
    ChameleonTimeoutError,
)
from .scheduler import CommandScheduler, Priority

_LOGGER = logging.getLogger(__name__)


class ChameleonConnectionBlocking:
    """Blocking socket connection with priority command scheduling.

    Architecture:
        - User commands (mute, volume, source) get HIGH priority
        - Refresh queries get LOW priority
        - Worker always processes HIGH before LOW
        - Maximum wait for user command: ~1-2 seconds (one device I/O)
    """

    def __init__(
        self,
        host: str,
        port: int = 8899,
        timeout: float = 2.5,
        max_retries: int = 2,
    ) -> None:
        """Initialize connection.

        Args:
            host: Device IP address
            port: TCP port (default 8899)
            timeout: Socket timeout in seconds (2.5s default for faster failure)
            max_retries: Maximum retry attempts per command (2 = max 5.5s total)
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.max_retries = max_retries

        # Create scheduler with our blocking execute function
        self._scheduler = CommandScheduler(
            execute_fn=self._send_command_blocking,
            max_queue_size=100,
        )
        self._scheduler_started = False

    @property
    def is_connected(self) -> bool:
        """Check if connected (always True for fresh-socket-per-command)."""
        return True

    @property
    def has_high_pending(self) -> bool:
        """Check if any HIGH priority commands are waiting."""
        return self._scheduler.has_high_pending

    @property
    def high_queue_size(self) -> int:
        """Number of HIGH priority commands in queue."""
        return self._scheduler.high_queue_size

    @property
    def low_queue_size(self) -> int:
        """Number of LOW priority commands in queue."""
        return self._scheduler.low_queue_size

    async def connect(self) -> None:
        """Start the command scheduler."""
        if not self._scheduler_started:
            await self._scheduler.start()
            self._scheduler_started = True
            _LOGGER.debug("Connection scheduler started")

    async def disconnect(self) -> None:
        """Stop the command scheduler."""
        if self._scheduler_started:
            await self._scheduler.stop()
            self._scheduler_started = False
            _LOGGER.debug("Connection scheduler stopped")

    def _send_command_blocking(self, command: str, trace_id: int) -> str:
        """Send command using blocking socket (called by scheduler worker).

        Args:
            command: Knox command string
            trace_id: Trace ID for logging

        Returns:
            Device response string

        Raises:
            ChameleonTimeoutError: Command timed out
            ChameleonConnectionError: Connection failed
        """
        for attempt in range(self.max_retries):
            sock = None
            io_start = time.monotonic()

            try:
                # Create fresh socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)

                _LOGGER.debug("cmd id=%d connecting to %s:%d", trace_id, self.host, self.port)
                sock.connect((self.host, self.port))

                # HF2211A sends initialization bytes - wait and flush
                time.sleep(0.2)
                sock.setblocking(False)
                try:
                    while True:
                        init_data = sock.recv(4096)
                        if not init_data:
                            break
                except BlockingIOError:
                    pass
                finally:
                    sock.setblocking(True)
                    sock.settimeout(self.timeout)

                # Send command
                sock.sendall(f"{command}\r".encode())

                # Read response
                response_data = bytearray()
                start_time = time.time()
                last_data_time = start_time
                is_vtb_query = command.startswith("$D")

                sock.settimeout(0.2)

                while time.time() - start_time < self.timeout:
                    try:
                        chunk = sock.recv(4096)
                        if chunk:
                            response_data.extend(chunk)
                            last_data_time = time.time()

                            response_str = response_data.decode("utf-8", errors="ignore")

                            # Check for complete response
                            if "DONE" in response_str or "ERROR" in response_str:
                                time.sleep(0.05)
                                try:
                                    trailing = sock.recv(4096)
                                    if trailing:
                                        response_data.extend(trailing)
                                except socket.timeout:
                                    pass
                                break

                            # VTB query optimization
                            if is_vtb_query and response_str.endswith("\n") and len(response_str) > 20:
                                time_since_data = time.time() - last_data_time
                                if time_since_data > 0.5:
                                    break
                        else:
                            if len(response_data) > 0:
                                break

                    except socket.timeout:
                        if len(response_data) > 0:
                            response_str = response_data.decode("utf-8", errors="ignore")
                            if "DONE" in response_str or "ERROR" in response_str:
                                break
                            if is_vtb_query and response_str.endswith("\n") and len(response_str) > 20:
                                if time.time() - last_data_time >= 1.0:
                                    break

                if len(response_data) == 0:
                    raise socket.timeout("No response received")

                response = response_data.decode("utf-8", errors="ignore").strip()
                io_ms = int((time.monotonic() - io_start) * 1000)

                _LOGGER.debug(
                    "cmd id=%d io_complete io_ms=%d bytes=%d",
                    trace_id, io_ms, len(response_data)
                )

                sock.close()
                time.sleep(0.1)  # Brief delay for HF2211A buffer clearing

                return response

            except socket.timeout:
                io_ms = int((time.monotonic() - io_start) * 1000)
                _LOGGER.warning(
                    "cmd id=%d attempt=%d/%d io_ms=%d err=Timeout",
                    trace_id, attempt + 1, self.max_retries, io_ms
                )
                if sock:
                    try:
                        sock.close()
                    except:
                        pass
                if attempt < self.max_retries - 1:
                    # Progressive backoff: 1s, 2s to let device recover
                    backoff = (attempt + 1) * 1.0
                    time.sleep(backoff)
                    continue
                raise ChameleonTimeoutError(f"Command timed out: {command}")

            except Exception as err:
                io_ms = int((time.monotonic() - io_start) * 1000)
                _LOGGER.error(
                    "cmd id=%d attempt=%d/%d io_ms=%d err=%s",
                    trace_id, attempt + 1, self.max_retries, io_ms, err
                )
                if sock:
                    try:
                        sock.close()
                    except:
                        pass
                if attempt < self.max_retries - 1:
                    time.sleep(0.5)
                    continue
                raise ChameleonConnectionError(f"Command failed: {err}") from err

        raise ChameleonConnectionError("Max retries exceeded")

    async def send_command(self, command: str, priority: bool = False) -> str:
        """Send command via scheduler.

        Args:
            command: Knox command string
            priority: If True, use HIGH priority (user action)

        Returns:
            Device response string
        """
        # Ensure scheduler is running
        if not self._scheduler_started:
            await self.connect()

        prio = Priority.HIGH if priority else Priority.LOW
        return await self._scheduler.submit(command, prio)

    async def send_command_priority(self, command: str) -> str:
        """Send a HIGH priority command (user action).

        HIGH priority commands preempt LOW (refresh) commands.
        Maximum wait: time for current command to complete (~1-2s).
        """
        return await self.send_command(command, priority=True)

    async def send_command_low(self, command: str) -> str:
        """Send a LOW priority command (refresh query).

        LOW priority commands yield to HIGH commands.
        """
        return await self.send_command(command, priority=False)

    async def health_check(self) -> bool:
        """Check if connection is healthy."""
        return True

"""Blocking socket connection for Knox Chameleon64i (matches old working code)."""

import asyncio
import logging
import socket
import time
from typing import Optional
import itertools

from .exceptions import (
    ChameleonConnectionError,
    ChameleonTimeoutError,
)

_LOGGER = logging.getLogger(__name__)

# Command trace ID counter for instrumentation
_trace_counter = itertools.count(1)


class ChameleonConnectionBlocking:
    """Blocking socket connection (like old pyknox code that worked).

    FIX: Added priority command support and instrumentation for Issue A & B.
    - User commands (mute, volume, source) use send_command_priority() with timeout
    - Polling commands use send_command() without timeout (can wait)
    - All commands have trace IDs for debugging
    """

    # Lock acquisition timeout for priority commands (user actions)
    PRIORITY_LOCK_TIMEOUT = 5.0  # seconds - fail fast if coordinator is hogging lock

    # Warning threshold for lock wait time
    LOCK_WAIT_WARNING_MS = 2000  # Log warning if lock wait > 2 seconds

    def __init__(
        self,
        host: str,
        port: int = 8899,
        timeout: float = 3.0,  # Optimized for balance between reliability and speed
        max_retries: int = 3,
    ) -> None:
        """Initialize connection.

        Args:
            host: Device IP address
            port: TCP port (default 8899)
            timeout: Socket timeout in seconds (default 3.0 - balanced for HF2211A)
            max_retries: Maximum retry attempts
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self.max_retries = max_retries

        self._socket: Optional[socket.socket] = None
        self._connected = False

        # FIX #4: Add semaphore to throttle concurrent connections
        # HF2211A ethernet-to-serial adapter gets overwhelmed with concurrent connections
        # Testing showed: semaphore=1 (sequential) = 100% reliability
        #                semaphore=4-8 = device crashes under stress
        # Sequential execution is slower (60s for 35 zones) but 100% reliable
        # Given coordinator polls every 300s, the 60s delay is acceptable
        self._connection_semaphore = asyncio.Semaphore(1)

        # Track if a priority command is waiting (for coordinator to yield)
        self._priority_command_waiting = False

        # Track current command for debugging
        self._current_command: Optional[str] = None
        self._current_trace_id: Optional[int] = None

    @property
    def is_connected(self) -> bool:
        """Check if connected.

        Always returns True since we use fresh sockets per command.
        """
        return True

    @property
    def is_lock_available(self) -> bool:
        """Check if the connection lock is available (not held by another command).

        Used by coordinator to decide whether to skip refresh if a command is pending.
        """
        return not self._connection_semaphore.locked()

    @property
    def priority_command_waiting(self) -> bool:
        """Check if a priority command is waiting for the lock.

        Coordinator should yield if this is True.
        """
        return self._priority_command_waiting

    async def connect(self) -> None:
        """Connect (no-op for fresh-socket-per-command mode).

        Connection happens automatically when sending commands.
        """
        _LOGGER.debug("Connect called (no-op - using fresh sockets per command)")
        pass

    async def disconnect(self) -> None:
        """Disconnect (no-op for fresh-socket-per-command mode).

        Sockets are closed automatically after each command.
        """
        _LOGGER.debug("Disconnect called (no-op - sockets closed per command)")
        pass

    def _send_command_blocking(self, command: str, trace_id: int) -> str:
        """Send command using blocking socket with fresh connection per command.

        CRITICAL FOR HF2211A: The adapter has buffering issues that cause
        response contamination with persistent connections. We MUST create
        a fresh socket for each command to get clean responses.

        Args:
            command: Knox command string
            trace_id: Unique trace ID for this command (for instrumentation)
        """
        io_start = time.monotonic()
        for attempt in range(self.max_retries):
            sock = None
            try:
                # Create fresh socket for this command
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)

                _LOGGER.debug("Connecting for command: %s", command)
                sock.connect((self.host, self.port))

                # HF2211A sends initialization bytes on connect - wait and flush
                time.sleep(0.2)  # Reduced from 0.5s for better performance
                sock.setblocking(False)
                try:
                    while True:
                        init_data = sock.recv(4096)
                        if not init_data:
                            break
                        _LOGGER.debug("Flushed %d init bytes after connect", len(init_data))
                except BlockingIOError:
                    pass
                finally:
                    sock.setblocking(True)
                    sock.settimeout(self.timeout)

                # Send command
                sock.sendall(f"{command}\r".encode())
                _LOGGER.debug("Sent command: %s", command)

                # Receive response - read until we get DONE/ERROR or main timeout expires
                # CRITICAL: HF2211A is VERY slow and sends data in bursts with long gaps
                response_data = bytearray()
                start_time = time.time()
                last_data_time = start_time

                # Detect command type for smart timeout
                is_vtb_query = command.startswith("$D")  # Single-zone VTB query

                # Use shorter individual recv timeouts but keep looping until main timeout
                sock.settimeout(0.2)  # Reduced from 0.3s for faster responses

                while time.time() - start_time < self.timeout:
                    try:
                        chunk = sock.recv(4096)
                        if chunk:
                            response_data.extend(chunk)
                            last_data_time = time.time()
                            _LOGGER.debug("Received %d bytes (total: %d)", len(chunk), len(response_data))

                            # Check if we have complete response
                            response_str = response_data.decode("utf-8", errors="ignore")

                            # Standard terminator check
                            if "DONE" in response_str or "ERROR" in response_str:
                                _LOGGER.debug("Got complete response with terminator")
                                # Wait briefly to catch any trailing data
                                time.sleep(0.05)  # Reduced from 0.1s
                                try:
                                    trailing = sock.recv(4096)
                                    if trailing:
                                        response_data.extend(trailing)
                                        _LOGGER.debug("Got %d trailing bytes", len(trailing))
                                except socket.timeout:
                                    pass
                                break

                            # PERFORMANCE FIX: VTB queries ($Dxx) return single line without DONE
                            # Response format: "V:32  M:0  L:0  BL:00 BR:00 B: 0 T: 0\r\n"
                            # If we've received data ending with \r\n and it's been >0.5s with no more data,
                            # consider it complete
                            if is_vtb_query and response_str.endswith("\n") and len(response_str) > 20:
                                time_since_data = time.time() - last_data_time
                                if time_since_data > 0.5:
                                    _LOGGER.debug("VTB query complete (got newline, no more data)")
                                    break
                        else:
                            # Empty recv = connection closed
                            if len(response_data) > 0:
                                break

                    except socket.timeout:
                        # Timeout on individual recv() - this is expected for slow adapter
                        # CRITICAL: HF2211A sends data in bursts with gaps >2s between bursts!
                        if len(response_data) > 0:
                            response_str = response_data.decode("utf-8", errors="ignore")

                            # Check for standard terminator
                            if "DONE" in response_str or "ERROR" in response_str:
                                _LOGGER.debug("Found terminator, response complete")
                                break

                            # PERFORMANCE FIX: For VTB queries, check if response looks complete
                            # If we got a line ending with \r\n and haven't received data in 1s, done
                            if is_vtb_query and response_str.endswith("\n") and len(response_str) > 20:
                                time_since_data = time.time() - last_data_time
                                if time_since_data >= 1.0:
                                    _LOGGER.debug("VTB query timeout after complete line (%.1fs idle)", time_since_data)
                                    break

                            # Otherwise keep waiting for main timeout
                            time_since_data = time.time() - last_data_time
                            _LOGGER.debug("Waiting... %d bytes so far, %.1fs since last data", len(response_data), time_since_data)
                        # Keep looping until main timeout or terminator found

                if len(response_data) == 0:
                    raise socket.timeout("No response received")

                response = response_data.decode("utf-8", errors="ignore").strip()
                io_ms = int((time.monotonic() - io_start) * 1000)
                _LOGGER.debug(
                    "cmd id=%d cmd=%s io_ms=%d bytes=%d ok=true",
                    trace_id, command, io_ms, len(response_data)
                )

                # Close socket immediately
                sock.close()

                # Brief delay before next command (HF2211A needs time to clear buffers)
                time.sleep(0.1)  # Reduced from 0.3s for better performance

                return response

            except socket.timeout:
                io_ms = int((time.monotonic() - io_start) * 1000)
                _LOGGER.warning(
                    "cmd id=%d cmd=%s io_ms=%d attempt=%d/%d ok=false err=Timeout",
                    trace_id, command, io_ms, attempt + 1, self.max_retries
                )
                if sock:
                    try:
                        sock.close()
                    except:
                        pass
                if attempt < self.max_retries - 1:
                    time.sleep(0.5)
                    continue
                raise ChameleonTimeoutError(f"Command timed out: {command}")

            except Exception as err:
                io_ms = int((time.monotonic() - io_start) * 1000)
                _LOGGER.error(
                    "cmd id=%d cmd=%s io_ms=%d ok=false err=%s",
                    trace_id, command, io_ms, err
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
        """Send command (async wrapper for concurrent execution).

        This wraps the blocking socket code in run_in_executor.
        Each command uses a fresh socket, so concurrent execution is safe.

        Args:
            command: Knox command string
            priority: If True, use timeout on lock acquisition (for user commands)

        FIX #4: Use semaphore to throttle concurrent connections and prevent
        device overload (8.5% timeout rate with 35 concurrent connections).

        FIX for Issue B: Priority commands have timeout on lock acquisition,
        so user actions don't wait indefinitely for coordinator refresh.
        """
        trace_id = next(_trace_counter)
        queued_time = time.monotonic()

        if priority:
            self._priority_command_waiting = True

        try:
            # Try to acquire lock with timeout for priority commands
            if priority:
                try:
                    await asyncio.wait_for(
                        self._connection_semaphore.acquire(),
                        timeout=self.PRIORITY_LOCK_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    lock_wait_ms = int((time.monotonic() - queued_time) * 1000)
                    _LOGGER.error(
                        "cmd id=%d cmd=%s lock_wait_ms=%d ok=false err=LockTimeout "
                        "(coordinator may be blocking - consider restarting integration)",
                        trace_id, command, lock_wait_ms
                    )
                    raise ChameleonTimeoutError(
                        f"Command {command} timed out waiting for lock "
                        f"(waited {lock_wait_ms}ms, another command may be stuck)"
                    )
            else:
                await self._connection_semaphore.acquire()

            lock_wait_ms = int((time.monotonic() - queued_time) * 1000)

            # Log warning if lock wait was long
            if lock_wait_ms > self.LOCK_WAIT_WARNING_MS:
                _LOGGER.warning(
                    "cmd id=%d cmd=%s lock_wait_ms=%d (slow - coordinator may be running)",
                    trace_id, command, lock_wait_ms
                )

            self._current_command = command
            self._current_trace_id = trace_id

            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, self._send_command_blocking, command, trace_id
                )
                return result
            finally:
                self._current_command = None
                self._current_trace_id = None
                self._connection_semaphore.release()

        finally:
            if priority:
                self._priority_command_waiting = False

    async def send_command_priority(self, command: str) -> str:
        """Send a priority command with timeout on lock acquisition.

        Use this for user-initiated commands (mute, volume, source) that should
        fail fast rather than wait behind a long coordinator refresh.

        Raises:
            ChameleonTimeoutError: If lock not acquired within PRIORITY_LOCK_TIMEOUT
        """
        return await self.send_command(command, priority=True)

    async def health_check(self) -> bool:
        """Check if connection is healthy.

        Returns True since we establish fresh connections per command.
        """
        return True

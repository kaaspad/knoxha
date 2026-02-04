"""Priority command scheduler for Knox Chameleon64i.

Implements a two-queue scheduler that ensures user commands (HIGH priority)
always preempt refresh queries (LOW priority).

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                    Command Scheduler                         │
    ├─────────────────────────────────────────────────────────────┤
    │  HIGH Queue (user commands)                                  │
    │  - set_mute, set_volume, set_input                          │
    │  - Max wait: time for current command to finish (~1-2s)     │
    │                                                              │
    │  LOW Queue (refresh queries)                                 │
    │  - get_vtb, get_crosspoint                                  │
    │  - Yields to HIGH after each command                        │
    │                                                              │
    │  Worker: Pulls from HIGH first, always                       │
    └─────────────────────────────────────────────────────────────┘

Key guarantees:
    1. User commands wait at most for ONE device I/O (~1-2 seconds)
    2. No command starves - LOW runs when HIGH is empty
    3. Refresh is interruptible between commands
"""

import asyncio
import logging
import time
import itertools
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Any

_LOGGER = logging.getLogger(__name__)

# Trace ID counter
_trace_counter = itertools.count(1)


class Priority(Enum):
    """Command priority levels."""
    HIGH = 1  # User actions - preempt everything
    LOW = 2   # Refresh queries - yield to HIGH


@dataclass
class CommandRequest:
    """A command waiting to be executed."""
    command: str
    priority: Priority
    trace_id: int = field(default_factory=lambda: next(_trace_counter))
    queued_at: float = field(default_factory=time.monotonic)
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())

    def set_result(self, result: str) -> None:
        """Set the command result."""
        if not self.future.done():
            self.future.set_result(result)

    def set_exception(self, exc: Exception) -> None:
        """Set an exception as the result."""
        if not self.future.done():
            self.future.set_exception(exc)


class CommandScheduler:
    """Priority-based command scheduler.

    Ensures user commands (HIGH) always preempt refresh queries (LOW).
    The worker pulls from HIGH first, guaranteeing user commands wait
    at most for the current command to complete (~1-2 seconds).
    """

    def __init__(
        self,
        execute_fn: Callable[[str, int], str],
        max_queue_size: int = 100,
    ):
        """Initialize scheduler.

        Args:
            execute_fn: Function to execute a command (blocking).
                       Signature: (command: str, trace_id: int) -> str
            max_queue_size: Maximum commands per queue
        """
        self._execute_fn = execute_fn
        self._high_queue: asyncio.Queue[CommandRequest] = asyncio.Queue(maxsize=max_queue_size)
        self._low_queue: asyncio.Queue[CommandRequest] = asyncio.Queue(maxsize=max_queue_size)
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False
        self._current_request: Optional[CommandRequest] = None
        self._executor_pool = None  # Will use default executor

        # Circuit breaker state
        self._consecutive_failures = 0
        self._last_failure_time: Optional[float] = None
        self._recovery_delay = 2.0  # seconds to wait after failures

    @property
    def high_queue_size(self) -> int:
        """Number of HIGH priority commands waiting."""
        return self._high_queue.qsize()

    @property
    def low_queue_size(self) -> int:
        """Number of LOW priority commands waiting."""
        return self._low_queue.qsize()

    @property
    def has_high_pending(self) -> bool:
        """Check if any HIGH priority commands are pending."""
        return not self._high_queue.empty()

    @property
    def current_command(self) -> Optional[str]:
        """Get the currently executing command."""
        return self._current_request.command if self._current_request else None

    async def start(self) -> None:
        """Start the scheduler worker."""
        if self._running:
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        _LOGGER.info("Command scheduler started")

    async def stop(self) -> None:
        """Stop the scheduler worker."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

        # Cancel any pending requests
        while not self._high_queue.empty():
            req = self._high_queue.get_nowait()
            req.set_exception(asyncio.CancelledError("Scheduler stopped"))

        while not self._low_queue.empty():
            req = self._low_queue.get_nowait()
            req.set_exception(asyncio.CancelledError("Scheduler stopped"))

        _LOGGER.info("Command scheduler stopped")

    async def submit(self, command: str, priority: Priority = Priority.LOW) -> str:
        """Submit a command for execution.

        Args:
            command: Knox command string
            priority: Command priority (HIGH for user actions, LOW for refresh)

        Returns:
            Device response string

        Raises:
            Exception: If command execution fails
        """
        request = CommandRequest(command=command, priority=priority)

        # Select queue based on priority
        queue = self._high_queue if priority == Priority.HIGH else self._low_queue

        # Log submission
        queue_name = "HIGH" if priority == Priority.HIGH else "LOW"
        _LOGGER.debug(
            "cmd id=%d cmd=%s prio=%s queue_depth=%d submitted",
            request.trace_id, command, queue_name, queue.qsize()
        )

        # Enqueue
        await queue.put(request)

        # Wait for result
        try:
            result = await request.future
            return result
        except Exception:
            raise

    async def submit_high(self, command: str) -> str:
        """Submit a HIGH priority command (user action)."""
        return await self.submit(command, Priority.HIGH)

    async def submit_low(self, command: str) -> str:
        """Submit a LOW priority command (refresh query)."""
        return await self.submit(command, Priority.LOW)

    async def _worker_loop(self) -> None:
        """Worker loop that processes commands by priority.

        Always checks HIGH queue first. Only processes LOW when HIGH is empty.
        This guarantees HIGH commands wait at most for the current command.
        """
        _LOGGER.debug("Scheduler worker started")

        while self._running:
            request = None
            try:
                # Try HIGH queue first (non-blocking)
                try:
                    request = self._high_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass

                # If no HIGH, try LOW (non-blocking)
                if request is None:
                    try:
                        request = self._low_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass

                # If both empty, wait for any command
                if request is None:
                    # Use wait() to get from either queue
                    high_get = asyncio.create_task(self._high_queue.get())
                    low_get = asyncio.create_task(self._low_queue.get())

                    done, pending = await asyncio.wait(
                        [high_get, low_get],
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    # Cancel the pending task
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                    # Get the completed request
                    for task in done:
                        request = task.result()
                        break

                if request is None:
                    continue

                # Execute the command
                self._current_request = request
                queue_wait_ms = int((time.monotonic() - request.queued_at) * 1000)

                try:
                    io_start = time.monotonic()

                    # Run blocking I/O in executor
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        self._executor_pool,
                        self._execute_fn,
                        request.command,
                        request.trace_id
                    )

                    io_ms = int((time.monotonic() - io_start) * 1000)

                    # Log completion
                    prio_str = "HIGH" if request.priority == Priority.HIGH else "LOW"
                    high_pending = self._high_queue.qsize()
                    _LOGGER.debug(
                        "cmd id=%d cmd=%s prio=%s queue_wait_ms=%d io_ms=%d "
                        "high_pending=%d ok=true",
                        request.trace_id, request.command, prio_str,
                        queue_wait_ms, io_ms, high_pending
                    )

                    # Warn if HIGH waited too long
                    if request.priority == Priority.HIGH and queue_wait_ms > 1000:
                        _LOGGER.warning(
                            "cmd id=%d HIGH command waited %dms in queue",
                            request.trace_id, queue_wait_ms
                        )

                    # Success - reset circuit breaker
                    self._consecutive_failures = 0
                    request.set_result(result)

                except Exception as e:
                    io_ms = int((time.monotonic() - io_start) * 1000) if 'io_start' in dir() else 0
                    prio_str = "HIGH" if request.priority == Priority.HIGH else "LOW"
                    _LOGGER.error(
                        "cmd id=%d cmd=%s prio=%s queue_wait_ms=%d io_ms=%d "
                        "ok=false err=%s",
                        request.trace_id, request.command, prio_str,
                        queue_wait_ms, io_ms, e
                    )

                    # Circuit breaker: track failures and add recovery delay
                    self._consecutive_failures += 1
                    self._last_failure_time = time.monotonic()

                    if self._consecutive_failures >= 2:
                        delay = min(self._recovery_delay * self._consecutive_failures, 10.0)
                        _LOGGER.warning(
                            "Circuit breaker: %d consecutive failures, waiting %.1fs for device recovery",
                            self._consecutive_failures, delay
                        )
                        await asyncio.sleep(delay)

                    request.set_exception(e)

                finally:
                    self._current_request = None

            except asyncio.CancelledError:
                # Worker cancelled, clean up current request if any
                if request and not request.future.done():
                    request.set_exception(asyncio.CancelledError("Worker cancelled"))
                break

            except Exception as e:
                _LOGGER.error("Scheduler worker error: %s", e)
                if request and not request.future.done():
                    request.set_exception(e)

        _LOGGER.debug("Scheduler worker stopped")

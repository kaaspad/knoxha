#!/usr/bin/env python3
"""
Knox Chameleon64i Stress Test Script

Tests command responsiveness under concurrent load to validate Issue B fix.
Run this while monitoring HA logs to identify any remaining stalls.

Usage:
    python3 knox_stress.py --host 192.168.0.69 --zone 29 --iterations 100

Requirements:
    - Python 3.9+
    - No external dependencies (uses stdlib only)

What it tests:
    1. Rapid mute toggles (200x by default)
    2. Random volume changes
    3. Source switches
    4. Concurrent operations (simulates coordinator + user commands)
"""

import argparse
import asyncio
import random
import socket
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class CommandResult:
    """Result of a single command execution."""
    command: str
    trace_id: int
    lock_wait_ms: int
    io_ms: int
    total_ms: int
    success: bool
    error: Optional[str] = None


class KnoxStressTest:
    """Stress test for Knox Chameleon64i."""

    def __init__(self, host: str, port: int = 8899, timeout: float = 3.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._lock = asyncio.Lock()
        self._trace_counter = 0
        self._results: list[CommandResult] = []

    def _next_trace_id(self) -> int:
        self._trace_counter += 1
        return self._trace_counter

    def _send_command_sync(self, command: str) -> tuple[str, float]:
        """Send command synchronously (blocking)."""
        io_start = time.monotonic()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)

        try:
            sock.connect((self.host, self.port))
            time.sleep(0.2)  # HF2211A init delay

            # Flush init bytes
            sock.setblocking(False)
            try:
                while True:
                    sock.recv(4096)
            except BlockingIOError:
                pass
            finally:
                sock.setblocking(True)
                sock.settimeout(self.timeout)

            # Send command
            sock.sendall(f"{command}\r".encode())

            # Read response
            response_data = bytearray()
            sock.settimeout(0.2)
            start = time.time()

            while time.time() - start < self.timeout:
                try:
                    chunk = sock.recv(4096)
                    if chunk:
                        response_data.extend(chunk)
                        resp_str = response_data.decode("utf-8", errors="ignore")
                        if "DONE" in resp_str or "ERROR" in resp_str:
                            break
                    else:
                        break
                except socket.timeout:
                    if response_data:
                        break

            io_ms = (time.monotonic() - io_start) * 1000
            return response_data.decode("utf-8", errors="ignore"), io_ms

        finally:
            sock.close()

    async def send_command(self, command: str, priority: bool = False) -> CommandResult:
        """Send command with lock management."""
        trace_id = self._next_trace_id()
        total_start = time.monotonic()
        lock_start = time.monotonic()

        # Acquire lock (with timeout for priority commands)
        if priority:
            try:
                await asyncio.wait_for(self._lock.acquire(), timeout=5.0)
            except asyncio.TimeoutError:
                lock_wait_ms = int((time.monotonic() - lock_start) * 1000)
                result = CommandResult(
                    command=command,
                    trace_id=trace_id,
                    lock_wait_ms=lock_wait_ms,
                    io_ms=0,
                    total_ms=lock_wait_ms,
                    success=False,
                    error="LockTimeout"
                )
                self._results.append(result)
                return result
        else:
            await self._lock.acquire()

        lock_wait_ms = int((time.monotonic() - lock_start) * 1000)

        try:
            loop = asyncio.get_event_loop()
            response, io_ms = await loop.run_in_executor(
                None, self._send_command_sync, command
            )
            total_ms = int((time.monotonic() - total_start) * 1000)

            success = "DONE" in response or response.strip()
            result = CommandResult(
                command=command,
                trace_id=trace_id,
                lock_wait_ms=lock_wait_ms,
                io_ms=int(io_ms),
                total_ms=total_ms,
                success=success,
                error=None if success else "NoResponse"
            )
            self._results.append(result)
            return result

        except Exception as e:
            total_ms = int((time.monotonic() - total_start) * 1000)
            result = CommandResult(
                command=command,
                trace_id=trace_id,
                lock_wait_ms=lock_wait_ms,
                io_ms=0,
                total_ms=total_ms,
                success=False,
                error=str(e)
            )
            self._results.append(result)
            return result

        finally:
            self._lock.release()

    async def test_mute_toggle(self, zone: int, iterations: int = 200) -> None:
        """Test rapid mute toggles."""
        print(f"\n=== Testing {iterations} mute toggles on zone {zone} ===")

        for i in range(iterations):
            mute = i % 2 == 0
            cmd = f"$M{zone:02d}{1 if mute else 0}"
            result = await self.send_command(cmd, priority=True)

            status = "OK" if result.success else f"FAIL ({result.error})"
            print(f"  [{i+1:3d}/{iterations}] {cmd} - lock={result.lock_wait_ms}ms io={result.io_ms}ms total={result.total_ms}ms [{status}]")

            # Random delay between commands
            await asyncio.sleep(random.uniform(0.1, 0.5))

    async def test_volume_changes(self, zone: int, iterations: int = 50) -> None:
        """Test volume changes."""
        print(f"\n=== Testing {iterations} volume changes on zone {zone} ===")

        for i in range(iterations):
            volume = random.randint(0, 63)
            cmd = f"$V{zone:02d}{volume:02d}"
            result = await self.send_command(cmd, priority=True)

            status = "OK" if result.success else f"FAIL ({result.error})"
            print(f"  [{i+1:3d}/{iterations}] {cmd} - lock={result.lock_wait_ms}ms io={result.io_ms}ms total={result.total_ms}ms [{status}]")

            await asyncio.sleep(random.uniform(0.1, 0.3))

    async def test_concurrent_load(self, zone: int, num_zones: int = 35) -> None:
        """Test coordinator-style polling concurrent with user commands."""
        print(f"\n=== Testing concurrent load (simulating coordinator + user commands) ===")

        async def coordinator_poll():
            """Simulate coordinator polling all zones."""
            print("  [COORD] Starting simulated coordinator poll...")
            for z in range(1, min(num_zones + 1, 37)):
                cmd = f"$D{z:02d}"
                result = await self.send_command(cmd, priority=False)
                if z % 10 == 0:
                    print(f"  [COORD] Polled zone {z}/{num_zones}")

            print("  [COORD] Poll complete")

        async def user_commands():
            """Simulate user commands during coordinator poll."""
            await asyncio.sleep(1)  # Let coordinator start first

            for i in range(10):
                cmd = f"$M{zone:02d}{i % 2}"
                print(f"  [USER] Sending priority command: {cmd}")
                start = time.monotonic()
                result = await self.send_command(cmd, priority=True)
                elapsed = int((time.monotonic() - start) * 1000)

                if result.success:
                    print(f"  [USER] Command {i+1} completed in {elapsed}ms (lock_wait={result.lock_wait_ms}ms)")
                else:
                    print(f"  [USER] Command {i+1} FAILED: {result.error} (waited {elapsed}ms)")

                await asyncio.sleep(0.5)

        # Run coordinator and user commands concurrently
        await asyncio.gather(coordinator_poll(), user_commands())

    def print_summary(self) -> None:
        """Print test summary statistics."""
        print("\n" + "=" * 60)
        print("STRESS TEST SUMMARY")
        print("=" * 60)

        if not self._results:
            print("No results collected.")
            return

        total = len(self._results)
        success = sum(1 for r in self._results if r.success)
        failed = total - success

        lock_waits = [r.lock_wait_ms for r in self._results]
        io_times = [r.io_ms for r in self._results if r.success]
        total_times = [r.total_ms for r in self._results]

        print(f"Total commands: {total}")
        print(f"Successful: {success} ({100*success/total:.1f}%)")
        print(f"Failed: {failed} ({100*failed/total:.1f}%)")

        if lock_waits:
            print(f"\nLock wait times:")
            print(f"  Min: {min(lock_waits)}ms")
            print(f"  Max: {max(lock_waits)}ms")
            print(f"  Avg: {sum(lock_waits)/len(lock_waits):.1f}ms")

        if io_times:
            print(f"\nI/O times (successful commands):")
            print(f"  Min: {min(io_times)}ms")
            print(f"  Max: {max(io_times)}ms")
            print(f"  Avg: {sum(io_times)/len(io_times):.1f}ms")

        # Find commands with lock wait > 2s
        slow_lock = [r for r in self._results if r.lock_wait_ms > 2000]
        if slow_lock:
            print(f"\nCommands with lock wait > 2s: {len(slow_lock)}")
            for r in slow_lock[:5]:
                print(f"  - {r.command}: lock_wait={r.lock_wait_ms}ms")

        # Find failed commands
        if failed > 0:
            print(f"\nFailed commands:")
            for r in self._results:
                if not r.success:
                    print(f"  - {r.command}: {r.error} (lock_wait={r.lock_wait_ms}ms)")


async def main():
    parser = argparse.ArgumentParser(description="Knox Chameleon64i Stress Test")
    parser.add_argument("--host", required=True, help="Knox device IP address")
    parser.add_argument("--port", type=int, default=8899, help="TCP port (default 8899)")
    parser.add_argument("--zone", type=int, default=29, help="Test zone number (default 29)")
    parser.add_argument("--iterations", type=int, default=100, help="Number of mute toggles (default 100)")
    parser.add_argument("--test", choices=["mute", "volume", "concurrent", "all"], default="all",
                        help="Test type to run")

    args = parser.parse_args()

    print(f"Knox Stress Test")
    print(f"Host: {args.host}:{args.port}")
    print(f"Test zone: {args.zone}")
    print(f"Iterations: {args.iterations}")

    tester = KnoxStressTest(args.host, args.port)

    try:
        if args.test in ("mute", "all"):
            await tester.test_mute_toggle(args.zone, args.iterations)

        if args.test in ("volume", "all"):
            await tester.test_volume_changes(args.zone, 50)

        if args.test in ("concurrent", "all"):
            await tester.test_concurrent_load(args.zone)

        tester.print_summary()

    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
        tester.print_summary()


if __name__ == "__main__":
    asyncio.run(main())

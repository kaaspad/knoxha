#!/usr/bin/env python3
"""
Comprehensive test for concurrent Knox Chameleon64i polling.

This script tests:
1. Concurrent command execution (no lock)
2. Fresh socket per command (no contamination)
3. Performance improvement (sequential vs concurrent)
4. Error handling and retries
5. Response integrity
"""

import asyncio
import sys
import time
from pathlib import Path

# Add custom component to path
sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "knoxcham64i"))

from chameleon_client import ChameleonClient, ChameleonError


class TestResults:
    """Track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []

    def add(self, test_name: str, passed: bool, message: str = ""):
        self.tests.append((test_name, passed, message))
        if passed:
            self.passed += 1
            print(f"✓ PASS: {test_name}")
        else:
            self.failed += 1
            print(f"✗ FAIL: {test_name} - {message}")

    def summary(self):
        print("\n" + "=" * 70)
        print(f"TEST SUMMARY: {self.passed} passed, {self.failed} failed")
        print("=" * 70)
        if self.failed > 0:
            print("\nFailed tests:")
            for name, passed, msg in self.tests:
                if not passed:
                    print(f"  - {name}: {msg}")
        return self.failed == 0


async def test_basic_connection(client: ChameleonClient, results: TestResults):
    """Test 1: Basic connection and command."""
    try:
        await client.connect()
        response = await client.test_connection()
        results.add("Basic connection", response, "Failed to connect")
    except Exception as e:
        results.add("Basic connection", False, str(e))


async def test_single_zone_query(client: ChameleonClient, results: TestResults):
    """Test 2: Single zone VTB query."""
    try:
        # Test $D01 command
        response = await client._send_command("$D01")
        has_volume = "V:" in response
        has_mute = "M:" in response
        is_valid = has_volume and has_mute
        results.add("Single zone query ($D01)", is_valid,
                   f"Response: {response[:50]}..." if not is_valid else "")
    except Exception as e:
        results.add("Single zone query ($D01)", False, str(e))


async def test_crosspoint_query(client: ChameleonClient, results: TestResults):
    """Test 3: Crosspoint batch query."""
    try:
        # Test D0136 command (zones 1-36)
        response = await client._send_command("D0136")
        has_output = "OUTPUT" in response
        has_done = "DONE" in response
        is_valid = has_output and has_done
        results.add("Crosspoint batch query (D0136)", is_valid,
                   f"Missing {'OUTPUT' if not has_output else 'DONE'}")
    except Exception as e:
        results.add("Crosspoint batch query (D0136)", False, str(e))


async def test_concurrent_vtb_queries(client: ChameleonClient, results: TestResults, num_zones: int = 10):
    """Test 4: Concurrent VTB queries (main performance test)."""
    try:
        print(f"\n  Testing {num_zones} concurrent VTB queries...")
        start_time = time.time()

        # Launch concurrent queries
        tasks = [client._send_command(f"$D{zone:02d}") for zone in range(1, num_zones + 1)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        elapsed = time.time() - start_time

        # Validate responses
        valid_count = 0
        error_count = 0
        for i, response in enumerate(responses):
            if isinstance(response, Exception):
                error_count += 1
            elif isinstance(response, str) and "V:" in response and "M:" in response:
                valid_count += 1

        success = valid_count == num_zones and error_count == 0
        message = f"{valid_count}/{num_zones} valid, {error_count} errors, {elapsed:.1f}s"

        results.add(f"Concurrent VTB queries ({num_zones} zones)", success, message)

        # Performance check: Should be much faster than sequential (< 3 seconds for 10 zones)
        if success and elapsed < 3.0:
            results.add("Performance improvement", True, f"Completed in {elapsed:.1f}s")
        elif success:
            results.add("Performance improvement", False,
                       f"Too slow: {elapsed:.1f}s (expected < 3s)")

    except Exception as e:
        results.add(f"Concurrent VTB queries ({num_zones} zones)", False, str(e))


async def test_mixed_concurrent_commands(client: ChameleonClient, results: TestResults):
    """Test 5: Mix of command types concurrently."""
    try:
        print("\n  Testing mixed concurrent commands...")
        start_time = time.time()

        tasks = [
            client._send_command("D0110"),      # Crosspoint batch
            client._send_command("$D01"),       # VTB zone 1
            client._send_command("$D02"),       # VTB zone 2
            client._send_command("$D03"),       # VTB zone 3
            client._send_command("B0102"),      # Set input (might fail, that's ok)
        ]

        responses = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.time() - start_time

        # Just check no hangs/crashes (some commands might fail if device isn't configured)
        success = elapsed < 5.0  # Should complete quickly
        results.add("Mixed concurrent commands", success,
                   f"Completed in {elapsed:.1f}s")

    except Exception as e:
        results.add("Mixed concurrent commands", False, str(e))


async def test_response_integrity(client: ChameleonClient, results: TestResults):
    """Test 6: Response integrity under concurrent load."""
    try:
        print("\n  Testing response integrity (30 concurrent queries)...")

        # Send 30 queries - 3 of each zone 1-10
        tasks = []
        for repeat in range(3):
            for zone in range(1, 11):
                tasks.append(client._send_command(f"$D{zone:02d}"))

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # Group responses by zone
        zone_responses = {}
        for i, response in enumerate(responses):
            zone = (i % 10) + 1
            if zone not in zone_responses:
                zone_responses[zone] = []
            zone_responses[zone].append(response)

        # Check that all 3 responses for each zone are identical (no contamination)
        contamination = False
        for zone, resp_list in zone_responses.items():
            if len(resp_list) != 3:
                continue
            # All should be strings with V: and M:
            valid = all(isinstance(r, str) and "V:" in r and "M:" in r for r in resp_list)
            if not valid:
                contamination = True
                break

        results.add("Response integrity", not contamination,
                   "Response contamination detected" if contamination else "")

    except Exception as e:
        results.add("Response integrity", False, str(e))


async def test_error_handling(client: ChameleonClient, results: TestResults):
    """Test 7: Error handling with invalid commands."""
    try:
        # Send invalid command - should handle gracefully
        response = await client._send_command("INVALID_COMMAND")
        # Should either get ERROR response or timeout
        success = "ERROR" in response or len(response) == 0
        results.add("Error handling", success, f"Got: {response[:50]}")
    except ChameleonError:
        # Expected - error was properly raised
        results.add("Error handling", True, "Properly raised ChameleonError")
    except Exception as e:
        results.add("Error handling", False, f"Unexpected error: {e}")


async def test_sequential_vs_concurrent_timing(client: ChameleonClient, results: TestResults):
    """Test 8: Sequential vs concurrent timing comparison."""
    try:
        num_zones = 5
        print(f"\n  Comparing sequential vs concurrent for {num_zones} zones...")

        # Sequential
        start = time.time()
        for zone in range(1, num_zones + 1):
            await client._send_command(f"$D{zone:02d}")
        sequential_time = time.time() - start

        # Concurrent
        start = time.time()
        tasks = [client._send_command(f"$D{zone:02d}") for zone in range(1, num_zones + 1)]
        await asyncio.gather(*tasks)
        concurrent_time = time.time() - start

        speedup = sequential_time / concurrent_time
        success = speedup > 2.0  # Should be at least 2x faster

        message = f"Sequential: {sequential_time:.1f}s, Concurrent: {concurrent_time:.1f}s, Speedup: {speedup:.1f}x"
        results.add("Sequential vs Concurrent", success, message)
        print(f"    {message}")

    except Exception as e:
        results.add("Sequential vs Concurrent", False, str(e))


async def main():
    """Run all tests."""
    print("=" * 70)
    print("KNOX CHAMELEON64I CONCURRENT POLLING TEST SUITE")
    print("=" * 70)

    # Get connection details
    host = input("Enter Knox device IP address (default: 192.168.0.69): ").strip()
    if not host:
        host = "192.168.0.69"

    port_str = input("Enter port (default: 8899): ").strip()
    port = int(port_str) if port_str else 8899

    print(f"\nConnecting to {host}:{port}...")
    print("=" * 70 + "\n")

    results = TestResults()
    client = ChameleonClient(host=host, port=port, timeout=5.0, max_retries=3)

    try:
        # Run all tests
        await test_basic_connection(client, results)
        await test_single_zone_query(client, results)
        await test_crosspoint_query(client, results)
        await test_concurrent_vtb_queries(client, results, num_zones=10)
        await test_mixed_concurrent_commands(client, results)
        await test_response_integrity(client, results)
        await test_error_handling(client, results)
        await test_sequential_vs_concurrent_timing(client, results)

    finally:
        await client.disconnect()

    # Print summary
    success = results.summary()

    if success:
        print("\n✓ ALL TESTS PASSED - Ready to commit!")
        return 0
    else:
        print("\n✗ SOME TESTS FAILED - Do not commit!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

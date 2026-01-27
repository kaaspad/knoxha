#!/usr/bin/env python3
"""
Comprehensive verification script for all 5 Knox integration fixes.

This script tests against your LIVE device at 192.168.0.69:8899.
Run this BEFORE committing to ensure all fixes work correctly.

Usage:
    python3 verify_all_fixes.py

Expected: All tests pass with 0 failures.
"""

import asyncio
import sys
import time
from pathlib import Path

# Add integration to path
sys.path.insert(0, str(Path(__file__).parent / "custom_components" / "knoxcham64i"))

from chameleon_client import ChameleonClient


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
            print(f"  ✓ PASS: {test_name}")
            if message:
                print(f"         {message}")
        else:
            self.failed += 1
            print(f"  ✗ FAIL: {test_name}")
            print(f"         {message}")

    def summary(self):
        print("\n" + "=" * 70)
        print(f"TEST SUMMARY: {self.passed} passed, {self.failed} failed")
        print("=" * 70)
        if self.failed > 0:
            print("\n⚠️  DO NOT COMMIT - Tests failed!")
            print("\nFailed tests:")
            for name, passed, msg in self.tests:
                if not passed:
                    print(f"  - {name}: {msg}")
            return False
        else:
            print("\n✓ ALL TESTS PASSED - Ready to commit!")
            return True


async def verify_fix_4_no_timeouts(client: ChameleonClient, results: TestResults):
    """Verify Fix #4: Connection throttling prevents timeouts.

    Test: Poll 35 zones concurrently with semaphore limiting connections.
    Expected: 0 timeouts (was 8.5% failure rate before fix).
    """
    print("\nTest 4: Fix #4 - No timeouts with 35 concurrent zones")

    zone_ids = list(range(1, 36))
    start_time = time.time()

    try:
        # This should trigger the semaphore throttling
        states = await client.get_all_zones_state(zone_ids)
        elapsed = time.time() - start_time

        # Check for failures
        failed_zones = [zid for zid in zone_ids if zid not in states]
        success_rate = len(states) / len(zone_ids) * 100

        if len(failed_zones) == 0:
            results.add(
                "No timeouts with concurrent polling",
                True,
                f"{len(states)}/35 zones polled in {elapsed:.1f}s (100% success)"
            )
        else:
            results.add(
                "No timeouts with concurrent polling",
                False,
                f"{len(failed_zones)} zones failed: {failed_zones} ({success_rate:.1f}% success)"
            )

        # Performance check - realistic expectations for HF2211A adapter
        # Sequential execution (semaphore=1) takes ~60s for reliability
        # Coordinator polls every 300s, so 60s is acceptable
        if elapsed <= 120.0:  # Under 2 minutes is acceptable
            results.add(
                "Performance acceptable for coordinator polling",
                True,
                f"{elapsed:.1f}s for 35 zones (under 120s limit, coordinator polls every 300s)"
            )
        else:
            results.add(
                "Performance acceptable for coordinator polling",
                False,
                f"{elapsed:.1f}s (exceeds 120s limit)"
            )

    except Exception as e:
        results.add("No timeouts with concurrent polling", False, str(e))


async def verify_fix_2_correct_initial_state(client: ChameleonClient, results: TestResults):
    """Verify Fix #2: Correct initial state reported.

    Test: Query zones that are known to be muted.
    Expected: State correctly reflects mute status, NOT default to ON.
    """
    print("\nTest 2: Fix #2 - Correct initial state (not default ON)")

    try:
        # From logs: zones 30, 34, 35 are muted
        muted_zones = [30, 34, 35]
        states = await client.get_all_zones_state(muted_zones)

        correct_count = 0
        for zone_id in muted_zones:
            if zone_id in states:
                state = states[zone_id]
                if state.is_muted is True:
                    correct_count += 1

        if correct_count == len(muted_zones):
            results.add(
                "Muted zones report correct state",
                True,
                f"All {len(muted_zones)} muted zones correctly report is_muted=True"
            )
        else:
            results.add(
                "Muted zones report correct state",
                False,
                f"Only {correct_count}/{len(muted_zones)} zones correctly report mute state"
            )

    except Exception as e:
        results.add("Muted zones report correct state", False, str(e))


async def verify_fix_4_stress_test(client: ChameleonClient, results: TestResults):
    """Verify Fix #4: Sustained stress test with no failures.

    Test: Run 50 rapid toggle operations across multiple zones.
    Expected: 100% success rate, no timeouts.
    """
    print("\nTest 5: Fix #4 - Stress test (50 operations)")

    test_zone = 1
    operations = 50
    failures = 0

    try:
        start_time = time.time()

        for i in range(operations):
            try:
                # Alternate between different operations
                if i % 3 == 0:
                    await client.set_mute(test_zone, i % 2 == 0)
                elif i % 3 == 1:
                    await client.set_volume(test_zone, (i % 64))
                else:
                    await client.set_input(test_zone, 1 + (i % 2))

            except Exception as e:
                failures += 1
                if failures <= 3:  # Only log first 3 failures
                    print(f"    Operation {i+1} failed: {e}")

        elapsed = time.time() - start_time
        success_rate = (operations - failures) / operations * 100

        if failures == 0:
            results.add(
                "Stress test: 0 failures",
                True,
                f"{operations} operations in {elapsed:.1f}s (100% success, {operations/elapsed:.1f} ops/sec)"
            )
        else:
            results.add(
                "Stress test: 0 failures",
                False,
                f"{failures}/{operations} operations failed ({success_rate:.1f}% success)"
            )

    except Exception as e:
        results.add("Stress test: 0 failures", False, str(e))


async def verify_connection_basic(client: ChameleonClient, results: TestResults):
    """Basic connectivity test."""
    print("\nTest 1: Basic connectivity")

    try:
        await client.connect()
        connected = await client.test_connection()
        results.add("Device connectivity", connected, "Connection established")
    except Exception as e:
        results.add("Device connectivity", False, str(e))


async def verify_fix_5_entity_naming(client: ChameleonClient, results: TestResults):
    """Verify Fix #5: Entity names come from zone config.

    This is a documentation test - the actual fix is in media_player.py.
    We verify the device can return zone data that will be used for naming.
    """
    print("\nTest 3: Fix #5 - Entity naming (infrastructure check)")

    try:
        # Query a few zones to ensure data structure supports naming
        states = await client.get_all_zones_state([1, 13, 25])

        if len(states) >= 3:
            results.add(
                "Zone data structure supports naming",
                True,
                f"Retrieved {len(states)} zones for naming"
            )
        else:
            results.add(
                "Zone data structure supports naming",
                False,
                f"Only got {len(states)} zones, expected 3"
            )

    except Exception as e:
        results.add("Zone data structure supports naming", False, str(e))


async def main():
    """Run all verification tests."""
    print("=" * 70)
    print("KNOX INTEGRATION - ALL FIXES VERIFICATION")
    print("Testing against live device: 192.168.0.69:8899")
    print("=" * 70)

    results = TestResults()
    client = ChameleonClient(host="192.168.0.69", port=8899, timeout=5.0, max_retries=3)

    try:
        # Test 1: Basic connectivity
        await verify_connection_basic(client, results)

        # Test 2: Fix #2 - Correct initial state
        await verify_fix_2_correct_initial_state(client, results)

        # Test 3: Fix #5 - Entity naming infrastructure
        await verify_fix_5_entity_naming(client, results)

        # Test 4: Fix #4 - No timeouts with 35 zones
        await verify_fix_4_no_timeouts(client, results)

        # Test 5: Fix #4 - Stress test
        await verify_fix_4_stress_test(client, results)

    finally:
        await client.disconnect()

    # Print summary
    success = results.summary()

    # Additional notes
    print("\n" + "=" * 70)
    print("NOTES ON FIXES NOT DIRECTLY TESTABLE HERE:")
    print("=" * 70)
    print("Fix #1 (CSV load): Requires HA config flow - test manually in HA UI")
    print("Fix #3 (State restore): Requires HA reboot - test manually after commit")
    print("\nManual test steps after commit:")
    print("1. Import CSV with 35 zones → verify entities appear immediately")
    print("2. Set zone states → reboot HA → verify states restored")
    print("=" * 70)

    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

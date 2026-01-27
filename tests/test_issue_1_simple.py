"""Simple test for Issue #1 without external dependencies."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock

# Add integration to path
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "knoxcham64i"))

from __init__ import async_reload_entry
from const import DOMAIN, CONF_ZONES


async def test_csv_load_bug():
    """Reproduce the CSV load bug."""
    print("=" * 70)
    print("REPRODUCING ISSUE #1: CSV Load Does Nothing Until Manual Reload")
    print("=" * 70)

    # Setup mock HA
    hass = Mock()
    hass.data = {DOMAIN: {}}

    # Config entry starts with NO zones
    config_entry = Mock()
    config_entry.entry_id = "test_entry"
    config_entry.data = {CONF_ZONES: []}

    # Mock coordinator references the SAME config entry
    mock_coordinator = Mock()
    mock_coordinator.config_entry = config_entry  # SAME REFERENCE = BUG!
    mock_coordinator.data = {}

    hass.data[DOMAIN]["test_entry"] = {
        "coordinator": mock_coordinator,
        "client": Mock()
    }

    # Track if reload was called
    reload_called = []

    async def mock_reload(entry_id):
        reload_called.append(entry_id)
        print(f"  ✓ Full reload triggered for {entry_id}")

    hass.config_entries = Mock()
    hass.config_entries.async_reload = mock_reload

    print("\n1. Initial state: 0 zones configured")
    print(f"   old_zones: {config_entry.data.get(CONF_ZONES, [])}")

    # Simulate CSV import - updates config_entry.data IN PLACE
    print("\n2. CSV Import: Adding 3 zones")
    config_entry.data = {
        CONF_ZONES: [
            {"id": 1, "name": "Zone 1"},
            {"id": 2, "name": "Zone 2"},
            {"id": 3, "name": "Zone 3"},
        ]
    }
    print(f"   new_zones: {[z['name'] for z in config_entry.data[CONF_ZONES]]}")

    # The async_reload_entry listener fires
    print("\n3. async_reload_entry fires (update listener)")
    print("   Comparing old_zones vs new_zones...")
    print(f"   coordinator.config_entry.data is config_entry.data: {mock_coordinator.config_entry.data is config_entry.data}")

    await async_reload_entry(hass, config_entry)

    # Check result
    print("\n4. RESULT:")
    if len(reload_called) > 0:
        print(f"   ✓ PASS: Full reload was triggered")
        print(f"   ✓ Entities would be created")
        return True
    else:
        print(f"   ✗ FAIL: No reload triggered!")
        print(f"   ✗ BUG REPRODUCED: CSV import did nothing")
        print(f"   ✗ User must manually reload integration to see entities")
        return False


async def main():
    success = await test_csv_load_bug()
    print("\n" + "=" * 70)
    if not success:
        print("BUG CONFIRMED: This test proves Issue #1 exists")
        print("Next step: Implement fix and re-run test")
    else:
        print("Bug NOT reproduced (unexpected!)")
    print("=" * 70)
    return 0 if not success else 1  # Return 0 if bug reproduced (expected failure)


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

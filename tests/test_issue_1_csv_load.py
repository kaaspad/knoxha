"""Test Issue #1: CSV load does nothing until manual reload.

This test reproduces the bug where importing zones via CSV doesn't create
entities until a manual integration reload is performed.

Root cause: async_reload_entry compares config_entry against itself after
the update has already happened, so it thinks nothing changed.
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

# Import from integration
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "knoxcham64i"))

from custom_components.knoxcham64i import async_reload_entry
from custom_components.knoxcham64i.const import DOMAIN, CONF_ZONES


@pytest.mark.asyncio
async def test_csv_load_creates_entities_immediately():
    """Test that CSV zone import triggers entity creation without manual reload.

    Repro steps:
    1. Start with no zones configured
    2. Import zones via CSV in config flow
    3. Verify entities are created immediately (full reload triggered)

    Expected: full reload triggered, entities created
    Actual (buggy): "only inputs changed" logged, no entities created
    """
    # Setup mock HA
    hass = Mock(spec=HomeAssistant)
    hass.data = {DOMAIN: {}}

    # Mock config entry - starts with no zones
    config_entry = Mock(spec=ConfigEntry)
    config_entry.entry_id = "test_entry"
    config_entry.data = {CONF_ZONES: []}

    # Mock coordinator with reference to old config entry
    mock_coordinator = Mock()
    mock_coordinator.config_entry = config_entry  # Same reference!
    mock_coordinator.data = {}

    # Store coordinator in hass.data
    hass.data[DOMAIN]["test_entry"] = {
        "coordinator": mock_coordinator,
        "client": Mock()
    }

    # Mock the reload function to track if it was called
    reload_called = []
    async def mock_reload(entry_id):
        reload_called.append(entry_id)

    hass.config_entries = Mock()
    hass.config_entries.async_reload = mock_reload

    # Now simulate CSV import updating zones (this happens in config_flow)
    # This is the key: config_entry.data is updated IN PLACE
    config_entry.data = {
        CONF_ZONES: [
            {"id": 1, "name": "Zone 1"},
            {"id": 2, "name": "Zone 2"},
            {"id": 3, "name": "Zone 3"},
        ]
    }

    # The update listener fires (async_reload_entry)
    # BUG: At this point, both coordinator.config_entry.data and entry.data
    # point to the SAME dict, so old_zones == new_zones
    await async_reload_entry(hass, config_entry)

    # ASSERTION: Full reload should have been triggered
    assert len(reload_called) > 0, (
        "BUG REPRODUCED: async_reload_entry did NOT trigger full reload "
        "even though zones were added. This is because it compared the "
        "updated config_entry against itself, making old_zones == new_zones."
    )

    assert reload_called[0] == "test_entry"


@pytest.mark.asyncio
async def test_input_only_change_does_not_reload():
    """Test that changing ONLY inputs does NOT trigger full reload.

    This is the correct behavior we want to preserve.
    """
    hass = Mock(spec=HomeAssistant)
    hass.data = {DOMAIN: {}}

    config_entry = Mock(spec=ConfigEntry)
    config_entry.entry_id = "test_entry"
    config_entry.data = {
        CONF_ZONES: [{"id": 1, "name": "Zone 1"}],
        "inputs": [{"id": 1, "name": "Input 1"}]
    }

    mock_coordinator = Mock()
    mock_coordinator.config_entry = config_entry
    mock_coordinator.data = {1: Mock(input_id=1, volume=10, is_muted=False)}
    mock_coordinator.async_set_updated_data = Mock()

    hass.data[DOMAIN]["test_entry"] = {
        "coordinator": mock_coordinator,
        "client": Mock()
    }

    reload_called = []
    async def mock_reload(entry_id):
        reload_called.append(entry_id)

    hass.config_entries = Mock()
    hass.config_entries.async_reload = mock_reload

    # Update ONLY inputs (zones unchanged)
    config_entry.data = {
        CONF_ZONES: [{"id": 1, "name": "Zone 1"}],  # SAME zones
        "inputs": [{"id": 1, "name": "Input 1"}, {"id": 2, "name": "Input 2"}]  # NEW input
    }

    await async_reload_entry(hass, config_entry)

    # Should NOT reload, just notify entities
    assert len(reload_called) == 0, "Input-only change should not trigger full reload"
    assert mock_coordinator.async_set_updated_data.called, "Should notify entities of input change"


if __name__ == "__main__":
    # Run tests
    import asyncio
    print("Running Issue #1 Tests...")
    print("\nTest 1: CSV load triggers entity creation")
    try:
        asyncio.run(test_csv_load_creates_entities_immediately())
        print("❌ TEST FAILED - Bug NOT reproduced (unexpected!)")
    except AssertionError as e:
        print(f"✓ BUG REPRODUCED: {e}")

    print("\nTest 2: Input-only change doesn't reload")
    try:
        asyncio.run(test_input_only_change_does_not_reload())
        print("✓ TEST PASSED")
    except AssertionError as e:
        print(f"❌ TEST FAILED: {e}")

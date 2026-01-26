"""The Knox Chameleon64i integration."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .chameleon_client import ChameleonClient, ChameleonError
from .const import DOMAIN, DEFAULT_PORT, CONF_ZONES, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.MEDIA_PLAYER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Knox Chameleon64i from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    zones = entry.data.get(CONF_ZONES, [])

    # Create client
    client = ChameleonClient(host=host, port=port, timeout=5.0, max_retries=3)

    # Test connection
    try:
        await client.connect()
        connection_ok = await client.test_connection()
        if not connection_ok:
            _LOGGER.error("Failed to connect to Knox device at %s:%s", host, port)
            raise ConfigEntryNotReady(f"Cannot connect to Knox device at {host}:{port}")

        _LOGGER.info("Successfully connected to Knox device at %s:%s", host, port)

    except ChameleonError as err:
        _LOGGER.error("Error connecting to Knox device: %s", err)
        raise ConfigEntryNotReady(f"Cannot connect to Knox device: {err}") from err

    # Create coordinator for state updates
    async def async_update_data() -> dict[int, Any]:
        """Fetch data from Knox device."""
        try:
            # Get list of zone IDs
            zone_ids = [zone["id"] for zone in zones]

            if not zone_ids:
                _LOGGER.debug("No zones configured, skipping update")
                return {}

            # Fetch state for all zones
            _LOGGER.debug("Updating state for zones: %s", zone_ids)
            states = await client.get_all_zones_state(zone_ids)
            _LOGGER.debug("Got states: %s", {k: f"input={v.input_id}, vol={v.volume}, mute={v.is_muted}" for k, v in states.items()})

            return states

        except ChameleonError as err:
            _LOGGER.error("Error fetching zone states: %s", err)
            raise UpdateFailed(f"Error communicating with Knox device: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"Knox Chameleon64i ({host})",
        update_method=async_update_data,
        update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Store client and coordinator
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    # Forward entry setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Add update listener for config changes
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Disconnect client
        data = hass.data[DOMAIN].pop(entry.entry_id)
        client = data["client"]
        await client.disconnect()
        _LOGGER.info("Disconnected from Knox device")

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)

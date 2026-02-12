"""The Knox Chameleon64i integration."""
from __future__ import annotations

from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .chameleon_client import ChameleonClient, ChameleonError
from .chameleon_client.models import ZoneState
from .const import DOMAIN, DEFAULT_PORT, CONF_ZONES, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

# Cache storage version and key
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.zone_state_cache"

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.SELECT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Knox Chameleon64i from a config entry."""
    startup_start = time.monotonic()
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    zones = entry.data.get(CONF_ZONES, [])

    _LOGGER.info(
        "knox: startup stage=begin host=%s zones=%d",
        host, len(zones)
    )

    # Create state cache store (persists across restarts)
    store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry.entry_id}")

    # Load cached state for fast startup
    cache_start = time.monotonic()
    cached_data = await store.async_load()
    cached_state: dict[int, Any] = {}

    if cached_data and isinstance(cached_data, dict):
        # Convert string keys back to int and dicts back to ZoneState objects
        # (JSON serialization converts dataclasses to dicts and int keys to strings)
        for k, v in cached_data.get("zones", {}).items():
            zone_id = int(k)
            if isinstance(v, dict):
                cached_state[zone_id] = ZoneState(
                    zone_id=v.get("zone_id", zone_id),
                    input_id=v.get("input_id"),
                    volume=v.get("volume"),
                    is_muted=v.get("is_muted"),
                )
            else:
                cached_state[zone_id] = v
        cache_age = cached_data.get("timestamp", 0)
        cache_ms = int((time.monotonic() - cache_start) * 1000)
        _LOGGER.info(
            "knox: startup stage=cache_load duration_ms=%d zones=%d cache_age_s=%.0f",
            cache_ms, len(cached_state), time.time() - cache_age
        )
    else:
        cache_ms = int((time.monotonic() - cache_start) * 1000)
        _LOGGER.info(
            "knox: startup stage=cache_load duration_ms=%d zones=0 (no cache)",
            cache_ms
        )

    # Create client
    client = ChameleonClient(host=host, port=port, timeout=5.0, max_retries=3)

    # Test connection and start scheduler
    connect_start = time.monotonic()
    try:
        await client.connect()
        connection_ok = await client.test_connection()
        if not connection_ok:
            _LOGGER.error("Failed to connect to Knox device at %s:%s", host, port)
            raise ConfigEntryNotReady(f"Cannot connect to Knox device at {host}:{port}")

        connect_ms = int((time.monotonic() - connect_start) * 1000)
        _LOGGER.info(
            "knox: startup stage=connect duration_ms=%d ok=true",
            connect_ms
        )

    except ChameleonError as err:
        connect_ms = int((time.monotonic() - connect_start) * 1000)
        _LOGGER.error(
            "knox: startup stage=connect duration_ms=%d ok=false err=%s",
            connect_ms, err
        )
        raise ConfigEntryNotReady(f"Cannot connect to Knox device: {err}") from err

    # Create coordinator for state updates
    async def async_update_data() -> dict[int, Any]:
        """Fetch data from Knox device.

        Uses LOW priority commands which yield to HIGH (user actions).
        The scheduler ensures user commands preempt refresh queries.
        """
        refresh_start = time.monotonic()
        try:
            zone_ids = [zone["id"] for zone in zones]

            if not zone_ids:
                _LOGGER.debug("No zones configured, skipping update")
                return {}

            # Log queue status before refresh
            high_pending = client.high_queue_size
            if high_pending > 0:
                _LOGGER.info(
                    "knox: coordinator starting refresh with %d HIGH commands pending",
                    high_pending
                )

            # Fetch state for all zones
            # VTB queries go into LOW queue and yield to HIGH commands automatically
            states = await client.get_all_zones_state(zone_ids)

            refresh_ms = int((time.monotonic() - refresh_start) * 1000)
            _LOGGER.info(
                "knox: coordinator stage=refresh duration_ms=%d zones=%d ok=true",
                refresh_ms, len(zone_ids)
            )

            # Save to cache for next startup (non-blocking)
            hass.async_create_task(
                store.async_save({"zones": states, "timestamp": time.time()})
            )

            return states

        except ChameleonError as err:
            refresh_ms = int((time.monotonic() - refresh_start) * 1000)
            _LOGGER.error(
                "knox: coordinator stage=refresh duration_ms=%d ok=false err=%s",
                refresh_ms, err
            )
            raise UpdateFailed(f"Error communicating with Knox device: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"Knox Chameleon64i ({host})",
        update_method=async_update_data,
        update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
    )

    # Fast startup: use cached state if available, refresh in background
    zone_ids = [zone["id"] for zone in zones]
    if cached_state and all(z in cached_state for z in zone_ids):
        # All zones have cached state - use it immediately
        _LOGGER.info(
            "knox: startup stage=using_cache zones=%d (skipping initial refresh)",
            len(zone_ids)
        )
        coordinator.async_set_updated_data(cached_state)

        # Schedule background refresh to update state (non-blocking)
        async def background_refresh():
            await coordinator.async_request_refresh()
            _LOGGER.info("knox: startup background refresh complete")

        hass.async_create_task(background_refresh())
    else:
        # No cache or incomplete cache - must do initial refresh (blocking)
        initial_refresh_start = time.monotonic()
        await coordinator.async_config_entry_first_refresh()
        initial_refresh_ms = int((time.monotonic() - initial_refresh_start) * 1000)
        _LOGGER.info(
            "knox: startup stage=initial_refresh duration_ms=%d zones=%d",
            initial_refresh_ms, len(zones)
        )

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

    total_startup_ms = int((time.monotonic() - startup_start) * 1000)
    _LOGGER.info(
        "knox: startup stage=complete duration_ms=%d zones=%d",
        total_startup_ms, len(zones)
    )

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
    """Reload config entry when zones change, or just update entities when inputs change."""
    # Get previous data to compare what changed
    data = hass.data[DOMAIN].get(entry.entry_id)
    if not data:
        # First load or something went wrong, do full reload
        await hass.config_entries.async_reload(entry.entry_id)
        return

    coordinator = data["coordinator"]

    # Compare against RUNTIME state (coordinator.data keys) not config_entry
    old_zone_ids = set(coordinator.data.keys()) if coordinator.data else set()
    new_zone_ids = set(zone["id"] for zone in entry.data.get(CONF_ZONES, []))

    # Check if zones changed (added or removed)
    if old_zone_ids != new_zone_ids:
        _LOGGER.info(
            "Zones changed: %d -> %d zones, performing full reload",
            len(old_zone_ids),
            len(new_zone_ids)
        )
        await hass.config_entries.async_reload(entry.entry_id)
    else:
        # Only inputs changed - entities read inputs dynamically from config_entry
        # Just notify entities to update their state (no polling needed)
        _LOGGER.info("Only inputs changed, notifying entities without polling")
        coordinator.async_set_updated_data(coordinator.data)

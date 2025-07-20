"""The Knox Chameleon64i integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant

from .pyknox import get_knox

from .const import DOMAIN, DEFAULT_PORT, CONF_INPUTS

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Knox Chameleon64i from a config entry."""
    try:
        knox = await hass.async_add_executor_job(
            get_knox,
            entry.data[CONF_HOST],
            entry.data.get(CONF_PORT, DEFAULT_PORT),
        )

        if knox is None:
            _LOGGER.error("Knox object is None after connection attempt for host: %s", entry.data[CONF_HOST])
            return False

        _LOGGER.debug("Knox object initialized successfully: %s", knox)

        # Store knox instance and inputs in hass.data
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = {
            "knox": knox,
            "inputs": entry.data.get(CONF_INPUTS, []),
        }

        # Forward the setup to the media_player platform and return its result
        await hass.config_entries.async_forward_entry_setups(entry, ["media_player"])

        # Add a listener for config entry updates
        entry.add_update_listener(async_reload_entry)

        _LOGGER.debug("Knox Chameleon64i async_setup_entry returning True")
        return True

    except Exception as err:
        _LOGGER.error("Error setting up Knox Chameleon64i integration for host %s: %s", entry.data[CONF_HOST], err)
        return False

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    try:
        data = hass.data[DOMAIN][entry.entry_id]
        knox = data["knox"]
        await hass.async_add_executor_job(knox.disconnect)
        hass.data[DOMAIN].pop(entry.entry_id)

        return await hass.config_entries.async_unload_platforms(entry, ["media_player"])
    except Exception as err:
        _LOGGER.error("Error unloading Knox Chameleon64i integration for entry %s: %s", entry.entry_id, err)
        return False

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id) 
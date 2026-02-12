"""Select platform for Knox Chameleon64i - Input Source selection.

Workaround for HA frontend bug where the media player more-info dialog's
source dropdown doesn't fire the select_source service call. This was caused
by the @wa-select event handler being placed on the wrong element during
the ha-dropdown migration (fixed in frontend PR #29400, but may not be
included in all HA 2026.2.x builds).

This select entity provides a standalone source dropdown that works
regardless of the media player more-info dialog state.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .chameleon_client import ChameleonClient, ChameleonError
from .const import (
    DOMAIN,
    CONF_ZONES,
    CONF_INPUTS,
    CONF_ZONE_NAME,
    CONF_ZONE_ID,
    CONF_HA_AREA,
    CONF_INPUT_NAME,
    CONF_INPUT_ID,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Knox Chameleon64i source select entities."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    client = data["client"]
    coordinator = data["coordinator"]

    zones = config_entry.data.get(CONF_ZONES, [])

    entities = []
    for zone in zones:
        entities.append(
            ChameleonSourceSelect(
                coordinator=coordinator,
                client=client,
                zone_id=zone[CONF_ZONE_ID],
                zone_name=zone[CONF_ZONE_NAME],
                ha_area=zone.get(CONF_HA_AREA),
                config_entry=config_entry,
                entry_id=config_entry.entry_id,
            )
        )

    async_add_entities(entities)


class ChameleonSourceSelect(CoordinatorEntity, SelectEntity):
    """Select entity for Knox zone input source."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:video-input-hdmi"

    def __init__(
        self,
        coordinator,
        client: ChameleonClient,
        zone_id: int,
        zone_name: str,
        ha_area: str | None,
        config_entry: ConfigEntry,
        entry_id: str,
    ) -> None:
        """Initialize the source select entity."""
        super().__init__(coordinator)

        self._client = client
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._ha_area = ha_area
        self._config_entry = config_entry
        self._entry_id = entry_id

        self._attr_unique_id = f"{entry_id}_{zone_id}_source"
        self._attr_name = "Input Source"
        self._attr_translation_key = "input_source"

        self._last_command_time: float = 0.0
        self._command_grace_period: float = 30.0

    @property
    def _inputs(self) -> list[dict[str, Any]]:
        """Get current input list from config entry."""
        return self._config_entry.data.get(CONF_INPUTS, [])

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info - same device as the media player entity."""
        device_info_dict = {
            "identifiers": {(DOMAIN, f"{self._entry_id}_{self._zone_id}")},
            "name": self._zone_name,
            "model": "Chameleon64i Zone",
            "manufacturer": "Knox Video",
        }
        if self._ha_area:
            device_info_dict["suggested_area"] = self._ha_area
        return DeviceInfo(**device_info_dict)

    @property
    def options(self) -> list[str]:
        """Return list of available input sources."""
        return [inp[CONF_INPUT_NAME] for inp in self._inputs]

    @property
    def current_option(self) -> str | None:
        """Return current input source."""
        zone_state = self.coordinator.data.get(self._zone_id)
        if not zone_state or zone_state.input_id is None:
            return None

        for inp in self._inputs:
            if inp[CONF_INPUT_ID] == zone_state.input_id:
                return inp[CONF_INPUT_NAME]

        return None

    async def async_select_option(self, option: str) -> None:
        """Change the input source."""
        _LOGGER.info("Zone %d: select entity source change to '%s'", self._zone_id, option)
        try:
            input_id = None
            for inp in self._inputs:
                if inp[CONF_INPUT_NAME] == option:
                    input_id = inp[CONF_INPUT_ID]
                    break

            if input_id is None:
                _LOGGER.error("Unknown source: %s", option)
                return

            await self._client.set_input(self._zone_id, input_id)
            self._last_command_time = time.monotonic()
            zone_state = self.coordinator.data.get(self._zone_id)
            if zone_state is not None:
                zone_state.input_id = input_id
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error(
                "Failed to select source %s for zone %d: %s",
                option, self._zone_id, err,
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._last_command_time > 0:
            elapsed = time.monotonic() - self._last_command_time
            if elapsed < self._command_grace_period:
                return
        self.async_write_ha_state()

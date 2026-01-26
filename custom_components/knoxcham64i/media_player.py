"""Media player platform for Knox Chameleon64i integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
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
    CONF_INPUT_NAME,
    CONF_INPUT_ID,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Knox Chameleon64i media players."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    client = data["client"]
    coordinator = data["coordinator"]

    zones = config_entry.data.get(CONF_ZONES, [])
    inputs = config_entry.data.get(CONF_INPUTS, [])

    entities = []
    for zone in zones:
        entities.append(
            ChameleonMediaPlayer(
                coordinator=coordinator,
                client=client,
                zone_id=zone[CONF_ZONE_ID],
                zone_name=zone[CONF_ZONE_NAME],
                inputs=inputs,
                entry_id=config_entry.entry_id,
            )
        )

    async_add_entities(entities)


class ChameleonMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Representation of a Knox Chameleon64i zone."""

    _attr_has_entity_name = True
    _attr_should_poll = False  # Coordinator handles polling

    def __init__(
        self,
        coordinator,
        client: ChameleonClient,
        zone_id: int,
        zone_name: str,
        inputs: list[dict[str, Any]],
        entry_id: str,
    ) -> None:
        """Initialize the zone."""
        super().__init__(coordinator)

        self._client = client
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._inputs = inputs
        self._entry_id = entry_id

        # Set unique ID
        self._attr_unique_id = f"{entry_id}_{zone_id}"
        self._attr_name = zone_name

        # Build source list
        self._attr_source_list = [inp[CONF_INPUT_NAME] for inp in inputs]

        # Set supported features
        self._attr_supported_features = (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.SELECT_SOURCE
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._zone_id}")},
            name=self._zone_name,
            model="Chameleon64i Zone",
            manufacturer="Knox Video",
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the state of the zone."""
        zone_state = self.coordinator.data.get(self._zone_id)
        if not zone_state:
            return None

        # Zone is ON if not muted
        if zone_state.is_muted is True:
            return MediaPlayerState.OFF
        elif zone_state.is_muted is False:
            return MediaPlayerState.ON

        return None

    @property
    def volume_level(self) -> float | None:
        """Return the volume level (0.0 to 1.0)."""
        zone_state = self.coordinator.data.get(self._zone_id)
        if not zone_state or zone_state.volume is None:
            return None

        # Convert Knox volume (0-63, inverted) to HA volume (0.0-1.0)
        # Knox: 0=loudest, 63=quietest
        # HA: 0.0=quietest, 1.0=loudest
        return 1.0 - (zone_state.volume / 63.0)

    @property
    def is_volume_muted(self) -> bool | None:
        """Return true if volume is muted."""
        zone_state = self.coordinator.data.get(self._zone_id)
        if not zone_state:
            return None
        return zone_state.is_muted

    @property
    def source(self) -> str | None:
        """Return the current input source."""
        zone_state = self.coordinator.data.get(self._zone_id)
        if not zone_state or zone_state.input_id is None:
            return None

        # Find input name from input_id
        for inp in self._inputs:
            if inp[CONF_INPUT_ID] == zone_state.input_id:
                return inp[CONF_INPUT_NAME]

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        zone_state = self.coordinator.data.get(self._zone_id)

        return {
            "knox_zone_id": self._zone_id,
            "knox_volume_raw": zone_state.volume if zone_state else None,
            "integration_version": "2.0.0",
        }

    async def async_turn_on(self) -> None:
        """Turn the zone on (unmute)."""
        try:
            await self._client.set_mute(self._zone_id, False)
            await self.coordinator.async_request_refresh()
        except ChameleonError as err:
            _LOGGER.error("Failed to turn on zone %d: %s", self._zone_id, err)

    async def async_turn_off(self) -> None:
        """Turn the zone off (mute)."""
        try:
            await self._client.set_mute(self._zone_id, True)
            await self.coordinator.async_request_refresh()
        except ChameleonError as err:
            _LOGGER.error("Failed to turn off zone %d: %s", self._zone_id, err)

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level (0.0 to 1.0)."""
        try:
            # Convert HA volume (0.0-1.0) to Knox volume (0-63, inverted)
            # HA: 0.0=quietest, 1.0=loudest
            # Knox: 0=loudest, 63=quietest
            knox_volume = int((1.0 - volume) * 63)
            knox_volume = max(0, min(63, knox_volume))  # Clamp to valid range

            await self._client.set_volume(self._zone_id, knox_volume)
            await self.coordinator.async_request_refresh()
        except ChameleonError as err:
            _LOGGER.error(
                "Failed to set volume for zone %d: %s", self._zone_id, err
            )

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the zone."""
        try:
            await self._client.set_mute(self._zone_id, mute)
            await self.coordinator.async_request_refresh()
        except ChameleonError as err:
            _LOGGER.error(
                "Failed to %s zone %d: %s",
                "mute" if mute else "unmute",
                self._zone_id,
                err,
            )

    async def async_select_source(self, source: str) -> None:
        """Select input source."""
        try:
            # Find input ID from source name
            input_id = None
            for inp in self._inputs:
                if inp[CONF_INPUT_NAME] == source:
                    input_id = inp[CONF_INPUT_ID]
                    break

            if input_id is None:
                _LOGGER.error("Unknown source: %s", source)
                return

            await self._client.set_input(self._zone_id, input_id)
            await self.coordinator.async_request_refresh()
        except ChameleonError as err:
            _LOGGER.error(
                "Failed to select source %s for zone %d: %s",
                source,
                self._zone_id,
                err,
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

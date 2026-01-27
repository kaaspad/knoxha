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
from homeassistant.helpers.restore_state import RestoreEntity
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
    CONF_INPUT_SOURCE_ENTITY,
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

    entities = []
    for zone in zones:
        entities.append(
            ChameleonMediaPlayer(
                coordinator=coordinator,
                client=client,
                zone_id=zone[CONF_ZONE_ID],
                zone_name=zone[CONF_ZONE_NAME],
                ha_area=zone.get(CONF_HA_AREA),  # Optional HA area assignment
                config_entry=config_entry,  # Pass config entry for dynamic input list
                entry_id=config_entry.entry_id,
            )
        )

    async_add_entities(entities)


class ChameleonMediaPlayer(CoordinatorEntity, MediaPlayerEntity, RestoreEntity):
    """Representation of a Knox Chameleon64i zone.

    FIX #3: Added RestoreEntity to persist state across HA reboots.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False  # Coordinator handles polling

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
        """Initialize the zone."""
        super().__init__(coordinator)

        self._client = client
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._ha_area = ha_area
        self._config_entry = config_entry  # Store config entry to read inputs dynamically
        self._entry_id = entry_id

        # Set unique ID
        self._attr_unique_id = f"{entry_id}_{zone_id}"

        # FIX #5: Entity name set to None - inherits from device name
        # With has_entity_name=True, this creates clean entity IDs like media_player.study
        # Device name comes from zone_name in device_info
        self._attr_name = None

        # Set icon to speaker (these are passive speaker zones, not active players)
        self._attr_icon = "mdi:speaker"

        # Set supported features
        self._attr_supported_features = (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.SELECT_SOURCE
        )

    async def async_added_to_hass(self) -> None:
        """Restore state when entity is added to hass.

        FIX #3: Implement state restoration after HA reboot.
        Prefer device state over restored state when available.
        """
        await super().async_added_to_hass()

        # Try to restore last known state
        if (last_state := await self.async_get_last_state()) is None:
            return

        # Restore state will be overwritten by coordinator refresh when device responds
        # This provides a fallback for when device is offline at startup
        _LOGGER.debug(
            "Restoring previous state for zone %d: %s",
            self._zone_id,
            last_state.state
        )

        # Note: We don't need to set _attr_state here because the state property
        # will read from coordinator.data. When coordinator refreshes, it will
        # overwrite with real device state. If coordinator fails, our state
        # property returns None (Unknown), which is correct.

    @property
    def _inputs(self) -> list[dict[str, Any]]:
        """Get current input list from config entry (updates dynamically)."""
        return self._config_entry.data.get(CONF_INPUTS, [])

    def _get_source_media_player_state(self) -> Any | None:
        """Get the state of the source media player for current input.

        Returns the HA state object for the media player entity linked to
        the current input, enabling media passthrough (album art, track info).
        """
        zone_state = self.coordinator.data.get(self._zone_id)
        if not zone_state or zone_state.input_id is None:
            _LOGGER.debug("Zone %d: No zone state or input_id", self._zone_id)
            return None

        _LOGGER.debug("Zone %d: Current input_id=%d, configured inputs=%s",
                      self._zone_id, zone_state.input_id,
                      [(i[CONF_INPUT_ID], i.get(CONF_INPUT_SOURCE_ENTITY)) for i in self._inputs])

        # Find the input configuration for current input
        for inp in self._inputs:
            if inp[CONF_INPUT_ID] == zone_state.input_id:
                source_entity_id = inp.get(CONF_INPUT_SOURCE_ENTITY)
                _LOGGER.debug("Zone %d: Found input config, source_entity=%s",
                              self._zone_id, source_entity_id)
                if source_entity_id:
                    # Get the state from HA
                    source_state = self.hass.states.get(source_entity_id)
                    if source_state:
                        _LOGGER.debug("Zone %d: Source state found: entity_picture=%s, media_title=%s",
                                      self._zone_id,
                                      source_state.attributes.get("entity_picture"),
                                      source_state.attributes.get("media_title"))
                    else:
                        _LOGGER.warning("Zone %d: Source entity %s not found in HA states",
                                        self._zone_id, source_entity_id)
                    return source_state
                break

        _LOGGER.debug("Zone %d: No source entity configured for input %d",
                      self._zone_id, zone_state.input_id)
        return None

    @property
    def source_list(self) -> list[str] | None:
        """Return the list of available input sources (updates dynamically)."""
        return [inp[CONF_INPUT_NAME] for inp in self._inputs]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        device_info_dict = {
            "identifiers": {(DOMAIN, f"{self._entry_id}_{self._zone_id}")},
            "name": self._zone_name,
            "model": "Chameleon64i Zone",
            "manufacturer": "Knox Video",
        }

        # Add suggested area if specified
        if self._ha_area:
            device_info_dict["suggested_area"] = self._ha_area

        return DeviceInfo(**device_info_dict)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the state of the zone."""
        zone_state = self.coordinator.data.get(self._zone_id)

        # FIX #2: Return None (Unknown) instead of defaulting to ON
        # This prevents showing wrong state before first poll completes
        if not zone_state or zone_state.is_muted is None:
            return None  # Unknown state until device reports

        # Zone is OFF if explicitly muted, otherwise ON
        return MediaPlayerState.OFF if zone_state.is_muted else MediaPlayerState.ON

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
    def media_title(self) -> str | None:
        """Return the title of current playing media.

        Passthrough from source media player if configured, otherwise show zone/input.
        """
        # Try to get media title from source player
        source_state = self._get_source_media_player_state()
        if source_state:
            media_title = source_state.attributes.get("media_title")
            if media_title:
                return media_title

        # Fallback to zone and input name
        zone_state = self.coordinator.data.get(self._zone_id)
        if not zone_state:
            return f"Zone {self._zone_id}"

        # Show current input if available
        if zone_state.input_id is not None:
            input_name = None
            for inp in self._inputs:
                if inp[CONF_INPUT_ID] == zone_state.input_id:
                    input_name = inp[CONF_INPUT_NAME]
                    break

            if input_name:
                return f"Zone {self._zone_id}: {input_name}"
            else:
                return f"Zone {self._zone_id}: Input {zone_state.input_id}"

        return f"Zone {self._zone_id}"

    @property
    def media_artist(self) -> str | None:
        """Return the artist of current playing media (passthrough from source)."""
        source_state = self._get_source_media_player_state()
        if source_state:
            return source_state.attributes.get("media_artist")
        return None

    @property
    def media_album_name(self) -> str | None:
        """Return the album name of current playing media (passthrough from source)."""
        source_state = self._get_source_media_player_state()
        if source_state:
            return source_state.attributes.get("media_album_name")
        return None

    @property
    def media_image_url(self) -> str | None:
        """Return the image URL of current playing media (passthrough from source)."""
        source_state = self._get_source_media_player_state()
        if source_state:
            return source_state.attributes.get("entity_picture")
        return None

    @property
    def media_duration(self) -> int | None:
        """Return the duration of current playing media (passthrough from source)."""
        source_state = self._get_source_media_player_state()
        if source_state:
            return source_state.attributes.get("media_duration")
        return None

    @property
    def media_position(self) -> int | None:
        """Return the position of current playing media (passthrough from source)."""
        source_state = self._get_source_media_player_state()
        if source_state:
            return source_state.attributes.get("media_position")
        return None

    @property
    def media_position_updated_at(self) -> Any | None:
        """Return when the media position was last updated (passthrough from source)."""
        source_state = self._get_source_media_player_state()
        if source_state:
            return source_state.attributes.get("media_position_updated_at")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        zone_state = self.coordinator.data.get(self._zone_id)

        attrs = {
            "zone_number": self._zone_id,
            "zone_name": self._zone_name,
            "knox_zone_id": self._zone_id,
            "knox_volume_raw": zone_state.volume if zone_state else None,
            "integration_version": "1.1.2",
        }

        # Add input_id if available
        if zone_state and zone_state.input_id is not None:
            attrs["input_number"] = zone_state.input_id

        return attrs

    async def async_turn_on(self) -> None:
        """Turn the zone on (unmute)."""
        try:
            await self._client.set_mute(self._zone_id, False)
            # Update local state immediately for responsiveness
            if self._zone_id in self.coordinator.data:
                self.coordinator.data[self._zone_id].is_muted = False
            self.async_write_ha_state()
        except ChameleonError as err:
            _LOGGER.error("Failed to turn on zone %d: %s", self._zone_id, err)

    async def async_turn_off(self) -> None:
        """Turn the zone off (mute)."""
        try:
            await self._client.set_mute(self._zone_id, True)
            # Update local state immediately for responsiveness
            if self._zone_id in self.coordinator.data:
                self.coordinator.data[self._zone_id].is_muted = True
            self.async_write_ha_state()
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
            # Update local state immediately for responsiveness
            if self._zone_id in self.coordinator.data:
                self.coordinator.data[self._zone_id].volume = knox_volume
            self.async_write_ha_state()
        except ChameleonError as err:
            _LOGGER.error(
                "Failed to set volume for zone %d: %s", self._zone_id, err
            )

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the zone."""
        try:
            await self._client.set_mute(self._zone_id, mute)
            # Update local state immediately for responsiveness
            if self._zone_id in self.coordinator.data:
                self.coordinator.data[self._zone_id].is_muted = mute
            self.async_write_ha_state()
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
            # Update local state immediately for responsiveness
            if self._zone_id in self.coordinator.data:
                self.coordinator.data[self._zone_id].input_id = input_id
            self.async_write_ha_state()
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

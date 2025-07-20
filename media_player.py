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
from homeassistant.const import (
    ATTR_ENTITY_ID,
    CONF_NAME,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SERVICE_VOLUME_SET,
    SERVICE_VOLUME_MUTE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import entity_platform
import voluptuous as vol

from .const import (
    DOMAIN,
    DEFAULT_NAME,
    CONF_ZONES,
    CONF_INPUTS,
    CONF_ZONE_NAME,
    CONF_ZONE_ID,
    CONF_INPUT_NAME,
    CONF_INPUT_ID,
    DEFAULT_INPUT,
)
from .pyknox import Knox

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up Knox Chameleon64i media players."""
    _LOGGER.debug("media_player.py: async_setup_entry called.")
    _LOGGER.debug("media_player.py: config_entry.entry_id: %s", config_entry.entry_id)
    _LOGGER.debug("media_player.py: hass.data[DOMAIN]: %s", hass.data.get(DOMAIN))

    data = hass.data[DOMAIN][config_entry.entry_id]
    _LOGGER.debug("media_player.py: Retrieved data: %s", data)

    knox = data["knox"]
    _LOGGER.debug("media_player.py: Retrieved knox object: %s", knox)

    zones = config_entry.data[CONF_ZONES]
    _LOGGER.debug("media_player.py: Retrieved zones: %s", zones)

    inputs = data["inputs"]
    _LOGGER.debug("media_player.py: Retrieved inputs: %s", inputs)

    entities = []
    for zone in zones:
        _LOGGER.debug("media_player.py: Creating KnoxMediaPlayer for zone: %s", zone)
        entities.append(
            KnoxMediaPlayer(
                hass,
                knox,
                zone[CONF_ZONE_ID],
                zone[CONF_ZONE_NAME],
                inputs,
                config_entry.entry_id,
            )
        )
    _LOGGER.debug("media_player.py: Created %d entities.", len(entities))

    try:
        _LOGGER.debug("Attempting to add entities to Home Assistant.")
        async_add_entities(entities)
        _LOGGER.debug("Entities successfully added to Home Assistant.")
    except Exception as e:
        _LOGGER.error("Error adding entities to Home Assistant: %s", e)
        return False

    # Register services
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "set_volume",
        {vol.Required("volume_level"): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0))},
        "async_set_volume_level",
    )
    platform.async_register_entity_service(
        "set_mute",
        {vol.Required("mute"): vol.Coerce(bool)},
        "async_mute_volume",
    )
    platform.async_register_entity_service(
        "select_source",
        {vol.Required("source"): str},
        "async_select_source",
    )

    return True

class KnoxMediaPlayer(MediaPlayerEntity):
    """Representation of a Knox Chameleon64i zone."""

    def __init__(
        self,
        hass: HomeAssistant,
        knox: Knox,
        zone_id: int,
        zone_name: str,
        inputs: list[dict[str, Any]],
        entry_id: str,
    ) -> None:
        """Initialize the zone."""
        self._hass = hass
        self._knox = knox
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._inputs = inputs
        self._entry_id = entry_id

        # Initialize _attr_ properties directly
        self._attr_state = MediaPlayerState.OFF
        self._attr_volume_level = 0.0
        self._attr_is_volume_muted = True

        if self._inputs:
            self._attr_source = self._inputs[0][CONF_INPUT_NAME]
            self._attr_source_list = [input[CONF_INPUT_NAME] for input in inputs]
        else:
            # Fallback to a default input if no inputs are configured
            self._attr_source = DEFAULT_INPUT[CONF_INPUT_NAME]
            self._attr_source_list = [DEFAULT_INPUT[CONF_INPUT_NAME]]

        self._attr_unique_id = f"{entry_id}_{zone_id}"

        _LOGGER.debug(
            "KnoxMediaPlayer initialized for zone %s. State: %s, Volume: %s, Muted: %s, Source: %s, Source List: %s",
            self._zone_name, self._attr_state, self._attr_volume_level, self._attr_is_volume_muted, self._attr_source, self._attr_source_list
        )

    @property
    def name(self) -> str:
        """Return the name of the zone."""
        return self._zone_name

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the zone."""
        return self._attr_state

    @property
    def volume_level(self) -> float:
        """Return the volume level of the zone."""
        return self._attr_volume_level

    @property
    def is_volume_muted(self) -> bool:
        """Return true if the zone is muted."""
        return self._attr_is_volume_muted

    @property
    def source(self) -> str | None:
        """Return the current input source."""
        return self._attr_source

    @property
    def source_list(self) -> list[str]:
        """Return the list of available input sources."""
        return self._attr_source_list

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return the supported features."""
        return (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.SELECT_SOURCE
            | MediaPlayerEntityFeature.PLAY_MEDIA
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{self._zone_id}")},
            name=self._zone_name,
            model="Chameleon64i Zone",
            manufacturer="Knox",
        )

    async def async_turn_on(self) -> None:
        """Turn the zone on."""
        try:
            await self._hass.async_add_executor_job(
                self._knox.set_mute,
                self._zone_id,
                False,  # Unmute
            )
            self._attr_state = MediaPlayerState.ON
            self._attr_is_volume_muted = False
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Error turning on zone %s: %s", self._zone_id, err)

    async def async_turn_off(self) -> None:
        """Turn the zone off."""
        try:
            await self._hass.async_add_executor_job(
                self._knox.set_mute,
                self._zone_id,
                True,  # Mute
            )
            self._attr_state = MediaPlayerState.OFF
            self._attr_is_volume_muted = True
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Error turning off zone %s: %s", self._zone_id, err)

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume level."""
        try:
            # Convert volume (0-1) to Knox scale (0-63)
            # volume is 0-1 from HA, where 0 is lowest and 1 is highest
            # Knox uses 0 (lowest) to 63 (highest)
            volume_knox = int((1 - volume) * 63)  # This will map 0->63 and 1->0
            await self._hass.async_add_executor_job(
                self._knox.set_volume,
                self._zone_id,
                volume_knox,
            )
            self._attr_volume_level = volume
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Error setting volume for zone %s: %s", self._zone_id, err)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the zone."""
        try:
            await self._hass.async_add_executor_job(
                self._knox.set_mute,
                self._zone_id,
                mute,
            )
            self._attr_is_volume_muted = mute # Optimistically update internal state
            self._attr_state = MediaPlayerState.OFF if mute else MediaPlayerState.ON # Optimistically update internal state
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Error setting mute for zone %s: %s", self._zone_id, err)

    async def async_select_source(self, source: str) -> None:
        """Select the input source."""
        try:
            # Find the input ID for the selected source
            input_id = next(
                (input[CONF_INPUT_ID] for input in self._inputs if input[CONF_INPUT_NAME] == source),
                None,
            )
            if input_id is not None:
                await self._hass.async_add_executor_job(
                    self._knox.set_input,
                    self._zone_id,
                    input_id,
                )
                self._attr_source = source # Optimistically update internal state
                self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Error selecting source for zone %s: %s", self._zone_id, err)

    async def async_play_media(self, media_content_type: str, media_id: str, **kwargs: Any) -> None:
        """Play media via the Knox device.
        This integration does not directly play media. Please use an associated media player.
        """
        _LOGGER.info(
            "Knox Chameleon64i does not directly support playing media. Please use an associated media player for zone %s.",
            self._zone_name
        )
        # Optionally, you could try to select the input if media_id matches an input name
        # However, for cleanup, we are removing the delegation logic for now.

    async def async_update(self) -> None:
        """Update the state of the zone."""
        try:
            # Get current volume from Knox (0 to 63)
            volume_knox = await self._hass.async_add_executor_job(
                self._knox.get_volume,
                self._zone_id,
            )
            # Only update volume if we got a valid value
            if volume_knox is not None:
                # Convert Knox volume (0 to 63) to HA volume (0 to 1)
                # 63 -> 0, 0 -> 1
                self._attr_volume_level = 1 - (volume_knox / 63)
            else:
                _LOGGER.debug("No volume value returned for zone %s", self._zone_id)

            # Get mute state
            is_muted = await self._hass.async_add_executor_job(
                self._knox.get_mute,
                self._zone_id,
            )
            if is_muted is not None:
                self._attr_is_volume_muted = is_muted
                # Update state based on mute
                self._attr_state = MediaPlayerState.OFF if is_muted else MediaPlayerState.ON
            else:
                _LOGGER.debug("No mute state returned for zone %s", self._zone_id)

            # Get current input
            current_input = await self._hass.async_add_executor_job(
                self._knox.get_input,
                self._zone_id,
            )
            # Find the input name that matches the current input ID
            if current_input is not None:
                for input in self._inputs:
                    if input[CONF_INPUT_ID] == current_input:
                        self._attr_source = input[CONF_INPUT_NAME]
                        break
            else:
                _LOGGER.debug("No input value returned for zone %s", self._zone_id)

            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Error updating zone %s: %s", self._zone_id, err)

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        self.async_write_ha_state() # Ensure state is written to Home Assistant upon addition 
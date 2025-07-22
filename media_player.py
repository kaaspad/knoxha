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
from homeassistant.helpers.event import async_track_time_interval
import voluptuous as vol
import asyncio
from datetime import timedelta

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
    
    # Debug services
    platform.async_register_entity_service(
        "knox_debug_command",
        {
            vol.Required("command"): str,
            vol.Optional("expect_response", default=True): bool,
        },
        "async_debug_command",
    )
    
    platform.async_register_entity_service(
        "knox_test_all_functions",
        {
            vol.Optional("test_input", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=64)),
            vol.Optional("test_volume", default=32): vol.All(vol.Coerce(int), vol.Range(min=0, max=63)),
        },
        "async_test_all_functions",
    )
    
    platform.async_register_entity_service(
        "knox_get_device_info",
        {},
        "async_get_device_info",
    )
    
    platform.async_register_entity_service(
        "knox_start_debug_polling",
        {vol.Optional("interval", default=30): vol.All(vol.Coerce(int), vol.Range(min=5, max=300))},
        "async_start_debug_polling",
    )
    
    platform.async_register_entity_service(
        "knox_stop_debug_polling",
        {},
        "async_stop_debug_polling",
    )
    
    platform.async_register_entity_service(
        "knox_test_volume_conversion",
        {},
        "async_test_volume_conversion",
    )
    
    platform.async_register_entity_service(
        "knox_fix_audio",
        {vol.Optional("test_volume", default=16): vol.All(vol.Coerce(int), vol.Range(min=0, max=63))},
        "async_fix_audio",
    )
    
    platform.async_register_entity_service(
        "knox_diagnose_zone",
        {},
        "async_diagnose_zone",
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
        self._debug_polling = False
        self._debug_polling_interval = 30  # seconds
        self._debug_cancel_polling = None

        # Initialize _attr_ properties directly  
        self._attr_state = MediaPlayerState.OFF
        self._attr_volume_level = 0.5  # Start at 50% instead of 0% (silent)
        self._attr_is_volume_muted = False  # Start unmuted, will be updated from device

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
            _LOGGER.debug("DEBUG: Setting volume level %.2f for zone %d", volume, self._zone_id)
            # Convert volume (0-1) to Knox scale (0-63)
            # volume is 0-1 from HA, where 0 is lowest and 1 is highest
            # Knox uses 0 (lowest) to 63 (highest)
            volume_knox = int((1 - volume) * 63)  # This will map 0->63 and 1->0
            _LOGGER.debug("DEBUG: HA volume %.2f -> Knox volume %d (formula: int((1 - %.2f) * 63))", volume, volume_knox, volume)
            
            result = await self._hass.async_add_executor_job(
                self._knox.set_volume,
                self._zone_id,
                volume_knox,
            )
            _LOGGER.debug("DEBUG: set_volume returned: %s", result)
            self._attr_volume_level = volume
            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("DEBUG: Error setting volume for zone %s: %s", self._zone_id, err)

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
            _LOGGER.debug("DEBUG: Selecting source '%s' for zone %d", source, self._zone_id)
            _LOGGER.debug("DEBUG: Available inputs: %s", self._inputs)
            
            # Find the input ID for the selected source
            input_id = next(
                (input[CONF_INPUT_ID] for input in self._inputs if input[CONF_INPUT_NAME] == source),
                None,
            )
            _LOGGER.debug("DEBUG: Found input_id %s for source '%s'", input_id, source)
            
            if input_id is not None:
                _LOGGER.debug("DEBUG: Setting input %d for zone %d", input_id, self._zone_id)
                result = await self._hass.async_add_executor_job(
                    self._knox.set_input,
                    self._zone_id,
                    input_id,
                )
                _LOGGER.debug("DEBUG: set_input returned: %s", result)
                self._attr_source = source # Optimistically update internal state
                self.async_write_ha_state()
            else:
                _LOGGER.error("DEBUG: No input_id found for source '%s'", source)
        except Exception as err:
            _LOGGER.error("DEBUG: Error selecting source for zone %s: %s", self._zone_id, err)

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
            _LOGGER.debug("DEBUG: Updating state for zone %d", self._zone_id)
            
            # Get current volume from Knox (0 to 63)
            volume_knox = await self._hass.async_add_executor_job(
                self._knox.get_volume,
                self._zone_id,
            )
            _LOGGER.debug("DEBUG: Retrieved Knox volume: %s", volume_knox)
            
            # Only update volume if we got a valid value
            if volume_knox is not None:
                # Convert Knox volume (0 to 63) to HA volume (0 to 1)
                # 63 -> 0, 0 -> 1
                old_volume = self._attr_volume_level
                self._attr_volume_level = 1 - (volume_knox / 63)
                _LOGGER.debug("DEBUG: Knox volume %d -> HA volume %.2f (was %.2f)", volume_knox, self._attr_volume_level, old_volume)
            else:
                _LOGGER.debug("DEBUG: No volume value returned for zone %s", self._zone_id)

            # Get mute state
            is_muted = await self._hass.async_add_executor_job(
                self._knox.get_mute,
                self._zone_id,
            )
            _LOGGER.debug("DEBUG: Retrieved mute state: %s", is_muted)
            
            if is_muted is not None:
                old_muted = self._attr_is_volume_muted
                old_state = self._attr_state
                self._attr_is_volume_muted = is_muted
                # Update state based on mute
                self._attr_state = MediaPlayerState.OFF if is_muted else MediaPlayerState.ON
                _LOGGER.debug("DEBUG: Mute %s -> %s, State %s -> %s", old_muted, is_muted, old_state, self._attr_state)
            else:
                _LOGGER.debug("DEBUG: No mute state returned for zone %s", self._zone_id)

            # Get current input
            current_input = await self._hass.async_add_executor_job(
                self._knox.get_input,
                self._zone_id,
            )
            _LOGGER.debug("DEBUG: Retrieved current input: %s", current_input)
            
            # Find the input name that matches the current input ID
            if current_input is not None:
                old_source = self._attr_source
                found_source = None
                for input in self._inputs:
                    if input[CONF_INPUT_ID] == current_input:
                        self._attr_source = input[CONF_INPUT_NAME]
                        found_source = input[CONF_INPUT_NAME]
                        break
                _LOGGER.debug("DEBUG: Input ID %d -> source '%s' (was '%s')", current_input, found_source, old_source)
            else:
                _LOGGER.debug("DEBUG: No input value returned for zone %s", self._zone_id)

            self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("DEBUG: Error updating zone %s: %s", self._zone_id, err)

    async def async_added_to_hass(self) -> None:
        """When entity is added to Home Assistant."""
        self.async_write_ha_state() # Ensure state is written to Home Assistant upon addition
        
    async def async_will_remove_from_hass(self) -> None:
        """When entity is removed from Home Assistant."""
        if self._debug_cancel_polling:
            self._debug_cancel_polling()
            self._debug_cancel_polling = None
        
    async def async_debug_command(self, command: str, expect_response: bool = True) -> None:
        """Send a raw command to the Knox device for debugging."""
        try:
            _LOGGER.info("DEBUG SERVICE: Sending raw command '%s' to zone %d", command, self._zone_id)
            response = await self._hass.async_add_executor_job(
                self._knox._send_command,
                command,
            )
            _LOGGER.info("DEBUG SERVICE: Raw response: %s", repr(response))
            
            if expect_response:
                result = await self._hass.async_add_executor_job(
                    self._knox._parse_response,
                    response,
                )
                _LOGGER.info("DEBUG SERVICE: Parsed result: %s", result)
                
        except Exception as err:
            _LOGGER.error("DEBUG SERVICE: Error with command '%s': %s", command, err)
            
    async def async_test_all_functions(self, test_input: int = 1, test_volume: int = 32) -> None:
        """Test all Knox functions for this zone."""
        _LOGGER.info("DEBUG SERVICE: Starting comprehensive test for zone %d", self._zone_id)
        
        try:
            # Test get_input
            _LOGGER.info("DEBUG SERVICE: Testing get_input...")
            current_input = await self._hass.async_add_executor_job(
                self._knox.get_input,
                self._zone_id,
            )
            _LOGGER.info("DEBUG SERVICE: get_input result: %s", current_input)
            
            # Test set_input
            _LOGGER.info("DEBUG SERVICE: Testing set_input with input %d...", test_input)
            set_input_result = await self._hass.async_add_executor_job(
                self._knox.set_input,
                self._zone_id,
                test_input,
            )
            _LOGGER.info("DEBUG SERVICE: set_input result: %s", set_input_result)
            
            # Test get_volume
            _LOGGER.info("DEBUG SERVICE: Testing get_volume...")
            current_volume = await self._hass.async_add_executor_job(
                self._knox.get_volume,
                self._zone_id,
            )
            _LOGGER.info("DEBUG SERVICE: get_volume result: %s", current_volume)
            
            # Test set_volume
            _LOGGER.info("DEBUG SERVICE: Testing set_volume with volume %d...", test_volume)
            set_volume_result = await self._hass.async_add_executor_job(
                self._knox.set_volume,
                self._zone_id,
                test_volume,
            )
            _LOGGER.info("DEBUG SERVICE: set_volume result: %s", set_volume_result)
            
            # Test get_mute
            _LOGGER.info("DEBUG SERVICE: Testing get_mute...")
            current_mute = await self._hass.async_add_executor_job(
                self._knox.get_mute,
                self._zone_id,
            )
            _LOGGER.info("DEBUG SERVICE: get_mute result: %s", current_mute)
            
            # Test set_mute (unmute)
            _LOGGER.info("DEBUG SERVICE: Testing set_mute (unmute)...")
            set_mute_result = await self._hass.async_add_executor_job(
                self._knox.set_mute,
                self._zone_id,
                False,
            )
            _LOGGER.info("DEBUG SERVICE: set_mute (unmute) result: %s", set_mute_result)
            
            # Test set_mute (mute)
            _LOGGER.info("DEBUG SERVICE: Testing set_mute (mute)...")
            set_mute_result2 = await self._hass.async_add_executor_job(
                self._knox.set_mute,
                self._zone_id,
                True,
            )
            _LOGGER.info("DEBUG SERVICE: set_mute (mute) result: %s", set_mute_result2)
            
            # Test get_zone_state
            _LOGGER.info("DEBUG SERVICE: Testing get_zone_state...")
            zone_state = await self._hass.async_add_executor_job(
                self._knox.get_zone_state,
                self._zone_id,
            )
            _LOGGER.info("DEBUG SERVICE: get_zone_state result: %s", zone_state)
            
            _LOGGER.info("DEBUG SERVICE: Comprehensive test completed for zone %d", self._zone_id)
            
        except Exception as err:
            _LOGGER.error("DEBUG SERVICE: Error during comprehensive test: %s", err)
            
    async def async_get_device_info(self) -> None:
        """Get detailed device information and current state."""
        _LOGGER.info("DEBUG SERVICE: Getting device info for zone %d", self._zone_id)
        
        try:
            # Get current state
            _LOGGER.info("DEBUG SERVICE: Current HA state:")
            _LOGGER.info("  - Name: %s", self.name)
            _LOGGER.info("  - Zone ID: %d", self._zone_id)
            _LOGGER.info("  - State: %s", self._attr_state)
            _LOGGER.info("  - Volume Level: %.2f", self._attr_volume_level)
            _LOGGER.info("  - Is Muted: %s", self._attr_is_volume_muted)
            _LOGGER.info("  - Current Source: %s", self._attr_source)
            _LOGGER.info("  - Available Sources: %s", self._attr_source_list)
            _LOGGER.info("  - Unique ID: %s", self._attr_unique_id)
            
            # Get device state directly from Knox
            _LOGGER.info("DEBUG SERVICE: Knox device state:")
            zone_state = await self._hass.async_add_executor_job(
                self._knox.get_zone_state,
                self._zone_id,
            )
            _LOGGER.info("  - Zone State: %s", zone_state)
            
            # Connection info
            _LOGGER.info("DEBUG SERVICE: Knox connection info:")
            _LOGGER.info("  - Host: %s", self._knox._host)
            _LOGGER.info("  - Port: %d", self._knox._port)
            _LOGGER.info("  - Connected: %s", self._knox._connected)
            
            # Input mapping
            _LOGGER.info("DEBUG SERVICE: Input configuration:")
            for i, input_config in enumerate(self._inputs):
                _LOGGER.info("  - Input %d: ID=%s, Name='%s'", i+1, input_config[CONF_INPUT_ID], input_config[CONF_INPUT_NAME])
                
        except Exception as err:
            _LOGGER.error("DEBUG SERVICE: Error getting device info: %s", err)
            
    async def async_start_debug_polling(self, interval: int = 30) -> None:
        """Start debug polling to monitor device state changes."""
        if self._debug_polling:
            _LOGGER.info("DEBUG SERVICE: Debug polling already active for zone %d", self._zone_id)
            return
            
        self._debug_polling = True
        self._debug_polling_interval = interval
        _LOGGER.info("DEBUG SERVICE: Starting debug polling every %d seconds for zone %d", interval, self._zone_id)
        
        async def _poll_debug():
            if not self._debug_polling:
                return
            try:
                _LOGGER.info("DEBUG POLL: Polling zone %d state...", self._zone_id)
                await self.async_update()
                _LOGGER.info("DEBUG POLL: Zone %d - State: %s, Volume: %.2f, Muted: %s, Source: %s", 
                           self._zone_id, self._attr_state, self._attr_volume_level, 
                           self._attr_is_volume_muted, self._attr_source)
            except Exception as err:
                _LOGGER.error("DEBUG POLL: Error polling zone %d: %s", self._zone_id, err)
        
        self._debug_cancel_polling = async_track_time_interval(
            self._hass, lambda _: asyncio.create_task(_poll_debug()), timedelta(seconds=interval)
        )
        
    async def async_stop_debug_polling(self) -> None:
        """Stop debug polling."""
        if not self._debug_polling:
            _LOGGER.info("DEBUG SERVICE: Debug polling not active for zone %d", self._zone_id)
            return
            
        self._debug_polling = False
        if self._debug_cancel_polling:
            self._debug_cancel_polling()
            self._debug_cancel_polling = None
            
        _LOGGER.info("DEBUG SERVICE: Stopped debug polling for zone %d", self._zone_id)
        
    async def async_test_volume_conversion(self) -> None:
        """Test volume conversion between HA and Knox scales."""
        _LOGGER.info("DEBUG SERVICE: Testing volume conversion for zone %d", self._zone_id)
        
        # Test conversion from HA to Knox
        test_volumes_ha = [0.0, 0.25, 0.5, 0.75, 1.0]
        _LOGGER.info("DEBUG SERVICE: HA to Knox volume conversion:")
        for ha_vol in test_volumes_ha:
            knox_vol = int((1 - ha_vol) * 63)
            _LOGGER.info("  HA %.2f -> Knox %d", ha_vol, knox_vol)
            
        # Test conversion from Knox to HA
        test_volumes_knox = [0, 16, 32, 48, 63]
        _LOGGER.info("DEBUG SERVICE: Knox to HA volume conversion:")
        for knox_vol in test_volumes_knox:
            ha_vol = 1 - (knox_vol / 63)
            _LOGGER.info("  Knox %d -> HA %.2f", knox_vol, ha_vol)
            
        # Test actual volume setting and reading
        try:
            _LOGGER.info("DEBUG SERVICE: Testing actual volume operations...")
            
            # Get current volume
            current_knox = await self._hass.async_add_executor_job(
                self._knox.get_volume,
                self._zone_id,
            )
            if current_knox is not None:
                current_ha = 1 - (current_knox / 63)
                _LOGGER.info("  Current: Knox %d -> HA %.2f", current_knox, current_ha)
                
            # Test setting different volumes
            for ha_vol in [0.2, 0.5, 0.8]:
                _LOGGER.info("  Testing HA volume %.2f...", ha_vol)
                knox_vol = int((1 - ha_vol) * 63)
                _LOGGER.info("    Calculated Knox volume: %d", knox_vol)
                
                # Set the volume
                result = await self._hass.async_add_executor_job(
                    self._knox.set_volume,
                    self._zone_id,
                    knox_vol,
                )
                _LOGGER.info("    Set volume result: %s", result)
                
                # Wait a moment for the device to process
                await asyncio.sleep(1)
                
                # Read back the volume
                read_knox = await self._hass.async_add_executor_job(
                    self._knox.get_volume,
                    self._zone_id,
                )
                if read_knox is not None:
                    read_ha = 1 - (read_knox / 63)
                    _LOGGER.info("    Read back: Knox %d -> HA %.2f", read_knox, read_ha)
                else:
                    _LOGGER.warning("    Failed to read back volume")
                    
        except Exception as err:
            _LOGGER.error("DEBUG SERVICE: Error testing volume operations: %s", err)
            
    async def async_fix_audio(self, test_volume: int = 16) -> None:
        """Attempt to fix audio issues by setting volume and unmuting."""
        _LOGGER.info("AUDIO FIX: Starting audio fix for zone %d with volume %d", self._zone_id, test_volume)
        
        try:
            # Step 1: Get current state
            _LOGGER.info("AUDIO FIX: Step 1 - Getting current state...")
            current_volume = await self._hass.async_add_executor_job(
                self._knox.get_volume,
                self._zone_id,
            )
            current_mute = await self._hass.async_add_executor_job(
                self._knox.get_mute,
                self._zone_id,
            )
            _LOGGER.info("AUDIO FIX: Current state - Volume: %s, Muted: %s", current_volume, current_mute)
            
            # Step 2: Unmute if muted
            _LOGGER.info("AUDIO FIX: Step 2 - Ensuring unmuted...")
            unmute_result = await self._hass.async_add_executor_job(
                self._knox.set_mute,
                self._zone_id,
                False,  # Unmute
            )
            _LOGGER.info("AUDIO FIX: Unmute result: %s", unmute_result)
            
            # Step 3: Set a reasonable volume
            _LOGGER.info("AUDIO FIX: Step 3 - Setting volume to %d...", test_volume)
            volume_result = await self._hass.async_add_executor_job(
                self._knox.set_volume,
                self._zone_id,
                test_volume,
            )
            _LOGGER.info("AUDIO FIX: Set volume result: %s", volume_result)
            
            # Step 4: Wait and verify
            await asyncio.sleep(1)
            _LOGGER.info("AUDIO FIX: Step 4 - Verifying changes...")
            new_volume = await self._hass.async_add_executor_job(
                self._knox.get_volume,
                self._zone_id,
            )
            new_mute = await self._hass.async_add_executor_job(
                self._knox.get_mute,
                self._zone_id,
            )
            _LOGGER.info("AUDIO FIX: New state - Volume: %s, Muted: %s", new_volume, new_mute)
            
            # Step 5: Update HA state
            _LOGGER.info("AUDIO FIX: Step 5 - Updating Home Assistant state...")
            if new_volume is not None and new_volume >= 0:
                self._attr_volume_level = 1 - (new_volume / 63)
            if new_mute is not None:
                self._attr_is_volume_muted = new_mute
                self._attr_state = MediaPlayerState.OFF if new_mute else MediaPlayerState.ON
            self.async_write_ha_state()
            
            _LOGGER.info("AUDIO FIX: Audio fix completed for zone %d", self._zone_id)
            
            # Step 6: Recommendations
            if new_volume is not None and new_volume >= 0:
                ha_volume = 1 - (new_volume / 63)
                _LOGGER.info("AUDIO FIX: SUCCESS! Audio should now work.")
                _LOGGER.info("AUDIO FIX: Knox volume: %d (0=loudest, 63=quietest)", new_volume)
                _LOGGER.info("AUDIO FIX: HA volume: %.2f (0=quietest, 1=loudest)", ha_volume)
            else:
                _LOGGER.warning("AUDIO FIX: Volume is still invalid (%s). Check device connection.", new_volume)
                
        except Exception as err:
            _LOGGER.error("AUDIO FIX: Error during audio fix: %s", err)
            
    async def async_diagnose_zone(self) -> None:
        """Comprehensive diagnosis of zone audio problems."""
        _LOGGER.info("=== ZONE DIAGNOSIS START for Zone %d (%s) ===", self._zone_id, self._zone_name)
        
        try:
            # Current HA state
            _LOGGER.info("DIAGNOSIS: Home Assistant State:")
            _LOGGER.info("  - HA Volume Level: %.2f (0.0=quiet, 1.0=loud)", self._attr_volume_level)
            _LOGGER.info("  - HA Muted: %s", self._attr_is_volume_muted)
            _LOGGER.info("  - HA State: %s", self._attr_state)
            _LOGGER.info("  - HA Source: %s", self._attr_source)
            
            # Test all raw commands
            _LOGGER.info("DIAGNOSIS: Testing Raw Device Commands:")
            
            # Test volume query
            _LOGGER.info("DIAGNOSIS: 1. Testing volume query ($D%02d)...", self._zone_id)
            vol_response = await self._hass.async_add_executor_job(
                self._knox._send_command, f"$D{self._zone_id:02d}"
            )
            _LOGGER.info("  Raw volume response: %s", repr(vol_response))
            
            # Test crosspoint query  
            _LOGGER.info("DIAGNOSIS: 2. Testing crosspoint query (D%02d)...", self._zone_id)
            cp_response = await self._hass.async_add_executor_job(
                self._knox._send_command, f"D{self._zone_id:02d}"
            )
            _LOGGER.info("  Raw crosspoint response: %s", repr(cp_response))
            
            # Test setting volume to 20 (should be audible)
            _LOGGER.info("DIAGNOSIS: 3. Testing volume set to 20 ($V%02d20)...", self._zone_id) 
            set_vol_response = await self._hass.async_add_executor_job(
                self._knox._send_command, f"$V{self._zone_id:02d}20"
            )
            _LOGGER.info("  Set volume response: %s", repr(set_vol_response))
            
            # Test unmute
            _LOGGER.info("DIAGNOSIS: 4. Testing unmute ($M%02d0)...", self._zone_id)
            unmute_response = await self._hass.async_add_executor_job(
                self._knox._send_command, f"$M{self._zone_id:02d}0"
            )
            _LOGGER.info("  Unmute response: %s", repr(unmute_response))
            
            # Test input setting (Input 1 = IL Sonos)
            _LOGGER.info("DIAGNOSIS: 5. Testing input set to 1 (B%02d01)...", self._zone_id)
            input_response = await self._hass.async_add_executor_job(
                self._knox._send_command, f"B{self._zone_id:02d}01"
            )
            _LOGGER.info("  Set input response: %s", repr(input_response))
            
            # Wait and re-check state
            await asyncio.sleep(2)
            _LOGGER.info("DIAGNOSIS: 6. Re-checking device state...")
            
            # Check final volume
            final_volume = await self._hass.async_add_executor_job(
                self._knox.get_volume, self._zone_id
            )
            final_mute = await self._hass.async_add_executor_job(
                self._knox.get_mute, self._zone_id
            )
            final_input = await self._hass.async_add_executor_job(
                self._knox.get_input, self._zone_id
            )
            
            _LOGGER.info("DIAGNOSIS: Final Device State:")
            _LOGGER.info("  - Device Volume: %s (0=loudest, 63=quietest, -1=not set)", final_volume)
            _LOGGER.info("  - Device Muted: %s (True=muted, False=unmuted)", final_mute) 
            _LOGGER.info("  - Device Input: %s (should be 1 for IL Sonos)", final_input)
            
            # Recommendations
            _LOGGER.info("DIAGNOSIS: Recommendations:")
            if final_volume == -1 or final_volume is None:
                _LOGGER.warning("  ❌ PROBLEM: Volume is not set (-1) or unreadable")
                _LOGGER.info("     → Try: Set volume manually via Knox device")
            elif final_volume > 40:
                _LOGGER.warning("  ⚠️  PROBLEM: Volume %d is very quiet (>40)", final_volume)
                _LOGGER.info("     → Try: Lower number for louder audio")
            else:
                _LOGGER.info("  ✅ Volume %d should be audible", final_volume)
                
            if final_mute is True:
                _LOGGER.warning("  ❌ PROBLEM: Device is muted")
            else:
                _LOGGER.info("  ✅ Device is unmuted")
                
            if final_input != 1 and final_input != 2:
                _LOGGER.warning("  ❌ PROBLEM: Input %s is not 1 (IL Sonos) or 2 (US Sonos)", final_input)
            else:
                _LOGGER.info("  ✅ Input %s is configured", final_input)
                
        except Exception as err:
            _LOGGER.error("DIAGNOSIS: Error during diagnosis: %s", err)
            
        _LOGGER.info("=== ZONE DIAGNOSIS END ===")
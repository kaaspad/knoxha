"""Config flow for Knox Chameleon64i integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    DEFAULT_PORT,
    DEFAULT_NAME,
    CONF_HOST,
    CONF_PORT,
    CONF_ZONES,
    CONF_INPUTS,
    CONF_ZONE_NAME,
    CONF_ZONE_ID,
    CONF_INPUT_NAME,
    CONF_INPUT_ID,
    DEFAULT_ZONE_NAMES,
    DEFAULT_INPUT_NAMES,
    DEFAULT_INPUT,
)
from .pyknox import get_knox

_LOGGER = logging.getLogger(__name__)

class KnoxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Knox Chameleon64i."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow."""
        return KnoxOptionsFlowHandler(config_entry)

    def __init__(self) -> None:
        """Initialize the config flow."""
        _LOGGER.error("KnoxConfigFlow __init__ called!")
        self._host = None
        self._port = None
        self._zones = []
        self._inputs = []
        self._editing_zone = None
        self._editing_input = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                # Test connection
                knox = await self.hass.async_add_executor_job(
                    get_knox,
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                )
                await self.hass.async_add_executor_job(knox.disconnect)

                # Create entry with basic defaults - zones/inputs configured via options
                return self.async_create_entry(
                    title=f"Knox Chameleon64i ({user_input[CONF_HOST]})",
                    data={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_ZONES: [],  # Start with no zones - configure via options
                        CONF_INPUTS: [DEFAULT_INPUT],  # At least one default input
                    },
                )

            except Exception as err:
                _LOGGER.error("Error connecting to Knox device: %s", err)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration of connection settings."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        errors = {}

        if user_input is not None:
            try:
                # Test new connection
                knox = await self.hass.async_add_executor_job(
                    get_knox,
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                )
                await self.hass.async_add_executor_job(knox.disconnect)

                # Update entry with new connection info, preserve zones/inputs
                new_data = entry.data.copy()
                new_data[CONF_HOST] = user_input[CONF_HOST]
                new_data[CONF_PORT] = user_input[CONF_PORT]
                
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                
                return self.async_abort(reason="reconfigure_successful")

            except Exception as err:
                _LOGGER.error("Error connecting to Knox device: %s", err)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                    vol.Required(CONF_PORT, default=entry.data[CONF_PORT]): int,
                }
            ),
            errors=errors,
        )

class KnoxOptionsFlowHandler(config_entries.OptionsFlow):
    """Knox options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self._zones = config_entry.data.get(CONF_ZONES, []).copy()
        self._inputs = config_entry.data.get(CONF_INPUTS, []).copy()
        self._editing_zone = None
        self._editing_input = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Handle form choices
            if user_input.get("configure_zones"):
                return await self.async_step_zones()
            elif user_input.get("configure_inputs"):
                return await self.async_step_inputs()
            
            # Save the configuration and exit
            config_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
            new_data = config_entry.data.copy()
            new_data[CONF_ZONES] = self._zones
            new_data[CONF_INPUTS] = self._inputs
            
            self.hass.config_entries.async_update_entry(
                config_entry, data=new_data
            )
            return self.async_create_entry(title="", data={})

        # Build the configuration form
        zones_text = "\n".join(
            f"Zone {zone[CONF_ZONE_ID]}: {zone[CONF_ZONE_NAME]}"
            for zone in self._zones
        ) if self._zones else "No zones configured"
        
        inputs_text = "\n".join(
            f"Input {input[CONF_INPUT_ID]}: {input[CONF_INPUT_NAME]}"
            for input in self._inputs
        ) if self._inputs else "Default input only"

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("configure_zones", default=False): bool,
                vol.Required("configure_inputs", default=False): bool,
            }),
            description_placeholders={
                "current_zones": zones_text,
                "current_inputs": inputs_text,
            },
        )

    async def async_step_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure zones."""
        if user_input is not None:
            # Process the form data
            new_zones = self._zones.copy()
            errors = {}
            
            # Process up to 5 zone additions
            for i in range(1, 6):
                zone_id_key = f"zone_id_{i}"
                zone_name_key = f"zone_name_{i}"
                
                zone_id = user_input.get(zone_id_key)
                zone_name = user_input.get(zone_name_key, "").strip()
                
                if zone_id and zone_name:
                    zone_id = int(zone_id)
                    # Check for duplicates
                    if any(zone[CONF_ZONE_ID] == zone_id for zone in new_zones):
                        errors[zone_id_key] = "zone_already_configured"
                    else:
                        new_zones.append({
                            CONF_ZONE_ID: zone_id,
                            CONF_ZONE_NAME: zone_name
                        })
                elif zone_id and not zone_name:
                    errors[zone_name_key] = "zone_name_required"
                elif zone_name and not zone_id:
                    errors[zone_id_key] = "zone_id_required"
            
            # Handle deletions
            zones_to_delete = []
            for zone in self._zones:
                delete_key = f"delete_zone_{zone[CONF_ZONE_ID]}"
                if user_input.get(delete_key, False):
                    zones_to_delete.append(zone[CONF_ZONE_ID])
            
            # Remove deleted zones
            new_zones = [zone for zone in new_zones if zone[CONF_ZONE_ID] not in zones_to_delete]
            
            if not errors:
                # Sort zones by ID
                new_zones.sort(key=lambda x: x[CONF_ZONE_ID])
                self._zones = new_zones
                return await self.async_step_init()
            
            # If there are errors, show the form again with error messages
            return self._show_zones_form(errors)

        return self._show_zones_form()

    def _show_zones_form(self, errors=None):
        """Show the zones configuration form."""
        if errors is None:
            errors = {}
            
        # Get available zone IDs (not already configured)
        used_zone_ids = {zone[CONF_ZONE_ID] for zone in self._zones}
        available_zone_ids = {str(i): f"Zone {i}" for i in range(1, 65) if i not in used_zone_ids}
        
        # Build the schema dynamically
        schema_dict = {}
        
        # Show current zones with delete options
        if self._zones:
            for zone in self._zones:
                delete_key = f"delete_zone_{zone[CONF_ZONE_ID]}"
                schema_dict[vol.Optional(delete_key, default=False)] = bool
        
        # Add up to 5 new zone fields
        for i in range(1, 6):
            zone_id_key = f"zone_id_{i}"
            zone_name_key = f"zone_name_{i}"
            
            if available_zone_ids:
                schema_dict[vol.Optional(zone_id_key)] = vol.In(available_zone_ids)
                schema_dict[vol.Optional(zone_name_key)] = str
        
        # Current zones display
        current_zones = "\n".join(
            f"Zone {zone[CONF_ZONE_ID]}: {zone[CONF_ZONE_NAME]}"
            for zone in sorted(self._zones, key=lambda x: x[CONF_ZONE_ID])
        ) if self._zones else "No zones configured"

        return self.async_show_form(
            step_id="zones",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={
                "current_zones": current_zones,
                "help_text": "Select zone IDs from the dropdown and enter names. Check boxes to delete existing zones."
            },
        )

    async def async_step_inputs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Configure inputs.""" 
        if user_input is not None:
            # Process the form data
            new_inputs = self._inputs.copy()
            errors = {}
            
            # Process up to 5 input additions
            for i in range(1, 6):
                input_id_key = f"input_id_{i}"
                input_name_key = f"input_name_{i}"
                
                input_id = user_input.get(input_id_key)
                input_name = user_input.get(input_name_key, "").strip()
                
                if input_id and input_name:
                    input_id = int(input_id)
                    # Check for duplicates in the new list being built
                    if any(input[CONF_INPUT_ID] == input_id for input in new_inputs):
                        errors[input_id_key] = "input_already_configured"
                    else:
                        # Remove existing input with same ID if it exists, then add new one
                        new_inputs = [inp for inp in new_inputs if inp[CONF_INPUT_ID] != input_id]
                        new_inputs.append({
                            CONF_INPUT_ID: input_id,
                            CONF_INPUT_NAME: input_name
                        })
                elif input_id and not input_name:
                    errors[input_name_key] = "input_name_required"
                elif input_name and not input_id:
                    errors[input_id_key] = "input_id_required"
            
            # Handle deletions
            inputs_to_delete = []
            for input in self._inputs:
                delete_key = f"delete_input_{input[CONF_INPUT_ID]}"
                if user_input.get(delete_key, False):
                    inputs_to_delete.append(input[CONF_INPUT_ID])
            
            # Remove deleted inputs
            new_inputs = [input for input in new_inputs if input[CONF_INPUT_ID] not in inputs_to_delete]
            
            # Ensure at least default input if all deleted
            if not new_inputs:
                new_inputs = [DEFAULT_INPUT]
            
            if not errors:
                # Sort inputs by ID
                new_inputs.sort(key=lambda x: x[CONF_INPUT_ID])
                self._inputs = new_inputs
                return await self.async_step_init()
            
            # If there are errors, show the form again with error messages
            return self._show_inputs_form(errors)

        return self._show_inputs_form()

    def _show_inputs_form(self, errors=None):
        """Show the inputs configuration form."""
        if errors is None:
            errors = {}
            
        # Get available input IDs (show all inputs 1-64, user can replace existing ones)
        available_input_ids = {str(i): f"Input {i}" for i in range(1, 65)}
        
        # Build the schema dynamically
        schema_dict = {}
        
        # Show current inputs with delete options
        if self._inputs:
            for input in self._inputs:
                # Allow deletion of any input (system will add default input if none left)
                delete_key = f"delete_input_{input[CONF_INPUT_ID]}"
                schema_dict[vol.Optional(delete_key, default=False)] = bool
        
        # Add up to 5 new input fields
        for i in range(1, 6):
            input_id_key = f"input_id_{i}"
            input_name_key = f"input_name_{i}"
            
            if available_input_ids:
                schema_dict[vol.Optional(input_id_key)] = vol.In(available_input_ids)
                schema_dict[vol.Optional(input_name_key)] = str
        
        # Current inputs display
        current_inputs = "\n".join(
            f"Input {input[CONF_INPUT_ID]}: {input[CONF_INPUT_NAME]}"
            for input in sorted(self._inputs, key=lambda x: x[CONF_INPUT_ID])
        ) if self._inputs else "No inputs configured"

        return self.async_show_form(
            step_id="inputs",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={
                "current_inputs": current_inputs,
                "help_text": "Select input IDs from the dropdown and enter names. Check boxes to delete existing inputs."
            },
        )

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth.""" 
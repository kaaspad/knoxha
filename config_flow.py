"""Config flow for Knox Chameleon64i integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
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

                # Store connection info and move to zone configuration
                self._host = user_input[CONF_HOST]
                self._port = user_input[CONF_PORT]
                return await self.async_step_zones()

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
            last_step=False,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration - directly go to zones step."""
        # Load existing config
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry:
            self._host = entry.data[CONF_HOST]
            self._port = entry.data[CONF_PORT]
            self._zones = entry.data.get(CONF_ZONES, [])
            self._inputs = entry.data.get(CONF_INPUTS, [])
        return await self.async_step_zones()

    async def async_step_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle zone configuration."""
        if user_input is not None:
            # Handle actions from the menu or form submission
            if "add_zone" == user_input.get("next_step"):
                return await self.async_step_add_zone()
            
            if "inputs" == user_input.get("next_step"):
                return await self.async_step_inputs()

            if "edit_zone" in user_input and user_input["edit_zone"]:
                zone_id = int(user_input["edit_zone"])
                self._editing_zone = next(
                    (zone for zone in self._zones if zone[CONF_ZONE_ID] == zone_id),
                    None
                )
                if self._editing_zone:
                    return await self.async_step_edit_zone()

            if "delete_zone" in user_input and user_input["delete_zone"]:
                zone_id = int(user_input["delete_zone"])
                self._zones = [zone for zone in self._zones if zone[CONF_ZONE_ID] != zone_id]
                return await self.async_step_zones()

            if "finish" in user_input:
                return await self.async_step_finish()

        # Define menu options for the zones step
        _LOGGER.debug("async_step_zones: self._zones: %s", self._zones)
        menu_options = {
            "add_zone": "Add a new zone",
            "inputs": "Configure inputs",
            "finish": "Finish Setup",
        }

        # Add edit/delete options only if zones exist
        if self._zones:
            menu_options["edit_zone"] = "Edit a zone"
            menu_options["delete_zone"] = "Delete a zone"
        _LOGGER.debug("async_step_zones: final menu_options: %s", menu_options)

        # Show current zones and options
        return self.async_show_menu(
            step_id="zones",
            menu_options=menu_options,
            description_placeholders={
                "zones": "\n".join(
                    f"Zone {zone[CONF_ZONE_ID]}: {zone[CONF_ZONE_NAME]}"
                    for zone in self._zones
                ) if self._zones else "No zones configured"
            },
        )

    async def async_step_add_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle adding a new zone."""
        if user_input is not None:
            zone_id = user_input[CONF_ZONE_ID]
            zone_name = user_input[CONF_ZONE_NAME]
            
            # Check if zone ID is already configured
            if any(zone[CONF_ZONE_ID] == zone_id for zone in self._zones):
                return self.async_show_form(
                    step_id="add_zone",
                    data_schema=vol.Schema(
                        {
                            vol.Required(CONF_ZONE_ID): vol.All(
                                vol.Coerce(int),
                                vol.Range(min=1, max=64)
                            ),
                            vol.Required(CONF_ZONE_NAME): str,
                        }
                    ),
                    errors={"base": "zone_already_configured"},
                    last_step=False,
                )

            self._zones.append({
                CONF_ZONE_ID: zone_id,
                CONF_ZONE_NAME: zone_name,
            })
            return await self.async_step_zones()

        return self.async_show_form(
            step_id="add_zone",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ZONE_ID): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=1, max=64)
                    ),
                    vol.Required(CONF_ZONE_NAME): str,
                }
            ),
            errors={},
            last_step=False,
        )

    async def async_step_edit_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle editing an existing zone."""
        if user_input is not None:
            zone_name = user_input[CONF_ZONE_NAME]
            
            # Update the zone name
            for zone in self._zones:
                if zone[CONF_ZONE_ID] == self._editing_zone[CONF_ZONE_ID]:
                    zone[CONF_ZONE_NAME] = zone_name
                    break
            
            self._editing_zone = None
            return await self.async_step_zones()

        return self.async_show_form(
            step_id="edit_zone",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ZONE_NAME, default=self._editing_zone[CONF_ZONE_NAME]): str,
                }
            ),
            errors={},
            last_step=False,
        )

    async def async_step_delete_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle deleting an existing zone."""
        if user_input is not None:
            zone_id_to_delete = int(user_input["delete_zone_id"])
            self._zones = [zone for zone in self._zones if zone[CONF_ZONE_ID] != zone_id_to_delete]
            return await self.async_step_zones()

        # Display a form to confirm deletion, listing zones to delete
        if not self._zones:
            return self.async_show_form(step_id="zones", errors={"base": "no_zones_to_delete"})

        return self.async_show_form(
            step_id="delete_zone",
            data_schema=vol.Schema(
                {
                    vol.Required("delete_zone_id"): vol.In(
                        {str(zone[CONF_ZONE_ID]): f"{zone[CONF_ZONE_NAME]} (ID: {zone[CONF_ZONE_ID]})"
                         for zone in self._zones}
                    )
                }
            ),
            description_placeholders={
                "zones_to_delete": "Select a zone to delete."
            },
            last_step=False,
        )

    async def async_step_inputs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle input configuration."""
        _LOGGER.debug("async_step_inputs: self._inputs: %s", self._inputs)
        if user_input is not None:
            if "add_input" == user_input.get("next_step"):
                return await self.async_step_add_input()
            
            if "edit_input" in user_input and user_input["edit_input"]:
                input_id = int(user_input["edit_input"])
                self._editing_input = next(
                    (input for input in self._inputs if input[CONF_INPUT_ID] == input_id),
                    None
                )
                if self._editing_input:
                    return await self.async_step_edit_input()

            if "delete_input" in user_input and user_input["delete_input"]:
                input_id = int(user_input["delete_input"])
                self._inputs = [input for input in self._inputs if input[CONF_INPUT_ID] != input_id]
                return await self.async_step_inputs()

            if "zones" == user_input.get("next_step"):
                return await self.async_step_zones()

            if "finish" in user_input:
                return await self.async_step_finish()

        # Define menu options for the inputs step
        menu_options = {
            "add_input": "Add a new input",
            "zones": "Back to Zones",
            "finish": "Finish Setup",
        }

        # Add edit/delete options only if inputs exist
        if self._inputs:
            menu_options["edit_input"] = "Edit an input"
            menu_options["delete_input"] = "Delete an input"
        _LOGGER.debug("async_step_inputs: final menu_options: %s", menu_options)

        # Show current inputs and options
        return self.async_show_menu(
            step_id="inputs",
            menu_options=menu_options,
            description_placeholders={
                "inputs": "\n".join(
                    f"Input {input[CONF_INPUT_ID]}: {input[CONF_INPUT_NAME]}"
                    for input in self._inputs
                ) if self._inputs else "No inputs configured"
            },
        )

    async def async_step_add_input(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle adding a new input."""
        if user_input is not None:
            input_id = user_input[CONF_INPUT_ID]
            input_name = user_input[CONF_INPUT_NAME]
            
            # Check if input ID is already configured
            if any(input[CONF_INPUT_ID] == input_id for input in self._inputs):
                return self.async_show_form(
                    step_id="add_input",
                    data_schema=vol.Schema(
                        {
                            vol.Required(CONF_INPUT_ID): vol.All(
                                vol.Coerce(int),
                                vol.Range(min=1, max=64)
                            ),
                            vol.Required(CONF_INPUT_NAME): str,
                        }
                    ),
                    errors={"base": "input_already_configured"},
                    last_step=False,
                )

            self._inputs.append({
                CONF_INPUT_ID: input_id,
                CONF_INPUT_NAME: input_name,
            })
            return await self.async_step_inputs()

        return self.async_show_form(
            step_id="add_input",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_INPUT_ID): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=1, max=64)
                    ),
                    vol.Required(CONF_INPUT_NAME): str,
                }
            ),
            errors={},
            last_step=False,
        )

    async def async_step_edit_input(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle editing an existing input."""
        if user_input is not None:
            input_name = user_input[CONF_INPUT_NAME]
            
            # Update the input name
            for input in self._inputs:
                if input[CONF_INPUT_ID] == self._editing_input[CONF_INPUT_ID]:
                    input[CONF_INPUT_NAME] = input_name
                    break
            
            self._editing_input = None
            return await self.async_step_inputs()

        return self.async_show_form(
            step_id="edit_input",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_INPUT_NAME, default=self._editing_input[CONF_INPUT_NAME]): str,
                }
            ),
            errors={},
            last_step=False,
        )

    async def async_step_delete_input(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle deleting an existing input."""
        if user_input is not None:
            input_id_to_delete = int(user_input["delete_input_id"])
            self._inputs = [input for input in self._inputs if input[CONF_INPUT_ID] != input_id_to_delete]
            return await self.async_step_inputs()

        # Display a form to confirm deletion, listing inputs to delete
        if not self._inputs:
            return self.async_show_form(step_id="inputs", errors={"base": "no_inputs_to_delete"})

        return self.async_show_form(
            step_id="delete_input",
            data_schema=vol.Schema(
                {
                    vol.Required("delete_input_id"): vol.In(
                        {str(input[CONF_INPUT_ID]): f"{input[CONF_INPUT_NAME]} (ID: {input[CONF_INPUT_ID]})"
                         for input in self._inputs}
                    )
                }
            ),
            description_placeholders={
                "inputs_to_delete": "Select an input to delete."
            },
            last_step=False,
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the finish step."""
        _LOGGER.debug("*** ENTRY async_step_finish. user_input: %s", user_input)
        if user_input is not None:
            _LOGGER.debug("async_step_finish: user_input is not None, proceeding to save.")
            # Ensure at least one default input if none are configured
            if not self._inputs:
                self._inputs.append(DEFAULT_INPUT)

            # Create or update the config entry
            data = {
                CONF_HOST: self._host,
                CONF_PORT: self._port,
                CONF_ZONES: self._zones,
                CONF_INPUTS: self._inputs,
            }
            _LOGGER.debug("async_step_finish: Data to save: %s", data)
            
            if self.context.get("source") == config_entries.SOURCE_RECONFIGURE:
                _LOGGER.debug("async_step_finish: Reconfiguring existing entry.")
                # Get the existing entry
                entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
                if entry is None:
                    _LOGGER.error("async_step_finish: Entry not found during reconfigure.")
                    return self.async_abort(reason="entry_not_found")
                
                # Update the existing entry
                self.hass.config_entries.async_update_entry(entry, data=data)
                _LOGGER.debug("async_step_finish: Entry updated successfully.")

                # Trigger a reload of the integration to apply changes
                await self.hass.config_entries.async_reload(entry.entry_id)
                _LOGGER.debug("async_step_finish: Integration reloaded, aborting flow with success.")
                return self.async_abort(reason="reconfigure_successful")
            else:
                _LOGGER.debug("async_step_finish: Creating new entry.")
                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data=data,
                )

        # If we get here, show the finish form (first time entering async_step_finish for this flow)
        _LOGGER.debug("async_step_finish: Showing finish form.")
        return self.async_show_form(
            step_id="finish",
            data_schema=vol.Schema({vol.Required("submit_changes", default=True): bool}),
            description_placeholders={
                "zones": "\n".join(
                    f"Zone {zone[CONF_ZONE_ID]}: {zone[CONF_ZONE_NAME]}"
                    for zone in self._zones
                ) if self._zones else "No zones configured",
                "inputs": "\n".join(
                    f"Input {input[CONF_INPUT_ID]}: {input[CONF_INPUT_NAME]}"
                    for input in self._inputs
                ) if self._inputs else "No inputs configured",
            },
            last_step=True,
        )

class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""

class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth.""" 
"""Config flow for Knox Chameleon64i integration."""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    DEFAULT_PORT,
    CONF_HOST,
    CONF_PORT,
    CONF_ZONES,
    CONF_INPUTS,
    CONF_ZONE_NAME,
    CONF_ZONE_ID,
    CONF_HA_AREA,
    CONF_INPUT_NAME,
    CONF_INPUT_ID,
    CONF_INPUT_SOURCE_ENTITY,
)
from .chameleon_client import ChameleonClient, ChameleonError

_LOGGER = logging.getLogger(__name__)


class KnoxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Knox Chameleon64i."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow."""
        return KnoxOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                # Test connection
                client = ChameleonClient(
                    host=user_input[CONF_HOST],
                    port=user_input[CONF_PORT],
                )
                await client.connect()
                connection_ok = await client.test_connection()
                await client.disconnect()

                if not connection_ok:
                    raise CannotConnect("Connection test failed")

                # Set unique ID to prevent duplicates
                await self.async_set_unique_id(user_input[CONF_HOST])
                self._abort_if_unique_id_configured()

                # Create entry - zones/inputs configured via options
                return self.async_create_entry(
                    title=f"Knox Chameleon64i ({user_input[CONF_HOST]})",
                    data={
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_ZONES: [],
                        CONF_INPUTS: [],
                    },
                )

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception("Unexpected error: %s", err)
                errors["base"] = "unknown"

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
                client = ChameleonClient(
                    host=user_input[CONF_HOST],
                    port=user_input[CONF_PORT],
                )
                await client.connect()
                connection_ok = await client.test_connection()
                await client.disconnect()

                if not connection_ok:
                    raise CannotConnect("Connection test failed")

                # Update entry with new connection info, preserve zones/inputs
                new_data = entry.data.copy()
                new_data[CONF_HOST] = user_input[CONF_HOST]
                new_data[CONF_PORT] = user_input[CONF_PORT]

                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)

                return self.async_abort(reason="reconfigure_successful")

            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception("Unexpected error: %s", err)
                errors["base"] = "unknown"

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
    """Handle options flow for Knox Chameleon64i."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self._config_entry = config_entry
        self._zones = config_entry.data.get(CONF_ZONES, []).copy()
        self._inputs = config_entry.data.get(CONF_INPUTS, []).copy()
        # Track import statistics
        self._import_stats = {"added": 0, "updated": 0, "total": 0}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options - show menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["manage_zones", "manage_inputs", "import_zones_csv"],
        )

    async def async_step_manage_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Zone management submenu."""
        return self.async_show_menu(
            step_id="manage_zones",
            menu_options=["add_zone", "remove_zone", "list_zones"],
        )

    async def async_step_manage_inputs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Input management submenu."""
        return self.async_show_menu(
            step_id="manage_inputs",
            menu_options=["add_input", "remove_input", "list_inputs"],
        )

    async def async_step_add_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a single zone."""
        errors = {}

        if user_input is not None:
            zone_id = int(user_input[CONF_ZONE_ID])  # Convert to int!
            zone_name = user_input[CONF_ZONE_NAME].strip()
            ha_area = user_input.get(CONF_HA_AREA, "").strip()

            # Check for duplicates
            if any(zone[CONF_ZONE_ID] == zone_id for zone in self._zones):
                errors[CONF_ZONE_ID] = "zone_already_exists"
            elif not zone_name:
                errors[CONF_ZONE_NAME] = "zone_name_required"
            else:
                # Add zone
                zone_config = {
                    CONF_ZONE_ID: zone_id,
                    CONF_ZONE_NAME: zone_name,
                }
                if ha_area:
                    zone_config[CONF_HA_AREA] = ha_area

                self._zones.append(zone_config)
                self._zones.sort(key=lambda x: x[CONF_ZONE_ID])
                await self._save_config()
                return await self.async_step_init()  # Return to main menu

        # Get available zone IDs
        used_ids = {zone[CONF_ZONE_ID] for zone in self._zones}
        available_ids = [i for i in range(1, 65) if i not in used_ids]

        if not available_ids:
            return self.async_abort(reason="all_zones_configured")

        return self.async_show_form(
            step_id="add_zone",
            data_schema=vol.Schema({
                vol.Required(CONF_ZONE_ID): vol.In({
                    str(zone_id): f"Zone {zone_id}"
                    for zone_id in available_ids
                }),
                vol.Required(CONF_ZONE_NAME): str,
                vol.Optional(CONF_HA_AREA): selector.AreaSelector(),
            }),
            errors=errors,
            description_placeholders={
                "zones_count": str(len(self._zones)),
            },
        )

    async def async_step_remove_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Remove a zone."""
        if not self._zones:
            return self.async_abort(reason="no_zones_configured")

        if user_input is not None:
            zone_id = int(user_input["zone_to_remove"])
            self._zones = [z for z in self._zones if z[CONF_ZONE_ID] != zone_id]
            await self._save_config()
            return await self.async_step_init()  # Return to main menu

        return self.async_show_form(
            step_id="remove_zone",
            data_schema=vol.Schema({
                vol.Required("zone_to_remove"): vol.In({
                    str(zone[CONF_ZONE_ID]): f"Zone {zone[CONF_ZONE_ID]}: {zone[CONF_ZONE_NAME]}"
                    for zone in sorted(self._zones, key=lambda x: x[CONF_ZONE_ID])
                }),
            }),
        )

    async def async_step_list_zones(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """List all configured zones."""
        if user_input is not None:
            return await self.async_step_init()  # Return to main menu

        zones_list = "\n".join(
            f"• Zone {z[CONF_ZONE_ID]}: {z[CONF_ZONE_NAME]}"
            for z in sorted(self._zones, key=lambda x: x[CONF_ZONE_ID])
        ) if self._zones else "No zones configured yet."

        return self.async_show_form(
            step_id="list_zones",
            data_schema=vol.Schema({}),
            description_placeholders={"zones_list": zones_list},
        )

    async def async_step_import_zones_csv(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Import zones from CSV data."""
        errors = {}

        if user_input is not None:
            csv_data = user_input["csv_data"].strip()

            if not csv_data:
                errors["csv_data"] = "csv_data_required"
            else:
                try:
                    # Parse CSV
                    imported_zones = []
                    csv_file = io.StringIO(csv_data)
                    reader = csv.reader(csv_file)

                    # Check for header row
                    first_row = next(reader, None)
                    if first_row and (
                        "zone" in first_row[0].lower() or
                        "id" in first_row[0].lower()
                    ):
                        # Skip header row
                        pass
                    else:
                        # First row is data, process it
                        if first_row and len(first_row) >= 2:
                            try:
                                zone_id = int(first_row[0].strip())
                                zone_name = first_row[1].strip()
                                ha_area = first_row[2].strip() if len(first_row) >= 3 else ""

                                if 1 <= zone_id <= 64 and zone_name:
                                    zone_config = {
                                        CONF_ZONE_ID: zone_id,
                                        CONF_ZONE_NAME: zone_name,
                                    }
                                    if ha_area:
                                        zone_config[CONF_HA_AREA] = ha_area
                                    imported_zones.append(zone_config)
                            except (ValueError, IndexError):
                                pass

                    # Process remaining rows
                    for row in reader:
                        if len(row) >= 2:
                            try:
                                zone_id = int(row[0].strip())
                                zone_name = row[1].strip()
                                ha_area = row[2].strip() if len(row) >= 3 else ""

                                if not (1 <= zone_id <= 64):
                                    continue
                                if not zone_name:
                                    continue

                                zone_config = {
                                    CONF_ZONE_ID: zone_id,
                                    CONF_ZONE_NAME: zone_name,
                                }
                                if ha_area:
                                    zone_config[CONF_HA_AREA] = ha_area

                                imported_zones.append(zone_config)
                            except (ValueError, IndexError):
                                continue

                    if not imported_zones:
                        errors["csv_data"] = "no_valid_zones"
                    else:
                        # Merge with existing zones (new ones replace existing with same ID)
                        existing_ids = {z[CONF_ZONE_ID] for z in self._zones}
                        new_zones = [z for z in self._zones]

                        # Track statistics
                        added_count = 0
                        updated_count = 0

                        for imported in imported_zones:
                            if imported[CONF_ZONE_ID] not in existing_ids:
                                new_zones.append(imported)
                                added_count += 1
                            else:
                                # Replace existing zone
                                new_zones = [
                                    z for z in new_zones
                                    if z[CONF_ZONE_ID] != imported[CONF_ZONE_ID]
                                ]
                                new_zones.append(imported)
                                updated_count += 1

                        self._zones = sorted(new_zones, key=lambda x: x[CONF_ZONE_ID])
                        await self._save_config()

                        # Store import statistics for success message
                        self._import_stats = {
                            "added": added_count,
                            "updated": updated_count,
                            "total": len(imported_zones),
                        }

                        return await self.async_step_import_success()

                except Exception as err:
                    _LOGGER.exception("CSV parsing error: %s", err)
                    errors["csv_data"] = "csv_parse_error"

        return self.async_show_form(
            step_id="import_zones_csv",
            data_schema=vol.Schema({
                vol.Required("csv_data"): selector.TextSelector(
                    selector.TextSelectorConfig(
                        multiline=True,
                        type=selector.TextSelectorType.TEXT,
                    ),
                ),
            }),
            errors=errors,
            description_placeholders={
                "example_csv": "1,Living Room,Living Room\n2,Kitchen,Kitchen\n3,Bedroom,Upstairs\n25,Study,Office",
                "current_count": str(len(self._zones)),
            },
        )

    async def async_step_import_success(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show import success."""
        if user_input is not None:
            return await self.async_step_init()

        # Build detailed import summary
        added = self._import_stats.get("added", 0)
        updated = self._import_stats.get("updated", 0)
        total = self._import_stats.get("total", 0)

        summary_parts = []
        if added > 0:
            summary_parts.append(f"{added} new zone{'s' if added != 1 else ''} added")
        if updated > 0:
            summary_parts.append(f"{updated} existing zone{'s' if updated != 1 else ''} updated")

        import_summary = ", ".join(summary_parts) if summary_parts else "No changes"

        return self.async_show_form(
            step_id="import_success",
            data_schema=vol.Schema({}),
            description_placeholders={
                "zones_count": str(len(self._zones)),
                "import_summary": import_summary,
                "added_count": str(added),
                "updated_count": str(updated),
                "total_imported": str(total),
            },
        )

    async def async_step_add_input(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a single input."""
        errors = {}

        if user_input is not None:
            input_id = int(user_input[CONF_INPUT_ID])
            input_name = user_input[CONF_INPUT_NAME].strip()
            source_entity = user_input.get(CONF_INPUT_SOURCE_ENTITY)

            if any(inp[CONF_INPUT_ID] == input_id for inp in self._inputs):
                errors[CONF_INPUT_ID] = "input_already_exists"
            elif not input_name:
                errors[CONF_INPUT_NAME] = "input_name_required"
            else:
                # Add input
                input_data = {
                    CONF_INPUT_ID: input_id,
                    CONF_INPUT_NAME: input_name,
                }
                # Add source entity if provided (optional)
                if source_entity:
                    input_data[CONF_INPUT_SOURCE_ENTITY] = source_entity
                self._inputs.append(input_data)
                self._inputs.sort(key=lambda x: x[CONF_INPUT_ID])
                await self._save_config()
                return await self.async_step_init()  # Return to main menu

        # Get available input IDs
        used_ids = {inp[CONF_INPUT_ID] for inp in self._inputs}
        available_ids = [i for i in range(1, 65) if i not in used_ids]

        if not available_ids:
            return self.async_abort(reason="all_inputs_configured")

        return self.async_show_form(
            step_id="add_input",
            data_schema=vol.Schema({
                vol.Required(CONF_INPUT_ID): vol.In({
                    str(input_id): f"Input {input_id}"
                    for input_id in available_ids
                }),
                vol.Required(CONF_INPUT_NAME): str,
                vol.Optional(CONF_INPUT_SOURCE_ENTITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="media_player")
                ),
            }),
            errors=errors,
            description_placeholders={
                "inputs_count": str(len(self._inputs)),
            },
        )

    async def async_step_remove_input(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Remove an input."""
        if not self._inputs:
            return self.async_abort(reason="no_inputs_configured")

        if user_input is not None:
            input_id = int(user_input["input_to_remove"])
            self._inputs = [i for i in self._inputs if i[CONF_INPUT_ID] != input_id]
            await self._save_config()
            return await self.async_step_init()  # Return to main menu

        return self.async_show_form(
            step_id="remove_input",
            data_schema=vol.Schema({
                vol.Required("input_to_remove"): vol.In({
                    str(inp[CONF_INPUT_ID]): f"Input {inp[CONF_INPUT_ID]}: {inp[CONF_INPUT_NAME]}"
                    for inp in sorted(self._inputs, key=lambda x: x[CONF_INPUT_ID])
                }),
            }),
        )

    async def async_step_list_inputs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """List all configured inputs."""
        if user_input is not None:
            return await self.async_step_init()  # Return to main menu

        inputs_list = "\n".join(
            f"• Input {i[CONF_INPUT_ID]}: {i[CONF_INPUT_NAME]}"
            for i in sorted(self._inputs, key=lambda x: x[CONF_INPUT_ID])
        ) if self._inputs else "No inputs configured yet."

        return self.async_show_form(
            step_id="list_inputs",
            data_schema=vol.Schema({}),
            description_placeholders={"inputs_list": inputs_list},
        )

    async def _save_config(self) -> None:
        """Save configuration to config entry."""
        new_data = self._config_entry.data.copy()
        new_data[CONF_ZONES] = self._zones
        new_data[CONF_INPUTS] = self._inputs

        self.hass.config_entries.async_update_entry(
            self._config_entry, data=new_data
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""

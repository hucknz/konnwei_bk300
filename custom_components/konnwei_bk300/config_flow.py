"""Config flow for Konnwei BK300."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
    async_last_service_info,
    async_scanner_count,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_ADDRESS,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DEVICE_NAME,
    DOMAIN,
    MANUFACTURER_ID,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    SERVICE_UUID,
)

_LOGGER = logging.getLogger(__name__)


def _is_bk300(discovery: BluetoothServiceInfoBleak) -> bool:
    """Return True if this discovery looks like a BK300."""
    # Match by service UUID (most reliable)
    if SERVICE_UUID in [str(u).lower() for u in discovery.service_uuids]:
        return True
    # Match by Clarinox manufacturer ID 0x00B3 = 179
    if MANUFACTURER_ID in discovery.manufacturer_data:
        return True
    return False


class BK300ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config flow for Konnwei BK300."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_devices: dict[str, str] = {}
        self._address: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle auto-discovery via Bluetooth.

        HA calls this when a device matches any entry in manifest.json bluetooth list.
        We do a secondary check to avoid false positives from name/manufacturer matches.
        """
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        # Secondary filter — if matched only by local_name, verify service UUID or mfr ID
        service_match = SERVICE_UUID in [
            str(u).lower() for u in discovery_info.service_uuids
        ]
        mfr_match = MANUFACTURER_ID in discovery_info.manufacturer_data
        name_match = bool(
            discovery_info.name
            and DEVICE_NAME.lower() in discovery_info.name.lower()
        )

        if not (service_match or mfr_match or name_match):
            return self.async_abort(reason="not_supported")

        self._address = discovery_info.address
        self.context["title_placeholders"] = {
            "name": discovery_info.name or DEVICE_NAME,
            "address": discovery_info.address,
        }

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm auto-discovered device."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"BK300 ({self._address})",
                data={
                    CONF_ADDRESS: self._address,
                    CONF_POLL_INTERVAL: user_input.get(
                        CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                    ),
                },
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                    ),
                }
            ),
            description_placeholders={
                "address": self._address,
                "name": DEVICE_NAME,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual setup — shows dropdown of all visible BLE devices."""
        errors: dict[str, str] = {}

        # Build dropdown of ALL visible BLE devices (not just BK300 matches)
        # so the user can select any device even if auto-detection missed it
        current_addresses = self._async_current_ids()
        all_devices: dict[str, str] = {}
        bk300_devices: dict[str, str] = {}

        for discovery in async_discovered_service_info(self.hass, connectable=False):
            if discovery.address in current_addresses:
                continue
            label = f"{discovery.name or 'Unknown'} ({discovery.address})"
            all_devices[discovery.address] = label
            if _is_bk300(discovery):
                bk300_devices[discovery.address] = label

        # Put BK300 matches at the top, then everything else
        ordered: dict[str, str] = {}
        for addr, label in bk300_devices.items():
            ordered[addr] = f"⭐ {label}"
        for addr, label in all_devices.items():
            if addr not in ordered:
                ordered[addr] = label

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()

            # Use the device name from the dropdown if we have it
            raw_label = all_devices.get(address, f"BK300 ({address})")
            # Strip the ⭐ prefix if present
            title = raw_label.replace("⭐ ", "")

            return self.async_create_entry(
                title=title,
                data={
                    CONF_ADDRESS: address,
                    CONF_POLL_INTERVAL: user_input.get(
                        CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                    ),
                },
            )

        if not ordered:
            # No BLE devices visible at all — show a helpful error
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                errors={"base": "no_devices_found"},
                description_placeholders={"discovered_count": "0"},
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): vol.In(ordered),
                vol.Optional(
                    CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                ),
            }
        )

        bk300_count = len(bk300_devices)
        total_count = len(ordered)

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "discovered_count": str(bk300_count),
                "total_count": str(total_count),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return options flow."""
        return BK300OptionsFlow(config_entry)


class BK300OptionsFlow(OptionsFlow):
    """Handle options for BK300."""

    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_POLL_INTERVAL,
            self._config_entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_POLL_INTERVAL, default=current_interval
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                    ),
                }
            ),
        )

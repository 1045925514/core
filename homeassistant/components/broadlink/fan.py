"""Fan entities for BroadLink Magic fresh-air loads."""

from typing import Any, override

from broadlink_async.magic import (
    FRESH_AIR_FAN_HIGH,
    FRESH_AIR_FAN_LOW,
    FRESH_AIR_FAN_MEDIUM,
    FRESH_AIR_MODE_COOL,
    FRESH_AIR_MODE_FRESH,
    FRESH_AIR_MODE_PURIFY,
    FRESH_AIR_MODE_SLEEP,
    FRESH_AIR_MODE_SMART,
    FRESH_AIR_MODE_TURBO,
    ImportedDevice,
    encode_fresh_air_attribute,
)

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .const import DOMAIN, magic_device_identifier
from .coordinator import BroadLinkMagicConfigEntry, FamilyCoordinator
from .entity import BroadLinkMagicEntity, PendingCommands

PARALLEL_UPDATES = 1

_FRESH_AIR_SPEEDS = [FRESH_AIR_FAN_LOW, FRESH_AIR_FAN_MEDIUM, FRESH_AIR_FAN_HIGH]
_FRESH_AIR_PRESETS = {
    "fresh_air": FRESH_AIR_MODE_FRESH,
    "cool": FRESH_AIR_MODE_COOL,
    "smart": FRESH_AIR_MODE_SMART,
    "turbo": FRESH_AIR_MODE_TURBO,
    "sleep": FRESH_AIR_MODE_SLEEP,
    "purify": FRESH_AIR_MODE_PURIFY,
}
_MODE_TO_PRESET = {value: key for key, value in _FRESH_AIR_PRESETS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BroadLinkMagicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up fresh-air loads of three-in-one panels."""
    coordinator = entry.runtime_data
    async_add_entities(
        BroadLinkMagicFreshAir(coordinator, device)
        for device in coordinator.family.three_in_one_devices
    )


class BroadLinkMagicFreshAir(BroadLinkMagicEntity, FanEntity):
    """The fresh-air load of a three-in-one thermostat panel."""

    _attr_is_on = False
    _attr_preset_modes = list(_FRESH_AIR_PRESETS)
    _attr_speed_count = len(_FRESH_AIR_SPEEDS)
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    _attr_translation_key = "fresh_air"

    def __init__(
        self,
        coordinator: FamilyCoordinator,
        device: ImportedDevice,
    ) -> None:
        """Initialize a fresh-air entity."""
        super().__init__(coordinator)
        self._device = device
        self._pending_state = PendingCommands()
        self._attr_unique_id = (
            f"{coordinator.family.family_id}_{device.stable_id}_fresh_air"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, magic_device_identifier(device.stable_id))},
            manufacturer="BroadLink",
            model="Magic Home 3-in-1 Thermostat",
            name=device.name,
            suggested_area=coordinator.room_name(device.room_id),
            via_device_id=self._family_device_id(),
        )

    @property
    @override
    def is_on(self) -> bool:
        """Return the fresh-air power state, which is independent of its speed."""
        return bool(self._attr_is_on)

    @override
    @callback
    def _handle_coordinator_update(self) -> None:
        """Apply a real three-in-one status report."""
        state = self._confirmed_state(self._device, self._pending_state)
        if "fresh_air_power" in state:
            self._attr_is_on = bool(state["fresh_air_power"])
        if (speed := state.get("fresh_air_fan")) in _FRESH_AIR_SPEEDS:
            self._attr_percentage = ordered_list_item_to_percentage(
                _FRESH_AIR_SPEEDS, speed
            )
        if "fresh_air_mode" in state:
            self._attr_preset_mode = _MODE_TO_PRESET.get(int(state["fresh_air_mode"]))
        super()._handle_coordinator_update()

    async def _async_send(self, attributes: list[tuple[str, int]]) -> None:
        await self.coordinator.async_send_payloads(
            self._device,
            [
                encode_fresh_air_attribute(attribute, value)
                for attribute, value in attributes
            ],
        )
        for attribute, value in attributes:
            self._pending_state.set(f"fresh_air_{attribute}", value)

    @override
    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn fresh air on, optionally with a speed or mode."""
        attributes = [("power", 1)]
        if percentage:
            speed = percentage_to_ordered_list_item(_FRESH_AIR_SPEEDS, percentage)
            attributes.append(("fan", speed))
            self._attr_percentage = percentage
        if preset_mode is not None:
            attributes.append(("mode", _FRESH_AIR_PRESETS[preset_mode]))
            self._attr_preset_mode = preset_mode
        await self._async_send(attributes)
        self._attr_is_on = True
        self.async_write_ha_state()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn fresh air off."""
        await self._async_send([("power", 0)])
        self._attr_is_on = False
        self.async_write_ha_state()

    @override
    async def async_set_percentage(self, percentage: int) -> None:
        """Set the fresh-air speed."""
        if percentage == 0:
            await self.async_turn_off()
            return
        speed = percentage_to_ordered_list_item(_FRESH_AIR_SPEEDS, percentage)
        await self._async_send_powered([("fan", speed)])
        self._attr_percentage = ordered_list_item_to_percentage(
            _FRESH_AIR_SPEEDS, speed
        )
        self.async_write_ha_state()

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the fresh-air mode."""
        await self._async_send_powered([("mode", _FRESH_AIR_PRESETS[preset_mode])])
        self._attr_preset_mode = preset_mode
        self.async_write_ha_state()

    async def _async_send_powered(self, attributes: list[tuple[str, int]]) -> None:
        """Send attributes, turning fresh air on first; the panel keeps it off otherwise."""
        if not self.is_on:
            attributes = [("power", 1), *attributes]
        await self._async_send(attributes)
        self._attr_is_on = True

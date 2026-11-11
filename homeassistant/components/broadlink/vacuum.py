"""Optimistic vacuum entities for BroadLink Magic RM children."""

from typing import Any, override

from broadlink_async.magic import ImportedDevice

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, magic_rm_device_identifier
from .coordinator import BroadLinkMagicConfigEntry, FamilyCoordinator
from .entity import BroadLinkMagicEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BroadLinkMagicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up RM vacuums."""
    coordinator = entry.runtime_data
    async_add_entities(
        BroadLinkMagicRMVacuum(coordinator, device)
        for device in coordinator.family.rm_vacuum_devices
    )


class BroadLinkMagicRMVacuum(BroadLinkMagicEntity, StateVacuumEntity):
    """An optimistic RM vacuum."""

    _attr_activity = VacuumActivity.IDLE
    _attr_assumed_state = True
    _attr_name = None
    _attr_supported_features = (
        VacuumEntityFeature.STATE
        | VacuumEntityFeature.START
        | VacuumEntityFeature.RETURN_HOME
    )

    def __init__(
        self,
        coordinator: FamilyCoordinator,
        device: ImportedDevice,
    ) -> None:
        """Initialize an RM vacuum."""
        super().__init__(coordinator)
        self._device = device
        self._attr_unique_id = f"{coordinator.family.family_id}_{device.stable_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, magic_rm_device_identifier(device.stable_id))},
            manufacturer="BroadLink",
            model="Magic Home RM Vacuum",
            name=device.name,
            suggested_area=coordinator.room_name(device.room_id),
            via_device_id=self._family_device_id(),
        )

    @override
    async def async_start(self) -> None:
        """Start automatic cleaning."""
        await self.coordinator.async_send_rm_commands(self._device, ["auto"])
        self._attr_activity = VacuumActivity.CLEANING
        self.async_write_ha_state()

    @override
    async def async_return_to_base(self, **kwargs: Any) -> None:
        """Return the vacuum to its charger."""
        await self.coordinator.async_send_rm_commands(self._device, ["charge"])
        self._attr_activity = VacuumActivity.RETURNING
        self.async_write_ha_state()

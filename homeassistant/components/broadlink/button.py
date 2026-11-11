"""Button entities for BroadLink Magic RM learned keys."""

from typing import override

from broadlink_async.magic import ImportedDevice, RMProfile

from homeassistant.components.button import ButtonEntity
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
    """Set up RM learned-key buttons."""
    coordinator = entry.runtime_data
    async_add_entities(
        BroadLinkMagicRMKeyButton(coordinator, device, key, code)
        for device in coordinator.family.rm_learned_devices
        for code, key in {
            code: key for key, code in reversed(device.functions.items())
        }.items()
    )


class BroadLinkMagicRMKeyButton(BroadLinkMagicEntity, ButtonEntity):
    """A key learned by an RM child device."""

    def __init__(
        self,
        coordinator: FamilyCoordinator,
        device: ImportedDevice,
        key: str,
        code: int,
    ) -> None:
        """Initialize an RM learned-key button."""
        super().__init__(coordinator)
        self._device = device
        self._key = key
        self._attr_name = key
        self._attr_unique_id = (
            f"{coordinator.family.family_id}_{device.stable_id}_key_{code}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, magic_rm_device_identifier(device.stable_id))},
            manufacturer="BroadLink",
            model=(
                "Magic Home RM Learned RF"
                if device.rm_profile is RMProfile.LEARNED_RF
                else "Magic Home RM Learned IR"
            ),
            name=device.name,
            suggested_area=coordinator.room_name(device.room_id),
            via_device_id=self._family_device_id(),
        )

    @override
    async def async_press(self) -> None:
        """Send the learned key."""
        await self.coordinator.async_send_rm_commands(self._device, [self._key])

"""Curtain entities for BroadLink Magic."""

from typing import Any, override

from broadlink_async.magic import (
    CURTAIN_CLOSE,
    CURTAIN_OPEN,
    CURTAIN_STOP,
    ImportedDevice,
    encode_curtain_motion,
    encode_curtain_position,
)

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, magic_device_identifier, magic_rm_device_identifier
from .coordinator import BroadLinkMagicConfigEntry, FamilyCoordinator
from .entity import BroadLinkMagicEntity
from .magic_helpers import rm_command_supported

PARALLEL_UPDATES = 1

# Motors with travel limits may stop at 1% after a full close.
CURTAIN_CLOSED_MAX_POSITION = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BroadLinkMagicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up imported curtain motors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(
                BroadLinkMagicCurtain(coordinator, device)
                for device in coordinator.family.curtain_devices
            ),
            *(
                BroadLinkMagicRMCover(
                    coordinator,
                    device,
                    drying_rack=False,
                )
                for device in coordinator.family.rm_curtain_devices
            ),
            *(
                BroadLinkMagicRMCover(
                    coordinator,
                    device,
                    drying_rack=True,
                )
                for device in coordinator.family.rm_drying_rack_devices
            ),
        ]
    )


class BroadLinkMagicCurtain(BroadLinkMagicEntity, CoverEntity):
    """An EasyIndustry CURTAIN device, optimistic until it reports a position."""

    _attr_current_cover_position = 0
    _attr_device_class = CoverDeviceClass.CURTAIN
    _attr_is_closed = True
    _attr_name = None
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(
        self,
        coordinator: FamilyCoordinator,
        device: ImportedDevice,
    ) -> None:
        """Initialize an imported curtain."""
        super().__init__(coordinator)
        self._device = device
        self._report_serial = 0
        self._area_name = coordinator.room_name(device.room_id)
        self._attr_unique_id = f"{coordinator.family.family_id}_{device.stable_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, magic_device_identifier(device.stable_id))},
            manufacturer="BroadLink",
            model="Magic Home Curtain",
            name=device.name,
            suggested_area=self._area_name,
            via_device_id=self._family_device_id(),
        )

    @override
    @callback
    def _handle_coordinator_update(self) -> None:
        """Apply a reported curtain position."""
        serial = self.coordinator.report_serials.get(self._device.stable_id, 0)
        if serial != self._report_serial:
            self._report_serial = serial
            state = self.coordinator.device_states.get(self._device.stable_id, {})
            if "position" in state:
                position = int(state["position"])
                self._attr_current_cover_position = position
                self._attr_is_closed = position <= CURTAIN_CLOSED_MAX_POSITION
                motion = state.get("motion")
                self._attr_is_opening = motion == "opening"
                self._attr_is_closing = motion == "closing"
        super()._handle_coordinator_update()

    @override
    async def async_added_to_hass(self) -> None:
        """Assign the imported room without overriding user changes."""
        await super().async_added_to_hass()
        if self._area_name and self.registry_entry is not None:
            device_id = self.registry_entry.device_id
            registry = dr.async_get(self.hass)
            registry_device = registry.async_get(device_id) if device_id else None
            if registry_device is not None and registry_device.area_id is None:
                area = ar.async_get(self.hass).async_get_or_create(self._area_name)
                registry.async_update_device(registry_device.id, area_id=area.id)

    def _set_optimistic_state(self, position: int | None = None) -> None:
        if position is not None:
            self._attr_current_cover_position = position
            self._attr_is_closed = position == 0
        self._attr_is_opening = False
        self._attr_is_closing = False
        self.async_write_ha_state()

    @override
    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the curtain."""
        await self.coordinator.async_send_curtain(
            self._device,
            encode_curtain_motion(CURTAIN_OPEN),
        )
        self._set_optimistic_state(100)

    @override
    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the curtain."""
        await self.coordinator.async_send_curtain(
            self._device,
            encode_curtain_motion(CURTAIN_CLOSE),
        )
        self._set_optimistic_state(0)

    @override
    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the curtain."""
        await self.coordinator.async_send_curtain(
            self._device,
            encode_curtain_motion(CURTAIN_STOP),
        )
        self._set_optimistic_state()

    @override
    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set an optimistic curtain position."""
        position = int(kwargs[ATTR_POSITION])
        await self.coordinator.async_send_curtain(
            self._device,
            encode_curtain_position(position),
        )
        self._set_optimistic_state(position)


class BroadLinkMagicRMCover(BroadLinkMagicEntity, CoverEntity):
    """An optimistic RM curtain or drying-rack cover."""

    _attr_assumed_state = True
    _attr_current_cover_position = 0
    _attr_device_class = CoverDeviceClass.CURTAIN
    _attr_is_closed = True
    _attr_name = None

    def __init__(
        self,
        coordinator: FamilyCoordinator,
        device: ImportedDevice,
        *,
        drying_rack: bool,
    ) -> None:
        """Initialize an RM cover."""
        super().__init__(coordinator)
        self._device = device
        self._open_command = "up" if drying_rack else "open"
        self._close_command = "down" if drying_rack else "close"
        features = CoverEntityFeature(0)
        for feature, command in (
            (CoverEntityFeature.OPEN, self._open_command),
            (CoverEntityFeature.CLOSE, self._close_command),
            (CoverEntityFeature.STOP, "stop"),
        ):
            if rm_command_supported(device, command):
                features |= feature
        self._attr_supported_features = features
        self._attr_unique_id = f"{coordinator.family.family_id}_{device.stable_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, magic_rm_device_identifier(device.stable_id))},
            manufacturer="BroadLink",
            model=(
                "Magic Home RM Drying Rack" if drying_rack else "Magic Home RM Curtain"
            ),
            name=device.name,
            suggested_area=coordinator.room_name(device.room_id),
            via_device_id=self._family_device_id(),
        )

    def _set_closed(self, closed: bool) -> None:
        self._attr_is_closed = closed
        self._attr_current_cover_position = 0 if closed else 100
        self.async_write_ha_state()

    @override
    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open or raise the RM cover."""
        await self.coordinator.async_send_rm_commands(
            self._device, [self._open_command]
        )
        self._set_closed(False)

    @override
    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close or lower the RM cover."""
        await self.coordinator.async_send_rm_commands(
            self._device, [self._close_command]
        )
        self._set_closed(True)

    @override
    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the RM cover."""
        await self.coordinator.async_send_rm_commands(self._device, ["stop"])

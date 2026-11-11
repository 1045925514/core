"""Media player entities for RM audio and video child devices."""

from typing import override

from broadlink_async.magic import ImportedDevice, RMProfile

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN, magic_rm_device_identifier
from .coordinator import BroadLinkMagicConfigEntry, FamilyCoordinator
from .entity import BroadLinkMagicEntity
from .magic_helpers import rm_command_supported

PARALLEL_UPDATES = 1

_PROFILE_DEVICE_CLASS = {
    RMProfile.TV: MediaPlayerDeviceClass.TV,
    RMProfile.STB: MediaPlayerDeviceClass.TV,
    RMProfile.PROJECTOR: MediaPlayerDeviceClass.PROJECTOR,
    RMProfile.SMART_BOX: MediaPlayerDeviceClass.TV,
    RMProfile.DVD: MediaPlayerDeviceClass.RECEIVER,
    RMProfile.SPEAKER: MediaPlayerDeviceClass.SPEAKER,
    RMProfile.AMPLIFIER: MediaPlayerDeviceClass.RECEIVER,
}

_CHANNEL_PROFILES = {RMProfile.TV, RMProfile.STB, RMProfile.SMART_BOX}

_FEATURE_COMMANDS: tuple[tuple[MediaPlayerEntityFeature, tuple[str, ...]], ...] = (
    (
        MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF,
        ("power",),
    ),
    (MediaPlayerEntityFeature.VOLUME_STEP, ("volume_up", "volume_down")),
    (MediaPlayerEntityFeature.VOLUME_MUTE, ("mute",)),
    (MediaPlayerEntityFeature.PLAY, ("play",)),
    (MediaPlayerEntityFeature.PAUSE, ("pause",)),
    (MediaPlayerEntityFeature.STOP, ("stop",)),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BroadLinkMagicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up imported RM audio and video devices."""
    coordinator = entry.runtime_data
    async_add_entities(
        BroadLinkMagicMediaPlayer(coordinator, device)
        for device in coordinator.family.rm_remote_devices
    )


class BroadLinkMagicMediaPlayer(BroadLinkMagicEntity, MediaPlayerEntity):
    """An optimistic RM audio or video device."""

    _attr_is_volume_muted = False
    _attr_name = None
    _attr_state = MediaPlayerState.ON

    def __init__(
        self,
        coordinator: FamilyCoordinator,
        device: ImportedDevice,
    ) -> None:
        """Initialize an imported RM media player."""
        super().__init__(coordinator)
        self._device = device
        self._area_name = coordinator.room_name(device.room_id)
        self._attr_unique_id = f"{coordinator.family.family_id}_{device.stable_id}"
        profile = device.rm_profile
        assert profile is not None
        self._profile = profile
        self._attr_device_class = _PROFILE_DEVICE_CLASS[profile]

        def supports(command: str) -> bool:
            return rm_command_supported(device, command)

        features = MediaPlayerEntityFeature(0)
        for feature, commands in _FEATURE_COMMANDS:
            if all(supports(command) for command in commands):
                features |= feature
        next_commands = ("channel_up", "next")
        previous_commands = ("channel_down", "previous")
        if profile not in _CHANNEL_PROFILES:
            next_commands = next_commands[::-1]
            previous_commands = previous_commands[::-1]
        self._next_command = next(filter(supports, next_commands), None)
        self._previous_command = next(filter(supports, previous_commands), None)
        if self._next_command:
            features |= MediaPlayerEntityFeature.NEXT_TRACK
        if self._previous_command:
            features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
        self._attr_supported_features = features
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, magic_rm_device_identifier(device.stable_id))},
            manufacturer="BroadLink",
            model=f"Magic Home RM {_profile_name(profile)}",
            name=device.name,
            suggested_area=self._area_name,
            via_device_id=self._family_device_id(),
        )

    @override
    async def async_added_to_hass(self) -> None:
        """Assign the imported room without overriding user changes."""
        await super().async_added_to_hass()
        if self._area_name and self.registry_entry is not None:
            device_id = self.registry_entry.device_id
            registry = dr.async_get(self.hass)
            device = registry.async_get(device_id) if device_id else None
            if device is not None and device.area_id is None:
                area = ar.async_get(self.hass).async_get_or_create(self._area_name)
                if isinstance(device, dr.ChildDeviceEntry):
                    registry.async_update_child_device(device.id, area_id=area.id)
                else:
                    registry.async_update_device(device.id, area_id=area.id)

    async def _async_send_command(self, command: str) -> None:
        await self.coordinator.async_send_rm_commands(self._device, [command])

    @override
    async def async_turn_on(self) -> None:
        """Turn on the media device optimistically."""
        if self._attr_state is not MediaPlayerState.OFF:
            return
        await self._async_send_command("power")
        self._attr_state = MediaPlayerState.ON
        self.async_write_ha_state()

    @override
    async def async_turn_off(self) -> None:
        """Turn off the media device optimistically."""
        if self._attr_state is MediaPlayerState.OFF:
            return
        await self._async_send_command("power")
        self._attr_state = MediaPlayerState.OFF
        self.async_write_ha_state()

    @override
    async def async_volume_up(self) -> None:
        """Increase the volume."""
        await self._async_send_command("volume_up")

    @override
    async def async_volume_down(self) -> None:
        """Decrease the volume."""
        await self._async_send_command("volume_down")

    @override
    async def async_mute_volume(self, mute: bool) -> None:
        """Toggle mute when the optimistic state needs to change."""
        if self._attr_is_volume_muted is mute:
            return
        await self._async_send_command("mute")
        self._attr_is_volume_muted = mute
        self.async_write_ha_state()

    @override
    async def async_media_play(self) -> None:
        """Start playback."""
        await self._async_send_command("play")
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    @override
    async def async_media_pause(self) -> None:
        """Pause playback."""
        await self._async_send_command("pause")
        self._attr_state = MediaPlayerState.PAUSED
        self.async_write_ha_state()

    @override
    async def async_media_stop(self) -> None:
        """Stop playback."""
        await self._async_send_command("stop")
        self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    @override
    async def async_media_next_track(self) -> None:
        """Select the next channel or track."""
        assert self._next_command is not None
        await self._async_send_command(self._next_command)

    @override
    async def async_media_previous_track(self) -> None:
        """Select the previous channel or track."""
        assert self._previous_command is not None
        await self._async_send_command(self._previous_command)


def _profile_name(profile: RMProfile) -> str:
    """Return a human-readable RM profile name."""
    if profile in {RMProfile.TV, RMProfile.STB, RMProfile.DVD}:
        return profile.value.upper()
    return profile.value.replace("_", " ").title()

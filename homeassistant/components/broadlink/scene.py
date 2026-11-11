"""Scene entities imported from Magic Home."""

from typing import Any, override

from broadlink_async.magic import ImportedScene

from homeassistant.components.scene import Scene
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BroadLinkMagicConfigEntry, FamilyCoordinator
from .entity import BroadLinkMagicEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BroadLinkMagicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up imported scenes."""
    async_add_entities(
        BroadLinkMagicScene(entry.runtime_data, scene)
        for scene in entry.runtime_data.family.scenes
    )


class BroadLinkMagicScene(BroadLinkMagicEntity, Scene):
    """A Magic Home scene activated through all online gateways."""

    _attr_should_poll = False

    def __init__(
        self,
        coordinator: FamilyCoordinator,
        scene: ImportedScene,
    ) -> None:
        """Initialize an imported scene."""
        super().__init__(coordinator)
        self._scene = scene
        self._attr_icon = "mdi:play-circle-outline"
        self._attr_name = scene.name
        self._attr_unique_id = f"{coordinator.family.family_id}_{scene.scene_id}"

    @override
    async def async_added_to_hass(self) -> None:
        """Assign the scene directly to its imported area."""
        await super().async_added_to_hass()
        area_name = self._scene.room_name or self.coordinator.room_name(
            self._scene.room_id
        )
        entity_registry = er.async_get(self.hass)
        entry = entity_registry.async_get(self.entity_id)
        if entry is None:
            return
        area_id = entry.area_id
        if area_id is None and area_name:
            area_id = ar.async_get(self.hass).async_get_or_create(area_name).id
        entity_registry.async_update_entity(
            self.entity_id,
            area_id=area_id,
            device_id=None,
        )

    @override
    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the imported FastCon scene."""
        await self.coordinator.async_activate_scene(self._scene)

"""Tests for BroadLink Magic RM child entities."""

import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from broadlink_async.magic import (
    MSG_HEARTBEAT,
    DeviceKind,
    DiscoveredRMMax,
    RMProfile,
    pack_message,
    parse_import_payload,
)
import pytest
from pytest_homeassistant.common import MockConfigEntry

from homeassistant.components.broadlink.const import (
    CONF_ENTRY_KIND,
    DOMAIN,
    ENTRY_KIND_MAGIC_FAMILY,
    magic_device_identifier,
    magic_rm_device_identifier,
)
from homeassistant.components.broadlink.magic_helpers import (
    family_from_entry_data,
    family_to_entry_data,
)
from homeassistant.components.cover import CoverEntityFeature
from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntityFeature,
)
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er

pytestmark = pytest.mark.usefixtures("socket_enabled")


def _import_payload(devices: list[dict[str, object]]) -> bytes:
    def encode(value: object) -> str:
        return base64.b64encode(json.dumps(value).encode()).decode()

    return json.dumps(
        [
            {
                "did": "rm-family",
                "dataList": [
                    {"mtag": "familyInfo", "data": encode({"bletoken": "00010203"})},
                    {"mtag": "devlist", "data": encode(devices)},
                ],
            }
        ]
    ).encode()


def _actual_family():
    """Parse the anonymized real-home RM child fixture."""
    devices = json.loads(
        (Path(__file__).with_name("fixtures") / "rm_child_devlist.json").read_text()
    )
    family = parse_import_payload(_import_payload(devices))[0]
    family.name = "RM test home"
    return family


def _entry_for_family() -> MockConfigEntry:
    family = _actual_family()
    gateways = [DiscoveredRMMax("192.0.2.20", "a1b2c3d4e5f6", 0xAF8B, "RM Max")]
    return MockConfigEntry(
        domain=DOMAIN,
        title=family.name,
        unique_id=f"magic:{family.family_id}",
        data={
            **family_to_entry_data(family, gateways),
            CONF_ENTRY_KIND: ENTRY_KIND_MAGIC_FAMILY,
        },
    )


def test_actual_fixture_classification_and_serialization() -> None:
    """Test real-home devices retain RM profile classification in entries."""
    family = _actual_family()
    devices = {device.name: device for device in family.devices}

    assert devices["TV"].rm_profile is RMProfile.TV
    assert devices["Projector"].kind is DeviceKind.RM_REMOTE
    assert devices["Smart box"].rm_profile is RMProfile.SMART_BOX
    assert len(family.rm_curtain_devices) == 2
    assert len(family.rm_fan_devices) == 1
    assert len(family.rm_light_devices) == 1
    assert len(family.rm_power_devices) == 3
    assert len(family.rm_vacuum_devices) == 1
    assert len(family.rm_drying_rack_devices) == 1
    assert len(family.rm_relay_devices) == 1
    assert devices["Unknown door"].kind is DeviceKind.OTHER
    assert devices["Learned IR"].rm_profile is RMProfile.LEARNED_IR
    assert devices["Learned RF"].rm_profile is RMProfile.LEARNED_RF
    assert devices["BLE light"].kind is DeviceKind.LIGHT
    assert not devices["BLE light"].is_rm_child
    assert devices["Hidden light group"].kind is DeviceKind.GROUP
    restored = family_from_entry_data(family_to_entry_data(family, []))
    restored_tv = next(device for device in restored.devices if device.name == "TV")
    assert restored_tv.is_rm_child
    assert restored_tv.rm_profile is RMProfile.TV

    old_data = family_to_entry_data(family, [])
    old_data["devices"][1].pop("is_rm_child")
    old_data["devices"][1].pop("rm_profile")
    old_tv = family_from_entry_data(old_data).devices[1]
    assert old_tv.is_rm_child
    assert old_tv.rm_profile is RMProfile.TV


async def test_rm_entities_commands_and_optimistic_state(
    hass: HomeAssistant,
    mock_send: AsyncMock,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test RM native entities, stale cleanup, and command payloads."""
    entry = _entry_for_family()
    entry.add_to_hass(hass)
    imported_family = family_from_entry_data(dict(entry.data))
    fan_device = imported_family.rm_fan_devices[0]
    tv_device = imported_family.rm_remote_devices[0]
    entity_registry.async_get_or_create(
        "remote",
        DOMAIN,
        f"{imported_family.family_id}_{fan_device.stable_id}_companion_remote",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    entity_registry.async_get_or_create(
        "remote",
        DOMAIN,
        f"{imported_family.family_id}_{tv_device.stable_id}_remote",
        config_entry=entry,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    family_id = "rm-family"

    def entity(domain: str, unique_id: str) -> er.RegistryEntry:
        entity_id = entity_registry.async_get_entity_id(
            domain,
            DOMAIN,
            unique_id,
        )
        assert entity_id is not None
        registry_entry = entity_registry.async_get(entity_id)
        assert registry_entry is not None
        return registry_entry

    ids = {
        device.name: device.stable_id for device in entry.runtime_data.family.devices
    }
    tv = entity("media_player", f"{family_id}_{ids['TV']}")
    curtain = entity("cover", f"{family_id}_{ids['Curtain A']}")
    fan = entity("fan", f"{family_id}_{ids['Fan']}")
    purifier = entity("fan", f"{family_id}_{ids['Purifier']}")
    rm_light = entity("light", f"{family_id}_{ids['RM light']}")
    heater = entity("switch", f"{family_id}_{ids['Water heater']}")
    humidifier = entity("switch", f"{family_id}_{ids['Humidifier']}")
    drying_cover = entity("cover", f"{family_id}_{ids['Drying rack']}")
    drying_light = entity("light", f"{family_id}_{ids['Drying rack']}")
    relay_1 = entity("switch", f"{family_id}_{ids['Relay panel']}_1")
    relay_2 = entity("switch", f"{family_id}_{ids['Relay panel']}_2")
    relay_3 = entity("switch", f"{family_id}_{ids['Relay panel']}_3")
    ble_light = entity("light", f"{family_id}_{ids['BLE light']}")

    assert drying_cover.device_id == drying_light.device_id
    assert drying_cover.device_id is not None
    drying_device = device_registry.async_get(drying_cover.device_id)
    assert drying_device is not None
    assert (DOMAIN, f"magic:rm:{ids['Drying rack']}") in drying_device.identifiers
    assert drying_device.model == "Magic Home RM Drying Rack"
    assert ble_light.device_id is not None
    ordinary_device = device_registry.async_get(ble_light.device_id)
    assert ordinary_device is not None
    assert (DOMAIN, f"magic:dev:{ids['BLE light']}") in ordinary_device.identifiers

    for device in entry.runtime_data.family.rm_companion_devices:
        assert (
            entity_registry.async_get_entity_id(
                "remote",
                DOMAIN,
                f"{family_id}_{device.stable_id}_companion_remote",
            )
            is None
        )
    assert tv.disabled_by is None
    assert (
        entity_registry.async_get_entity_id(
            "remote", DOMAIN, f"{family_id}_{ids['TV']}_remote"
        )
        is None
    )
    tv_state = hass.states.get(tv.entity_id)
    assert tv_state is not None
    assert tv_state.attributes["device_class"] == MediaPlayerDeviceClass.TV
    expected_media_classes = {
        "TV": MediaPlayerDeviceClass.TV,
        "Projector": MediaPlayerDeviceClass.PROJECTOR,
        "Smart box": MediaPlayerDeviceClass.TV,
    }
    for name, device_class in expected_media_classes.items():
        player = entity("media_player", f"{family_id}_{ids[name]}")
        state = hass.states.get(player.entity_id)
        assert state is not None
        assert state.attributes["device_class"] == device_class
    assert all(
        "a1b2c3d4e5f6000e" not in item.unique_id
        and "a1b2c3d4e5f6000f" not in item.unique_id
        and "a1b2c3d4e5f60010" not in item.unique_id
        for item in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    )
    assert (
        entity_registry.async_get_entity_id(
            "light", DOMAIN, f"{family_id}_light-group_light"
        )
        is None
    )

    coordinator = entry.runtime_data
    coordinator.gateway_set.handle_packet(
        "a1b2c3d4e5f6",
        pack_message(
            MSG_HEARTBEAT,
            1,
            bytes.fromhex("a1b2c3d4e5f6"),
        ),
        ("192.0.2.20", 41001),
    )
    coordinator.async_set_updated_data(coordinator.gateway_set)
    await hass.async_block_till_done()

    async def call(
        domain: str,
        service: str,
        registry_entry: er.RegistryEntry,
        **data: object,
    ) -> bytes:
        mock_send.reset_mock()
        await hass.services.async_call(
            domain,
            service,
            {ATTR_ENTITY_ID: registry_entry.entity_id, **data},
            blocking=True,
        )
        return mock_send.await_args.args[1][0]

    with patch.object(
        coordinator.gateway_set,
        "send_status_query",
        new_callable=AsyncMock,
    ) as status_query:
        assert await call("media_player", "volume_up", tv) == b"\x11"
        status_query.assert_not_awaited()
    assert await call("media_player", "turn_off", tv) == b"\x01"
    assert hass.states.get(tv.entity_id).state == "off"
    assert await call("media_player", "turn_on", tv) == b"\x01"
    assert hass.states.get(tv.entity_id).state == "on"
    assert await call("media_player", "volume_down", tv) == b"\x12"
    assert (
        await call(
            "media_player",
            "volume_mute",
            tv,
            is_volume_muted=True,
        )
        == b"\x03"
    )
    assert await call("media_player", "media_play", tv) == b"\x22"
    assert hass.states.get(tv.entity_id).state == "playing"
    assert await call("media_player", "media_pause", tv) == b"\x21"
    assert hass.states.get(tv.entity_id).state == "paused"
    assert await call("media_player", "media_stop", tv) == b"\x36"
    assert hass.states.get(tv.entity_id).state == "idle"
    assert await call("media_player", "media_next_track", tv) == b"\x13"
    assert await call("media_player", "media_previous_track", tv) == b"\x14"
    assert await call("cover", "open_cover", curtain) == b"\x01"
    assert hass.states.get(curtain.entity_id).state == "open"
    assert await call("fan", "turn_on", fan) == b"\x01"
    assert hass.states.get(fan.entity_id).state == "on"
    assert await call("fan", "turn_on", purifier) == b"\x01"
    assert await call("light", "turn_on", rm_light) == b"\x01"
    assert hass.states.get(rm_light.entity_id).state == "on"
    assert await call("switch", "turn_on", heater) == b"\x01"
    assert await call("switch", "turn_off", humidifier) == b"\x01"
    assert await call("cover", "open_cover", drying_cover) == b"\x01"
    assert await call("light", "turn_on", drying_light) == b"\x07"
    assert await call("switch", "turn_off", relay_1) == b"\x10"
    assert await call("switch", "turn_on", relay_1) == b"\x11"
    assert await call("switch", "turn_off", relay_2) == b"\x20"
    assert await call("switch", "turn_on", relay_2) == b"\x21"
    assert await call("switch", "turn_off", relay_3) == b"\x30"
    assert await call("switch", "turn_on", relay_3) == b"\x31"

    async def call_rm_action(registry_entry: er.RegistryEntry, command: str) -> bytes:
        assert registry_entry.device_id is not None
        mock_send.reset_mock()
        await hass.services.async_call(
            DOMAIN,
            "send_rm_command",
            {
                ATTR_DEVICE_ID: [registry_entry.device_id],
                "command": command,
            },
            blocking=True,
        )
        return mock_send.await_args.args[1][0]

    assert await call_rm_action(fan, "oscillate") == b"\x02"
    assert await call_rm_action(relay_1, "all_off") == b"\xf0"


async def test_send_rm_command_rejects_invalid_targets(
    hass: HomeAssistant,
    mock_send: AsyncMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test the RM action rejects unknown, non-RM, unloaded and unsupported targets."""
    entry = _entry_for_family()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    devices = {device.name: device for device in entry.runtime_data.family.devices}

    def device_id(identifier: str) -> str:
        registry_device = device_registry.async_get_device_by_identifier(
            (DOMAIN, identifier), entry.entry_id
        )
        assert registry_device is not None
        return registry_device.id

    fan_id = device_id(magic_rm_device_identifier(devices["Fan"].stable_id))
    ble_light_id = device_id(magic_device_identifier(devices["BLE light"].stable_id))

    async def send(target: str, command: str = "power") -> None:
        await hass.services.async_call(
            DOMAIN,
            "send_rm_command",
            {ATTR_DEVICE_ID: [target], "command": command},
            blocking=True,
        )

    with pytest.raises(ServiceValidationError) as err:
        await send("missing-device")
    assert err.value.translation_key == "rm_device_not_found"
    with pytest.raises(ServiceValidationError) as err:
        await send(ble_light_id)
    assert err.value.translation_key == "rm_device_not_found"
    with pytest.raises(ServiceValidationError) as err:
        await send(fan_id, "not_a_command")
    assert err.value.translation_key == "rm_command_not_supported"
    removed = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, magic_rm_device_identifier("removed-child"))},
    )
    with pytest.raises(ServiceValidationError) as err:
        await send(removed.id)
    assert err.value.translation_key == "rm_device_not_found"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as err:
        await send(fan_id)
    assert err.value.translation_key == "rm_device_not_found"
    mock_send.assert_not_awaited()


def _entry_for_devices(devices: list[dict[str, object]]) -> MockConfigEntry:
    family = parse_import_payload(_import_payload(devices))[0]
    gateways = [DiscoveredRMMax("192.0.2.20", "a1b2c3d4e5f6", 0xAF8B, "RM Max")]
    return MockConfigEntry(
        domain=DOMAIN,
        title="RM test home",
        unique_id="magic:rm-family",
        data={
            **family_to_entry_data(family, gateways),
            CONF_ENTRY_KIND: ENTRY_KIND_MAGIC_FAMILY,
        },
    )


def _rm_child(index: int, spid: str, name: str, functions: list[dict[str, object]]):
    return {
        "did": "00000000000000000000a1b2c3d4e5f6",
        "pid": "0000000000000000000000008baf0000",
        "sdid": f"a1b2c3d4e5f6{index:020x}",
        "spid": f"000000000000000000000000{spid}0000",
        "shortaddr": str(index + 1),
        "devname": name,
        "extend": json.dumps({"functionList": functions}),
    }


async def test_imported_function_list_drives_rm_entities(
    hass: HomeAssistant,
    mock_send: AsyncMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test imported functionList codes and feature filtering."""
    entry = _entry_for_devices(
        [
            {
                "did": "00000000000000000000a1b2c3d4e5f6",
                "pid": "0000000000000000000000008baf0000",
                "mac": "a1b2c3d4e5f6",
                "devname": "RM Max",
            },
            _rm_child(
                2,
                "2baf",
                "TV",
                [
                    {"function": "power", "type": 1},
                    {"function": "volume_up", "type": 0x51},
                    {"function": "volume_down", "type": 0x52},
                    {"function": "channel_up", "type": 19},
                ],
            ),
            _rm_child(3, "65b2", "Drying rack", [{"function": "dry_up", "type": 1}]),
            _rm_child(
                4,
                "5ab1",
                "Relay panel",
                [
                    {"function": "switch1_open", "type": 0x11},
                    {"function": "switch1_close", "type": 0x10},
                ],
            ),
            _rm_child(
                5,
                "32af",
                "Learned IR",
                [{"function": "extend", "name": "红外开关", "type": 1}],
            ),
        ]
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    ids = {
        device.name: device.stable_id for device in entry.runtime_data.family.devices
    }

    def entity_id(domain: str, unique_id: str) -> str | None:
        return entity_registry.async_get_entity_id(domain, DOMAIN, unique_id)

    tv = entity_id("media_player", f"rm-family_{ids['TV']}")
    drying_cover = entity_id("cover", f"rm-family_{ids['Drying rack']}")
    assert tv and drying_cover
    assert entity_id("light", f"rm-family_{ids['Drying rack']}") is None
    assert entity_id("switch", f"rm-family_{ids['Relay panel']}_1")
    assert entity_id("switch", f"rm-family_{ids['Relay panel']}_2") is None

    tv_features = hass.states.get(tv).attributes["supported_features"]
    assert tv_features == (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.NEXT_TRACK
    )
    assert (
        hass.states.get(drying_cover).attributes["supported_features"]
        == CoverEntityFeature.OPEN
    )
    coordinator = entry.runtime_data
    coordinator.gateway_set.handle_packet(
        "a1b2c3d4e5f6",
        pack_message(MSG_HEARTBEAT, 1, bytes.fromhex("a1b2c3d4e5f6")),
        ("192.0.2.20", 41001),
    )
    coordinator.async_set_updated_data(coordinator.gateway_set)
    await hass.async_block_till_done()

    async def call(domain: str, service: str, target: str, **data: object) -> bytes:
        mock_send.reset_mock()
        await hass.services.async_call(
            domain, service, {ATTR_ENTITY_ID: target, **data}, blocking=True
        )
        return mock_send.await_args.args[1][0]

    assert await call("media_player", "volume_up", tv) == b"\x51"
    assert await call("cover", "open_cover", drying_cover) == b"\x01"

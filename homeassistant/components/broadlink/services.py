"""Service actions for stateless RM child commands."""

from broadlink_async.magic import BroadLinkMagicError
import probatio

from homeassistant.const import ATTR_COMMAND, ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN, is_magic_entry

SERVICE_SEND_RM_COMMAND = "send_rm_command"
RM_IDENTIFIER_PREFIX = "magic:rm:"


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register RM child service actions once."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_RM_COMMAND):
        return

    async def async_send_rm_command(call: ServiceCall) -> None:
        """Send one profile command to selected RM child devices."""
        registry = dr.async_get(hass)
        command = call.data[ATTR_COMMAND].strip().lower()
        for device_id in call.data[ATTR_DEVICE_ID]:
            registry_device = registry.async_get(device_id)
            if registry_device is None:
                raise _device_not_found(device_id)
            stable_id = next(
                (
                    identifier.removeprefix(RM_IDENTIFIER_PREFIX)
                    for domain, identifier in registry_device.identifiers
                    if domain == DOMAIN and identifier.startswith(RM_IDENTIFIER_PREFIX)
                ),
                None,
            )
            config_entry = hass.config_entries.async_get_entry(
                registry_device.config_entry_id
            )
            if (
                stable_id is None
                or config_entry is None
                or not is_magic_entry(config_entry)
                or not hasattr(config_entry, "runtime_data")
            ):
                raise _device_not_found(device_id)
            coordinator = config_entry.runtime_data
            imported_device = next(
                (
                    device
                    for device in coordinator.family.devices
                    if device.stable_id == stable_id and device.is_rm_child
                ),
                None,
            )
            if imported_device is None:
                raise _device_not_found(device_id)
            try:
                await coordinator.async_send_rm_commands(
                    imported_device,
                    [command],
                )
            except (BroadLinkMagicError, ValueError) as err:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="rm_command_not_supported",
                    translation_placeholders={
                        "command": command,
                        "device": imported_device.name,
                    },
                ) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_RM_COMMAND,
        async_send_rm_command,
        schema=probatio.Schema(
            {
                probatio.Required(ATTR_DEVICE_ID): probatio.All(
                    probatio.EnsureList(),
                    [cv.string],
                ),
                probatio.Required(ATTR_COMMAND): cv.string,
            }
        ),
    )


def _device_not_found(device_id: str) -> ServiceValidationError:
    """Return a translated invalid RM target error."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="rm_device_not_found",
        translation_placeholders={"device_id": device_id},
    )

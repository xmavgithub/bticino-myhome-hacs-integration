"""MyHOME integration."""

from .OWNd.message import OWNCommand, OWNGatewayCommand

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er, config_validation as cv
from homeassistant.const import CONF_MAC

from .const import (
    ATTR_AREA_END,
    ATTR_AREA_START,
    ATTR_CLEAR,
    ATTR_DURATION,
    ATTR_GATEWAY,
    ATTR_MESSAGE,
    ATTR_POINT_END,
    ATTR_POINT_START,
    ATTR_SCAN_COVERS,
    ATTR_SCAN_CLIMATE,
    ATTR_SCAN_POWER,
    ATTR_SCAN_LIGHTS,
    CONF_PLATFORMS,
    CONF_ENTITY,
    CONF_ENTITIES,
    DISCOVERY_DEFAULT_AREA_END,
    DISCOVERY_DEFAULT_AREA_START,
    DISCOVERY_DEFAULT_DURATION,
    DISCOVERY_DEFAULT_POINT_END,
    DISCOVERY_DEFAULT_POINT_START,
    CONF_WORKER_COUNT,
    CONF_FILE_PATH,
    CONF_GENERATE_EVENTS,
    DOMAIN,
    LOGGER,
)
from .validate import config_schema, format_mac
from .gateway import MyHOMEGatewayHandler
from .web import async_setup_web, async_unload_web
from .config_store import (
    async_get_or_migrate_gateway_config,
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = ["light", "switch", "cover", "climate", "binary_sensor", "sensor"]


async def async_setup(hass, config):
    """Set up the MyHOME component."""
    hass.data[DOMAIN] = {}

    if DOMAIN not in config:
        return True

    LOGGER.error("configuration.yaml not supported for this component!")

    return False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    if entry.data[CONF_MAC] not in hass.data[DOMAIN]:
        hass.data[DOMAIN][entry.data[CONF_MAC]] = {}

    _config_file_path = (
        str(entry.options[CONF_FILE_PATH])
        if CONF_FILE_PATH in entry.options
        else "/config/myhome.yaml"
    )
    _generate_events = (
        entry.options[CONF_GENERATE_EVENTS]
        if CONF_GENERATE_EVENTS in entry.options
        else False
    )
    _discovery_by_activation = True

    raw_gateway_config = await async_get_or_migrate_gateway_config(
        hass,
        entry.data[CONF_MAC],
        _config_file_path,
    )
    _validated_config = config_schema({entry.data[CONF_MAC]: raw_gateway_config})
    hass.data[DOMAIN][entry.data[CONF_MAC]] = _validated_config[entry.data[CONF_MAC]]

    # Migrating the config entry's unique_id if it was not formated to the recommended hass standard
    if entry.unique_id != dr.format_mac(entry.unique_id):
        hass.config_entries.async_update_entry(
            entry, unique_id=dr.format_mac(entry.unique_id)
        )
        LOGGER.warning("Migrating config entry unique_id to %s", entry.unique_id)

    hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY] = MyHOMEGatewayHandler(
        hass=hass,
        config_entry=entry,
        generate_events=_generate_events,
        discovery_by_activation=_discovery_by_activation,
    )

    try:
        tests_results = await hass.data[DOMAIN][entry.data[CONF_MAC]][
            CONF_ENTITY
        ].test()
    except OSError as ose:
        _gateway_data = hass.data[DOMAIN].pop(entry.data[CONF_MAC], {})
        _gateway_handler = _gateway_data.get(CONF_ENTITY)
        _host = (
            _gateway_handler.gateway.host
            if _gateway_handler is not None
            else entry.data.get("host", "unknown")
        )
        raise ConfigEntryNotReady(
            f"Gateway cannot be reached at {_host}, make sure its address is correct."
        ) from ose

    if not tests_results["Success"]:
        if (
            tests_results["Message"] == "password_error"
            or tests_results["Message"] == "password_required"
        ):
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": SOURCE_REAUTH},
                    data=entry.data,
                )
            )
        del hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY]
        return False

    _command_worker_count = (
        int(entry.options[CONF_WORKER_COUNT])
        if CONF_WORKER_COUNT in entry.options
        else 1
    )

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    gateway_device_entry = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, entry.data[CONF_MAC])},
        identifiers={
            (DOMAIN, hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].unique_id)
        },
        manufacturer=hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].manufacturer,
        name=hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].name,
        model=hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].model,
        sw_version=hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].firmware,
    )

    await hass.config_entries.async_forward_entry_setups(
        entry, hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_PLATFORMS].keys()
    )

    hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].listening_worker = (
        hass.loop.create_task(
            hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].listening_loop()
        )
    )
    for i in range(_command_worker_count):
        hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].sending_workers.append(
            hass.loop.create_task(
                hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_ENTITY].sending_loop(i)
            )
        )

    # Pruning lose entities and devices from the registry
    entity_entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)

    entities_to_be_removed = []
    devices_to_be_removed = [
        device_entry.id
        for device_entry in device_registry.devices.values()
        if entry.entry_id in device_entry.config_entries
    ]

    configured_entities = []

    for _platform in hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_PLATFORMS].keys():
        for _device in hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_PLATFORMS][
            _platform
        ].keys():
            for _entity_name in hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_PLATFORMS][
                _platform
            ][_device][CONF_ENTITIES]:
                if _entity_name != _platform:
                    configured_entities.append(
                        f"{entry.data[CONF_MAC]}-{_device}-{_entity_name}"
                    )  # extrapolating _attr_unique_id out of the entity's place in the config data structure
                else:
                    configured_entities.append(
                        f"{entry.data[CONF_MAC]}-{_device}"
                    )  # extrapolating _attr_unique_id out of the entity's place in the config data structure

    for entity_entry in entity_entries:
        if entity_entry.unique_id in configured_entities:
            if entity_entry.device_id in devices_to_be_removed:
                devices_to_be_removed.remove(entity_entry.device_id)
            continue
        entities_to_be_removed.append(entity_entry.entity_id)

    for enity_id in entities_to_be_removed:
        entity_registry.async_remove(enity_id)

    if gateway_device_entry.id in devices_to_be_removed:
        devices_to_be_removed.remove(gateway_device_entry.id)

    for device_id in devices_to_be_removed:
        if (
            len(
                er.async_entries_for_device(
                    entity_registry, device_id, include_disabled_entities=True
                )
            )
            == 0
        ):
            device_registry.async_remove_device(device_id)

    # Defining the services
    async def handle_sync_time(call):
        gateway = call.data.get(ATTR_GATEWAY, None)
        if gateway is None:
            gateway = list(hass.data[DOMAIN].keys())[0]
        else:
            mac = format_mac(gateway)
            if mac is None:
                LOGGER.error(
                    "Invalid gateway mac `%s`, could not send time synchronisation message.",
                    gateway,
                )
                return False
            else:
                gateway = mac
        timezone = hass.config.as_dict()["time_zone"]
        if gateway in hass.data[DOMAIN]:
            await hass.data[DOMAIN][gateway][CONF_ENTITY].send(
                OWNGatewayCommand.set_datetime_to_now(timezone)
            )
        else:
            LOGGER.error(
                "Gateway `%s` not found, could not send time synchronisation message.",
                gateway,
            )
            return False

    hass.services.async_register(DOMAIN, "sync_time", handle_sync_time)

    async def handle_send_message(call):
        gateway = call.data.get(ATTR_GATEWAY, None)
        message = call.data.get(ATTR_MESSAGE, None)
        if gateway is None:
            gateway = list(hass.data[DOMAIN].keys())[0]
        else:
            mac = format_mac(gateway)
            if mac is None:
                LOGGER.error(
                    "Invalid gateway mac `%s`, could not send message `%s`.",
                    gateway,
                    message,
                )
                return False
            else:
                gateway = mac
        LOGGER.debug("Handling message `%s` to be sent to `%s`", message, gateway)
        if gateway in hass.data[DOMAIN]:
            if message is not None:
                own_message = OWNCommand.parse(message)
                if own_message is not None:
                    if own_message.is_valid:
                        LOGGER.debug(
                            "%s Sending valid OpenWebNet Message: `%s`",
                            hass.data[DOMAIN][gateway][CONF_ENTITY].log_id,
                            own_message,
                        )
                        await hass.data[DOMAIN][gateway][CONF_ENTITY].send(own_message)
                else:
                    LOGGER.error(
                        "Could not parse message `%s`, not sending it.", message
                    )
                    return False
        else:
            LOGGER.error(
                "Gateway `%s` not found, could not send message `%s`.", gateway, message
            )
            return False

    hass.services.async_register(DOMAIN, "send_message", handle_send_message)

    def _resolve_gateway(gateway):
        if gateway is None:
            return list(hass.data[DOMAIN].keys())[0]
        mac = format_mac(gateway)
        return mac

    def _build_suggestion_lines(
        light_results,
        cover_results,
        climate_results=None,
        power_results=None,
    ):
        suggestion_lines = []
        if light_results:
            suggestion_lines.append("Light:")
            for where in light_results:
                suggestion_lines.append(
                    f"- where={where} (suggested key: discovered_light_{where})"
                )

        if cover_results:
            suggestion_lines.append("Cover:")
            for where in cover_results:
                suggestion_lines.append(
                    f"- where={where} (suggested key: discovered_cover_{where})"
                )

        if climate_results:
            suggestion_lines.append("Climate:")
            for zone in climate_results:
                suggestion_lines.append(
                    f"- zone={zone} (suggested key: discovered_climate_{zone})"
                )

        if power_results:
            suggestion_lines.append("Power sensor:")
            for where in power_results:
                suggestion_lines.append(
                    f"- where={where} (suggested key: discovered_power_{where})"
                )

        return suggestion_lines

    async def handle_discover_devices(call):
        gateway = _resolve_gateway(call.data.get(ATTR_GATEWAY, None))
        if gateway is None:
            LOGGER.error(
                "Invalid gateway mac `%s`, could not start discovery.",
                call.data.get(ATTR_GATEWAY, None),
            )
            return False

        if gateway not in hass.data[DOMAIN]:
            LOGGER.error("Gateway `%s` not found, could not start discovery.", gateway)
            return False

        scan_lights = bool(call.data.get(ATTR_SCAN_LIGHTS, True))
        scan_covers = bool(call.data.get(ATTR_SCAN_COVERS, True))
        scan_climate = bool(call.data.get(ATTR_SCAN_CLIMATE, True))
        scan_power = bool(call.data.get(ATTR_SCAN_POWER, True))
        area_start = int(call.data.get(ATTR_AREA_START, DISCOVERY_DEFAULT_AREA_START))
        area_end = int(call.data.get(ATTR_AREA_END, DISCOVERY_DEFAULT_AREA_END))
        point_start = int(
            call.data.get(ATTR_POINT_START, DISCOVERY_DEFAULT_POINT_START)
        )
        point_end = int(call.data.get(ATTR_POINT_END, DISCOVERY_DEFAULT_POINT_END))
        duration = int(call.data.get(ATTR_DURATION, DISCOVERY_DEFAULT_DURATION))

        gateway_handler = hass.data[DOMAIN][gateway][CONF_ENTITY]
        LOGGER.info(
            "%s Starting device discovery (lights=%s, covers=%s, climate=%s, power=%s, area=%s-%s, point=%s-%s, duration=%ss).",
            gateway_handler.log_id,
            scan_lights,
            scan_covers,
            scan_climate,
            scan_power,
            area_start,
            area_end,
            point_start,
            point_end,
            duration,
        )

        try:
            results = await gateway_handler.discover_devices(
                scan_lights=scan_lights,
                scan_covers=scan_covers,
                scan_climate=scan_climate,
                scan_power=scan_power,
                area_start=area_start,
                area_end=area_end,
                point_start=point_start,
                point_end=point_end,
                duration=duration,
            )
        except RuntimeError as runtime_error:
            LOGGER.warning("%s %s", gateway_handler.log_id, runtime_error)
            return False

        light_results = results.get("light", [])
        cover_results = results.get("cover", [])
        climate_results = results.get("climate", [])
        power_results = results.get("power", [])

        LOGGER.info(
            "%s Discovery completed: %s lights, %s covers, %s climate zones, %s power sensors.",
            gateway_handler.log_id,
            len(light_results),
            len(cover_results),
            len(climate_results),
            len(power_results),
        )

        suggestion_lines = _build_suggestion_lines(
            light_results,
            cover_results,
            climate_results,
            power_results,
        )

        summary_lines = [
            f"Gateway: `{gateway}`",
            f"Lights found: **{len(light_results)}**",
            f"Covers found: **{len(cover_results)}**",
            f"Climate zones found: **{len(climate_results)}**",
            f"Power sensors found: **{len(power_results)}**",
            "",
            "Open the MyHOME Discovery panel and use `Importa nuovi in configurazione` to add them.",
        ]
        if suggestion_lines:
            summary_lines.append("")
            summary_lines.append("Detected endpoints:")
            summary_lines.extend(suggestion_lines)
        else:
            summary_lines.append("No devices found in scanned range.")

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "MyHOME discovery results",
                "message": "\n".join(summary_lines),
                "notification_id": f"myhome_discovery_{gateway}",
            },
            blocking=False,
        )

        return True

    async def handle_set_discovery_by_activation(call):
        gateway = _resolve_gateway(call.data.get(ATTR_GATEWAY, None))
        if gateway is None:
            LOGGER.error(
                "Invalid gateway mac `%s`, could not set discovery_by_activation.",
                call.data.get(ATTR_GATEWAY, None),
            )
            return False

        if gateway not in hass.data[DOMAIN]:
            LOGGER.error(
                "Gateway `%s` not found, could not set discovery_by_activation.",
                gateway,
            )
            return False

        gateway_handler = hass.data[DOMAIN][gateway][CONF_ENTITY]
        gateway_handler.set_discovery_by_activation(True)
        LOGGER.info(
            "%s discovery_by_activation forced to always-on mode.",
            gateway_handler.log_id,
        )
        return True

    async def handle_show_activation_discovery(call):
        gateway = _resolve_gateway(call.data.get(ATTR_GATEWAY, None))
        if gateway is None:
            LOGGER.error(
                "Invalid gateway mac `%s`, could not show activation discovery.",
                call.data.get(ATTR_GATEWAY, None),
            )
            return False

        if gateway not in hass.data[DOMAIN]:
            LOGGER.error(
                "Gateway `%s` not found, could not show activation discovery.",
                gateway,
            )
            return False

        clear = bool(call.data.get(ATTR_CLEAR, False))
        gateway_handler = hass.data[DOMAIN][gateway][CONF_ENTITY]
        results = gateway_handler.get_activation_discovery_results(clear=clear)
        light_results = results.get("light", [])
        cover_results = results.get("cover", [])
        climate_results = results.get("climate", [])
        power_results = results.get("power", [])

        suggestion_lines = _build_suggestion_lines(
            light_results,
            cover_results,
            climate_results,
            power_results,
        )

        summary_lines = [
            f"Gateway: `{gateway}`",
            f"Discovery by activation enabled: **{gateway_handler.discovery_by_activation}**",
            f"Lights found: **{len(light_results)}**",
            f"Covers found: **{len(cover_results)}**",
            f"Climate zones found: **{len(climate_results)}**",
            f"Power sensors found: **{len(power_results)}**",
            "",
            "Open the MyHOME Discovery panel and use `Importa nuovi in configurazione` to add them.",
        ]
        if suggestion_lines:
            summary_lines.append("")
            summary_lines.append("Detected endpoints:")
            summary_lines.extend(suggestion_lines)
        else:
            summary_lines.append("No devices found yet from activation discovery.")

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "MyHOME activation discovery results",
                "message": "\n".join(summary_lines),
                "notification_id": f"myhome_activation_discovery_{gateway}",
            },
            blocking=False,
        )

        return True

    hass.services.async_register(DOMAIN, "discover_devices", handle_discover_devices)
    hass.services.async_register(
        DOMAIN,
        "set_discovery_by_activation",
        handle_set_discovery_by_activation,
    )
    hass.services.async_register(
        DOMAIN,
        "show_activation_discovery",
        handle_show_activation_discovery,
    )
    await async_setup_web(hass)

    return True


async def async_unload_entry(hass, entry):
    """Unload a config entry."""

    LOGGER.info("Unloading MyHome entry.")

    for platform in hass.data[DOMAIN][entry.data[CONF_MAC]][CONF_PLATFORMS].keys():
        await hass.config_entries.async_forward_entry_unload(entry, platform)

    hass.services.async_remove(DOMAIN, "sync_time")
    hass.services.async_remove(DOMAIN, "send_message")
    hass.services.async_remove(DOMAIN, "discover_devices")
    hass.services.async_remove(DOMAIN, "set_discovery_by_activation")
    hass.services.async_remove(DOMAIN, "show_activation_discovery")

    gateway_handler = hass.data[DOMAIN][entry.data[CONF_MAC]].pop(CONF_ENTITY)
    del hass.data[DOMAIN][entry.data[CONF_MAC]]
    async_unload_web(hass)

    return await gateway_handler.close_listener()

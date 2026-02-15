"""Web UI endpoints and panel registration for MyHOME discovery."""

from __future__ import annotations

from http import HTTPStatus
from json import JSONDecodeError
from pathlib import Path
from typing import Any
import re

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.const import CONF_MAC

from .const import (
    CONF_BUS_INTERFACE,
    CONF_DEVICE_CLASS,
    CONF_DEVICE_MODEL,
    CONF_ENTITY,
    CONF_MANUFACTURER,
    CONF_PLATFORMS,
    CONF_WHERE,
    CONF_WHO,
    CONF_ZONE,
    DISCOVERY_DEFAULT_AREA_END,
    DISCOVERY_DEFAULT_AREA_START,
    DISCOVERY_DEFAULT_DURATION,
    DISCOVERY_DEFAULT_POINT_END,
    DISCOVERY_DEFAULT_POINT_START,
    DOMAIN,
    LOGGER,
)
from .config_store import (
    async_clear_activation_discovery_results,
    async_get_activation_discovery_results,
    async_get_gateway_config,
    async_set_activation_discovery_results,
    async_set_gateway_config,
)
from .validate import config_schema, format_mac

PANEL_URL_PATH = "myhome-discovery"
PANEL_WEBCOMPONENT_NAME = "myhome-discovery-panel"
PANEL_TITLE = "bticino MyHome Unofficial Integration"
PANEL_ICON = "mdi:radar"
PANEL_STATIC_URL_PATH = "/api/myhome/panel"
PANEL_MODULE_URL = f"{PANEL_STATIC_URL_PATH}/myhome-discovery-panel.js"
WEB_RUNTIME_DATA = f"{DOMAIN}_web_runtime"
LIGHT_PLATFORM = "light"
COVER_PLATFORM = "cover"
CLIMATE_PLATFORM = "climate"
SENSOR_PLATFORM = "sensor"
CONFIG_PLATFORMS = {LIGHT_PLATFORM, COVER_PLATFORM, CLIMATE_PLATFORM, SENSOR_PLATFORM}
SENSOR_CLASSES = {"power", "temperature", "energy", "illuminance"}
_SAFE_KEY_PATTERN = re.compile(r"[^a-z0-9_]+")


def _runtime_data(hass) -> dict[str, Any]:
    """Return mutable runtime data for web resources."""
    return hass.data.setdefault(
        WEB_RUNTIME_DATA,
        {
            "api_registered": False,
            "panel_registered": False,
            "entry_count": 0,
        },
    )


def _to_bool(value: Any, default: bool) -> bool:
    """Convert user payload values to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _to_int(value: Any, default: int) -> int:
    """Convert user payload values to integer."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sanitize_key(value: str) -> str:
    clean = _SAFE_KEY_PATTERN.sub("_", str(value).strip().lower())
    clean = re.sub(r"_+", "_", clean).strip("_")
    return clean or "device"


def _resolve_gateway_from_payload(configured_gateways, requested_gateway):
    if not configured_gateways:
        return None, "No MyHOME gateways are configured.", HTTPStatus.NOT_FOUND

    if requested_gateway is None:
        return next(iter(configured_gateways.keys())), None, None

    gateway = format_mac(requested_gateway)
    if gateway is None:
        return None, f"Invalid gateway `{requested_gateway}`.", HTTPStatus.BAD_REQUEST
    if gateway not in configured_gateways:
        return None, f"Gateway `{gateway}` was not found.", HTTPStatus.NOT_FOUND
    return gateway, None, None


def _entry_for_gateway(hass, gateway: str):
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_MAC) == gateway:
            return entry
    return None


async def _reload_gateway_entry(hass, gateway: str) -> None:
    if entry := _entry_for_gateway(hass, gateway):
        await hass.config_entries.async_reload(entry.entry_id)


def _device_from_payload(platform: str, payload: dict[str, Any]) -> tuple[str | None, dict | None, str | None]:
    name = str(payload.get("name") or "").strip()
    if platform in (LIGHT_PLATFORM, COVER_PLATFORM, SENSOR_PLATFORM):
        where = str(payload.get("where") or "").strip()
        if not where:
            return None, None, "Field `where` is required."
        if not name:
            name = f"{platform.capitalize()} {where}"
        if platform == LIGHT_PLATFORM:
            return where, {
                "where": where,
                "name": name,
                "dimmable": _to_bool(payload.get("dimmable"), False),
            }, None
        if platform == COVER_PLATFORM:
            return where, {"where": where, "name": name}, None
        sensor_class = str(payload.get("class") or "power").strip().lower()
        if sensor_class not in SENSOR_CLASSES:
            return None, None, f"Invalid sensor class `{sensor_class}`."
        return where, {"where": where, "name": name, "class": sensor_class}, None

    zone = str(payload.get("zone") or "").strip()
    if not zone:
        return None, None, "Field `zone` is required."
    if not name:
        name = f"Climate {zone}"
    return zone, {
        "zone": zone,
        "name": name,
        "heat": _to_bool(payload.get("heat"), True),
        "cool": _to_bool(payload.get("cool"), True),
        "fan": _to_bool(payload.get("fan"), True),
        "standalone": _to_bool(payload.get("standalone"), True),
    }, None


def _devices_for_ui(gateway_payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    devices: dict[str, list[dict[str, Any]]] = {
        LIGHT_PLATFORM: [],
        COVER_PLATFORM: [],
        CLIMATE_PLATFORM: [],
        SENSOR_PLATFORM: [],
    }
    for platform in CONFIG_PLATFORMS:
        platform_data = gateway_payload.get(platform, {})
        if not isinstance(platform_data, dict):
            continue
        for key, value in sorted(platform_data.items()):
            if not isinstance(value, dict):
                continue
            entry = {
                "key": key,
                "name": value.get("name"),
                "where": value.get("where"),
                "zone": value.get("zone"),
                "who": value.get(CONF_WHO),
                "interface": value.get(CONF_BUS_INTERFACE),
                "manufacturer": value.get(CONF_MANUFACTURER),
                "model": value.get(CONF_DEVICE_MODEL),
            }
            if platform == LIGHT_PLATFORM:
                entry["dimmable"] = bool(value.get("dimmable", False))
            if platform == SENSOR_PLATFORM:
                entry["class"] = value.get("class")
            if platform == CLIMATE_PLATFORM:
                entry["heat"] = bool(value.get("heat", True))
                entry["cool"] = bool(value.get("cool", False))
                entry["fan"] = bool(value.get("fan", False))
                entry["standalone"] = bool(value.get("standalone", False))
            devices[platform].append(entry)
    return devices


def _configured_discovery_endpoints(hass, gateway: str) -> dict[str, set[str]]:
    """Return already configured endpoints from runtime config."""
    gateway_data = hass.data.get(DOMAIN, {}).get(gateway, {})
    platforms = gateway_data.get(CONF_PLATFORMS, {})

    light_where = {
        str(device_data.get(CONF_WHERE))
        for device_data in platforms.get(LIGHT_PLATFORM, {}).values()
        if device_data.get(CONF_WHERE) is not None
    }
    cover_where = {
        str(device_data.get(CONF_WHERE))
        for device_data in platforms.get(COVER_PLATFORM, {}).values()
        if device_data.get(CONF_WHERE) is not None
    }
    climate_zone = {
        str(device_data.get(CONF_ZONE))
        for device_data in platforms.get(CLIMATE_PLATFORM, {}).values()
        if device_data.get(CONF_ZONE) is not None
    }
    power_where = set()
    for device_data in platforms.get(SENSOR_PLATFORM, {}).values():
        where = device_data.get(CONF_WHERE)
        if where is None:
            continue
        device_class = str(device_data.get(CONF_DEVICE_CLASS, "")).lower().split(".")[-1]
        if device_class in ("power", "energy"):
            power_where.add(str(where))

    return {
        "light": light_where,
        "cover": cover_where,
        "climate": climate_zone,
        "power": power_where,
    }


def _mapped_results(items: list[str], configured: set[str]) -> tuple[list[str], list[str]]:
    """Split results between already configured and new endpoints."""
    mapped = [str(item) for item in items if str(item) in configured]
    new = [str(item) for item in items if str(item) not in configured]
    return mapped, new


def _merge_discovery_results(
    left: dict[str, list[str]],
    right: dict[str, list[str]],
) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for kind in ("light", "cover", "climate", "power"):
        values = {str(item) for item in left.get(kind, [])}
        values.update({str(item) for item in right.get(kind, [])})
        merged[kind] = sorted(values)
    return merged


def _is_valid_discovery_climate(where_raw: str) -> bool:
    where = str(where_raw)
    if not where or where == "*":
        return False

    parts = [part for part in where.split("#") if part]
    if not parts:
        return False

    if parts[0] == "0" and len(parts) >= 2:
        zone = parts[1]
    else:
        zone = parts[0]

    return zone.isdigit() and int(zone) > 0


def _build_discovery_snippet(
    light_results: list[str],
    cover_results: list[str],
    climate_results: list[str] | None = None,
    power_results: list[str] | None = None,
    mapped: dict[str, set[str]] | None = None,
) -> str:
    """Build a YAML snippet from discovery results."""
    snippet_lines: list[str] = []
    mapped = mapped or {"light": set(), "cover": set(), "climate": set(), "power": set()}

    if light_results:
        snippet_lines.append("light:")
        for where in light_results:
            suffix = "  # already_configured" if str(where) in mapped["light"] else ""
            snippet_lines.append(f"  discovered_light_{where}:{suffix}")
            snippet_lines.append(f"    where: '{where}'")
            snippet_lines.append(f"    name: Light {where}")
            snippet_lines.append("    dimmable: false")

    if cover_results:
        snippet_lines.append("cover:")
        for where in cover_results:
            suffix = "  # already_configured" if str(where) in mapped["cover"] else ""
            snippet_lines.append(f"  discovered_cover_{where}:{suffix}")
            snippet_lines.append(f"    where: '{where}'")
            snippet_lines.append(f"    name: Cover {where}")

    if climate_results:
        snippet_lines.append("climate:")
        for zone in climate_results:
            suffix = "  # already_configured" if str(zone) in mapped["climate"] else ""
            snippet_lines.append(f"  discovered_climate_{zone}:{suffix}")
            snippet_lines.append(f"    zone: '{zone}'")
            snippet_lines.append(f"    name: Climate {zone}")
            snippet_lines.append("    heat: true")
            snippet_lines.append("    cool: true")
            snippet_lines.append("    fan: true")

    if power_results:
        snippet_lines.append("sensor:")
        for where in power_results:
            suffix = "  # already_configured" if str(where) in mapped["power"] else ""
            snippet_lines.append(f"  discovered_power_{where}:{suffix}")
            snippet_lines.append(f"    where: '{where}'")
            snippet_lines.append(f"    name: Power {where}")
            snippet_lines.append("    class: power")

    if not snippet_lines:
        snippet_lines.append("# No devices found in scanned range")

    return "\n".join(snippet_lines)


class MyHOMEGatewaysView(HomeAssistantView):
    """Return configured gateways for panel UI."""

    url = "/api/myhome/gateways"
    name = "api:myhome:gateways"
    requires_auth = True

    async def get(self, request):
        """Handle gateway list requests."""
        hass = request.app["hass"]
        gateways = []

        for mac, gateway_data in hass.data.get(DOMAIN, {}).items():
            gateway_handler = gateway_data.get(CONF_ENTITY)
            if gateway_handler is None:
                continue

            gateways.append(
                {
                    "mac": mac,
                    "name": gateway_handler.name,
                    "host": gateway_handler.gateway.host,
                    "discovery_by_activation": gateway_handler.discovery_by_activation,
                }
            )

        gateways.sort(key=lambda gateway: gateway["mac"])
        return self.json({"gateways": gateways})


class MyHOMEConfigurationView(HomeAssistantView):
    """Read/write configured devices from panel UI."""

    url = "/api/myhome/configuration"
    name = "api:myhome:configuration"
    requires_auth = True

    async def get(self, request):
        hass = request.app["hass"]
        configured_gateways = hass.data.get(DOMAIN, {})
        gateway, error, status = _resolve_gateway_from_payload(
            configured_gateways,
            request.query.get("gateway"),
        )
        if gateway is None:
            return self.json_message(error, status_code=status)

        gateway_payload = await async_get_gateway_config(hass, gateway) or {CONF_MAC: gateway}
        return self.json(
            {
                "gateway": gateway,
                "devices": _devices_for_ui(gateway_payload),
            }
        )


class MyHOMEConfigurationDeviceView(HomeAssistantView):
    """Upsert a single configured device from panel UI."""

    url = "/api/myhome/configuration/device"
    name = "api:myhome:configuration:device"
    requires_auth = True

    async def post(self, request):
        hass = request.app["hass"]
        try:
            payload = await request.json()
        except JSONDecodeError:
            payload = {}

        configured_gateways = hass.data.get(DOMAIN, {})
        gateway, error, status = _resolve_gateway_from_payload(
            configured_gateways,
            payload.get("gateway"),
        )
        if gateway is None:
            return self.json_message(error, status_code=status)

        platform = str(payload.get("platform") or "").strip().lower()
        if platform not in CONFIG_PLATFORMS:
            return self.json_message(
                f"Invalid platform `{platform}`.",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        address, device, device_error = _device_from_payload(platform, payload)
        if device_error:
            return self.json_message(device_error, status_code=HTTPStatus.BAD_REQUEST)

        provided_key = payload.get("key")
        raw_key = (
            str(provided_key).strip()
            if provided_key is not None and str(provided_key).strip()
            else f"manual_{platform}_{address}"
        )
        key = _sanitize_key(raw_key)

        gateway_payload = await async_get_gateway_config(hass, gateway) or {CONF_MAC: gateway}
        platform_payload = gateway_payload.setdefault(platform, {})
        if not isinstance(platform_payload, dict):
            platform_payload = {}
            gateway_payload[platform] = platform_payload
        platform_payload[key] = device

        try:
            config_schema({gateway: gateway_payload})
        except Exception as err:  # pylint: disable=broad-except
            return self.json_message(
                f"Invalid configuration: {err}",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        await async_set_gateway_config(hass, gateway, gateway_payload)
        await _reload_gateway_entry(hass, gateway)
        return self.json(
            {
                "ok": True,
                "gateway": gateway,
                "platform": platform,
                "key": key,
                "devices": _devices_for_ui(gateway_payload),
            }
        )


class MyHOMEConfigurationDeleteView(HomeAssistantView):
    """Delete a configured device from panel UI."""

    url = "/api/myhome/configuration/device_delete"
    name = "api:myhome:configuration:device_delete"
    requires_auth = True

    async def post(self, request):
        hass = request.app["hass"]
        try:
            payload = await request.json()
        except JSONDecodeError:
            payload = {}

        configured_gateways = hass.data.get(DOMAIN, {})
        gateway, error, status = _resolve_gateway_from_payload(
            configured_gateways,
            payload.get("gateway"),
        )
        if gateway is None:
            return self.json_message(error, status_code=status)

        platform = str(payload.get("platform") or "").strip().lower()
        key = str(payload.get("key") or "").strip()
        if platform not in CONFIG_PLATFORMS or not key:
            return self.json_message(
                "Both `platform` and `key` are required.",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        gateway_payload = await async_get_gateway_config(hass, gateway) or {CONF_MAC: gateway}
        platform_payload = gateway_payload.get(platform, {})
        if isinstance(platform_payload, dict):
            platform_payload.pop(key, None)
            if len(platform_payload) == 0:
                gateway_payload.pop(platform, None)

        await async_set_gateway_config(hass, gateway, gateway_payload)
        await _reload_gateway_entry(hass, gateway)
        return self.json({"ok": True, "gateway": gateway, "devices": _devices_for_ui(gateway_payload)})


class MyHOMEConfigurationImportDiscoveryView(HomeAssistantView):
    """Import discovered devices into persistent configuration."""

    url = "/api/myhome/configuration/import_discovery"
    name = "api:myhome:configuration:import_discovery"
    requires_auth = True

    async def post(self, request):
        hass = request.app["hass"]
        try:
            payload = await request.json()
        except JSONDecodeError:
            payload = {}

        configured_gateways = hass.data.get(DOMAIN, {})
        gateway, error, status = _resolve_gateway_from_payload(
            configured_gateways,
            payload.get("gateway"),
        )
        if gateway is None:
            return self.json_message(error, status_code=status)

        gateway_payload = await async_get_gateway_config(hass, gateway) or {CONF_MAC: gateway}

        imported = {"light": 0, "cover": 0, "climate": 0, "power": 0}

        for where in payload.get("lights", []) or []:
            where = str(where)
            light_payload = gateway_payload.get(LIGHT_PLATFORM)
            if not isinstance(light_payload, dict):
                light_payload = {}
                gateway_payload[LIGHT_PLATFORM] = light_payload
            key = _sanitize_key(f"discovered_light_{where}")
            if key not in light_payload:
                light_payload[key] = {"where": where, "name": f"Light {where}", "dimmable": False}
                imported["light"] += 1

        for where in payload.get("covers", []) or []:
            where = str(where)
            cover_payload = gateway_payload.get(COVER_PLATFORM)
            if not isinstance(cover_payload, dict):
                cover_payload = {}
                gateway_payload[COVER_PLATFORM] = cover_payload
            key = _sanitize_key(f"discovered_cover_{where}")
            if key not in cover_payload:
                cover_payload[key] = {"where": where, "name": f"Cover {where}"}
                imported["cover"] += 1

        for zone in payload.get("climates", []) or []:
            zone = str(zone)
            climate_payload = gateway_payload.get(CLIMATE_PLATFORM)
            if not isinstance(climate_payload, dict):
                climate_payload = {}
                gateway_payload[CLIMATE_PLATFORM] = climate_payload
            key = _sanitize_key(f"discovered_climate_{zone}")
            if key not in climate_payload:
                climate_payload[key] = {
                    "zone": zone,
                    "name": f"Climate {zone}",
                    "heat": True,
                    "cool": True,
                    "fan": True,
                    "standalone": True,
                }
                imported["climate"] += 1

        for where in payload.get("powers", []) or []:
            where = str(where)
            sensor_payload = gateway_payload.get(SENSOR_PLATFORM)
            if not isinstance(sensor_payload, dict):
                sensor_payload = {}
                gateway_payload[SENSOR_PLATFORM] = sensor_payload
            key = _sanitize_key(f"discovered_power_{where}")
            if key not in sensor_payload:
                sensor_payload[key] = {"where": where, "name": f"Power {where}", "class": "power"}
                imported["power"] += 1

        # Keep payload schema-compliant: empty platform sections are invalid.
        for platform in CONFIG_PLATFORMS:
            platform_payload = gateway_payload.get(platform)
            if isinstance(platform_payload, dict) and len(platform_payload) == 0:
                gateway_payload.pop(platform, None)

        try:
            config_schema({gateway: gateway_payload})
        except Exception as err:  # pylint: disable=broad-except
            return self.json_message(
                f"Invalid configuration: {err}",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        await async_set_gateway_config(hass, gateway, gateway_payload)
        await _reload_gateway_entry(hass, gateway)

        return self.json(
            {
                "ok": True,
                "gateway": gateway,
                "imported": imported,
                "devices": _devices_for_ui(gateway_payload),
            }
        )


class MyHOMEDiscoveryView(HomeAssistantView):
    """Run MyHOME discovery from the web panel."""

    url = "/api/myhome/discovery"
    name = "api:myhome:discovery"
    requires_auth = True

    async def post(self, request):
        """Handle discovery requests."""
        hass = request.app["hass"]
        try:
            payload = await request.json()
        except JSONDecodeError:
            payload = {}

        configured_gateways = hass.data.get(DOMAIN, {})
        if not configured_gateways:
            return self.json_message(
                "No MyHOME gateways are configured.",
                status_code=HTTPStatus.NOT_FOUND,
            )

        requested_gateway = payload.get("gateway")
        if requested_gateway is None:
            gateway = next(iter(configured_gateways.keys()))
        else:
            formatted_gateway = format_mac(requested_gateway)
            if formatted_gateway is None:
                return self.json_message(
                    f"Invalid gateway `{requested_gateway}`.",
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            gateway = formatted_gateway

        gateway_data = configured_gateways.get(gateway)
        if gateway_data is None:
            return self.json_message(
                f"Gateway `{gateway}` was not found.",
                status_code=HTTPStatus.NOT_FOUND,
            )

        gateway_handler = gateway_data[CONF_ENTITY]
        scan_lights = _to_bool(payload.get("scan_lights"), True)
        scan_covers = _to_bool(payload.get("scan_covers"), True)
        scan_climate = _to_bool(payload.get("scan_climate"), True)
        scan_power = _to_bool(payload.get("scan_power"), True)
        area_start = _to_int(payload.get("area_start"), DISCOVERY_DEFAULT_AREA_START)
        area_end = _to_int(payload.get("area_end"), DISCOVERY_DEFAULT_AREA_END)
        point_start = _to_int(payload.get("point_start"), DISCOVERY_DEFAULT_POINT_START)
        point_end = _to_int(payload.get("point_end"), DISCOVERY_DEFAULT_POINT_END)
        duration = _to_int(payload.get("duration"), DISCOVERY_DEFAULT_DURATION)

        LOGGER.info(
            "%s Discovery requested via web panel (lights=%s, covers=%s, climate=%s, power=%s, area=%s-%s, point=%s-%s, duration=%ss).",
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
            return self.json_message(
                str(runtime_error),
                status_code=HTTPStatus.CONFLICT,
            )
        except Exception as err:  # pylint: disable=broad-except
            LOGGER.exception(
                "%s Discovery failed from web panel: %s",
                gateway_handler.log_id,
                err,
            )
            return self.json_message(
                "Unexpected discovery failure.",
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        light_results = results.get("light", [])
        cover_results = results.get("cover", [])
        climate_results = [
            str(item)
            for item in results.get("climate", [])
            if _is_valid_discovery_climate(str(item))
        ]
        power_results = results.get("power", [])
        configured = _configured_discovery_endpoints(hass, gateway)
        mapped_light, new_light = _mapped_results(light_results, configured["light"])
        mapped_cover, new_cover = _mapped_results(cover_results, configured["cover"])
        mapped_climate, new_climate = _mapped_results(
            climate_results,
            configured["climate"],
        )
        mapped_power, new_power = _mapped_results(power_results, configured["power"])
        return self.json(
            {
                "kind": "active_discovery",
                "gateway": gateway,
                "light": [str(item) for item in light_results],
                "cover": [str(item) for item in cover_results],
                "climate": climate_results,
                "power": [str(item) for item in power_results],
                "mapped_light": mapped_light,
                "mapped_cover": mapped_cover,
                "mapped_climate": mapped_climate,
                "mapped_power": mapped_power,
                "new_light": new_light,
                "new_cover": new_cover,
                "new_climate": new_climate,
                "new_power": new_power,
                "total_light": len(light_results),
                "total_cover": len(cover_results),
                "total_climate": len(climate_results),
                "total_power": len(power_results),
                "snippet": _build_discovery_snippet(
                    [str(item) for item in light_results],
                    [str(item) for item in cover_results],
                    [str(item) for item in climate_results],
                    [str(item) for item in power_results],
                    {
                        "light": set(mapped_light),
                        "cover": set(mapped_cover),
                        "climate": set(mapped_climate),
                        "power": set(mapped_power),
                    },
                ),
            }
        )


class MyHOMEDiscoveryByActivationView(HomeAssistantView):
    """Keep discovery-by-activation enabled from panel UI."""

    url = "/api/myhome/discovery_by_activation"
    name = "api:myhome:discovery_by_activation"
    requires_auth = True

    async def post(self, request):
        hass = request.app["hass"]
        try:
            payload = await request.json()
        except JSONDecodeError:
            payload = {}

        configured_gateways = hass.data.get(DOMAIN, {})
        if not configured_gateways:
            return self.json_message(
                "No MyHOME gateways are configured.",
                status_code=HTTPStatus.NOT_FOUND,
            )

        requested_gateway = payload.get("gateway")
        if requested_gateway is None:
            gateway = next(iter(configured_gateways.keys()))
        else:
            gateway = format_mac(requested_gateway)
            if gateway is None:
                return self.json_message(
                    f"Invalid gateway `{requested_gateway}`.",
                    status_code=HTTPStatus.BAD_REQUEST,
                )

        gateway_data = configured_gateways.get(gateway)
        if gateway_data is None:
            return self.json_message(
                f"Gateway `{gateway}` was not found.",
                status_code=HTTPStatus.NOT_FOUND,
            )

        gateway_handler = gateway_data[CONF_ENTITY]
        gateway_handler.set_discovery_by_activation(True)

        return self.json(
            {
                "gateway": gateway,
                "enabled": gateway_handler.discovery_by_activation,
            }
        )


class MyHOMEActivationDiscoveryResultsView(HomeAssistantView):
    """Return activation discovery results from panel UI."""

    url = "/api/myhome/activation_discovery"
    name = "api:myhome:activation_discovery"
    requires_auth = True

    async def post(self, request):
        hass = request.app["hass"]
        try:
            payload = await request.json()
        except JSONDecodeError:
            payload = {}

        configured_gateways = hass.data.get(DOMAIN, {})
        if not configured_gateways:
            return self.json_message(
                "No MyHOME gateways are configured.",
                status_code=HTTPStatus.NOT_FOUND,
            )

        requested_gateway = payload.get("gateway")
        if requested_gateway is None:
            gateway = next(iter(configured_gateways.keys()))
        else:
            gateway = format_mac(requested_gateway)
            if gateway is None:
                return self.json_message(
                    f"Invalid gateway `{requested_gateway}`.",
                    status_code=HTTPStatus.BAD_REQUEST,
                )

        gateway_data = configured_gateways.get(gateway)
        if gateway_data is None:
            return self.json_message(
                f"Gateway `{gateway}` was not found.",
                status_code=HTTPStatus.NOT_FOUND,
            )

        clear = _to_bool(payload.get("clear"), False)
        gateway_handler = gateway_data[CONF_ENTITY]
        gateway_handler.set_discovery_by_activation(True)

        runtime_results = gateway_handler.get_activation_discovery_results(clear=False)
        stored_results = await async_get_activation_discovery_results(hass, gateway)
        results = _merge_discovery_results(runtime_results, stored_results)
        results["climate"] = [
            str(item)
            for item in results.get("climate", [])
            if _is_valid_discovery_climate(str(item))
        ]

        if clear:
            gateway_handler.clear_activation_discovery_results()
            await async_clear_activation_discovery_results(hass, gateway)
            results = {kind: [] for kind in ("light", "cover", "climate", "power")}
        else:
            await async_set_activation_discovery_results(hass, gateway, results)

        light_results = results.get("light", [])
        cover_results = results.get("cover", [])
        climate_results = results.get("climate", [])
        power_results = results.get("power", [])
        configured = _configured_discovery_endpoints(hass, gateway)
        mapped_light, new_light = _mapped_results(light_results, configured["light"])
        mapped_cover, new_cover = _mapped_results(cover_results, configured["cover"])
        mapped_climate, new_climate = _mapped_results(
            climate_results,
            configured["climate"],
        )
        mapped_power, new_power = _mapped_results(power_results, configured["power"])

        return self.json(
            {
                "kind": "activation_discovery",
                "gateway": gateway,
                "enabled": gateway_handler.discovery_by_activation,
                "light": [str(item) for item in light_results],
                "cover": [str(item) for item in cover_results],
                "climate": [str(item) for item in climate_results],
                "power": [str(item) for item in power_results],
                "mapped_light": mapped_light,
                "mapped_cover": mapped_cover,
                "mapped_climate": mapped_climate,
                "mapped_power": mapped_power,
                "new_light": new_light,
                "new_cover": new_cover,
                "new_climate": new_climate,
                "new_power": new_power,
                "total_light": len(light_results),
                "total_cover": len(cover_results),
                "total_climate": len(climate_results),
                "total_power": len(power_results),
                "snippet": _build_discovery_snippet(
                    [str(item) for item in light_results],
                    [str(item) for item in cover_results],
                    [str(item) for item in climate_results],
                    [str(item) for item in power_results],
                    {
                        "light": set(mapped_light),
                        "cover": set(mapped_cover),
                        "climate": set(mapped_climate),
                        "power": set(mapped_power),
                    },
                ),
                "cleared": clear,
            }
        )


async def async_setup_web(hass) -> None:
    """Set up MyHOME web resources and register panel when needed."""
    runtime_data = _runtime_data(hass)

    if not runtime_data["api_registered"]:
        panel_directory = Path(__file__).parent / "frontend"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_STATIC_URL_PATH, str(panel_directory), False)]
        )
        hass.http.register_view(MyHOMEGatewaysView)
        hass.http.register_view(MyHOMEConfigurationView)
        hass.http.register_view(MyHOMEConfigurationDeviceView)
        hass.http.register_view(MyHOMEConfigurationDeleteView)
        hass.http.register_view(MyHOMEConfigurationImportDiscoveryView)
        hass.http.register_view(MyHOMEDiscoveryView)
        hass.http.register_view(MyHOMEDiscoveryByActivationView)
        hass.http.register_view(MyHOMEActivationDiscoveryResultsView)
        runtime_data["api_registered"] = True

    runtime_data["entry_count"] += 1
    if runtime_data["panel_registered"]:
        return

    await panel_custom.async_register_panel(
        hass=hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_WEBCOMPONENT_NAME,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=PANEL_MODULE_URL,
        require_admin=True,
    )
    runtime_data["panel_registered"] = True


def async_unload_web(hass) -> None:
    """Unload MyHOME panel when last entry is removed."""
    runtime_data = _runtime_data(hass)
    runtime_data["entry_count"] = max(runtime_data["entry_count"] - 1, 0)

    if runtime_data["entry_count"] != 0 or not runtime_data["panel_registered"]:
        return

    frontend.async_remove_panel(
        hass=hass,
        frontend_url_path=PANEL_URL_PATH,
        warn_if_unknown=False,
    )
    runtime_data["panel_registered"] = False

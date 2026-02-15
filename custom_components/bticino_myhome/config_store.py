"""Persistent configuration storage for MyHOME devices."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.const import CONF_MAC
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION

_ACTIVATION_KEY = "activation_discovery"
_ACTIVATION_TYPES = ("light", "cover", "climate", "power")


def _store(hass) -> Store:
    return Store(hass, STORAGE_VERSION, STORAGE_KEY)


async def async_load_data(hass) -> dict[str, Any]:
    """Load full MyHOME config storage payload."""
    data = await _store(hass).async_load()
    if not isinstance(data, dict):
        return {"gateways": {}}
    gateways = data.get("gateways")
    if not isinstance(gateways, dict):
        data["gateways"] = {}
    activation = data.get(_ACTIVATION_KEY)
    if not isinstance(activation, dict):
        data[_ACTIVATION_KEY] = {}
    return data


async def async_save_data(hass, data: dict[str, Any]) -> None:
    """Save full MyHOME config storage payload."""
    await _store(hass).async_save(data)


def _normalize_gateway_payload(gateway: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    base = deepcopy(payload) if isinstance(payload, dict) else {}
    base[CONF_MAC] = gateway
    return base


async def async_get_gateway_config(hass, gateway: str) -> dict[str, Any] | None:
    """Get a single gateway raw config from storage."""
    data = await async_load_data(hass)
    raw = data["gateways"].get(gateway)
    if not isinstance(raw, dict):
        return None
    return _normalize_gateway_payload(gateway, raw)


async def async_set_gateway_config(hass, gateway: str, payload: dict[str, Any]) -> None:
    """Upsert gateway raw config in storage."""
    data = await async_load_data(hass)
    data["gateways"][gateway] = _normalize_gateway_payload(gateway, payload)
    await async_save_data(hass, data)


async def async_remove_gateway_config(hass, gateway: str) -> None:
    """Remove gateway raw config from storage."""
    data = await async_load_data(hass)
    data["gateways"].pop(gateway, None)
    activation = data.get(_ACTIVATION_KEY, {})
    if isinstance(activation, dict):
        activation.pop(gateway, None)
    await async_save_data(hass, data)


def _normalize_activation_snapshot(raw: dict[str, Any] | None) -> dict[str, list[str]]:
    snapshot: dict[str, list[str]] = {kind: [] for kind in _ACTIVATION_TYPES}
    if not isinstance(raw, dict):
        return snapshot

    for kind in _ACTIVATION_TYPES:
        values = raw.get(kind, [])
        if isinstance(values, (list, set, tuple)):
            normalized = sorted({str(value) for value in values if str(value)})
            snapshot[kind] = normalized
    return snapshot


async def async_get_activation_discovery_results(hass, gateway: str) -> dict[str, list[str]]:
    """Get persisted activation discovery snapshot for one gateway."""
    data = await async_load_data(hass)
    activation = data.get(_ACTIVATION_KEY, {})
    raw = activation.get(gateway) if isinstance(activation, dict) else None
    return _normalize_activation_snapshot(raw)


async def async_set_activation_discovery_results(
    hass,
    gateway: str,
    snapshot: dict[str, Any],
) -> None:
    """Persist activation discovery snapshot for one gateway."""
    data = await async_load_data(hass)
    activation = data.get(_ACTIVATION_KEY)
    if not isinstance(activation, dict):
        activation = {}
        data[_ACTIVATION_KEY] = activation
    activation[gateway] = _normalize_activation_snapshot(snapshot)
    await async_save_data(hass, data)


async def async_clear_activation_discovery_results(hass, gateway: str) -> None:
    """Clear persisted activation discovery snapshot for one gateway."""
    data = await async_load_data(hass)
    activation = data.get(_ACTIVATION_KEY)
    if isinstance(activation, dict):
        activation.pop(gateway, None)
        await async_save_data(hass, data)


async def async_get_or_init_gateway_config(hass, gateway: str) -> dict[str, Any]:
    """Return gateway config from storage, initializing an empty one when absent."""
    if stored := await async_get_gateway_config(hass, gateway):
        return stored

    empty = {CONF_MAC: gateway}
    await async_set_gateway_config(hass, gateway, empty)
    return empty

"""Code to handle a MyHome Gateway."""
import asyncio
import logging
import re
from typing import Dict, List

from homeassistant.const import (
    CONF_ENTITIES,
    CONF_HOST,
    CONF_PORT,
    CONF_PASSWORD,
    CONF_NAME,
    CONF_MAC,
    CONF_FRIENDLY_NAME,
)
from homeassistant.components.light import DOMAIN as LIGHT
from homeassistant.components.button import DOMAIN as BUTTON
from homeassistant.components.sensor import DOMAIN as SENSOR
from homeassistant.components.climate import DOMAIN as CLIMATE

from OWNd.connection import OWNSession, OWNEventSession, OWNCommandSession, OWNGateway
from OWNd.message import (
    OWNMessage,
    OWNLightingEvent,
    OWNLightingCommand,
    OWNEnergyEvent,
    OWNEnergyCommand,
    OWNAutomationEvent,
    OWNAutomationCommand,
    OWNDryContactEvent,
    OWNAuxEvent,
    OWNHeatingEvent,
    OWNHeatingCommand,
    OWNCENPlusEvent,
    OWNCENEvent,
    OWNGatewayEvent,
    OWNGatewayCommand,
    OWNCommand,
)

from .const import (
    CONF_PLATFORMS,
    CONF_FIRMWARE,
    CONF_SSDP_LOCATION,
    CONF_SSDP_ST,
    CONF_DEVICE_TYPE,
    CONF_MANUFACTURER,
    CONF_MANUFACTURER_URL,
    CONF_UDN,
    CONF_SHORT_PRESS,
    CONF_SHORT_RELEASE,
    CONF_LONG_PRESS,
    CONF_LONG_RELEASE,
    CONF_ZONE,
    DISCOVERY_DEFAULT_AREA_END,
    DISCOVERY_DEFAULT_AREA_START,
    DISCOVERY_DEFAULT_DURATION,
    DISCOVERY_DEFAULT_POINT_END,
    DISCOVERY_DEFAULT_POINT_START,
    DOMAIN,
    LOGGER,
)
from .myhome_device import MyHOMEEntity
from .button import (
    DisableCommandButtonEntity,
    EnableCommandButtonEntity,
)

HEATING_DIM20_PATTERN = re.compile(
    r"^\*#4\*(?P<where>[^*]+)\*\#20\*(?P<value>\d{1,3})##$"
)
UNSUPPORTED_MESSAGE_SIGNATURE_PATTERN = re.compile(
    r"^\*#?(?P<who>\d+)\*(?P<where>[^*#]+)(?:\*\#?(?P<dimension>\d+))?"
)
POWER_DISCOVERY_DEFAULT_ENDPOINTS = ("51",)


class DiscoverySendErrorDowngradeFilter(logging.Filter):
    """Downgrade expected send failures during discovery scans."""

    def __init__(self, gateway_handler):
        super().__init__()
        self._gateway_handler = gateway_handler

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._gateway_handler._discovery_in_progress:
            return True

        if record.levelno < logging.ERROR:
            return True

        message = record.getMessage()
        if "Could not send message" not in message:
            return True

        if self._gateway_handler.log_id not in message:
            return True

        record.levelno = logging.DEBUG
        record.levelname = "DEBUG"
        return True


class MyHOMEGatewayHandler:
    """Manages a single MyHOME Gateway."""

    def __init__(
        self,
        hass,
        config_entry,
        generate_events=False,
        discovery_by_activation=False,
    ):
        build_info = {
            "address": config_entry.data[CONF_HOST],
            "port": config_entry.data[CONF_PORT],
            "password": config_entry.data[CONF_PASSWORD],
            "ssdp_location": config_entry.data[CONF_SSDP_LOCATION],
            "ssdp_st": config_entry.data[CONF_SSDP_ST],
            "deviceType": config_entry.data[CONF_DEVICE_TYPE],
            "friendlyName": config_entry.data[CONF_FRIENDLY_NAME],
            "manufacturer": config_entry.data[CONF_MANUFACTURER],
            "manufacturerURL": config_entry.data[CONF_MANUFACTURER_URL],
            "modelName": config_entry.data[CONF_NAME],
            "modelNumber": config_entry.data[CONF_FIRMWARE],
            "serialNumber": config_entry.data[CONF_MAC],
            "UDN": config_entry.data[CONF_UDN],
        }
        self.hass = hass
        self.config_entry = config_entry
        self.generate_events = generate_events
        self.gateway = OWNGateway(build_info)
        self._terminate_listener = False
        self._terminate_sender = False
        self.is_connected = False
        self.listening_worker: asyncio.tasks.Task = None
        self.sending_workers: List[asyncio.tasks.Task] = []
        self.send_buffer = asyncio.Queue()
        # Rate limiting for repetitive messages
        self._message_count: Dict[str, int] = {}
        self._log_interval = 60  # Log every N occurrences
        self._discovery_in_progress = False
        self._discovery_results = {
            "light": set(),
            "cover": set(),
            "climate": set(),
            "power": set(),
        }
        self._discovery_by_activation = discovery_by_activation
        self._activation_discovery_results = {
            "light": set(),
            "cover": set(),
            "climate": set(),
            "power": set(),
        }
        self._discovery_log_filter = DiscoverySendErrorDowngradeFilter(self)
        LOGGER.addFilter(self._discovery_log_filter)

    @property
    def discovery_by_activation(self) -> bool:
        return self._discovery_by_activation

    def set_discovery_by_activation(self, enabled: bool):
        self._discovery_by_activation = bool(enabled)

    def get_activation_discovery_results(self, clear: bool = False) -> Dict[str, List[str]]:
        snapshot = {
            "light": sorted(self._activation_discovery_results["light"]),
            "cover": sorted(self._activation_discovery_results["cover"]),
            "climate": sorted(self._activation_discovery_results["climate"]),
            "power": sorted(self._activation_discovery_results["power"]),
        }
        if clear:
            self.clear_activation_discovery_results()
        return snapshot

    def clear_activation_discovery_results(self):
        self._activation_discovery_results = {
            "light": set(),
            "cover": set(),
            "climate": set(),
            "power": set(),
        }

    @property
    def mac(self) -> str:
        return self.gateway.serial

    @property
    def unique_id(self) -> str:
        return self.mac

    @property
    def log_id(self) -> str:
        return self.gateway.log_id

    @property
    def manufacturer(self) -> str:
        return self.gateway.manufacturer

    @property
    def name(self) -> str:
        return f"{self.gateway.model_name} Gateway"

    @property
    def model(self) -> str:
        return self.gateway.model_name

    @property
    def firmware(self) -> str:
        return self.gateway.firmware

    async def test(self) -> Dict:
        return await OWNSession(gateway=self.gateway, logger=LOGGER).test_connection()

    @staticmethod
    def _extract_zone_and_channel(where: str):
        """Extract zone/channel from OpenWebNet WHERE fragments."""
        parts = [part for part in str(where).split("#") if part]
        if not parts:
            return None, None

        # Central style examples can use "#0#<zone>".
        if parts[0] == "0" and len(parts) >= 2:
            zone = parts[1]
            channel = parts[2] if len(parts) >= 3 else None
            return zone if zone.isdigit() else None, channel

        zone = parts[0]
        channel = parts[1] if len(parts) >= 2 else None
        return zone if zone.isdigit() else None, channel

    @staticmethod
    def _format_point_to_point_where(area: int, point: int) -> str:
        """Format a point-to-point WHERE according to OpenWebNet conventions."""
        if area <= 9 and point <= 9:
            return f"{area}{point}"
        return f"{area:02d}{point:02d}"

    def _collect_discovery_result(self, message: OWNMessage):
        """Collect discovery candidates while a scan is running."""
        if not self._discovery_in_progress:
            return

        if isinstance(message, OWNLightingEvent):
            if message.is_general or message.is_area or message.is_group:
                return
            self._discovery_results["light"].add(str(message.where))
            return

        if isinstance(message, OWNAutomationEvent):
            if message.is_general or message.is_area or message.is_group:
                return
            self._discovery_results["cover"].add(str(message.where))
            return

        if isinstance(message, OWNHeatingEvent):
            where = self._extract_discovery_climate_where(message.where)
            if where is not None:
                self._discovery_results["climate"].add(where)
            return

        if isinstance(message, OWNEnergyEvent):
            where = self._extract_energy_where(message)
            if where is not None:
                self._discovery_results["power"].add(where)

    def _collect_activation_discovery_result(self, message: OWNMessage):
        """Collect discovered endpoints from regular bus activity."""
        if not self._discovery_by_activation:
            return

        if isinstance(message, OWNLightingEvent):
            if message.is_general or message.is_area or message.is_group:
                return
            self._activation_discovery_results["light"].add(str(message.where))
            return

        if isinstance(message, OWNAutomationEvent):
            if message.is_general or message.is_area or message.is_group:
                return
            self._activation_discovery_results["cover"].add(str(message.where))
            return

        if isinstance(message, OWNHeatingEvent):
            where = self._extract_discovery_climate_where(message.where)
            if where is not None:
                self._activation_discovery_results["climate"].add(where)
            return

        if isinstance(message, OWNEnergyEvent):
            where = self._extract_energy_where(message)
            if where is not None:
                self._activation_discovery_results["power"].add(where)

    @staticmethod
    def _extract_energy_where(message: OWNEnergyEvent) -> str | None:
        """Extract WHERE for energy events."""
        where = getattr(message, "where", None)
        if where is not None:
            where = str(where)
            if where:
                return where

        entity = str(getattr(message, "entity", ""))
        if entity.startswith("18-"):
            return entity.split("-", 1)[1].split("#", 1)[0]
        if entity:
            return entity.split("#", 1)[0]
        return None

    @classmethod
    def _extract_discovery_climate_where(cls, where_raw) -> str | None:
        """Filter climate discovery endpoints, excluding central zone 0."""
        where = str(where_raw)
        if not where or where == "*":
            return None

        zone, _channel = cls._extract_zone_and_channel(where)
        if zone is None:
            return None

        if int(zone) <= 0:
            return None

        return where

    async def discover_devices(
        self,
        scan_lights: bool = True,
        scan_covers: bool = True,
        scan_climate: bool = True,
        scan_power: bool = True,
        area_start: int = DISCOVERY_DEFAULT_AREA_START,
        area_end: int = DISCOVERY_DEFAULT_AREA_END,
        point_start: int = DISCOVERY_DEFAULT_POINT_START,
        point_end: int = DISCOVERY_DEFAULT_POINT_END,
        duration: int = DISCOVERY_DEFAULT_DURATION,
    ) -> Dict[str, List[str]]:
        """Discover devices by sending status requests on point-to-point addresses."""
        if self._discovery_in_progress:
            raise RuntimeError("A discovery scan is already in progress.")

        area_start = max(0, min(10, area_start))
        area_end = max(0, min(10, area_end))
        point_start = max(0, min(15, point_start))
        point_end = max(0, min(15, point_end))
        duration = max(2, min(30, duration))

        if area_start > area_end:
            area_start, area_end = area_end, area_start
        if point_start > point_end:
            point_start, point_end = point_end, point_start

        self._discovery_in_progress = True
        self._discovery_results = {
            "light": set(),
            "cover": set(),
            "climate": set(),
            "power": set(),
        }

        try:
            for area in range(area_start, area_end + 1):
                for point in range(point_start, point_end + 1):
                    where = self._format_point_to_point_where(area, point)
                    if scan_lights:
                        await self.send_status_request(OWNLightingCommand.status(where))
                    if scan_covers:
                        await self.send_status_request(OWNAutomationCommand.status(where))
                    if scan_climate:
                        await self.send_status_request(OWNHeatingCommand.status(where))
            if scan_power:
                for where in POWER_DISCOVERY_DEFAULT_ENDPOINTS:
                    await self.send_status_request(
                        OWNEnergyCommand.get_total_consumption(where)
                    )

            await asyncio.sleep(duration)

            return {
                "light": sorted(self._discovery_results["light"]),
                "cover": sorted(self._discovery_results["cover"]),
                "climate": sorted(self._discovery_results["climate"]),
                "power": sorted(self._discovery_results["power"]),
            }
        finally:
            self._discovery_in_progress = False

    def _handle_heating_dimension_20(self, message) -> bool:
        """Handle WHO=4 dimension #20 messages when OWNd cannot parse them yet."""
        _raw_message = str(message)
        _match = HEATING_DIM20_PATTERN.match(_raw_message)
        if _match is None:
            return False

        _where = _match.group("where")
        _zone, _channel = self._extract_zone_and_channel(_where)

        if _zone is None:
            LOGGER.debug(
                "%s Ignoring malformed WHO=4 dim#20 zone in message `%s`.",
                self.log_id,
                _raw_message,
            )
            return True

        _value = int(_match.group("value"))
        if _value < 0 or _value > 100:
            LOGGER.debug(
                "%s Ignoring out-of-range WHO=4 dim#20 value %s in message `%s`.",
                self.log_id,
                _value,
                _raw_message,
            )
            return True

        _platforms = self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS]
        if CLIMATE not in _platforms:
            return True

        _found_entity = False
        for _device_data in _platforms[CLIMATE].values():
            _configured_zone, _ = self._extract_zone_and_channel(
                str(_device_data.get(CONF_ZONE, ""))
            )
            if _configured_zone != _zone:
                continue

            _climate_entity = _device_data.get(CONF_ENTITIES, {}).get(CLIMATE)
            if _climate_entity is not None and hasattr(
                _climate_entity, "handle_valve_position"
            ):
                _climate_entity.handle_valve_position(_value, _channel)
                _found_entity = True

        if _found_entity:
            _channel_suffix = f", channel {_channel}" if _channel is not None else ""
            LOGGER.debug(
                "%s Zone %s valve position updated to %s%% (dim#20%s).",
                self.log_id,
                _zone,
                _value,
                _channel_suffix,
            )
        else:
            LOGGER.debug(
                "%s Received WHO=4 dim#20 for zone %s but no climate entity matched.",
                self.log_id,
                _zone,
            )

        return True

    @staticmethod
    def _unsupported_message_key(message) -> str:
        """Return a stable key for unsupported messages, ignoring volatile payload."""
        raw_message = str(message)
        match = UNSUPPORTED_MESSAGE_SIGNATURE_PATTERN.match(raw_message)
        if match is None:
            return f"unsupported_{raw_message[:30]}"

        who = match.group("who")
        where = match.group("where")
        dimension = match.group("dimension") or "na"
        return f"unsupported_who{who}_where{where}_dim{dimension}"

    async def listening_loop(self):
        """Listen for events from the gateway with retry logic."""
        self._terminate_listener = False
        retry_count = 0
        max_retries = 5
        base_delay = 2  # seconds

        LOGGER.debug("%s Creating listening worker.", self.log_id)

        # Outer loop: Retry connection on failure
        while not self._terminate_listener and retry_count < max_retries:
            _event_session = None
            try:
                # Connect to gateway with exponential backoff on retry
                if retry_count > 0:
                    delay = base_delay * (2 ** (retry_count - 1))
                    LOGGER.warning(
                        "%s Connection failed, retrying in %s seconds (attempt %s/%s)",
                        self.log_id,
                        delay,
                        retry_count + 1,
                        max_retries,
                    )
                    await asyncio.sleep(delay)

                _event_session = OWNEventSession(gateway=self.gateway, logger=LOGGER)
                await _event_session.connect()
                self.is_connected = True
                retry_count = 0  # Reset retry count on successful connection
                LOGGER.info("%s Successfully connected to gateway.", self.log_id)

            except (OSError, ConnectionError, TimeoutError) as conn_err:
                retry_count += 1
                self.is_connected = False
                LOGGER.error(
                    "%s Failed to connect to gateway: %s",
                    self.log_id,
                    conn_err,
                )
                if retry_count >= max_retries:
                    LOGGER.error(
                        "%s Maximum retry attempts reached, listener stopping.",
                        self.log_id,
                    )
                    break
                continue
            except Exception as e:
                LOGGER.exception(
                    "%s Unexpected error during connection: %s",
                    self.log_id,
                    e,
                )
                break

            # Inner loop: Process messages
            try:
                while not self._terminate_listener:
                    message = await _event_session.get_next()
                    LOGGER.debug("%s Message received: `%s`", self.log_id, message)

                    if self.generate_events:
                        if isinstance(message, OWNMessage):
                            _event_content = {"gateway": str(self.gateway.host)}
                            _event_content.update(message.event_content)
                            self.hass.bus.async_fire("myhome_message_event", _event_content)
                        else:
                            self.hass.bus.async_fire("myhome_message_event", {"gateway": str(self.gateway.host), "message": str(message)})

                    if isinstance(message, OWNMessage):
                        self._collect_discovery_result(message)
                        self._collect_activation_discovery_result(message)

                    if not isinstance(message, OWNMessage):
                        LOGGER.warning(
                            "%s Data received is not a message: `%s`",
                            self.log_id,
                            message,
                        )
                    elif isinstance(message, OWNEnergyEvent):
                        if SENSOR in self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS] and message.entity in self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][SENSOR]:
                            for _entity in self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][SENSOR][message.entity][CONF_ENTITIES]:
                                if isinstance(
                                    self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][SENSOR][message.entity][CONF_ENTITIES][_entity],
                                    MyHOMEEntity,
                                ):
                                    self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][SENSOR][message.entity][CONF_ENTITIES][_entity].handle_event(message)
                        else:
                            continue
                    elif (
                        isinstance(message, OWNLightingEvent)
                        or isinstance(message, OWNAutomationEvent)
                        or isinstance(message, OWNDryContactEvent)
                        or isinstance(message, OWNAuxEvent)
                        or isinstance(message, OWNHeatingEvent)
                    ):
                        if not message.is_translation:
                            is_event = False
                            if isinstance(message, OWNLightingEvent):
                                if message.is_general:
                                    is_event = True
                                    event = "on" if message.is_on else "off"
                                    self.hass.bus.async_fire(
                                        "myhome_general_light_event",
                                        {"message": str(message), "event": event},
                                    )
                                    await asyncio.sleep(0.1)
                                    await self.send_status_request(OWNLightingCommand.status("0"))
                                elif message.is_area:
                                    is_event = True
                                    event = "on" if message.is_on else "off"
                                    self.hass.bus.async_fire(
                                        "myhome_area_light_event",
                                        {
                                            "message": str(message),
                                            "area": message.area,
                                            "event": event,
                                        },
                                    )
                                    await asyncio.sleep(0.1)
                                    await self.send_status_request(OWNLightingCommand.status(message.area))
                                elif message.is_group:
                                    is_event = True
                                    event = "on" if message.is_on else "off"
                                    self.hass.bus.async_fire(
                                        "myhome_group_light_event",
                                        {
                                            "message": str(message),
                                            "group": message.group,
                                            "event": event,
                                        },
                                    )
                            elif isinstance(message, OWNAutomationEvent):
                                if message.is_general:
                                    is_event = True
                                    if message.is_opening and not message.is_closing:
                                        event = "open"
                                    elif message.is_closing and not message.is_opening:
                                        event = "close"
                                    else:
                                        event = "stop"
                                    self.hass.bus.async_fire(
                                        "myhome_general_automation_event",
                                        {"message": str(message), "event": event},
                                    )
                                elif message.is_area:
                                    is_event = True
                                    if message.is_opening and not message.is_closing:
                                        event = "open"
                                    elif message.is_closing and not message.is_opening:
                                        event = "close"
                                    else:
                                        event = "stop"
                                    self.hass.bus.async_fire(
                                        "myhome_area_automation_event",
                                        {
                                            "message": str(message),
                                            "area": message.area,
                                            "event": event,
                                        },
                                    )
                                elif message.is_group:
                                    is_event = True
                                    if message.is_opening and not message.is_closing:
                                        event = "open"
                                    elif message.is_closing and not message.is_opening:
                                        event = "close"
                                    else:
                                        event = "stop"
                                    self.hass.bus.async_fire(
                                        "myhome_group_automation_event",
                                        {
                                            "message": str(message),
                                            "group": message.group,
                                            "event": event,
                                        },
                                    )
                            if not is_event:
                                if isinstance(message, OWNLightingEvent) and message.brightness_preset:
                                    if isinstance(
                                        self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][LIGHT][message.entity][CONF_ENTITIES][LIGHT],
                                        MyHOMEEntity,
                                    ):
                                        await self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][LIGHT][message.entity][CONF_ENTITIES][LIGHT].async_update()
                                else:
                                    for _platform in self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS]:
                                        if _platform != BUTTON and message.entity in self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][_platform]:
                                            for _entity in self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][_platform][message.entity][CONF_ENTITIES]:
                                                if (
                                                    isinstance(
                                                        self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][_platform][message.entity][CONF_ENTITIES][_entity],
                                                        MyHOMEEntity,
                                                    )
                                                    and not isinstance(
                                                        self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][_platform][message.entity][CONF_ENTITIES][_entity],
                                                        DisableCommandButtonEntity,
                                                    )
                                                    and not isinstance(
                                                        self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][_platform][message.entity][CONF_ENTITIES][_entity],
                                                        EnableCommandButtonEntity,
                                                    )
                                                ):
                                                    self.hass.data[DOMAIN][self.mac][CONF_PLATFORMS][_platform][message.entity][CONF_ENTITIES][_entity].handle_event(message)

                        else:
                            LOGGER.debug(
                                "%s Ignoring translation message `%s`",
                                self.log_id,
                                message,
                            )
                    elif isinstance(message, OWNHeatingCommand) and message.dimension is not None and message.dimension == 14:
                        where = message.where[1:] if message.where.startswith("#") else message.where
                        LOGGER.debug(
                            "%s Received heating command, sending query to zone %s",
                            self.log_id,
                            where,
                        )
                        await self.send_status_request(OWNHeatingCommand.status(where))
                    elif isinstance(message, OWNCENPlusEvent):
                        event = None
                        if message.is_short_pressed:
                            event = CONF_SHORT_PRESS
                        elif message.is_held or message.is_still_held:
                            event = CONF_LONG_PRESS
                        elif message.is_released:
                            event = CONF_LONG_RELEASE
                        else:
                            event = None
                        self.hass.bus.async_fire(
                            "myhome_cenplus_event",
                            {
                                "object": int(message.object),
                                "pushbutton": int(message.push_button),
                                "event": event,
                            },
                        )
                        LOGGER.info(
                            "%s %s",
                            self.log_id,
                            message.human_readable_log,
                        )
                    elif isinstance(message, OWNCENEvent):
                        event = None
                        if message.is_pressed:
                            event = CONF_SHORT_PRESS
                        elif message.is_released_after_short_press:
                            event = CONF_SHORT_RELEASE
                        elif message.is_held:
                            event = CONF_LONG_PRESS
                        elif message.is_released_after_long_press:
                            event = CONF_LONG_RELEASE
                        else:
                            event = None
                        self.hass.bus.async_fire(
                            "myhome_cen_event",
                            {
                                "object": int(message.object),
                                "pushbutton": int(message.push_button),
                                "event": event,
                            },
                        )
                        LOGGER.info(
                            "%s %s",
                            self.log_id,
                            message.human_readable_log,
                        )
                    elif self._handle_heating_dimension_20(message):
                        continue
                    elif isinstance(message, OWNGatewayEvent) or isinstance(message, OWNGatewayCommand):
                        # Rate limiting for repetitive gateway messages (date/time updates)
                        msg_type = type(message).__name__
                        self._message_count[msg_type] = self._message_count.get(msg_type, 0) + 1

                        # Log first occurrence and then every N occurrences
                        if self._message_count[msg_type] == 1:
                            LOGGER.info(
                                "%s %s (further messages will be logged every %s occurrences)",
                                self.log_id,
                                message.human_readable_log,
                                self._log_interval,
                            )
                        elif self._message_count[msg_type] % self._log_interval == 0:
                            LOGGER.debug(
                                "%s %s (logged %s times)",
                                self.log_id,
                                message.human_readable_log,
                                self._message_count[msg_type],
                            )
                    else:
                        # Rate limiting for unsupported messages
                        msg_key = self._unsupported_message_key(message)
                        self._message_count[msg_key] = self._message_count.get(msg_key, 0) + 1

                        # Log first occurrence and then every N occurrences
                        if self._message_count[msg_key] == 1:
                            LOGGER.warning(
                                "%s Unsupported message type: `%s` (further occurrences will be logged every %s messages)",
                                self.log_id,
                                message,
                                self._log_interval,
                            )
                        elif self._message_count[msg_key] % self._log_interval == 0:
                            LOGGER.debug(
                                "%s Unsupported message: `%s` (received %s times)",
                                self.log_id,
                                message,
                                self._message_count[msg_key],
                            )

            except (OSError, ConnectionError, asyncio.CancelledError) as e:
                # Connection lost during message processing
                self.is_connected = False
                if isinstance(e, asyncio.CancelledError):
                    LOGGER.info("%s Listener cancelled.", self.log_id)
                    break  # Exit retry loop
                else:
                    LOGGER.error(
                        "%s Connection lost during message processing: %s",
                        self.log_id,
                        e,
                    )
                    # Will retry connection in outer loop
            except KeyError as ke:
                # Entity not found in hass.data - likely race condition during startup
                LOGGER.warning(
                    "%s Entity not found during message processing (startup race condition?): %s",
                    self.log_id,
                    ke,
                )
                await asyncio.sleep(1)  # Brief pause before retrying
            except Exception as e:
                # Unexpected error during message processing
                LOGGER.exception(
                    "%s Unexpected error in message processing loop: %s",
                    self.log_id,
                    e,
                )
                await asyncio.sleep(5)  # Pause before retry
            finally:
                # Ensure event session is closed
                if _event_session is not None:
                    try:
                        await _event_session.close()
                    except Exception as e:
                        LOGGER.error(
                            "%s Error closing event session: %s",
                            self.log_id,
                            e,
                        )
                self.is_connected = False

        LOGGER.info("%s Listening worker stopped.", self.log_id)
        LOGGER.debug("%s Destroying listening worker.", self.log_id)
        self.listening_worker.cancel()

    async def sending_loop(self, worker_id: int):
        """Send commands to the gateway with retry/reconnect logic."""
        self._terminate_sender = False

        retry_count = 0
        base_delay = 2  # seconds
        max_backoff = 60  # seconds
        command_session = None

        LOGGER.debug(
            "%s Creating sending worker %s",
            self.log_id,
            worker_id,
        )

        while not self._terminate_sender:
            if command_session is None:
                try:
                    if retry_count > 0:
                        delay = min(base_delay * (2 ** (retry_count - 1)), max_backoff)
                        LOGGER.warning(
                            "%s Sender worker %s disconnected, retrying in %s seconds.",
                            self.log_id,
                            worker_id,
                            delay,
                        )
                        await asyncio.sleep(delay)

                    command_session = OWNCommandSession(gateway=self.gateway, logger=LOGGER)
                    await command_session.connect()
                    if retry_count > 0:
                        LOGGER.info(
                            "%s Sender worker %s reconnected to gateway.",
                            self.log_id,
                            worker_id,
                        )
                    retry_count = 0
                except asyncio.CancelledError:
                    LOGGER.info("%s Sender worker %s cancelled.", self.log_id, worker_id)
                    break
                except (OSError, ConnectionError, TimeoutError) as conn_err:
                    retry_count += 1
                    LOGGER.error(
                        "%s Sender worker %s failed to connect: %s",
                        self.log_id,
                        worker_id,
                        conn_err,
                    )
                    continue
                except Exception as err:  # pylint: disable=broad-except
                    retry_count += 1
                    LOGGER.exception(
                        "%s Unexpected sender worker %s connection error: %s",
                        self.log_id,
                        worker_id,
                        err,
                    )
                    continue

            try:
                task = await asyncio.wait_for(self.send_buffer.get(), timeout=1)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                LOGGER.info("%s Sender worker %s cancelled.", self.log_id, worker_id)
                break

            if task is None:
                self.send_buffer.task_done()
                LOGGER.debug(
                    "%s Sender worker %s received shutdown signal.",
                    self.log_id,
                    worker_id,
                )
                break

            retry_task = False
            cancel_requested = False
            try:
                LOGGER.debug(
                    "%s Message `%s` was successfully unqueued by worker %s.",
                    self.log_id,
                    task["message"],
                    worker_id,
                )
                await command_session.send(
                    message=task["message"],
                    is_status_request=task["is_status_request"],
                )
                retry_count = 0
            except asyncio.CancelledError:
                retry_task = not self._terminate_sender
                cancel_requested = True
                LOGGER.info("%s Sender worker %s cancelled.", self.log_id, worker_id)
            except (OSError, ConnectionError, TimeoutError) as send_err:
                retry_count += 1
                retry_task = True
                LOGGER.error(
                    "%s Sender worker %s lost connection while sending `%s`: %s",
                    self.log_id,
                    worker_id,
                    task["message"],
                    send_err,
                )
            except Exception as err:  # pylint: disable=broad-except
                retry_count += 1
                retry_task = True
                LOGGER.exception(
                    "%s Unexpected sender worker %s error while sending `%s`: %s",
                    self.log_id,
                    worker_id,
                    task["message"],
                    err,
                )
            finally:
                self.send_buffer.task_done()

                if retry_task and not self._terminate_sender:
                    await self.send_buffer.put(task)

                if retry_task and command_session is not None:
                    try:
                        await command_session.close()
                    except Exception as err:  # pylint: disable=broad-except
                        LOGGER.error(
                            "%s Sender worker %s failed to close command session: %s",
                            self.log_id,
                            worker_id,
                            err,
                        )
                    command_session = None

            if cancel_requested:
                break

        if command_session is not None:
            try:
                await command_session.close()
            except Exception as err:  # pylint: disable=broad-except
                LOGGER.error(
                    "%s Sender worker %s failed to close command session: %s",
                    self.log_id,
                    worker_id,
                    err,
                )

        LOGGER.debug(
            "%s Destroying sending worker %s",
            self.log_id,
            worker_id,
        )

    async def close_listener(self) -> bool:
        LOGGER.info("%s Closing event listener", self.log_id)
        self._terminate_sender = True
        self._terminate_listener = True
        LOGGER.removeFilter(self._discovery_log_filter)

        # Wake sender workers blocked on queue.get().
        for _ in self.sending_workers:
            await self.send_buffer.put(None)

        if self.listening_worker is not None and not self.listening_worker.done():
            self.listening_worker.cancel()

        return True

    async def send(self, message: OWNCommand):
        await self.send_buffer.put({"message": message, "is_status_request": False})
        LOGGER.debug(
            "%s Message `%s` was successfully queued.",
            self.log_id,
            message,
        )

    async def send_status_request(self, message: OWNCommand):
        await self.send_buffer.put({"message": message, "is_status_request": True})
        LOGGER.debug(
            "%s Message `%s` was successfully queued.",
            self.log_id,
            message,
        )

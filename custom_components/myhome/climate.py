"""Support for MyHome heating."""

from homeassistant.components.climate import (
    ClimateEntity,
    DOMAIN as PLATFORM,
)
from homeassistant.components.climate.const import (
    FAN_OFF,
    FAN_AUTO,
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    CONF_NAME,
    CONF_MAC,
    UnitOfTemperature,
)

from .OWNd.message import (
    OWNHeatingEvent,
    OWNHeatingCommand,
    CLIMATE_MODE_OFF,
    CLIMATE_MODE_HEAT,
    CLIMATE_MODE_COOL,
    CLIMATE_MODE_AUTO,
    MESSAGE_TYPE_MAIN_TEMPERATURE,
    MESSAGE_TYPE_MAIN_HUMIDITY,
    MESSAGE_TYPE_SECONDARY_TEMPERATURE,
    MESSAGE_TYPE_TARGET_TEMPERATURE,
    MESSAGE_TYPE_LOCAL_OFFSET,
    MESSAGE_TYPE_LOCAL_TARGET_TEMPERATURE,
    MESSAGE_TYPE_MODE,
    MESSAGE_TYPE_MODE_TARGET,
    MESSAGE_TYPE_ACTION,
)

from .const import (
    CONF_PLATFORMS,
    CONF_ENTITY,
    CONF_WHO,
    CONF_ZONE,
    CONF_MANUFACTURER,
    CONF_DEVICE_MODEL,
    CONF_HEATING_SUPPORT,
    CONF_COOLING_SUPPORT,
    CONF_FAN_SUPPORT,
    CONF_STANDALONE,
    CONF_CENTRAL,
    DOMAIN,
    LOGGER,
)
from .myhome_device import MyHOMEEntity
from .gateway import MyHOMEGatewayHandler


async def async_setup_entry(hass, config_entry, async_add_entities):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _climate_devices = []
    _configured_climate_devices = hass.data[DOMAIN][config_entry.data[CONF_MAC]][
        CONF_PLATFORMS
    ][PLATFORM]

    for _climate_device in _configured_climate_devices.keys():
        _climate_devices.append(
            MyHOMEClimate(
                hass=hass,
                device_id=_climate_device,
                who=_configured_climate_devices[_climate_device][CONF_WHO],
                where=_configured_climate_devices[_climate_device][CONF_ZONE],
                name=_configured_climate_devices[_climate_device][CONF_NAME],
                heating=_configured_climate_devices[_climate_device][
                    CONF_HEATING_SUPPORT
                ],
                cooling=_configured_climate_devices[_climate_device][
                    CONF_COOLING_SUPPORT
                ],
                fan=_configured_climate_devices[_climate_device][CONF_FAN_SUPPORT],
                standalone=_configured_climate_devices[_climate_device][
                    CONF_STANDALONE
                ],
                central=_configured_climate_devices[_climate_device][CONF_CENTRAL],
                manufacturer=_configured_climate_devices[_climate_device][
                    CONF_MANUFACTURER
                ],
                model=_configured_climate_devices[_climate_device][CONF_DEVICE_MODEL],
                gateway=hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_ENTITY],
            )
        )

    async_add_entities(_climate_devices)


async def async_unload_entry(hass, config_entry):
    if PLATFORM not in hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS]:
        return True

    _configured_climate_devices = hass.data[DOMAIN][config_entry.data[CONF_MAC]][
        CONF_PLATFORMS
    ][PLATFORM]

    for _climate_device in _configured_climate_devices.keys():
        del hass.data[DOMAIN][config_entry.data[CONF_MAC]][CONF_PLATFORMS][PLATFORM][
            _climate_device
        ]


class MyHOMEClimate(MyHOMEEntity, ClimateEntity):
    @staticmethod
    def _decode_thermo_state(value):
        try:
            _value = int(value)
        except (TypeError, ValueError):
            return None

        if _value == 0:
            return "off"
        if _value == 1:
            return "on"
        if _value == 2:
            return "opened"
        if _value == 3:
            return "closed"
        if _value == 4:
            return "stopped"
        if _value == 5:
            return "fan_off"
        if _value > 5:
            speed = _value - 5
            if speed <= 3:
                return f"fan_speed_{speed}"
            return "fan_auto"
        return None

    @staticmethod
    def _fan_mode_from_speed(is_on, speed):
        if is_on is False:
            return FAN_OFF
        if is_on is not True:
            return None
        if speed == 1:
            return FAN_LOW
        if speed == 2:
            return FAN_MEDIUM
        if speed == 3:
            return FAN_HIGH
        return FAN_AUTO

    def __init__(
        self,
        hass,
        name: str,
        device_id: str,
        who: str,
        where: str,
        heating: bool,
        cooling: bool,
        fan: bool,
        standalone: bool,
        central: bool,
        manufacturer: str,
        model: str,
        gateway: MyHOMEGatewayHandler,
    ):
        super().__init__(
            hass=hass,
            name=name,
            platform=PLATFORM,
            device_id=device_id,
            who=who,
            where=where,
            manufacturer=manufacturer,
            model=model,
            gateway=gateway,
        )

        self._standalone = standalone
        self._central = True if self._where == "#0" else central

        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_precision = 0.1
        self._attr_target_temperature_step = 0.5
        self._attr_min_temp = 5
        self._attr_max_temp = 40

        self._attr_supported_features = 0
        self._attr_hvac_modes = [HVACMode.OFF]
        self._heating = heating
        self._cooling = cooling
        if heating or cooling:
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE
            if not self._central:
                self._attr_hvac_modes.append(HVACMode.AUTO)
            if heating:
                self._attr_hvac_modes.append(HVACMode.HEAT)
            if cooling:
                self._attr_hvac_modes.append(HVACMode.COOL)

        self._attr_fan_modes = []
        self._fan = fan
        if fan:
            # OWNd exposes fan telemetry for WHO4 but not fan set command.
            self._attr_fan_modes = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH, FAN_OFF]

        self._attr_current_temperature = None
        self._attr_current_humidity = None
        self._target_temperature = None
        self._local_offset = 0
        self._local_target_temperature = None
        self._secondary_temperatures = {}

        self._attr_hvac_mode = None
        self._attr_hvac_action = None
        self._thermo_function = None

        self._attr_fan_mode = None
        self._fan_on = None
        self._fan_speed = None
        self._cooling_fan_on = None
        self._cooling_fan_speed = None

        self._heating_valve_state = None
        self._cooling_valve_state = None
        self._actuators_status = {}

        self._valve_position = None
        self._valve_channel = None

    async def async_update(self):
        """Update the entity.

        Only used by the generic entity update service.
        """
        await self._gateway_handler.send_status_request(
            OWNHeatingCommand.status(self._where)
        )

    @property
    def target_temperature(self) -> float:
        if self._local_target_temperature is not None:
            return self._local_target_temperature
        else:
            return self._target_temperature

    @property
    def extra_state_attributes(self):
        attrs = {}
        if self._local_offset is not None:
            attrs["local_offset"] = self._local_offset
        if self._local_target_temperature is not None:
            attrs["local_target_temperature"] = self._local_target_temperature
        if self._secondary_temperatures:
            attrs["secondary_temperatures"] = self._secondary_temperatures
        if self._thermo_function is not None:
            attrs["thermo_function"] = self._thermo_function

        if self._cooling_valve_state is not None:
            attrs["conditioning_valves_status"] = self._cooling_valve_state
        if self._heating_valve_state is not None:
            attrs["heating_valves_status"] = self._heating_valve_state
        if self._actuators_status:
            attrs["actuators_status"] = self._actuators_status

        if self._fan_on is not None:
            attrs["fan_on"] = self._fan_on
        if self._fan_speed is not None:
            attrs["fan_speed"] = self._fan_speed
        if self._cooling_fan_on is not None:
            attrs["cooling_fan_on"] = self._cooling_fan_on
        if self._cooling_fan_speed is not None:
            attrs["cooling_fan_speed"] = self._cooling_fan_speed

        if self._valve_position is not None:
            attrs["valve_position"] = self._valve_position
            attrs["valve_status"] = (
                "closed"
                if self._valve_position == 0
                else "open"
                if self._valve_position == 100
                else "partial"
            )
        if self._valve_channel is not None:
            attrs["valve_channel"] = self._valve_channel
        return attrs if attrs else None

    def handle_valve_position(self, valve_position: int, valve_channel: str = None):
        """Handle WHO=4 dim#20 valve position data."""
        self._valve_position = valve_position
        self._valve_channel = valve_channel
        if self._attr_hvac_mode == HVACMode.HEAT:
            self._attr_hvac_action = (
                HVACAction.HEATING if valve_position > 0 else HVACAction.IDLE
            )
        elif self._attr_hvac_mode == HVACMode.COOL:
            self._attr_hvac_action = (
                HVACAction.COOLING if valve_position > 0 else HVACAction.IDLE
            )
        self.async_schedule_update_ha_state()

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            await self._gateway_handler.send(
                OWNHeatingCommand.set_mode(
                    where=self._where,
                    mode=CLIMATE_MODE_OFF,
                    standalone=self._standalone,
                )
            )
        elif hvac_mode == HVACMode.AUTO:
            await self._gateway_handler.send(
                OWNHeatingCommand.set_mode(
                    where=self._where,
                    mode=CLIMATE_MODE_AUTO,
                    standalone=self._standalone,
                )
            )
        elif hvac_mode == HVACMode.HEAT:
            if self._target_temperature is not None:
                await self._gateway_handler.send(
                    OWNHeatingCommand.set_temperature(
                        where=self._where,
                        temperature=self._target_temperature,
                        mode=CLIMATE_MODE_HEAT,
                        standalone=self._standalone,
                    )
                )
        elif hvac_mode == HVACMode.COOL:
            if self._target_temperature is not None:
                await self._gateway_handler.send(
                    OWNHeatingCommand.set_temperature(
                        where=self._where,
                        temperature=self._target_temperature,
                        mode=CLIMATE_MODE_COOL,
                        standalone=self._standalone,
                    )
                )

    # async def async_set_fan_mode(self, fan_mode):
    #     """Set new target fan mode."""
    #     pass

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        target_temperature = (
            kwargs.get("temperature", self._local_target_temperature)
            - self._local_offset
        )
        if self._attr_hvac_mode == HVACMode.HEAT:
            await self._gateway_handler.send(
                OWNHeatingCommand.set_temperature(
                    where=self._where,
                    temperature=target_temperature,
                    mode=CLIMATE_MODE_HEAT,
                    standalone=self._standalone,
                )
            )
        elif self._attr_hvac_mode == HVACMode.COOL:
            await self._gateway_handler.send(
                OWNHeatingCommand.set_temperature(
                    where=self._where,
                    temperature=target_temperature,
                    mode=CLIMATE_MODE_COOL,
                    standalone=self._standalone,
                )
            )
        else:
            await self._gateway_handler.send(
                OWNHeatingCommand.set_temperature(
                    where=self._where,
                    temperature=target_temperature,
                    mode=CLIMATE_MODE_AUTO,
                    standalone=self._standalone,
                )
            )

    def handle_event(self, message: OWNHeatingEvent):
        """Handle an event message."""
        if message.message_type == MESSAGE_TYPE_MAIN_TEMPERATURE:
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            self._attr_current_temperature = message.main_temperature
        elif message.message_type == MESSAGE_TYPE_MAIN_HUMIDITY:
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            self._attr_current_humidity = message.main_humidity
        elif message.message_type == MESSAGE_TYPE_SECONDARY_TEMPERATURE:
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            sensor, temperature = message.secondary_temperature
            self._secondary_temperatures[str(sensor)] = temperature
        elif message.message_type == MESSAGE_TYPE_TARGET_TEMPERATURE:
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            self._target_temperature = message.set_temperature
            self._local_target_temperature = (
                self._target_temperature + self._local_offset
            )
        elif message.message_type == MESSAGE_TYPE_LOCAL_OFFSET:
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            self._local_offset = message.local_offset
            if self._target_temperature is not None:
                self._local_target_temperature = (
                    self._target_temperature + self._local_offset
                )
        elif message.message_type == MESSAGE_TYPE_LOCAL_TARGET_TEMPERATURE:
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            self._local_target_temperature = message.local_set_temperature
            self._target_temperature = (
                self._local_target_temperature - self._local_offset
            )
        elif message.message_type == MESSAGE_TYPE_MODE:
            if (
                message.mode == CLIMATE_MODE_AUTO
                and HVACMode.AUTO in self._attr_hvac_modes
            ):
                LOGGER.debug(
                    "%s %s",
                    self._gateway_handler.log_id,
                    message.human_readable_log,
                )
                self._attr_hvac_mode = HVACMode.AUTO
                self._thermo_function = "generic"
                if self._attr_hvac_action == HVACAction.OFF:
                    self._attr_hvac_action = HVACAction.IDLE
            elif (
                message.mode == CLIMATE_MODE_COOL
                and HVACMode.COOL in self._attr_hvac_modes
            ):
                LOGGER.debug(
                    "%s %s",
                    self._gateway_handler.log_id,
                    message.human_readable_log,
                )
                self._attr_hvac_mode = HVACMode.COOL
                self._thermo_function = "cooling"
                if self._attr_hvac_action == HVACAction.OFF:
                    self._attr_hvac_action = HVACAction.IDLE
            elif (
                message.mode == CLIMATE_MODE_HEAT
                and HVACMode.HEAT in self._attr_hvac_modes
            ):
                LOGGER.debug(
                    "%s %s",
                    self._gateway_handler.log_id,
                    message.human_readable_log,
                )
                self._attr_hvac_mode = HVACMode.HEAT
                self._thermo_function = "heating"
                if self._attr_hvac_action == HVACAction.OFF:
                    self._attr_hvac_action = HVACAction.IDLE
            elif message.mode == CLIMATE_MODE_OFF:
                LOGGER.debug(
                    "%s %s",
                    self._gateway_handler.log_id,
                    message.human_readable_log,
                )
                self._attr_hvac_mode = HVACMode.OFF
                self._thermo_function = "off"
                self._attr_hvac_action = HVACAction.OFF
        elif message.message_type == MESSAGE_TYPE_MODE_TARGET:
            if (
                message.mode == CLIMATE_MODE_AUTO
                and HVACMode.AUTO in self._attr_hvac_modes
            ):
                LOGGER.debug(
                    "%s %s",
                    self._gateway_handler.log_id,
                    message.human_readable_log,
                )
                self._attr_hvac_mode = HVACMode.AUTO
                self._thermo_function = "generic"
                if self._attr_hvac_action == HVACAction.OFF:
                    self._attr_hvac_action = HVACAction.IDLE
            elif (
                message.mode == CLIMATE_MODE_COOL
                and HVACMode.COOL in self._attr_hvac_modes
            ):
                LOGGER.debug(
                    "%s %s",
                    self._gateway_handler.log_id,
                    message.human_readable_log,
                )
                self._attr_hvac_mode = HVACMode.COOL
                self._thermo_function = "cooling"
                if self._attr_hvac_action == HVACAction.OFF:
                    self._attr_hvac_action = HVACAction.IDLE
            elif (
                message.mode == CLIMATE_MODE_HEAT
                and HVACMode.HEAT in self._attr_hvac_modes
            ):
                LOGGER.debug(
                    "%s %s",
                    self._gateway_handler.log_id,
                    message.human_readable_log,
                )
                self._attr_hvac_mode = HVACMode.HEAT
                self._thermo_function = "heating"
                if self._attr_hvac_action == HVACAction.OFF:
                    self._attr_hvac_action = HVACAction.IDLE
            elif message.mode == CLIMATE_MODE_OFF:
                LOGGER.debug(
                    "%s %s",
                    self._gateway_handler.log_id,
                    message.human_readable_log,
                )
                self._attr_hvac_mode = HVACMode.OFF
                self._thermo_function = "off"
                self._attr_hvac_action = HVACAction.OFF
            self._target_temperature = message.set_temperature
            self._local_target_temperature = (
                self._target_temperature + self._local_offset
            )
        elif message.message_type == MESSAGE_TYPE_ACTION:
            LOGGER.debug(
                "%s %s",
                self._gateway_handler.log_id,
                message.human_readable_log,
            )
            self._fan_on = getattr(message, "_fan_on", self._fan_on)
            self._fan_speed = getattr(message, "_fan_speed", self._fan_speed)
            self._cooling_fan_on = getattr(
                message, "_cooling_fan_on", self._cooling_fan_on
            )
            self._cooling_fan_speed = getattr(
                message, "_cooling_fan_speed", self._cooling_fan_speed
            )

            if self._fan:
                fan_mode = self._fan_mode_from_speed(self._fan_on, self._fan_speed)
                if fan_mode is None:
                    fan_mode = self._fan_mode_from_speed(
                        self._cooling_fan_on, self._cooling_fan_speed
                    )
                if fan_mode is not None:
                    self._attr_fan_mode = fan_mode

            dim_values = getattr(message, "_dimension_value", None)
            if isinstance(dim_values, list) and len(dim_values) >= 2:
                self._cooling_valve_state = self._decode_thermo_state(dim_values[0])
                self._heating_valve_state = self._decode_thermo_state(dim_values[1])
            elif isinstance(dim_values, list) and len(dim_values) == 1:
                actuator = getattr(message, "_actuator", None)
                if actuator is not None:
                    self._actuators_status[str(actuator)] = self._decode_thermo_state(
                        dim_values[0]
                    )

            if message.is_active():
                if self._heating and self._cooling:
                    if message.is_heating():
                        self._thermo_function = "heating"
                        self._attr_hvac_action = HVACAction.HEATING
                    elif message.is_cooling():
                        self._thermo_function = "cooling"
                        self._attr_hvac_action = HVACAction.COOLING
                elif self._heating:
                    self._thermo_function = "heating"
                    self._attr_hvac_action = HVACAction.HEATING
                elif self._cooling:
                    self._thermo_function = "cooling"
                    self._attr_hvac_action = HVACAction.COOLING
            elif self._attr_hvac_mode == HVACMode.OFF:
                self._thermo_function = "off"
                self._attr_hvac_action = HVACAction.OFF
            else:
                self._attr_hvac_action = HVACAction.IDLE

        self.async_schedule_update_ha_state()

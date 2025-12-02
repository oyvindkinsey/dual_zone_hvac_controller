"""Climate platform for Dual Zone HVAC Controller"""
import logging
from typing import Optional, Dict, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.const import STATE_UNKNOWN, STATE_UNAVAILABLE, UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    ATTR_CURRENT_TEMPERATURE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ATTR_HVAC_MODE,
)

from . import DOMAIN, DualZoneHVACController

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    """Set up the climate platform"""
    controller: DualZoneHVACController = hass.data[DOMAIN]

    entities = [
        DualZoneClimate(hass, controller, 'zone1', 'Zone 1', controller.zones['zone1'].climate_entity),
        DualZoneClimate(hass, controller, 'zone2', 'Zone 2', controller.zones['zone2'].climate_entity),
    ]

    # Store references in controller
    controller.climate_entities['zone1'] = entities[0]
    controller.climate_entities['zone2'] = entities[1]

    async_add_entities(entities)
    _LOGGER.info("Climate entities registered: climate.dual_zone_hvac_zone1, climate.dual_zone_hvac_zone2")


class DualZoneClimate(ClimateEntity):
    """Climate entity representing a single zone controlled by the dual zone controller"""

    def __init__(self, hass: HomeAssistant, controller: DualZoneHVACController,
                 zone_id: str, zone_name: str, physical_entity: str):
        """Initialize the climate entity"""
        self.hass = hass
        self._controller = controller
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._physical_entity = physical_entity
        self._attr_name = f"Dual Zone HVAC {zone_name}"
        self._attr_unique_id = f"{DOMAIN}_{zone_id}"
        self._attr_should_poll = False

        # Temperature unit
        self._attr_temperature_unit = UnitOfTemperature.FAHRENHEIT

        # Supported modes - heat, cool, auto (heat_cool), and off
        self._attr_hvac_modes = [
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.HEAT_COOL,
            HVACMode.OFF
        ]

        # Supported fan modes
        self._attr_fan_modes = ['quiet', 'low', 'medium', 'high']

    @property
    def supported_features(self) -> int:
        """Return the list of supported features - changes based on HVAC mode"""
        # Base features always include fan mode
        features = ClimateEntityFeature.FAN_MODE

        # Add temperature control features based on current mode
        current_mode = self._controller.zones[self._zone_id].hvac_mode

        if current_mode == HVACMode.HEAT_COOL:
            # Heat/Cool mode supports temperature range
            features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        else:
            # Heat, Cool, or Off modes support single temperature
            features |= ClimateEntityFeature.TARGET_TEMPERATURE

        return features

    @property
    def current_temperature(self) -> Optional[float]:
        """Return the current temperature from the physical climate entity"""
        state = self.hass.states.get(self._physical_entity)
        if state is None or state.state in [STATE_UNKNOWN, STATE_UNAVAILABLE]:
            return None
        return state.attributes.get(ATTR_CURRENT_TEMPERATURE)

    @property
    def target_temperature(self) -> Optional[float]:
        """Return the target temperature from controller state"""
        # For heat/cool modes, return the single setpoint
        # For heat_cool mode, this represents the midpoint
        return self._controller.zones[self._zone_id].target_setpoint

    @property
    def target_temperature_high(self) -> Optional[float]:
        """Return the high target temperature for heat_cool mode"""
        return self._controller.zones[self._zone_id].target_temp_high

    @property
    def target_temperature_low(self) -> Optional[float]:
        """Return the low target temperature for heat_cool mode"""
        return self._controller.zones[self._zone_id].target_temp_low

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the user-selected HVAC mode"""
        return HVACMode(self._controller.zones[self._zone_id].hvac_mode)

    @property
    def fan_mode(self) -> Optional[str]:
        """Return the nominal fan speed setting for this zone"""
        return self._controller.zones[self._zone_id].nominal_fan_speed

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes"""
        zone = self._controller.zones[self._zone_id]
        return {
            'heating_rate': f"{self._controller.heating_rate[self._zone_id]:.3f}°F/min",
            'cooling_rate': f"{self._controller.cooling_rate[self._zone_id]:.3f}°F/min",
            'leakage_rate': f"{self._controller.leakage_rate[self._zone_id]:.3f}°F/min",
            'physical_entity': self._physical_entity,
            'hvac_mode': zone.hvac_mode,
            'target_temp_range': f"{zone.target_temp_low:.1f}-{zone.target_temp_high:.1f}°F",
        }

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature or temperature range"""
        zone = self._controller.zones[self._zone_id]

        # Handle temperature range (for heat_cool mode)
        if ATTR_TARGET_TEMP_HIGH in kwargs and ATTR_TARGET_TEMP_LOW in kwargs:
            temp_high = float(kwargs[ATTR_TARGET_TEMP_HIGH])
            temp_low = float(kwargs[ATTR_TARGET_TEMP_LOW])

            old_high = zone.target_temp_high
            old_low = zone.target_temp_low

            zone.target_temp_high = temp_high
            zone.target_temp_low = temp_low
            # Update midpoint setpoint
            zone.target_setpoint = (temp_high + temp_low) / 2.0

            _LOGGER.info(
                f"Set {self._zone_id} temperature range: "
                f"{old_low:.1f}-{old_high:.1f}°F -> {temp_low:.1f}-{temp_high:.1f}°F"
            )

        # Handle single temperature (for heat/cool modes)
        elif ATTR_TEMPERATURE in kwargs:
            temperature = float(kwargs[ATTR_TEMPERATURE])
            old_temp = zone.target_setpoint

            zone.target_setpoint = temperature
            # Also update the range around this setpoint
            zone.target_temp_low = temperature - 2.0
            zone.target_temp_high = temperature + 2.0

            _LOGGER.info(f"Set {self._zone_id} target temperature: {old_temp:.1f}°F -> {temperature:.1f}°F")

        # Handle mode change if provided
        if ATTR_HVAC_MODE in kwargs:
            await self.async_set_hvac_mode(HVACMode(kwargs[ATTR_HVAC_MODE]))

        # Save state and trigger control loop
        await self._controller._save_state()
        await self._controller.async_control_loop()

        # Notify HA that state changed
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode (heat, cool, heat_cool, or off)"""
        old_mode = self._controller.zones[self._zone_id].hvac_mode
        self._controller.zones[self._zone_id].hvac_mode = hvac_mode
        _LOGGER.info(f"Set {self._zone_id} HVAC mode: {old_mode} -> {hvac_mode}")

        # Save state and trigger control loop
        await self._controller._save_state()
        await self._controller.async_control_loop()

        # Notify HA that state changed
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set nominal fan speed for this zone"""
        old_speed = self._controller.zones[self._zone_id].nominal_fan_speed
        self._controller.zones[self._zone_id].nominal_fan_speed = fan_mode
        _LOGGER.info(f"Set {self._zone_id} nominal fan speed: {old_speed} -> {fan_mode}")

        # Save state and trigger control loop
        await self._controller._save_state()
        await self._controller.async_control_loop()

        # Notify HA that state changed
        self.async_write_ha_state()

    def update_state(self) -> None:
        """Called by controller when state changes"""
        self.async_write_ha_state()

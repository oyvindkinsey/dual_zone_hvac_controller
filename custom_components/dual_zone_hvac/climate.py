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

        # Supported features
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.FAN_MODE
        )

        # Temperature unit
        self._attr_temperature_unit = UnitOfTemperature.FAHRENHEIT

        # Supported modes
        self._attr_hvac_modes = [
            HVACMode.HEAT,
            HVACMode.COOL,
            HVACMode.FAN_ONLY,
            HVACMode.OFF
        ]

        # Supported fan modes
        self._attr_fan_modes = ['quiet', 'low', 'medium', 'high']

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
        return self._controller.zones[self._zone_id].target_setpoint

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode calculated by the controller"""
        # Get the current mode from the physical entity since that reflects
        # what the controller has set
        state = self.hass.states.get(self._physical_entity)
        if state is None or state.state in [STATE_UNKNOWN, STATE_UNAVAILABLE]:
            return HVACMode.OFF
        return HVACMode(state.state)

    @property
    def fan_mode(self) -> Optional[str]:
        """Return the nominal fan speed setting for this zone"""
        return self._controller.zones[self._zone_id].nominal_fan_speed

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes"""
        return {
            'heating_rate': f"{self._controller.heating_rate[self._zone_id]:.3f}°F/min",
            'cooling_rate': f"{self._controller.cooling_rate[self._zone_id]:.3f}°F/min",
            'leakage_rate': f"{self._controller.leakage_rate[self._zone_id]:.3f}°F/min",
            'physical_entity': self._physical_entity,
        }

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature"""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        old_temp = self._controller.zones[self._zone_id].target_setpoint
        self._controller.zones[self._zone_id].target_setpoint = float(temperature)
        _LOGGER.info(f"Set {self._zone_id} target temperature: {old_temp}°F -> {temperature}°F")

        # Save state and trigger control loop
        await self._controller._save_state()
        await self._controller.async_control_loop()

        # Notify HA that state changed
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode - not directly supported, controller manages modes"""
        _LOGGER.warning(
            f"Direct HVAC mode changes not supported. The controller manages modes automatically. "
            f"Requested mode {hvac_mode} for {self._zone_id} ignored."
        )

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

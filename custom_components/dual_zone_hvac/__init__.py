"""
Home Assistant Custom Component: Dual Zone HVAC Controller with Leakage Compensation

COMPLETE INSTALLATION INSTRUCTIONS:

Step 1: Create the directory structure
----------------------------------------
In your Home Assistant config directory, create:
  config/custom_components/dual_zone_hvac/

Step 2: Create __init__.py
---------------------------
Save THIS ENTIRE FILE as:
  config/custom_components/dual_zone_hvac/__init__.py

Step 3: Create manifest.json
-----------------------------
Create a NEW file at:
  config/custom_components/dual_zone_hvac/manifest.json

With this EXACT content (copy everything between the lines):
---
{
  "domain": "dual_zone_hvac",
  "name": "Dual Zone HVAC Controller",
  "documentation": "https://github.com/yourusername/dual_zone_hvac",
  "requirements": [],
  "codeowners": [],
  "version": "1.0.0",
  "iot_class": "local_polling"
}
---

Step 4: Verify file structure
------------------------------
You should have these files:
  config/custom_components/dual_zone_hvac/__init__.py
  config/custom_components/dual_zone_hvac/manifest.json

Step 5: Add to configuration.yaml
----------------------------------
dual_zone_hvac:
  zone1:
    climate_entity: climate.zone_1_thermostat
    target_temperature: 68
  zone2:
    climate_entity: climate.zone_2_thermostat
    target_temperature: 68
  settings:
    deadband: 0.5
    min_offset: 0.3
    conflict_threshold: 2.0
    update_interval: 60

Step 6: Restart Home Assistant
-------------------------------
Full restart required (not just reload)

Step 7: Check logs
------------------
Check Configuration > Logs for any errors
Look for: "Dual Zone HVAC Controller initialized"

TROUBLESHOOTING:
- Ensure manifest.json has NO extra commas
- Ensure both files are in the correct directory
- Check file permissions (should be readable)
- Enable debug logging: logger: default: info; custom_components.dual_zone_hvac: debug
"""

import logging
import asyncio
import time
from datetime import timedelta
from typing import Dict, Optional, Literal, Any
from collections import deque
from dataclasses import dataclass, field

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.const import (
    CONF_NAME,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
)
from homeassistant.components.climate import HVACMode
from homeassistant.const import (
    ATTR_TEMPERATURE,
)

HVAC_MODE_HEAT = HVACMode.HEAT
HVAC_MODE_COOL = HVACMode.COOL
HVAC_MODE_HEAT_COOL = HVACMode.HEAT_COOL
HVAC_MODE_DRY = HVACMode.DRY
HVAC_MODE_FAN_ONLY = HVACMode.FAN_ONLY
HVAC_MODE_OFF = HVACMode.OFF

# Attribute name for current temperature
ATTR_CURRENT_TEMPERATURE = "current_temperature"

_LOGGER = logging.getLogger(__name__)

DOMAIN = "dual_zone_hvac"

# Configuration keys
# Configuration keys
CONF_ZONE1 = "zone1"
CONF_ZONE2 = "zone2"
CONF_CLIMATE_ENTITY = "climate_entity"
CONF_TARGET_TEMPERATURE = "target_temperature"
CONF_SETTINGS = "settings"
CONF_DEADBAND = "deadband"
CONF_MIN_OFFSET = "min_offset"
CONF_CONFLICT_THRESHOLD = "conflict_threshold"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_MAX_STARTS_PER_HOUR = "max_starts_per_hour"
CONF_MIN_COMPRESSOR_RUNTIME = "min_compressor_runtime"
CONF_MIN_COMPRESSOR_OFF_TIME = "min_compressor_off_time"

# Default values
DEFAULT_DEADBAND = 0.5
DEFAULT_MIN_OFFSET = 0.3
DEFAULT_CONFLICT_THRESHOLD = 2.0
DEFAULT_UPDATE_INTERVAL = 60
DEFAULT_NOMINAL_FAN_SPEED = "medium"
DEFAULT_MAX_STARTS_PER_HOUR = 3
DEFAULT_MIN_COMPRESSOR_RUNTIME = 180  # 3 minutes in seconds
DEFAULT_MIN_COMPRESSOR_OFF_TIME = 180  # 3 minutes in seconds

# Service names
SERVICE_SET_TARGET_TEMPERATURE = "set_target_temperature"
SERVICE_SET_NOMINAL_FAN_SPEED = "set_nominal_fan_speed"
SERVICE_SET_ENABLE = "set_enable"
SERVICE_RESET_LEARNING = "reset_learning"
SERVICE_GET_STATE = "get_state"

Mode = Literal['heat', 'cool', 'dry', 'fan_only', 'off']
FanSpeed = Literal['quiet', 'low', 'medium', 'high']

# Fan speed hierarchy for comparison
FAN_SPEED_LEVELS = {
    'quiet': 0,
    'low': 1,
    'medium': 2,
    'high': 3
}

# Configuration schema
ZONE_SCHEMA = vol.Schema({
    vol.Required(CONF_CLIMATE_ENTITY): cv.entity_id,
    vol.Required(CONF_TARGET_TEMPERATURE): vol.Coerce(float),
})

SETTINGS_SCHEMA = vol.Schema({
    vol.Optional(CONF_DEADBAND, default=DEFAULT_DEADBAND): vol.Coerce(float),
    vol.Optional(CONF_MIN_OFFSET, default=DEFAULT_MIN_OFFSET): vol.Coerce(float),
    vol.Optional(CONF_CONFLICT_THRESHOLD, default=DEFAULT_CONFLICT_THRESHOLD): vol.Coerce(float),
    vol.Optional(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): vol.Coerce(int),
    vol.Optional(CONF_MAX_STARTS_PER_HOUR, default=DEFAULT_MAX_STARTS_PER_HOUR): vol.Coerce(int),
    vol.Optional(CONF_MIN_COMPRESSOR_RUNTIME, default=DEFAULT_MIN_COMPRESSOR_RUNTIME): vol.Coerce(int),
    vol.Optional(CONF_MIN_COMPRESSOR_OFF_TIME, default=DEFAULT_MIN_COMPRESSOR_OFF_TIME): vol.Coerce(int),
})

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_ZONE1): ZONE_SCHEMA,
        vol.Required(CONF_ZONE2): ZONE_SCHEMA,
        vol.Optional(CONF_SETTINGS, default={}): SETTINGS_SCHEMA,
    })
}, extra=vol.ALLOW_EXTRA)


@dataclass
class ZoneState:
    """Tracks the state and history of a zone"""
    temperature_history: deque = field(default_factory=lambda: deque(maxlen=10))
    mode_history: deque = field(default_factory=lambda: deque(maxlen=10))
    last_mode: str = HVAC_MODE_OFF
    target_setpoint: float = 70.0
    target_temp_high: float = 72.0  # For heat_cool mode
    target_temp_low: float = 68.0   # For heat_cool mode
    hvac_mode: str = HVAC_MODE_HEAT  # User-selected mode: heat, cool, heat_cool, off
    climate_entity: str = ""
    nominal_fan_speed: str = "medium"  # Changed from max_fan_speed to nominal_fan_speed


class DualZoneHVACController:
    """Controller for managing two HVAC zones with leakage compensation"""

    def __init__(self, hass: HomeAssistant, config: dict):
        self.hass = hass
        self._config = config

        # Settings
        settings = config.get(CONF_SETTINGS, {})
        self.deadband = settings.get(CONF_DEADBAND, DEFAULT_DEADBAND)
        self.min_offset = settings.get(CONF_MIN_OFFSET, DEFAULT_MIN_OFFSET)
        self.conflict_threshold = settings.get(CONF_CONFLICT_THRESHOLD, DEFAULT_CONFLICT_THRESHOLD)
        self.update_interval = settings.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        self.max_starts_per_hour = settings.get(CONF_MAX_STARTS_PER_HOUR, DEFAULT_MAX_STARTS_PER_HOUR)
        self.min_compressor_runtime = settings.get(CONF_MIN_COMPRESSOR_RUNTIME, DEFAULT_MIN_COMPRESSOR_RUNTIME)
        self.min_compressor_off_time = settings.get(CONF_MIN_COMPRESSOR_OFF_TIME, DEFAULT_MIN_COMPRESSOR_OFF_TIME)

        # Zone configuration
        zone1_config = config[CONF_ZONE1]
        zone2_config = config[CONF_ZONE2]

        # Initialize zones with default temperature ranges
        initial_temp1 = zone1_config[CONF_TARGET_TEMPERATURE]
        initial_temp2 = zone2_config[CONF_TARGET_TEMPERATURE]

        self.zones = {
            'zone1': ZoneState(
                climate_entity=zone1_config[CONF_CLIMATE_ENTITY],
                target_setpoint=initial_temp1,
                target_temp_low=initial_temp1 - 2.0,
                target_temp_high=initial_temp1 + 2.0,
                hvac_mode=HVAC_MODE_HEAT_COOL,  # Default to auto mode
                nominal_fan_speed=DEFAULT_NOMINAL_FAN_SPEED
            ),
            'zone2': ZoneState(
                climate_entity=zone2_config[CONF_CLIMATE_ENTITY],
                target_setpoint=initial_temp2,
                target_temp_low=initial_temp2 - 2.0,
                target_temp_high=initial_temp2 + 2.0,
                hvac_mode=HVAC_MODE_HEAT_COOL,  # Default to auto mode
                nominal_fan_speed=DEFAULT_NOMINAL_FAN_SPEED
            )
        }

        # Learned coefficients
        self.heating_rate = {'zone1': 0.0, 'zone2': 0.0}
        self.cooling_rate = {'zone1': 0.0, 'zone2': 0.0}
        self.leakage_rate = {'zone1': 0.0, 'zone2': 0.0}

        # Tracking for rate calculation
        self.rate_samples = {
            'heating': {'zone1': [], 'zone2': []},
            'cooling': {'zone1': [], 'zone2': []},
            'leakage': {'zone1': [], 'zone2': []}
        }

        self.enabled = True
        self.iteration_count = 0
        self._cancel_interval = None

        # Compressor start tracking for short-cycle prevention
        self.compressor_start_times = deque(maxlen=20)  # Keep last 20 starts
        self.compressor_running = False
        self.compressor_last_start_time = None
        self.compressor_last_stop_time = None

        # Climate entities (will be populated by climate platform)
        self.climate_entities: Dict[str, Any] = {}
    
    async def async_setup(self):
        """Set up the controller"""
        # Load persisted state
        await self._load_state()

        # Load the climate platform to create climate entities
        await async_load_platform(self.hass, 'climate', DOMAIN, {}, self._config)

        # Register services (kept for backwards compatibility)
        self.hass.services.async_register(
            DOMAIN,
            SERVICE_SET_TARGET_TEMPERATURE,
            self.async_set_target_temperature,
            schema=vol.Schema({
                vol.Required('zone'): vol.In(['zone1', 'zone2']),
                vol.Required('temperature'): vol.Coerce(float),
            })
        )

        self.hass.services.async_register(
            DOMAIN,
            SERVICE_SET_NOMINAL_FAN_SPEED,
            self.async_set_nominal_fan_speed,
            schema=vol.Schema({
                vol.Required('zone'): vol.In(['zone1', 'zone2']),
                vol.Required('fan_speed'): vol.In(['quiet', 'low', 'medium', 'high']),
            })
        )

        self.hass.services.async_register(
            DOMAIN,
            SERVICE_SET_ENABLE,
            self.async_set_enable,
            schema=vol.Schema({
                vol.Required('enabled'): cv.boolean,
            })
        )

        self.hass.services.async_register(
            DOMAIN,
            SERVICE_RESET_LEARNING,
            self.async_reset_learning,
        )

        self.hass.services.async_register(
            DOMAIN,
            SERVICE_GET_STATE,
            self.async_get_state,
        )

        # Create sensor entities to expose state
        await self._create_sensors()

        # Run control loop immediately on startup
        await self.async_control_loop()

        # Start the periodic control loop
        self._cancel_interval = async_track_time_interval(
            self.hass,
            self.async_control_loop,
            timedelta(seconds=self.update_interval)
        )

        _LOGGER.info("Dual Zone HVAC Controller initialized")
        _LOGGER.info(f"Zone 1: {self.zones['zone1'].climate_entity} -> {self.zones['zone1'].target_setpoint}°F (mode: {self.zones['zone1'].hvac_mode})")
        _LOGGER.info(f"Zone 2: {self.zones['zone2'].climate_entity} -> {self.zones['zone2'].target_setpoint}°F (mode: {self.zones['zone2'].hvac_mode})")

        return True
    
    async def async_unload(self):
        """Unload the controller"""
        # Save state before unloading
        await self._save_state()
        
        if self._cancel_interval:
            self._cancel_interval()
        return True
    
    async def _load_state(self):
        """Load persisted state from storage"""
        try:
            store = Store(self.hass, 1, f"{DOMAIN}.state")
            data = await store.async_load()
            
            if data:
                # Load zone settings
                if 'zone1' in data:
                    self.zones['zone1'].target_setpoint = data['zone1'].get('target_setpoint', self.zones['zone1'].target_setpoint)
                    self.zones['zone1'].target_temp_low = data['zone1'].get('target_temp_low', self.zones['zone1'].target_temp_low)
                    self.zones['zone1'].target_temp_high = data['zone1'].get('target_temp_high', self.zones['zone1'].target_temp_high)
                    self.zones['zone1'].hvac_mode = data['zone1'].get('hvac_mode', self.zones['zone1'].hvac_mode)
                    self.zones['zone1'].nominal_fan_speed = data['zone1'].get('nominal_fan_speed', self.zones['zone1'].nominal_fan_speed)

                if 'zone2' in data:
                    self.zones['zone2'].target_setpoint = data['zone2'].get('target_setpoint', self.zones['zone2'].target_setpoint)
                    self.zones['zone2'].target_temp_low = data['zone2'].get('target_temp_low', self.zones['zone2'].target_temp_low)
                    self.zones['zone2'].target_temp_high = data['zone2'].get('target_temp_high', self.zones['zone2'].target_temp_high)
                    self.zones['zone2'].hvac_mode = data['zone2'].get('hvac_mode', self.zones['zone2'].hvac_mode)
                    self.zones['zone2'].nominal_fan_speed = data['zone2'].get('nominal_fan_speed', self.zones['zone2'].nominal_fan_speed)
                
                # Load learned rates
                if 'heating_rate' in data:
                    self.heating_rate = data['heating_rate']
                if 'cooling_rate' in data:
                    self.cooling_rate = data['cooling_rate']
                if 'leakage_rate' in data:
                    self.leakage_rate = data['leakage_rate']
                
                # Load enabled state
                if 'enabled' in data:
                    self.enabled = data['enabled']

                # Load compressor start times (filter to keep only last hour)
                if 'compressor_start_times' in data:
                    now = time.time()
                    cutoff = now - 3600  # Only keep starts from last hour
                    self.compressor_start_times = deque(
                        (t for t in data['compressor_start_times'] if t > cutoff),
                        maxlen=20
                    )
                    _LOGGER.info(f"Loaded {len(self.compressor_start_times)} compressor starts from last hour")

                _LOGGER.info(f"Loaded persisted state: Z1={self.zones['zone1'].target_setpoint}°F (fan:{self.zones['zone1'].nominal_fan_speed}), Z2={self.zones['zone2'].target_setpoint}°F (fan:{self.zones['zone2'].nominal_fan_speed})")
        except Exception as e:
            _LOGGER.warning(f"Could not load persisted state: {e}")
    
    async def _save_state(self):
        """Save current state to storage"""
        try:
            store = Store(self.hass, 1, f"{DOMAIN}.state")
            data = {
                'zone1': {
                    'target_setpoint': self.zones['zone1'].target_setpoint,
                    'target_temp_low': self.zones['zone1'].target_temp_low,
                    'target_temp_high': self.zones['zone1'].target_temp_high,
                    'hvac_mode': self.zones['zone1'].hvac_mode,
                    'nominal_fan_speed': self.zones['zone1'].nominal_fan_speed,
                },
                'zone2': {
                    'target_setpoint': self.zones['zone2'].target_setpoint,
                    'target_temp_low': self.zones['zone2'].target_temp_low,
                    'target_temp_high': self.zones['zone2'].target_temp_high,
                    'hvac_mode': self.zones['zone2'].hvac_mode,
                    'nominal_fan_speed': self.zones['zone2'].nominal_fan_speed,
                },
                'heating_rate': self.heating_rate,
                'cooling_rate': self.cooling_rate,
                'leakage_rate': self.leakage_rate,
                'enabled': self.enabled,
                'compressor_start_times': list(self.compressor_start_times),
            }
            await store.async_save(data)
            _LOGGER.debug("Saved controller state")
            
            # Update sensor states
            await self._update_sensors()
        except Exception as e:
            _LOGGER.error(f"Could not save state: {e}")
    
    async def _create_sensors(self):
        """Create sensor entities to expose controller state"""
        # Enabled sensor
        self.hass.states.async_set(
            f"sensor.{DOMAIN}_enabled",
            'on' if self.enabled else 'off',
            {
                'friendly_name': 'Dual Zone HVAC Enabled',
            }
        )

        # Learned rates sensor with diagnostic info
        self.hass.states.async_set(
            f"sensor.{DOMAIN}_learned_rates",
            'active' if any([
                self.heating_rate['zone1'] > 0,
                self.heating_rate['zone2'] > 0,
                self.cooling_rate['zone1'] > 0,
                self.cooling_rate['zone2'] > 0,
                self.leakage_rate['zone1'] > 0,
                self.leakage_rate['zone2'] > 0
            ]) else 'learning',
            {
                'friendly_name': 'Learned Rates',
                'zone1_heating_rate': f"{self.heating_rate['zone1']:.3f}°F/min",
                'zone1_cooling_rate': f"{self.cooling_rate['zone1']:.3f}°F/min",
                'zone1_leakage_rate': f"{self.leakage_rate['zone1']:.3f}°F/min",
                'zone2_heating_rate': f"{self.heating_rate['zone2']:.3f}°F/min",
                'zone2_cooling_rate': f"{self.cooling_rate['zone2']:.3f}°F/min",
                'zone2_leakage_rate': f"{self.leakage_rate['zone2']:.3f}°F/min",
                'compressor_starts_last_hour': self.count_recent_starts(),
            }
        )
    
    async def _update_sensors(self):
        """Update sensor entities with current state"""
        # Update enabled sensor
        self.hass.states.async_set(
            f"sensor.{DOMAIN}_enabled",
            'on' if self.enabled else 'off',
            {
                'friendly_name': 'Dual Zone HVAC Enabled',
            }
        )

        # Update learned rates sensor
        self.hass.states.async_set(
            f"sensor.{DOMAIN}_learned_rates",
            'active' if any([
                self.heating_rate['zone1'] > 0,
                self.heating_rate['zone2'] > 0,
                self.cooling_rate['zone1'] > 0,
                self.cooling_rate['zone2'] > 0,
                self.leakage_rate['zone1'] > 0,
                self.leakage_rate['zone2'] > 0
            ]) else 'learning',
            {
                'friendly_name': 'Learned Rates',
                'zone1_heating_rate': f"{self.heating_rate['zone1']:.3f}°F/min",
                'zone1_cooling_rate': f"{self.cooling_rate['zone1']:.3f}°F/min",
                'zone1_leakage_rate': f"{self.leakage_rate['zone1']:.3f}°F/min",
                'zone2_heating_rate': f"{self.heating_rate['zone2']:.3f}°F/min",
                'zone2_cooling_rate': f"{self.cooling_rate['zone2']:.3f}°F/min",
                'zone2_leakage_rate': f"{self.leakage_rate['zone2']:.3f}°F/min",
                'compressor_starts_last_hour': self.count_recent_starts(),
            }
        )

        # Update climate entities
        for entity in self.climate_entities.values():
            entity.update_state()
    
    async def async_set_target_temperature(self, call: ServiceCall):
        """Service to set target temperature for a zone"""
        zone = call.data['zone']
        temperature = call.data['temperature']
        old_temp = self.zones[zone].target_setpoint
        self.zones[zone].target_setpoint = temperature
        _LOGGER.info(f"SERVICE CALL: Set {zone} target temperature: {old_temp}°F -> {temperature}°F")
        
        # Save state after change
        await self._save_state()
        
        # Immediately run control loop to apply changes
        await self.async_control_loop()
    
    async def async_set_nominal_fan_speed(self, call: ServiceCall):
        """Service to set nominal fan speed for a zone"""
        zone = call.data['zone']
        fan_speed = call.data['fan_speed']
        old_speed = self.zones[zone].nominal_fan_speed
        self.zones[zone].nominal_fan_speed = fan_speed
        _LOGGER.info(f"SERVICE CALL: Set {zone} nominal fan speed: {old_speed} -> {fan_speed}")
        
        # Save state after change
        await self._save_state()
        
        # Immediately run control loop to apply changes
        await self.async_control_loop()
    
    async def async_set_enable(self, call: ServiceCall):
        """Service to enable/disable the controller"""
        old_state = self.enabled
        self.enabled = call.data['enabled']
        status = "enabled" if self.enabled else "disabled"
        _LOGGER.warning(f"SERVICE CALL: Controller {status} (was {'enabled' if old_state else 'disabled'})")
        
        # Save state after change
        await self._save_state()
        
        # If enabling, immediately run control loop
        if self.enabled:
            await self.async_control_loop()
    
    async def async_reset_learning(self, call: ServiceCall):
        """Service to reset learned rates"""
        _LOGGER.warning("SERVICE CALL: Resetting all learned rates")
        _LOGGER.info(f"Previous rates - Heating: {self.heating_rate}, Cooling: {self.cooling_rate}, Leakage: {self.leakage_rate}")
        
        self.heating_rate = {'zone1': 0.0, 'zone2': 0.0}
        self.cooling_rate = {'zone1': 0.0, 'zone2': 0.0}
        self.leakage_rate = {'zone1': 0.0, 'zone2': 0.0}
        self.rate_samples = {
            'heating': {'zone1': [], 'zone2': []},
            'cooling': {'zone1': [], 'zone2': []},
            'leakage': {'zone1': [], 'zone2': []}
        }
        _LOGGER.info("All learned rates have been reset to zero")
        
        # Save state after reset
        await self._save_state()
    
    async def async_get_state(self, call: ServiceCall):
        """Service to get current controller state"""
        return {
            'zone1': {
                'target_setpoint': self.zones['zone1'].target_setpoint,
                'nominal_fan_speed': self.zones['zone1'].nominal_fan_speed,
            },
            'zone2': {
                'target_setpoint': self.zones['zone2'].target_setpoint,
                'nominal_fan_speed': self.zones['zone2'].nominal_fan_speed,
            },
            'enabled': self.enabled,
            'heating_rate': self.heating_rate,
            'cooling_rate': self.cooling_rate,
            'leakage_rate': self.leakage_rate,
        }
    
    def _ha_mode_to_internal(self, ha_mode: str) -> Mode:
        """Convert Home Assistant HVAC mode to internal mode"""
        mapping = {
            HVAC_MODE_HEAT: 'heat',
            HVAC_MODE_COOL: 'cool',
            HVAC_MODE_DRY: 'dry',
            HVAC_MODE_FAN_ONLY: 'fan_only',
            HVAC_MODE_OFF: 'off',
        }
        return mapping.get(ha_mode, 'off')

    def _internal_mode_to_ha(self, mode: Mode) -> str:
        """Convert internal mode to Home Assistant HVAC mode"""
        mapping = {
            'heat': HVAC_MODE_HEAT,
            'cool': HVAC_MODE_COOL,
            'dry': HVAC_MODE_DRY,
            'fan_only': HVAC_MODE_FAN_ONLY,
            'off': HVAC_MODE_OFF,
        }
        return mapping.get(mode, HVAC_MODE_OFF)
    
    async def _get_climate_temperature(self, entity_id: str) -> Optional[float]:
        """Get current temperature from climate entity"""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in [STATE_UNKNOWN, STATE_UNAVAILABLE]:
            return None
        
        temp = state.attributes.get(ATTR_CURRENT_TEMPERATURE)
        return float(temp) if temp is not None else None
    
    async def _get_climate_mode(self, entity_id: str) -> str:
        """Get current HVAC mode from climate entity"""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in [STATE_UNKNOWN, STATE_UNAVAILABLE]:
            return HVAC_MODE_OFF
        return state.state
    
    async def _set_climate_temperature(self, entity_id: str, temperature: float):
        """Set target temperature for climate entity"""
        await self.hass.services.async_call(
            'climate',
            'set_temperature',
            {
                'entity_id': entity_id,
                'temperature': temperature,
            },
            blocking=False
        )
    
    async def _set_climate_mode(self, entity_id: str, mode: str = None, fan_speed: str = None):
        """Set HVAC mode and/or fan speed for climate entity"""
        _LOGGER.debug(f"Setting {entity_id}: mode={mode}, fan_speed={fan_speed}")
        
        # Check current state before making changes
        state = self.hass.states.get(entity_id)
        if state:
            current_fan_mode = state.attributes.get('fan_mode')
            _LOGGER.debug(f"{entity_id} current fan_mode: {current_fan_mode}")
        
        # Set HVAC mode if specified (blocking to ensure it completes before fan mode change)
        if mode is not None:
            await self.hass.services.async_call(
                'climate',
                'set_hvac_mode',
                {
                    'entity_id': entity_id,
                    'hvac_mode': mode,
                },
                blocking=True
            )
            # Small delay to allow mode change to fully propagate
            await asyncio.sleep(0.2)
        
        # Set fan mode if specified
        # The climate entity expects: 'low', 'medium', 'high', 'quiet' (all lowercase)
        if fan_speed is not None:
            _LOGGER.info(f"Calling climate.set_fan_mode for {entity_id} with fan_mode='{fan_speed}'")
            try:
                await self.hass.services.async_call(
                    'climate',
                    'set_fan_mode',
                    {
                        'entity_id': entity_id,
                        'fan_mode': fan_speed,
                    },
                    blocking=True  # Wait for the call to complete
                )
                
                # Check if it actually changed (give more time for state to update)
                await asyncio.sleep(1.0)  # Wait for state to propagate
                state_after = self.hass.states.get(entity_id)
                if state_after:
                    new_fan_mode = state_after.attributes.get('fan_mode')
                    _LOGGER.info(f"{entity_id} fan_mode after call: {new_fan_mode} (requested: {fan_speed})")
                    if new_fan_mode != fan_speed:
                        _LOGGER.warning(f"{entity_id} fan mode did not change as expected! Current mode: {state_after.state}")
            except Exception as e:
                _LOGGER.error(f"Failed to set fan mode for {entity_id}: {e}", exc_info=True)
    
    def calculate_optimal_fan_speed(self, zone: str, mode: Mode,
                                    temp_error: float, is_lead: bool, other_zone_mode: Mode = 'off') -> FanSpeed:
        """
        Calculate optimal fan speed based on mode and conditions

        Args:
            zone: Zone identifier
            mode: Current HVAC mode
            temp_error: Absolute temperature error from target
            is_lead: Whether this zone will reach target first
            other_zone_mode: The other zone's current mode (to detect leakage scenarios)

        Returns:
            Optimal fan speed
        """
        nominal_speed = self.zones[zone].nominal_fan_speed
        nominal_level = FAN_SPEED_LEVELS[nominal_speed]

        # Fan only mode - behavior depends on whether other zone is actively conditioning
        if mode == 'fan_only':
            # If other zone is actively heating/cooling, use quiet to minimize leakage impact
            if other_zone_mode in ['heat', 'cool']:
                _LOGGER.debug(f"{zone}: fan_only with other zone {other_zone_mode} - using quiet to minimize leakage")
                return 'quiet'
            # If other zone is also fan_only/off, no leakage concern - use nominal for circulation
            else:
                _LOGGER.debug(f"{zone}: fan_only with other zone {other_zone_mode} - using nominal for circulation")
                return nominal_speed
        
        # Off mode - quiet fan
        if mode == 'off':
            return 'quiet'
        
        # Active heating/cooling - modulate around nominal speed
        if mode in ['heat', 'cool']:
            # Very large error (>5°F) - always boost to high for maximum performance
            if temp_error > 5.0:
                _LOGGER.debug(f"{zone}: Very large error ({temp_error:.1f}°F) - boosting to high")
                return 'high'
            
            # Large error (>3°F) - boost aggressively (can go from quiet -> high)
            elif temp_error > 3.0:
                # Boost 2 levels above nominal, capped at high
                boost_level = min(nominal_level + 2, 3)
                speed_options = ['quiet', 'low', 'medium', 'high']
                speed = speed_options[boost_level]
                if speed != nominal_speed:
                    _LOGGER.debug(f"{zone}: Large error ({temp_error:.1f}°F) - boosting from {nominal_speed} to {speed}")
                return speed
            
            # Medium error (1.5-3°F) - boost one level above nominal
            elif temp_error > 1.5:
                boost_level = min(nominal_level + 1, 3)
                speed_options = ['quiet', 'low', 'medium', 'high']
                speed = speed_options[boost_level]
                if speed != nominal_speed:
                    _LOGGER.debug(f"{zone}: Medium error ({temp_error:.1f}°F) - boosting from {nominal_speed} to {speed}")
                return speed
            
            # Small error (<1.5°F) - modulate around nominal to avoid overshoot
            else:
                # Lead zone should reduce more aggressively to prevent overshoot
                if is_lead:
                    # Very close to target - drop to quiet
                    if temp_error < 0.5:
                        _LOGGER.debug(f"{zone}: Very small error ({temp_error:.1f}°F), lead zone - dropping to quiet")
                        return 'quiet'
                    # Drop 2 levels below nominal to slow approach
                    reduce_level = max(nominal_level - 2, 0)
                    speed_options = ['quiet', 'low', 'medium', 'high']
                    speed = speed_options[reduce_level]
                    _LOGGER.debug(f"{zone}: Small error ({temp_error:.1f}°F), lead zone - reducing from {nominal_speed} to {speed}")
                    return speed
                else:
                    # Lag zone can stay at or slightly below nominal to catch up
                    reduce_level = max(nominal_level - 1, 0)
                    speed_options = ['quiet', 'low', 'medium', 'high']
                    speed = speed_options[reduce_level]
                    if speed != nominal_speed:
                        _LOGGER.debug(f"{zone}: Small error ({temp_error:.1f}°F), lag zone - reducing from {nominal_speed} to {speed}")
                    return speed
        
        return nominal_speed
    
    def determine_desired_mode(self, zone: str, current_temp: float, deadband_override: float = None) -> Mode:
        """Determine what mode is needed based on current temp, user-selected hvac_mode, and target setpoints"""
        deadband = deadband_override if deadband_override is not None else self.deadband
        zone_state = self.zones[zone]
        hvac_mode = zone_state.hvac_mode

        # If OFF mode selected, return off
        if hvac_mode == HVAC_MODE_OFF:
            return 'off'

        # For heat_cool (auto) mode, use temperature range
        if hvac_mode == HVAC_MODE_HEAT_COOL:
            temp_low = zone_state.target_temp_low
            temp_high = zone_state.target_temp_high

            # Too cold - need heating
            if current_temp < temp_low - deadband:
                return 'heat'
            # Too hot - need cooling
            elif current_temp > temp_high + deadband:
                return 'cool'
            # Within range - just fan
            else:
                return 'fan_only'

        # For heat-only mode
        elif hvac_mode == HVAC_MODE_HEAT:
            target = zone_state.target_setpoint
            error = target - current_temp

            if error > deadband:
                return 'heat'
            else:
                return 'fan_only'

        # For cool-only mode
        elif hvac_mode == HVAC_MODE_COOL:
            target = zone_state.target_setpoint
            error = target - current_temp

            if error < -deadband:
                return 'cool'
            else:
                return 'fan_only'

        # For dry (dehumidification) mode
        elif hvac_mode == HVAC_MODE_DRY:
            # Dry mode runs to dehumidify regardless of temperature
            # Only switch to fan_only if temperature gets too far off target
            target = zone_state.target_setpoint
            error = abs(target - current_temp)

            # If temperature is within reasonable range, use dry mode
            if error < 5.0:  # Within 5°F of target
                return 'dry'
            else:
                # Temperature too far off, switch to fan_only to avoid over-cooling
                return 'fan_only'

        # Default to fan_only
        return 'fan_only'

    def count_recent_starts(self) -> int:
        """Count compressor starts in the last hour"""
        now = time.time()
        cutoff = now - 3600  # 60 minutes ago
        return sum(1 for t in self.compressor_start_times if t > cutoff)

    def get_dynamic_deadband(self) -> float:
        """Calculate deadband based on recent compressor starts to prevent short cycling"""
        recent_starts = self.count_recent_starts()

        if recent_starts >= self.max_starts_per_hour:
            # At or over limit - expand deadband to prevent another start
            expansion_factor = 3.0
            expanded_deadband = self.deadband * expansion_factor
            _LOGGER.warning(
                f"Compressor start limit reached ({recent_starts} starts in last hour, "
                f"limit={self.max_starts_per_hour}). Expanding deadband from "
                f"{self.deadband:.1f}°F to {expanded_deadband:.1f}°F to prevent short cycling."
            )
            return expanded_deadband

        return self.deadband

    def is_compressor_running(self, mode1: Mode, mode2: Mode) -> bool:
        """Check if compressor is running (either zone in heat/cool/dry)"""
        return mode1 in ['heat', 'cool', 'dry'] or mode2 in ['heat', 'cool', 'dry']

    def enforce_minimum_runtime(self, mode1: Mode, mode2: Mode) -> tuple[Mode, Mode]:
        """
        Enforce 3-minute rule: minimum runtime and minimum off-time

        Returns modified modes that comply with timing constraints
        """
        now = time.time()

        # Check if desired modes would start the compressor
        would_start = self.is_compressor_running(mode1, mode2) and not self.compressor_running

        # Check if desired modes would stop the compressor
        would_stop = not self.is_compressor_running(mode1, mode2) and self.compressor_running

        # Minimum off-time: prevent starting if we haven't been off long enough
        if would_start and self.compressor_last_stop_time is not None:
            off_time = now - self.compressor_last_stop_time
            if off_time < self.min_compressor_off_time:
                remaining = self.min_compressor_off_time - off_time
                _LOGGER.warning(
                    f"MINIMUM OFF-TIME: Preventing compressor start. "
                    f"Off for {off_time:.0f}s, need {self.min_compressor_off_time}s. "
                    f"Waiting {remaining:.0f}s more."
                )
                # Keep both zones in fan_only to prevent start
                return 'fan_only', 'fan_only'

        # Minimum runtime: prevent stopping if we haven't run long enough
        if would_stop and self.compressor_last_start_time is not None:
            runtime = now - self.compressor_last_start_time
            if runtime < self.min_compressor_runtime:
                remaining = self.min_compressor_runtime - runtime
                _LOGGER.warning(
                    f"MINIMUM RUNTIME: Preventing compressor stop. "
                    f"Running for {runtime:.0f}s, need {self.min_compressor_runtime}s. "
                    f"Continuing for {remaining:.0f}s more."
                )
                # Keep compressor running by returning the previous modes
                # that were keeping it in heat/cool
                prev_mode1 = self.zones['zone1'].last_mode
                prev_mode2 = self.zones['zone2'].last_mode
                _LOGGER.debug(f"Overriding to previous modes: Zone1={prev_mode1}, Zone2={prev_mode2}")
                return prev_mode1, prev_mode2

        # No timing constraints violated
        return mode1, mode2

    def modes_conflict(self, mode1: Mode, mode2: Mode) -> bool:
        """Check if two modes conflict"""
        # Heat and cool conflict
        if (mode1 == 'heat' and mode2 == 'cool') or (mode1 == 'cool' and mode2 == 'heat'):
            return True
        # Heat and dry conflict (dry typically involves cooling)
        if (mode1 == 'heat' and mode2 == 'dry') or (mode1 == 'dry' and mode2 == 'heat'):
            return True
        # Cool and dry don't conflict (both cool)
        return False
    
    def update_temperature_history(self, zone: str, temp: float, mode: Mode):
        """Update history and calculate rates of change"""
        state = self.zones[zone]
        state.temperature_history.append(temp)
        state.mode_history.append(mode)
        
        if len(state.temperature_history) < 2:
            return
        
        temp_change = state.temperature_history[-1] - state.temperature_history[-2]
        prev_mode = state.mode_history[-2] if len(state.mode_history) >= 2 else mode
        
        other_zone = 'zone2' if zone == 'zone1' else 'zone1'
        other_mode = self.zones[other_zone].last_mode
        
        _LOGGER.debug(f"{zone}: temp_change={temp_change:.3f}°F, prev_mode={prev_mode}, other_mode={other_mode}")
        
        # Active heating/cooling rate
        if prev_mode == 'heat' and temp_change > 0:
            self.rate_samples['heating'][zone].append(temp_change)
            _LOGGER.debug(f"{zone}: Recording heating sample: {temp_change:.3f}°F")
            self._update_rate(zone, 'heating')
        elif prev_mode == 'cool' and temp_change < 0:
            self.rate_samples['cooling'][zone].append(abs(temp_change))
            _LOGGER.debug(f"{zone}: Recording cooling sample: {abs(temp_change):.3f}°F")
            self._update_rate(zone, 'cooling')
        
        # Leakage rate
        elif prev_mode == 'fan_only' and other_mode in ['heat', 'cool']:
            if abs(temp_change) > 0.05:
                self.rate_samples['leakage'][zone].append(abs(temp_change))
                _LOGGER.debug(f"{zone}: Recording leakage sample: {abs(temp_change):.3f}°F (other zone in {other_mode})")
                self._update_leakage_rate(zone)
    
    def _update_rate(self, zone: str, rate_type: str):
        """Update heating or cooling rate using exponential moving average"""
        samples = self.rate_samples[rate_type][zone]
        if len(samples) >= 3:
            recent = samples[-5:]
            avg_rate = sum(recent) / len(recent)
            
            # Convert to per-minute rate (samples are per update_interval)
            avg_rate = avg_rate * (60.0 / self.update_interval)
            
            old_rate = self.heating_rate[zone] if rate_type == 'heating' else self.cooling_rate[zone]
            
            if rate_type == 'heating':
                if self.heating_rate[zone] == 0:
                    self.heating_rate[zone] = avg_rate
                    _LOGGER.info(f"{zone}: Initial heating rate learned: {avg_rate:.3f}°F/min")
                else:
                    self.heating_rate[zone] = 0.7 * self.heating_rate[zone] + 0.3 * avg_rate
                    _LOGGER.debug(f"{zone}: Heating rate updated: {old_rate:.3f} -> {self.heating_rate[zone]:.3f}°F/min")
            elif rate_type == 'cooling':
                if self.cooling_rate[zone] == 0:
                    self.cooling_rate[zone] = avg_rate
                    _LOGGER.info(f"{zone}: Initial cooling rate learned: {avg_rate:.3f}°F/min")
                else:
                    self.cooling_rate[zone] = 0.7 * self.cooling_rate[zone] + 0.3 * avg_rate
                    _LOGGER.debug(f"{zone}: Cooling rate updated: {old_rate:.3f} -> {self.cooling_rate[zone]:.3f}°F/min")
    
    def _update_leakage_rate(self, zone: str):
        """Update leakage rate"""
        samples = self.rate_samples['leakage'][zone]
        if len(samples) >= 2:
            recent = samples[-3:]
            avg_rate = sum(recent) / len(recent)
            
            # Convert to per-minute rate
            avg_rate = avg_rate * (60.0 / self.update_interval)
            
            old_rate = self.leakage_rate[zone]
            
            if self.leakage_rate[zone] == 0:
                self.leakage_rate[zone] = avg_rate
                _LOGGER.info(f"{zone}: Initial leakage rate learned: {avg_rate:.3f}°F/min")
            else:
                self.leakage_rate[zone] = 0.7 * self.leakage_rate[zone] + 0.3 * avg_rate
                _LOGGER.debug(f"{zone}: Leakage rate updated: {old_rate:.3f} -> {self.leakage_rate[zone]:.3f}°F/min")
    
    def calculate_time_to_target(self, zone: str, current_temp: float,
                                 target_temp: float, mode: Mode) -> float:
        """Estimate time to reach target temperature in minutes"""
        error = abs(target_temp - current_temp)
        
        if mode == 'heat':
            rate = self.heating_rate[zone]
        elif mode == 'cool':
            rate = self.cooling_rate[zone]
        else:
            return float('inf')
        
        if rate <= 0.001:
            return float('inf')
        
        return error / rate
    
    def calculate_compensation_offset(self, lead_zone: str, lag_zone: str,
                                     time_diff: float, mode: Mode) -> float:
        """Calculate the setpoint offset to compensate for leakage"""
        if time_diff <= 0:
            return 0.0
        
        leakage = self.leakage_rate[lead_zone]
        
        if leakage < 0.01:
            leakage = 0.15  # Conservative default
        
        offset = leakage * time_diff
        offset = max(offset, self.min_offset)
        offset = min(offset, 4.0)
        
        return offset
    
    async def async_control_loop(self, now=None):
        """Main control loop called at fixed interval"""
        if not self.enabled:
            _LOGGER.debug("Control loop skipped - controller disabled")
            return
        
        self.iteration_count += 1
        _LOGGER.debug(f"=== Control Loop Iteration {self.iteration_count} ===")
        
        try:
            # Read current temperatures
            t1 = await self._get_climate_temperature(self.zones['zone1'].climate_entity)
            t2 = await self._get_climate_temperature(self.zones['zone2'].climate_entity)
            
            if t1 is None or t2 is None:
                _LOGGER.warning("Unable to read temperatures from climate entities")
                return
            
            _LOGGER.debug(f"Current temperatures: Zone1={t1}°F, Zone2={t2}°F")
            
            # Get current modes
            current_ha_mode1 = await self._get_climate_mode(self.zones['zone1'].climate_entity)
            current_ha_mode2 = await self._get_climate_mode(self.zones['zone2'].climate_entity)
            
            current_mode1 = self._ha_mode_to_internal(current_ha_mode1)
            current_mode2 = self._ha_mode_to_internal(current_ha_mode2)
            
            _LOGGER.debug(f"Current modes: Zone1={current_mode1}, Zone2={current_mode2}")
            
            # Get target setpoints
            target1 = self.zones['zone1'].target_setpoint
            target2 = self.zones['zone2'].target_setpoint
            
            _LOGGER.debug(f"Target setpoints: Zone1={target1}°F, Zone2={target2}°F")
            
            # Update histories
            self.update_temperature_history('zone1', t1, current_mode1)
            self.update_temperature_history('zone2', t2, current_mode2)

            # Get dynamic deadband for short-cycle prevention
            dynamic_deadband = self.get_dynamic_deadband()
            if dynamic_deadband != self.deadband:
                _LOGGER.debug(f"Using dynamic deadband: {dynamic_deadband:.1f}°F (normal: {self.deadband:.1f}°F)")

            # Determine desired modes using dynamic deadband and user-selected hvac_mode
            desired_mode1 = self.determine_desired_mode('zone1', t1, dynamic_deadband)
            desired_mode2 = self.determine_desired_mode('zone2', t2, dynamic_deadband)

            error1 = target1 - t1
            error2 = target2 - t2

            _LOGGER.debug(f"Temperature errors: Zone1={error1:.2f}°F, Zone2={error2:.2f}°F")
            _LOGGER.debug(f"Desired modes: Zone1={desired_mode1}, Zone2={desired_mode2}")
            
            # Initialize fan speeds to None
            fan_speed1 = None
            fan_speed2 = None
            
            # Handle mode conflicts
            if self.modes_conflict(desired_mode1, desired_mode2):
                _LOGGER.info(f"MODE CONFLICT DETECTED: Zone1 wants {desired_mode1}, Zone2 wants {desired_mode2}")
                error1_abs = abs(target1 - t1)
                error2_abs = abs(target2 - t2)
                
                if error1_abs > error2_abs + self.conflict_threshold:
                    mode1, mode2 = desired_mode1, 'fan_only'
                    internal_setpoint1, internal_setpoint2 = target1, target2
                    _LOGGER.info(f"CONFLICT RESOLUTION: Prioritizing Zone1 (error {error1_abs:.2f}°F > {error2_abs:.2f}°F + {self.conflict_threshold}°F)")
                elif error2_abs > error1_abs + self.conflict_threshold:
                    mode1, mode2 = 'fan_only', desired_mode2
                    internal_setpoint1, internal_setpoint2 = target1, target2
                    _LOGGER.info(f"CONFLICT RESOLUTION: Prioritizing Zone2 (error {error2_abs:.2f}°F > {error1_abs:.2f}°F + {self.conflict_threshold}°F)")
                else:
                    mode1, mode2 = 'fan_only', 'fan_only'
                    internal_setpoint1, internal_setpoint2 = target1, target2
                    _LOGGER.info(f"CONFLICT RESOLUTION: Both zones to fan_only (errors too close: {error1_abs:.2f}°F vs {error2_abs:.2f}°F)")
            
            # Both need same conditioning mode
            elif desired_mode1 == desired_mode2 and desired_mode1 in ['heat', 'cool']:
                mode1 = desired_mode1
                mode2 = desired_mode2
                
                time1 = self.calculate_time_to_target('zone1', t1, target1, mode1)
                time2 = self.calculate_time_to_target('zone2', t2, target2, mode2)
                
                _LOGGER.debug(f"Time to target: Zone1={time1:.1f}min, Zone2={time2:.1f}min")
                
                if time1 < time2 and time1 != float('inf'):
                    time_diff = time2 - time1
                    offset = self.calculate_compensation_offset('zone1', 'zone2', time_diff, mode1)
                    
                    if mode1 == 'heat':
                        internal_setpoint1 = target1 - offset
                    else:
                        internal_setpoint1 = target1 + offset
                    internal_setpoint2 = target2
                    
                    _LOGGER.info(f"LEAKAGE COMPENSATION: Zone1 is lead by {time_diff:.1f}min, applying offset of {offset:.2f}°F")
                    _LOGGER.debug(f"Zone1 internal setpoint adjusted: {target1}°F -> {internal_setpoint1:.2f}°F")
                    
                elif time2 < time1 and time2 != float('inf'):
                    time_diff = time1 - time2
                    offset = self.calculate_compensation_offset('zone2', 'zone1', time_diff, mode2)
                    
                    internal_setpoint1 = target1
                    if mode2 == 'heat':
                        internal_setpoint2 = target2 - offset
                    else:
                        internal_setpoint2 = target2 + offset
                    
                    _LOGGER.info(f"LEAKAGE COMPENSATION: Zone2 is lead by {time_diff:.1f}min, applying offset of {offset:.2f}°F")
                    _LOGGER.debug(f"Zone2 internal setpoint adjusted: {target2}°F -> {internal_setpoint2:.2f}°F")
                else:
                    internal_setpoint1 = target1
                    internal_setpoint2 = target2
                    _LOGGER.debug("No leakage compensation needed (times equal or unknown)")
            
            else:
                mode1 = desired_mode1
                mode2 = desired_mode2
                internal_setpoint1 = target1
                internal_setpoint2 = target2
                _LOGGER.debug(f"No compensation needed - modes: {mode1}, {mode2}")

            # Enforce 3-minute rule: minimum runtime and off-time
            mode1, mode2 = self.enforce_minimum_runtime(mode1, mode2)

            # Determine which zone is lead (will reach target first)
            is_lead_zone1 = False
            is_lead_zone2 = False

            if mode1 in ['heat', 'cool'] and mode2 in ['heat', 'cool']:
                # Both zones active - determine lead based on time to target
                time1 = self.calculate_time_to_target('zone1', t1, target1, mode1)
                time2 = self.calculate_time_to_target('zone2', t2, target2, mode2)

                if time1 < time2 and time1 != float('inf'):
                    is_lead_zone1 = True
                    _LOGGER.debug("Zone1 is lead zone")
                elif time2 < time1 and time2 != float('inf'):
                    is_lead_zone2 = True
                    _LOGGER.debug("Zone2 is lead zone")
            elif mode1 in ['heat', 'cool'] and mode2 not in ['heat', 'cool']:
                # Only zone1 is actively conditioning
                is_lead_zone1 = True
                _LOGGER.debug("Zone1 is lead zone (only active zone)")
            elif mode2 in ['heat', 'cool'] and mode1 not in ['heat', 'cool']:
                # Only zone2 is actively conditioning
                is_lead_zone2 = True
                _LOGGER.debug("Zone2 is lead zone (only active zone)")

            # Calculate optimal fan speeds based on mode, error, lead/lag status, and other zone's mode
            error1_abs = abs(target1 - t1)
            error2_abs = abs(target2 - t2)

            fan_speed1 = self.calculate_optimal_fan_speed('zone1', mode1, error1_abs, is_lead_zone1, mode2)
            fan_speed2 = self.calculate_optimal_fan_speed('zone2', mode2, error2_abs, is_lead_zone2, mode1)

            _LOGGER.debug(f"Calculated fan speeds: Zone1={fan_speed1} (lead={is_lead_zone1}, error={error1_abs:.1f}°F, other_mode={mode2}), Zone2={fan_speed2} (lead={is_lead_zone2}, error={error2_abs:.1f}°F, other_mode={mode1})")

            # Apply control actions
            ha_mode1 = self._internal_mode_to_ha(mode1)
            ha_mode2 = self._internal_mode_to_ha(mode2)

            # Log if changes are being made
            mode_changed1 = current_ha_mode1 != ha_mode1
            mode_changed2 = current_ha_mode2 != ha_mode2

            if mode_changed1 or mode_changed2:
                _LOGGER.info(f"APPLYING MODE CHANGES: Zone1: {current_ha_mode1} -> {ha_mode1}, Zone2: {current_ha_mode2} -> {ha_mode2}")
            
            _LOGGER.info(f"SETTING CONTROLS: Zone1: mode={ha_mode1}, fan={fan_speed1}, setpoint={internal_setpoint1:.1f}°F | Zone2: mode={ha_mode2}, fan={fan_speed2}, setpoint={internal_setpoint2:.1f}°F")
            
            await self._set_climate_mode(self.zones['zone1'].climate_entity, ha_mode1, fan_speed1)
            await self._set_climate_mode(self.zones['zone2'].climate_entity, ha_mode2, fan_speed2)
            await self._set_climate_temperature(self.zones['zone1'].climate_entity, internal_setpoint1)
            await self._set_climate_temperature(self.zones['zone2'].climate_entity, internal_setpoint2)
            
            # Update state
            self.zones['zone1'].last_mode = mode1
            self.zones['zone2'].last_mode = mode2

            # Track compressor starts for short-cycle prevention
            new_compressor_state = self.is_compressor_running(mode1, mode2)
            if new_compressor_state and not self.compressor_running:
                # Compressor just started
                start_time = time.time()
                self.compressor_start_times.append(start_time)
                self.compressor_last_start_time = start_time
                recent_starts = self.count_recent_starts()
                _LOGGER.warning(
                    f"COMPRESSOR START detected. Total starts in last hour: {recent_starts}"
                )
            elif not new_compressor_state and self.compressor_running:
                # Compressor just stopped
                stop_time = time.time()
                self.compressor_last_stop_time = stop_time
                if self.compressor_last_start_time:
                    runtime = stop_time - self.compressor_last_start_time
                    _LOGGER.info(f"Compressor stopped after {runtime:.0f}s runtime")
                else:
                    _LOGGER.info("Compressor stopped")

            self.compressor_running = new_compressor_state

            # Log status summary every cycle
            _LOGGER.info(
                f"STATUS: Z1[{t1:.1f}°F->{internal_setpoint1:.1f}°F ({mode1})] Z2[{t2:.1f}°F->{internal_setpoint2:.1f}°F ({mode2})] | "
                f"Rates: H[{self.heating_rate['zone1']:.3f},{self.heating_rate['zone2']:.3f}] "
                f"C[{self.cooling_rate['zone1']:.3f},{self.cooling_rate['zone2']:.3f}] "
                f"L[{self.leakage_rate['zone1']:.3f},{self.leakage_rate['zone2']:.3f}]"
            )

            # Update climate entity states
            for entity in self.climate_entities.values():
                entity.update_state()

        except Exception as e:
            _LOGGER.error(f"Error in control loop: {e}", exc_info=True)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Dual Zone HVAC Controller component"""
    if DOMAIN not in config:
        return True
    
    controller = DualZoneHVACController(hass, config[DOMAIN])
    hass.data[DOMAIN] = controller
    
    return await controller.async_setup()


async def async_unload_entry(hass: HomeAssistant):
    """Unload the component"""
    controller = hass.data.get(DOMAIN)
    if controller:
        await controller.async_unload()
    return True

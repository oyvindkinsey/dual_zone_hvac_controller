# Dual Zone HVAC Controller

A Home Assistant custom component for managing two HVAC zones sharing a single condenser with intelligent refrigerant leakage compensation and compressor protection.

## Overview

This controller solves a common problem in dual-zone HVAC systems with branch boxes: the Electronic Expansion Valves (EEVs) maintain a minimal refrigerant flow to all zones for lubrication, even when a zone isn't calling for heating or cooling. If the "off" zone's air handler fan is running, this residual refrigerant still conditions the air passing through the coils. This "leakage" causes unintended temperature changes in zones that should be idle.

## Key Features

### Intelligent Leakage Compensation
- **Learns heating, cooling, and leakage rates** for each zone using exponential moving average
- **Predicts lead zone** - determines which zone will reach target temperature first
- **Prevents overshoot** - manages both zones to prevent the passive zone from drifting due to refrigerant leakage
- **Adapts in real-time** - continuously updates learned rates as system behavior changes

### Adaptive Fan Speed Control
- **Temperature-based modulation** - adjusts fan speed based on distance from target
  - >5°F error: HIGH speed (maximum performance)
  - >3°F error: +2 levels from nominal
  - >1.5°F error: +1 level from nominal
  - <1.5°F error: Reduced speed to prevent overshoot
- **Leakage minimization** - reduces fan speed in passive zones to minimize air flow over coils with residual refrigerant
- **Configurable nominal speed** per zone (quiet/low/medium/high)

### Compressor Protection
Three layers of protection prevent short cycling and extend equipment life:

1. **3-Minute Rule** (hard constraints)
   - Minimum runtime: 180 seconds before allowing stop
   - Minimum off-time: 180 seconds before allowing restart
   - Prevents rapid cycling regardless of temperature

2. **Start Counting** (long-term protection)
   - Limits starts to 3 per hour (configurable)
   - Dynamically expands deadband (0.5°F → 1.5°F) when limit reached
   - Prevents excessive cycling over longer periods

3. **State Persistence**
   - Tracks compressor start times across restarts
   - Maintains protection after Home Assistant restarts

### Climate Entity Integration
- **Standard Home Assistant thermostat cards** - no custom Lovelace resources needed
- **Voice assistant compatible** - works with Alexa, Google Home, etc.
- **Temperature control** - set target temperature for each zone
- **Fan speed control** - configure nominal fan speed per zone
- **Automatic mode management** - controller handles heat/cool/fan_only modes
- **Real-time status** - current temp, target temp, and operating mode displayed

### Monitoring & Diagnostics
- **Learned rates exposed as sensor entities**
  - `sensor.dual_zone_hvac_learned_rates` - all rates and compressor stats
  - Zone sensors include heating, cooling, and leakage rates as attributes
- **Comprehensive logging** with configurable debug levels
- **Compressor start tracking** - monitor starts per hour

## How It Works

### Refrigerant Leakage

In a dual-zone system with a branch box:
- The branch box contains Electronic Expansion Valves (EEVs) for each zone
- EEVs maintain minimal refrigerant flow to all zones for lubrication, even when "off"
- When one zone calls for heating/cooling, the condenser runs and refrigerant flows
- The "off" zone's EEV still allows some refrigerant through its coils
- If the "off" zone's air handler fan runs, air passing over its coils gets conditioned by this residual refrigerant
- This is **refrigerant leakage** - the passive zone drifts toward the active zone's conditioning temperature

### The Solution

The controller manages both zones simultaneously:

1. **Active (lead) zone** - needs conditioning to reach target
   - Uses higher fan speed to finish faster
   - Reduces total time the passive zone is exposed to leakage

2. **Passive (lag) zone** - not calling for conditioning
   - Uses lower fan speed to minimize air flow over coils
   - Reduces the impact of residual refrigerant

3. **When both zones satisfied**
   - Both switch to fan_only mode
   - Compressor stops (no refrigerant flow)
   - Fans run at nominal speed for circulation (no leakage concern)

### Control Loop (every 60 seconds)

1. Read current temperatures from climate entities
2. Update temperature history and learn rates
3. Calculate dynamic deadband (for short-cycle prevention)
4. Determine desired modes based on temperature errors
5. Resolve conflicts (if zones want opposing modes)
6. Calculate leakage compensation (if both need same mode)
7. Enforce 3-minute rule timing constraints
8. Calculate optimal fan speeds for each zone
9. Apply modes and fan speeds to climate entities
10. Track compressor state changes
11. Save state and update sensor entities

## Installation

### Option 1: HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Click the **three dots** in the top right
4. Select **Custom repositories**
5. Add repository URL: `https://github.com/oyvindkinsey/dual_zone_hvac_controller`
6. Category: **Integration**
7. Click **Add**
8. Find "Dual Zone HVAC Controller" and click **Install**
9. Restart Home Assistant

### Option 2: Manual Installation

1. Download this repository
2. Copy the `custom_components/dual_zone_hvac` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

### Configuration

Add to `configuration.yaml`:

```yaml
dual_zone_hvac:
  zone1:
    climate_entity: climate.heat_pump_1_upstairs_heat_pump
    target_temperature: 68
  zone2:
    climate_entity: climate.heat_pump_2_downstairs_heat_pump
    target_temperature: 68
  settings:
    deadband: 0.5                    # Temperature tolerance (°F)
    min_offset: 0.3                  # Minimum leakage compensation (°F)
    conflict_threshold: 2.0          # Error difference for conflict resolution (°F)
    update_interval: 60              # Control loop frequency (seconds)
    max_starts_per_hour: 3           # Compressor start limit
    min_compressor_runtime: 180      # Minimum runtime (seconds)
    min_compressor_off_time: 180     # Minimum off-time (seconds)
```

### Restart Home Assistant

Full restart required (not just reload).

## Climate Entities

After installation, the integration creates two climate entities that you can control through Home Assistant's standard thermostat card:

- `climate.dual_zone_hvac_zone1` - Control for Zone 1
- `climate.dual_zone_hvac_zone2` - Control for Zone 2

Each climate entity exposes:
- **Current temperature** - from the underlying physical climate entity
- **Target temperature** - set your desired temperature
- **HVAC mode** - shows current mode (heat/cool/fan_only/off) managed automatically by the controller
- **Fan mode** - set the nominal fan speed (quiet/low/medium/high) for this zone
- **Learned rates** - heating, cooling, and leakage rates shown as attributes

### Adding to Dashboard

Use Home Assistant's standard thermostat card:

```yaml
type: thermostat
entity: climate.dual_zone_hvac_zone1
name: Upstairs Zone
```

Or use a horizontal stack to show both zones:

```yaml
type: horizontal-stack
cards:
  - type: thermostat
    entity: climate.dual_zone_hvac_zone1
    name: Upstairs
  - type: thermostat
    entity: climate.dual_zone_hvac_zone2
    name: Downstairs
```

**Note:** The HVAC mode is managed automatically by the controller and cannot be changed directly. The controller determines the optimal mode based on both zones' temperatures and requirements.

## Services

**Note:** You can control the zones directly through the climate entities (`climate.dual_zone_hvac_zone1`, `climate.dual_zone_hvac_zone2`) using standard Home Assistant climate services. The services below are provided for backwards compatibility and advanced automation scenarios.

### `dual_zone_hvac.set_target_temperature`
Set target temperature for a zone (alternative to using `climate.set_temperature` on the climate entity).

```yaml
service: dual_zone_hvac.set_target_temperature
data:
  zone: zone1
  temperature: 70
```

### `dual_zone_hvac.set_nominal_fan_speed`
Set nominal fan speed for a zone (alternative to using `climate.set_fan_mode` on the climate entity).

```yaml
service: dual_zone_hvac.set_nominal_fan_speed
data:
  zone: zone1
  fan_speed: medium  # quiet, low, medium, high
```

### `dual_zone_hvac.set_enable`
Enable or disable the controller.

```yaml
service: dual_zone_hvac.set_enable
data:
  enabled: true
```

### `dual_zone_hvac.reset_learning`
Reset all learned rates to zero.

```yaml
service: dual_zone_hvac.reset_learning
```

## Sensor Entities

### `sensor.dual_zone_hvac_learned_rates`
Shows learning status and all learned rates.

**State:** `active` or `learning`

**Attributes:**
- `zone1_heating_rate` - °F/min
- `zone1_cooling_rate` - °F/min
- `zone1_leakage_rate` - °F/min
- `zone2_heating_rate` - °F/min
- `zone2_cooling_rate` - °F/min
- `zone2_leakage_rate` - °F/min
- `compressor_starts_last_hour` - count

### `sensor.dual_zone_hvac_zone1_target`
Zone 1 target temperature with learned rates.

### `sensor.dual_zone_hvac_zone2_target`
Zone 2 target temperature with learned rates.

### `sensor.dual_zone_hvac_enabled`
Controller enabled state (`on`/`off`).

## Logging

### Enable Debug Logging

Add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.dual_zone_hvac: debug
```

### Log Messages

The controller logs detailed information about:
- Control loop iterations
- Temperature changes and learned rates
- Mode decisions and conflict resolution
- Leakage compensation calculations
- Fan speed calculations
- Compressor starts/stops and timing constraints
- Short-cycle prevention actions

## Customization

### Climate Entity Requirements

Your climate entities must support:
- `set_hvac_mode` service (heat, cool, fan_only, off)
- `set_fan_mode` service (quiet, low, medium, high)
- `current_temperature` attribute
- `fan_mode` attribute

## Troubleshooting

### Controller Not Working

1. Check logs: **Settings** → **System** → **Logs**
2. Look for "Dual Zone HVAC Controller initialized"
3. Verify climate entity names in configuration
4. Ensure both climate entities exist and are working

### Fan Modes Not Changing

1. Check if climate entities support `set_fan_mode` service
2. Verify fan mode names match (quiet, low, medium, high)
3. Check logs for "fan mode did not change as expected" warnings
4. Increase delays in `_set_climate_mode` if needed

### Rates Not Learning

1. System needs time to observe temperature changes
2. Requires 3+ samples to establish initial rates
3. Check logs for "Recording heating/cooling/leakage sample" messages
4. View `sensor.dual_zone_hvac_learned_rates` in Developer Tools

### Compressor Short Cycling

This is what the controller prevents! If you see:
- "COMPRESSOR START LIMIT REACHED" - deadband expansion is working
- "MINIMUM RUNTIME: Preventing compressor stop" - 3-minute rule is working
- "MINIMUM OFF-TIME: Preventing compressor start" - 3-minute rule is working

These are protective actions, not errors.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Credits

Developed with assistance from Claude (Anthropic).

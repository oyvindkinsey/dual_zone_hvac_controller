# Dual Zone HVAC Controller

Intelligent management for dual-zone HVAC systems with refrigerant leakage compensation and compressor protection.

## Features

✅ **Refrigerant Leakage Compensation**
- Learns heating, cooling, and leakage rates for each zone
- Predicts lead zone and prevents passive zone overshoot
- Manages EEV residual flow impact

✅ **Adaptive Fan Speed Control**
- Temperature-based modulation (quiet to high)
- Leakage minimization in passive zones
- Per-zone configurable nominal speeds

✅ **Triple-Layer Compressor Protection**
- 3-minute rule (minimum runtime/off-time)
- Start counting (max 3/hour with dynamic deadband)
- State persistence across restarts

✅ **Climate Entity Integration**
- Standard thermostat cards (no custom resources)
- Voice assistant compatible
- Real-time status and mode display

✅ **Monitoring & Diagnostics**
- Learned rates exposed as sensors
- Compressor start tracking
- Comprehensive debug logging

## Quick Start

1. Install via HACS
2. Add configuration to `configuration.yaml`
3. Restart Home Assistant
4. Add climate entities to dashboard using standard thermostat cards

See [README](https://github.com/oyvindkinsey/dual_zone_hvac_controller) for detailed installation and configuration.

## Requirements

- Two climate entities with `set_hvac_mode` and `set_fan_mode` support
- Fan modes: quiet, low, medium, high
- HVAC modes: heat, cool, fan_only, off

## Support

- [Documentation](https://github.com/oyvindkinsey/dual_zone_hvac_controller#readme)
- [Issues](https://github.com/oyvindkinsey/dual_zone_hvac_controller/issues)

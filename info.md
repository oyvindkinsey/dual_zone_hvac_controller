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

✅ **Custom Lovelace UI Card**
- Discrete temperature controls (66-72°F)
- Per-zone fan speed settings
- Real-time status and mode display

✅ **Monitoring & Diagnostics**
- Learned rates exposed as sensors
- Compressor start tracking
- Comprehensive debug logging

## Quick Start

1. Install via HACS
2. Add configuration to `configuration.yaml`
3. Add Lovelace resource: `/local/dual-zone-hvac-card.js`
4. Add UI card to dashboard
5. Restart Home Assistant

See [README](https://github.com/oyvindkinsey/dual_zone_hvac_controller) for detailed installation and configuration.

## Requirements

- Two climate entities with `set_hvac_mode` and `set_fan_mode` support
- Fan modes: quiet, low, medium, high
- HVAC modes: heat, cool, fan_only, off

## Support

- [Documentation](https://github.com/oyvindkinsey/dual_zone_hvac_controller#readme)
- [Issues](https://github.com/oyvindkinsey/dual_zone_hvac_controller/issues)

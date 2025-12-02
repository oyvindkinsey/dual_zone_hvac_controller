/**
 * Dual Zone HVAC Controller Card
 * 
 * Installation:
 * 1. Copy this entire file to: /config/www/dual-zone-hvac-card.js
 * 2. Add to your resources in Lovelace:
 *    Settings > Dashboards > Three dots menu > Resources > Add Resource
 *    URL: /local/dual-zone-hvac-card.js
 *    Type: JavaScript Module
 * 3. Add card to dashboard with:
 *    type: custom:dual-zone-hvac-card
 *    zone1_entity: climate.zone_1_thermostat
 *    zone2_entity: climate.zone_2_thermostat
 *    zone1_target: 68
 *    zone2_target: 68
 */

class DualZoneHVACCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._zone1Target = null;
    this._zone2Target = null;
    this._zone1MaxFan = null;
    this._zone2MaxFan = null;
    this._enabled = true;
    this._stateLoaded = false;
  }

  setConfig(config) {
    if (!config.zone1_entity || !config.zone2_entity) {
      throw new Error('You need to define zone1_entity and zone2_entity');
    }

    this._config = config;
    
    // Only use config defaults if no persisted state exists
    if (this._zone1Target === null) {
      this._zone1Target = config.zone1_target || 68;
    }
    if (this._zone2Target === null) {
      this._zone2Target = config.zone2_target || 68;
    }
    if (this._zone1MaxFan === null) {
      this._zone1MaxFan = config.zone1_max_fan || 'high';
    }
    if (this._zone2MaxFan === null) {
      this._zone2MaxFan = config.zone2_max_fan || 'high';
    }
  }

  set hass(hass) {
    this._hass = hass;
    
    if (!this._stateLoaded) {
      this._stateLoaded = true;
      // Load persisted state from backend sensors
      this._loadPersistedState();
    }
    
    this._updateCard();
  }

  async _loadPersistedState() {
    try {
      // Read current state from sensor entities
      const zone1Sensor = this._hass.states['sensor.dual_zone_hvac_zone1_target'];
      const zone2Sensor = this._hass.states['sensor.dual_zone_hvac_zone2_target'];
      const enabledSensor = this._hass.states['sensor.dual_zone_hvac_enabled'];
      
      if (zone1Sensor) {
        this._zone1Target = parseFloat(zone1Sensor.state);
        this._zone1MaxFan = zone1Sensor.attributes.nominal_fan_speed || 'medium';
        console.log(`Loaded Zone 1 state: ${this._zone1Target}°F, fan: ${this._zone1MaxFan}`);
      }
      
      if (zone2Sensor) {
        this._zone2Target = parseFloat(zone2Sensor.state);
        this._zone2MaxFan = zone2Sensor.attributes.nominal_fan_speed || 'medium';
        console.log(`Loaded Zone 2 state: ${this._zone2Target}°F, fan: ${this._zone2MaxFan}`);
      }
      
      if (enabledSensor) {
        this._enabled = enabledSensor.state === 'on';
        console.log(`Loaded enabled state: ${this._enabled}`);
      }
      
      // Update the card to reflect loaded state
      this._updateCard();
    } catch (e) {
      console.warn("Could not load persisted state:", e);
    }
  }

  _updateCard() {
    if (!this._hass || !this._config) return;

    const zone1 = this._hass.states[this._config.zone1_entity];
    const zone2 = this._hass.states[this._config.zone2_entity];

    if (!zone1 || !zone2) {
      this.shadowRoot.innerHTML = `
        <ha-card>
          <div style="padding: 16px; color: red;">
            Error: Could not find climate entities
          </div>
        </ha-card>
      `;
      return;
    }

    const zone1Temp = zone1.attributes.current_temperature || 0;
    const zone2Temp = zone2.attributes.current_temperature || 0;
    const zone1Mode = zone1.state || 'unknown';
    const zone2Mode = zone2.state || 'unknown';
    
    // Get zone names from config
    const zone1Name = this._config.zone1_name || 'Zone 1';
    const zone2Name = this._config.zone2_name || 'Zone 2';

    this.shadowRoot.innerHTML = `
      <style>
        ha-card {
          padding: 16px;
        }
        .header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 20px;
          padding-bottom: 12px;
          border-bottom: 2px solid var(--divider-color);
        }
        .header-title {
          font-size: 20px;
          font-weight: 500;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .icon {
          width: 24px;
          height: 24px;
          fill: var(--primary-color);
        }
        .controls {
          display: flex;
          gap: 8px;
        }
        .button {
          padding: 8px 16px;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-size: 14px;
          font-weight: 500;
          transition: all 0.2s;
        }
        .button:hover {
          opacity: 0.8;
          transform: translateY(-1px);
        }
        .button:active {
          transform: translateY(0);
        }
        .button-enable {
          background: var(--primary-color);
          color: white;
        }
        .button-disable {
          background: var(--disabled-color, #999);
          color: white;
        }
        .button-reset {
          background: var(--warning-color, #ff9800);
          color: white;
        }
        .button.active {
          box-shadow: 0 0 0 2px var(--primary-color);
        }
        .zone-section {
          margin: 20px 0;
          padding: 16px;
          background: var(--card-background-color);
          border-radius: 8px;
          border: 1px solid var(--divider-color);
        }
        .zone-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }
        .zone-title {
          font-size: 18px;
          font-weight: 500;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .mode-badge {
          padding: 4px 12px;
          border-radius: 12px;
          font-size: 12px;
          font-weight: 600;
          text-transform: uppercase;
        }
        .mode-heat { background: #ff6b6b; color: white; }
        .mode-cool { background: #4dabf7; color: white; }
        .mode-fan_only { background: #51cf66; color: white; }
        .mode-off { background: #868e96; color: white; }
        .temp-display {
          display: flex;
          align-items: baseline;
          gap: 8px;
          margin: 12px 0;
        }
        .current-temp {
          font-size: 36px;
          font-weight: 300;
        }
        .target-temp {
          font-size: 18px;
          color: var(--secondary-text-color);
        }
        .quick-temps {
          display: flex;
          gap: 8px;
          margin-top: 12px;
          flex-wrap: wrap;
        }
        .temp-button {
          padding: 6px 12px;
          border: 1px solid var(--divider-color);
          border-radius: 4px;
          background: var(--card-background-color);
          cursor: pointer;
          font-size: 13px;
          transition: all 0.2s;
        }
        .temp-button:hover {
          background: var(--primary-color);
          color: white;
          border-color: var(--primary-color);
        }
        .temp-button.active {
          background: var(--primary-color);
          color: white;
          border-color: var(--primary-color);
        }
        .fan-control {
          margin-top: 12px;
          padding-top: 12px;
          border-top: 1px solid var(--divider-color);
        }
        .fan-label {
          font-size: 14px;
          margin-bottom: 8px;
          color: var(--secondary-text-color);
        }
        .fan-buttons {
          display: flex;
          gap: 8px;
        }
        .fan-button {
          flex: 1;
          padding: 8px;
          border: 1px solid var(--divider-color);
          border-radius: 4px;
          background: var(--card-background-color);
          cursor: pointer;
          font-size: 12px;
          transition: all 0.2s;
          text-transform: uppercase;
          font-weight: 500;
        }
        .fan-button:hover {
          background: var(--primary-color);
          color: white;
          border-color: var(--primary-color);
        }
        .fan-button.active {
          background: var(--primary-color);
          color: white;
          border-color: var(--primary-color);
        }
        .status-footer {
          margin-top: 16px;
          padding-top: 12px;
          border-top: 1px solid var(--divider-color);
          font-size: 12px;
          color: var(--secondary-text-color);
          text-align: center;
        }
      </style>

      <ha-card>
        <div class="header">
          <div class="header-title">
            <svg class="icon" viewBox="0 0 24 24">
              <path d="M12,2A10,10 0 0,1 22,12A10,10 0 0,1 12,22A10,10 0 0,1 2,12A10,10 0 0,1 12,2M12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20A8,8 0 0,0 20,12A8,8 0 0,0 12,4M14.5,9A1.5,1.5 0 0,1 16,10.5V14.5A1.5,1.5 0 0,1 14.5,16H9.5A1.5,1.5 0 0,1 8,14.5V10.5A1.5,1.5 0 0,1 9.5,9H14.5M14.5,10H9.5V14.5H14.5V10Z"/>
            </svg>
            Dual Zone HVAC Controller
          </div>
          <div class="controls">
            ${this._enabled ? `
              <button class="button button-disable">
                Disable
              </button>
            ` : `
              <button class="button button-enable">
                Enable
              </button>
            `}
            <button class="button button-reset">
              Reset
            </button>
          </div>
        </div>

        <!-- Zone 1 -->
        <div class="zone-section">
          <div class="zone-header">
            <div class="zone-title">
              🏠 ${zone1Name}
            </div>
            <div class="mode-badge mode-${zone1Mode}">${zone1Mode}</div>
          </div>
          
          <div class="temp-display">
            <div class="current-temp">${zone1Temp.toFixed(1)}°F</div>
            <div class="target-temp">→ ${this._zone1Target.toFixed(1)}°F</div>
          </div>

          <div class="quick-temps">
            ${[64, 64.5, 65, 65.5, 66, 66.5, 67, 67.5, 68, 68.5, 69, 69.5, 70, 70.5, 71, 71.5, 72, 72.5, 73].map(temp => `
              <button class="temp-button ${Math.abs(this._zone1Target - temp) < 0.1 ? 'active' : ''}"
                      data-zone="1" data-temp="${temp}">
                ${temp % 1 === 0 ? temp + '°' : temp.toFixed(1) + '°'}
              </button>
            `).join('')}
          </div>

          <div class="fan-control">
            <div class="fan-label">Nominal Fan Speed</div>
            <div class="fan-buttons">
              ${['quiet', 'low', 'medium', 'high'].map(speed => `
                <button class="fan-button ${this._zone1MaxFan === speed ? 'active' : ''}" 
                        data-zone="1" data-fan="${speed}">
                  ${speed}
                </button>
              `).join('')}
            </div>
          </div>
        </div>

        <!-- Zone 2 -->
        <div class="zone-section">
          <div class="zone-header">
            <div class="zone-title">
              🏠 ${zone2Name}
            </div>
            <div class="mode-badge mode-${zone2Mode}">${zone2Mode}</div>
          </div>
          
          <div class="temp-display">
            <div class="current-temp">${zone2Temp.toFixed(1)}°F</div>
            <div class="target-temp">→ ${this._zone2Target.toFixed(1)}°F</div>
          </div>

          <div class="quick-temps">
            ${[64, 64.5, 65, 65.5, 66, 66.5, 67, 67.5, 68, 68.5, 69, 69.5, 70, 70.5, 71, 71.5, 72, 72.5, 73].map(temp => `
              <button class="temp-button ${Math.abs(this._zone2Target - temp) < 0.1 ? 'active' : ''}"
                      data-zone="2" data-temp="${temp}">
                ${temp % 1 === 0 ? temp + '°' : temp.toFixed(1) + '°'}
              </button>
            `).join('')}
          </div>

          <div class="fan-control">
            <div class="fan-label">Nominal Fan Speed</div>
            <div class="fan-buttons">
              ${['quiet', 'low', 'medium', 'high'].map(speed => `
                <button class="fan-button ${this._zone2MaxFan === speed ? 'active' : ''}" 
                        data-zone="2" data-fan="${speed}">
                  ${speed}
                </button>
              `).join('')}
            </div>
          </div>
        </div>

        <div class="status-footer">
          💡 Check Settings > System > Logs for detailed operation info
        </div>
      </ha-card>
    `;

    // Add event listeners
    this._attachEventListeners();
  }

  _attachEventListeners() {
    // Temperature buttons
    this.shadowRoot.querySelectorAll('.temp-button').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const zone = e.currentTarget.dataset.zone;
        const temp = parseFloat(e.currentTarget.dataset.temp);

        if (zone === '1') {
          this._zone1Target = temp;
          this._callService('set_target_temperature', {
            zone: 'zone1',
            temperature: temp
          });
        } else {
          this._zone2Target = temp;
          this._callService('set_target_temperature', {
            zone: 'zone2',
            temperature: temp
          });
        }

        this._updateCard();
      });
    });

    // Fan speed buttons
    this.shadowRoot.querySelectorAll('.fan-button').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const zone = e.currentTarget.dataset.zone;
        const fanSpeed = e.currentTarget.dataset.fan;

        if (zone === '1') {
          this._zone1MaxFan = fanSpeed;
          this._callService('set_nominal_fan_speed', {
            zone: 'zone1',
            fan_speed: fanSpeed
          });
        } else {
          this._zone2MaxFan = fanSpeed;
          this._callService('set_nominal_fan_speed', {
            zone: 'zone2',
            fan_speed: fanSpeed
          });
        }

        this._updateCard();
      });
    });

    // Control buttons
    const enableBtn = this.shadowRoot.querySelector('.button-enable');
    const disableBtn = this.shadowRoot.querySelector('.button-disable');
    const resetBtn = this.shadowRoot.querySelector('.button-reset');

    if (enableBtn) {
      enableBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._toggleEnable(true);
      });
    }

    if (disableBtn) {
      disableBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._toggleEnable(false);
      });
    }

    if (resetBtn) {
      resetBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this._resetLearning();
      });
    }
  }

  _toggleEnable(enabled) {
    this._enabled = enabled;
    this._callService('set_enable', { enabled });
    this._updateCard();
  }

  _resetLearning() {
    if (confirm('Reset all learned heating, cooling, and leakage rates?')) {
      this._callService('reset_learning', {});
    }
  }

  _callService(service, data) {
    if (!this._hass) return;
    
    this._hass.callService('dual_zone_hvac', service, data);
  }

  getCardSize() {
    return 8;
  }

  static getConfigElement() {
    return document.createElement('dual-zone-hvac-card-editor');
  }

  static getStubConfig() {
    return {
      zone1_entity: 'climate.zone_1_thermostat',
      zone2_entity: 'climate.zone_2_thermostat',
      zone1_name: 'Upstairs',
      zone2_name: 'Downstairs',
      zone1_target: 68,
      zone2_target: 68,
      zone1_max_fan: 'medium',
      zone2_max_fan: 'medium'
    };
  }
}

// Configuration Editor
class DualZoneHVACCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  _render() {
    if (!this._config) return;

    this.innerHTML = `
      <div style="padding: 16px;">
        <h3 style="margin-top: 0;">Zone 1 Configuration</h3>
        
        <div style="margin-bottom: 16px;">
          <label>Zone 1 Name:</label>
          <input type="text" id="zone1_name" value="${this._config.zone1_name || 'Zone 1'}" 
                 placeholder="e.g., Upstairs, Living Room"
                 style="width: 100%; padding: 8px; margin-top: 4px;">
        </div>
        
        <div style="margin-bottom: 16px;">
          <label>Zone 1 Entity:</label>
          <input type="text" id="zone1_entity" value="${this._config.zone1_entity || ''}" 
                 placeholder="climate.zone_1_thermostat"
                 style="width: 100%; padding: 8px; margin-top: 4px;">
        </div>
        
        <div style="margin-bottom: 16px;">
          <label>Zone 1 Initial Target (°F):</label>
          <input type="number" id="zone1_target" value="${this._config.zone1_target || 68}" 
                 min="60" max="85" step="0.5"
                 style="width: 100%; padding: 8px; margin-top: 4px;">
        </div>

        <div style="margin-bottom: 16px;">
          <label>Zone 1 Initial Fan Speed:</label>
          <select id="zone1_max_fan" style="width: 100%; padding: 8px; margin-top: 4px;">
            <option value="quiet" ${this._config.zone1_max_fan === 'quiet' ? 'selected' : ''}>Quiet</option>
            <option value="low" ${this._config.zone1_max_fan === 'low' ? 'selected' : ''}>Low</option>
            <option value="medium" ${(!this._config.zone1_max_fan || this._config.zone1_max_fan === 'medium') ? 'selected' : ''}>Medium</option>
            <option value="high" ${this._config.zone1_max_fan === 'high' ? 'selected' : ''}>High</option>
          </select>
        </div>

        <hr style="margin: 24px 0; border: none; border-top: 1px solid #ccc;">
        
        <h3>Zone 2 Configuration</h3>
        
        <div style="margin-bottom: 16px;">
          <label>Zone 2 Name:</label>
          <input type="text" id="zone2_name" value="${this._config.zone2_name || 'Zone 2'}" 
                 placeholder="e.g., Downstairs, Bedroom"
                 style="width: 100%; padding: 8px; margin-top: 4px;">
        </div>
        
        <div style="margin-bottom: 16px;">
          <label>Zone 2 Entity:</label>
          <input type="text" id="zone2_entity" value="${this._config.zone2_entity || ''}" 
                 placeholder="climate.zone_2_thermostat"
                 style="width: 100%; padding: 8px; margin-top: 4px;">
        </div>
        
        <div style="margin-bottom: 16px;">
          <label>Zone 2 Initial Target (°F):</label>
          <input type="number" id="zone2_target" value="${this._config.zone2_target || 68}" 
                 min="60" max="85" step="0.5"
                 style="width: 100%; padding: 8px; margin-top: 4px;">
        </div>

        <div style="margin-bottom: 16px;">
          <label>Zone 2 Initial Fan Speed:</label>
          <select id="zone2_max_fan" style="width: 100%; padding: 8px; margin-top: 4px;">
            <option value="quiet" ${this._config.zone2_max_fan === 'quiet' ? 'selected' : ''}>Quiet</option>
            <option value="low" ${this._config.zone2_max_fan === 'low' ? 'selected' : ''}>Low</option>
            <option value="medium" ${(!this._config.zone2_max_fan || this._config.zone2_max_fan === 'medium') ? 'selected' : ''}>Medium</option>
            <option value="high" ${this._config.zone2_max_fan === 'high' ? 'selected' : ''}>High</option>
          </select>
        </div>
      </div>
    `;

    ['zone1_name', 'zone1_entity', 'zone1_target', 'zone1_max_fan', 'zone2_name', 'zone2_entity', 'zone2_target', 'zone2_max_fan'].forEach(key => {
      const element = this.querySelector(`#${key}`);
      if (element) {
        element.addEventListener('change', (e) => {
          this._config = {
            ...this._config,
            [key]: key.includes('target') ? parseFloat(e.target.value) : e.target.value
          };
          this.dispatchEvent(new CustomEvent('config-changed', { detail: { config: this._config } }));
        });
      }
    });
  }

  set hass(hass) {
    this._hass = hass;
  }
}

customElements.define('dual-zone-hvac-card', DualZoneHVACCard);
customElements.define('dual-zone-hvac-card-editor', DualZoneHVACCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'dual-zone-hvac-card',
  name: 'Dual Zone HVAC Controller',
  description: 'Control dual zone HVAC system with leakage compensation'
});

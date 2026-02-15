class MyHOMEDiscoveryPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._gateways = [];
    this._loadingGateways = false;
    this._loadingActivation = false;
    this._loadingConfig = false;
    this._savingConfig = false;
    this._result = null;
    this._configDevices = null;
    this._candidateDrafts = {};
    this._error = "";
    this._notice = "";
    this._state = {
      gateway: "",
      discovery_by_activation: true,
      manual_platform: "light",
      manual_key: "",
      manual_name: "",
      manual_address: "",
      manual_sensor_class: "power",
      manual_dimmable: false,
      manual_heat: true,
      manual_cool: true,
      manual_fan: true,
      manual_standalone: true,
      manual_section_open: false,
    };
  }

  set hass(hass) {
    if (this.childElementCount > 0) {
      this._readGatewayState();
      this._readManualState();
    }
    this._hass = hass;
    if (!this._loadingGateways && this._gateways.length === 0) {
      this._loadGateways();
    }
    this._render();
  }

  _esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  _gatewayByMac(mac) {
    return this._gateways.find((gateway) => gateway.mac === mac);
  }

  _syncGatewayState(mac) {
    this._state.gateway = mac || "";
    this._state.discovery_by_activation = true;
    const selectedGateway = this._gatewayByMac(this._state.gateway);
    if (selectedGateway) {
      selectedGateway.discovery_by_activation = true;
    }
  }

  _readGatewayState() {
    const gateway = this.querySelector("#gateway");
    if (gateway) {
      this._state.gateway = gateway.value || this._state.gateway;
    }
  }

  _readManualState() {
    const root = this;
    const manualPlatform = root.querySelector("#manual_platform");
    if (manualPlatform) {
      this._state.manual_platform = manualPlatform.value || this._state.manual_platform;
    }
    const manualKey = root.querySelector("#manual_key");
    if (manualKey) {
      this._state.manual_key = manualKey.value || "";
    }
    const manualName = root.querySelector("#manual_name");
    if (manualName) {
      this._state.manual_name = manualName.value || "";
    }
    const manualAddress = root.querySelector("#manual_address");
    if (manualAddress) {
      this._state.manual_address = manualAddress.value || "";
    }
    const sensorClass = root.querySelector("#manual_sensor_class");
    if (sensorClass) {
      this._state.manual_sensor_class = sensorClass.value || "power";
    }
    const dimmable = root.querySelector("#manual_dimmable");
    if (dimmable) {
      this._state.manual_dimmable = !!dimmable.checked;
    }
    const heat = root.querySelector("#manual_heat");
    if (heat) {
      this._state.manual_heat = !!heat.checked;
    }
    const cool = root.querySelector("#manual_cool");
    if (cool) {
      this._state.manual_cool = !!cool.checked;
    }
    const fan = root.querySelector("#manual_fan");
    if (fan) {
      this._state.manual_fan = !!fan.checked;
    }
    const standalone = root.querySelector("#manual_standalone");
    if (standalone) {
      this._state.manual_standalone = !!standalone.checked;
    }
    const manualSection = root.querySelector("#manual_section");
    if (manualSection) {
      this._state.manual_section_open = !!manualSection.open;
    }
  }

  async _ensurePassiveDiscoveryEnabled() {
    if (!this._hass || !this._state.gateway) {
      return;
    }
    try {
      const response = await this._hass.callApi("POST", "myhome/discovery_by_activation", {
        gateway: this._state.gateway,
        enabled: true,
      });
      this._state.discovery_by_activation = !!response.enabled;
      const selectedGateway = this._gatewayByMac(response.gateway);
      if (selectedGateway) {
        selectedGateway.discovery_by_activation = !!response.enabled;
      }
    } catch (_err) {
      // Best-effort: actual error surfaced by refresh call.
    }
  }

  async _loadGateways() {
    if (!this._hass) {
      return;
    }
    this._loadingGateways = true;
    this._error = "";
    this._render();
    try {
      const response = await this._hass.callApi("GET", "myhome/gateways");
      this._gateways = response.gateways || [];
      if (!this._state.gateway && this._gateways.length > 0) {
        this._syncGatewayState(this._gateways[0].mac);
      } else if (this._state.gateway) {
        this._syncGatewayState(this._state.gateway);
      }
      await this._ensurePassiveDiscoveryEnabled();
      await this._loadConfiguration();
      await this._showActivationResults(false, false);
    } catch (err) {
      this._error = `Error loading gateways: ${err?.body?.message || err?.message || "unknown"}`;
    } finally {
      this._loadingGateways = false;
      this._render();
    }
  }

  async _loadConfiguration() {
    if (!this._hass || !this._state.gateway) {
      return;
    }
    this._loadingConfig = true;
    this._render();
    try {
      const encodedGateway = encodeURIComponent(this._state.gateway);
      const response = await this._hass.callApi("GET", `myhome/configuration?gateway=${encodedGateway}`);
      this._configDevices = response.devices || {};
    } catch (err) {
      this._error = err?.body?.message || err?.message || "Error loading configuration.";
    } finally {
      this._loadingConfig = false;
      this._render();
    }
  }

  _defaultCandidate(platform, address) {
    if (platform === "light") {
      return {
        id: `${platform}:${address}`,
        selected: true,
        platform,
        address,
        key: `discovered_light_${address}`,
        name: `Light ${address}`,
        dimmable: false,
      };
    }
    if (platform === "cover") {
      return {
        id: `${platform}:${address}`,
        selected: true,
        platform,
        address,
        key: `discovered_cover_${address}`,
        name: `Cover ${address}`,
      };
    }
    if (platform === "climate") {
      return {
        id: `${platform}:${address}`,
        selected: true,
        platform,
        address,
        key: `discovered_climate_${address}`,
        name: `Climate ${address}`,
        heat: true,
        cool: true,
        fan: true,
        standalone: true,
      };
    }
    return {
      id: `${platform}:${address}`,
      selected: true,
      platform,
      address,
      key: `discovered_power_${address}`,
      name: `Power ${address}`,
      class: "power",
    };
  }

  _refreshCandidateDrafts() {
    const next = {};
    if (!this._result) {
      this._candidateDrafts = {};
      return;
    }

    const append = (platform, list) => {
      (list || []).forEach((address) => {
        const id = `${platform}:${address}`;
        next[id] = this._candidateDrafts[id] || this._defaultCandidate(platform, String(address));
      });
    };

    append("light", this._result.new_light);
    append("cover", this._result.new_cover);
    append("climate", this._result.new_climate);
    append("sensor", this._result.new_power);
    this._candidateDrafts = next;
  }

  _candidateEntries() {
    return Object.values(this._candidateDrafts).sort((a, b) => a.id.localeCompare(b.id));
  }

  async _showActivationResults(clear, renderStart = true) {
    if (!this._hass || !this._state.gateway) {
      return;
    }
    this._loadingActivation = true;
    if (renderStart) {
      this._error = "";
      this._notice = "";
      this._render();
    }

    try {
      this._result = await this._hass.callApi("POST", "myhome/activation_discovery", {
        gateway: this._state.gateway,
        clear,
      });
      this._state.discovery_by_activation = !!this._result.enabled;
      this._refreshCandidateDrafts();
      if (clear) {
        this._notice = "Automatic discovery list cleared.";
      }
    } catch (err) {
      this._error = err?.body?.message || err?.message || "Unable to read automatic discovery results.";
    } finally {
      this._loadingActivation = false;
      this._render();
    }
  }

  async _importSelectedCandidates() {
    if (!this._hass || !this._state.gateway) {
      return;
    }

    const selected = this._candidateEntries().filter((entry) => entry.selected);
    if (selected.length === 0) {
      this._notice = "No selected devices to import.";
      this._error = "";
      this._render();
      return;
    }

    this._savingConfig = true;
    this._error = "";
    this._notice = "";
    this._render();

    let imported = 0;
    const failures = [];

    for (const candidate of selected) {
      const body = {
        gateway: this._state.gateway,
        platform: candidate.platform,
        key: candidate.key,
        name: candidate.name,
      };

      if (candidate.platform === "climate") {
        body.zone = candidate.address;
        body.heat = !!candidate.heat;
        body.cool = !!candidate.cool;
        body.fan = !!candidate.fan;
        body.standalone = !!candidate.standalone;
      } else {
        body.where = candidate.address;
      }

      if (candidate.platform === "light") {
        body.dimmable = !!candidate.dimmable;
      }
      if (candidate.platform === "sensor") {
        body.class = candidate.class || "power";
      }

      try {
        await this._hass.callApi("POST", "myhome/configuration/device", body);
        imported += 1;
      } catch (err) {
        failures.push(`${candidate.platform}:${candidate.address} -> ${err?.body?.message || err?.message || "error"}`);
      }
    }

    await this._loadConfiguration();
    await this._showActivationResults(false, false);

    if (imported > 0) {
      this._notice = `Import completed: ${imported} devices.`;
    }
    if (failures.length > 0) {
      this._error = `Partial import. Errors: ${failures.join(" | ")}`;
    }

    this._savingConfig = false;
    this._render();
  }

  async _saveManualDevice(event) {
    event.preventDefault();
    if (!this._hass || !this._state.gateway) {
      return;
    }

    this._readManualState();
    this._savingConfig = true;
    this._error = "";
    this._notice = "";
    this._render();

    try {
      const platform = this._state.manual_platform;
      const body = {
        gateway: this._state.gateway,
        platform,
        key: this._state.manual_key,
        name: this._state.manual_name,
      };

      if (platform === "climate") {
        body.zone = this._state.manual_address;
        body.heat = this._state.manual_heat;
        body.cool = this._state.manual_cool;
        body.fan = this._state.manual_fan;
        body.standalone = this._state.manual_standalone;
      } else {
        body.where = this._state.manual_address;
      }

      if (platform === "light") {
        body.dimmable = this._state.manual_dimmable;
      }
      if (platform === "sensor") {
        body.class = this._state.manual_sensor_class;
      }

      const response = await this._hass.callApi("POST", "myhome/configuration/device", body);
      this._configDevices = response.devices || this._configDevices;
      this._notice = `Device saved (${response.platform}:${response.key}).`;
      this._state.manual_key = "";
      this._state.manual_name = "";
      this._state.manual_address = "";
      await this._loadConfiguration();
    } catch (err) {
      this._error = err?.body?.message || err?.message || "Device save failed.";
    } finally {
      this._savingConfig = false;
      this._render();
    }
  }

  async _deleteDevice(platform, key) {
    if (!this._hass || !this._state.gateway || !platform || !key) {
      return;
    }

    this._savingConfig = true;
    this._error = "";
    this._notice = "";
    this._render();

    try {
      const response = await this._hass.callApi("POST", "myhome/configuration/device_delete", {
        gateway: this._state.gateway,
        platform,
        key,
      });
      this._configDevices = response.devices || this._configDevices;
      this._notice = `Device removed (${platform}:${key}).`;
      await this._loadConfiguration();
    } catch (err) {
      this._error = err?.body?.message || err?.message || "Device removal failed.";
    } finally {
      this._savingConfig = false;
      this._render();
    }
  }

  _bindEvents() {
    const gatewaySelect = this.querySelector("#gateway");
    if (gatewaySelect) {
      gatewaySelect.addEventListener("change", async (event) => {
        this._syncGatewayState(event.target.value || "");
        await this._ensurePassiveDiscoveryEnabled();
        await this._loadConfiguration();
        await this._showActivationResults(false, false);
        this._render();
      });
    }

    const reloadButton = this.querySelector("#reload_gateways");
    if (reloadButton) {
      reloadButton.addEventListener("click", () => this._loadGateways());
    }

    const refreshActivation = this.querySelector("#show_activation_discovery");
    if (refreshActivation) {
      refreshActivation.addEventListener("click", () => this._showActivationResults(false));
    }

    const clearActivation = this.querySelector("#show_activation_discovery_clear");
    if (clearActivation) {
      clearActivation.addEventListener("click", () => this._showActivationResults(true));
    }

    const importSelected = this.querySelector("#import_selected_candidates");
    if (importSelected) {
      importSelected.addEventListener("click", () => this._importSelectedCandidates());
    }

    const manualForm = this.querySelector("#manual_device_form");
    if (manualForm) {
      manualForm.addEventListener("submit", this._saveManualDevice.bind(this));
    }

    const manualPlatform = this.querySelector("#manual_platform");
    if (manualPlatform) {
      manualPlatform.addEventListener("change", () => {
        this._readManualState();
        this._render();
      });
    }

    const manualSection = this.querySelector("#manual_section");
    if (manualSection) {
      manualSection.addEventListener("toggle", () => {
        this._state.manual_section_open = !!manualSection.open;
      });
    }

    const reloadConfigButton = this.querySelector("#reload_config");
    if (reloadConfigButton) {
      reloadConfigButton.addEventListener("click", () => this._loadConfiguration());
    }

    this.querySelectorAll("[data-delete-platform][data-delete-key]").forEach((button) => {
      button.addEventListener("click", () => {
        this._deleteDevice(button.dataset.deletePlatform, button.dataset.deleteKey);
      });
    });

    this.querySelectorAll("[data-candidate-id][data-candidate-field]").forEach((element) => {
      const eventName = element.type === "text" ? "input" : "change";
      element.addEventListener(eventName, () => {
        const id = element.dataset.candidateId;
        const field = element.dataset.candidateField;
        const type = element.dataset.candidateType || "text";
        const candidate = this._candidateDrafts[id];
        if (!candidate) {
          return;
        }
        candidate[field] = type === "bool" ? !!element.checked : element.value;
      });
    });
  }

  _renderGatewayOptions() {
    if (this._gateways.length === 0) {
      return '<option value="">No gateway available</option>';
    }

    return this._gateways
      .map((gateway) => {
        const selected = gateway.mac === this._state.gateway ? "selected" : "";
        return `<option value="${this._esc(gateway.mac)}" ${selected}>${this._esc(gateway.name)} (${this._esc(gateway.host)})</option>`;
      })
      .join("");
  }

  _renderConfigDevices() {
    if (this._loadingConfig) {
      return '<div class="subtle">Loading configuration...</div>';
    }

    const devices = this._configDevices || {};
    const platforms = ["light", "cover", "climate", "sensor"];
    let total = 0;

    const renderDetails = (item, platform) => {
      const details = [];

      if (platform === "light") {
        details.push(`dimmable=${item.dimmable ? "true" : "false"}`);
      }
      if (platform === "sensor" && item.class) {
        details.push(`class=${item.class}`);
      }
      if (platform === "climate") {
        details.push(`heat=${item.heat ? "true" : "false"}`);
        details.push(`cool=${item.cool ? "true" : "false"}`);
        details.push(`fan=${item.fan ? "true" : "false"}`);
        details.push(`standalone=${item.standalone ? "true" : "false"}`);
      }
      if (item.who !== undefined && item.who !== null && item.who !== "") {
        details.push(`who=${item.who}`);
      }
      if (item.interface !== undefined && item.interface !== null && item.interface !== "") {
        details.push(`interface=${item.interface}`);
      }
      if (item.manufacturer) {
        details.push(`manufacturer=${item.manufacturer}`);
      }
      if (item.model) {
        details.push(`model=${item.model}`);
      }

      if (details.length === 0) {
        return '<span class="subtle">-</span>';
      }

      return `
        <div class="detail-list">
          ${details.map((detail) => `<code class="detail-chip">${this._esc(detail)}</code>`).join("")}
        </div>
      `;
    };

    const blocks = platforms
      .map((platform) => {
        const items = devices[platform] || [];
        total += items.length;
        const rows = items
          .map((item) => {
            const address = item.where || item.zone || "-";
            return `
              <tr>
                <td><code>${this._esc(item.key)}</code></td>
                <td>${this._esc(item.name || "-")}</td>
                <td><code>${this._esc(address)}</code></td>
                <td>${renderDetails(item, platform)}</td>
                <td><button type="button" class="danger" data-delete-platform="${platform}" data-delete-key="${this._esc(item.key)}">Remove</button></td>
              </tr>
            `;
          })
          .join("");

        return `
          <section class="subpanel">
            <h4>${platform} (${items.length})</h4>
            <table>
              <thead>
                <tr><th>Key</th><th>Name</th><th>Address</th><th>Details</th><th></th></tr>
              </thead>
              <tbody>
                ${rows || '<tr><td colspan="5" class="subtle">No devices</td></tr>'}
              </tbody>
            </table>
          </section>
        `;
      })
      .join("");

    return `
      <div class="subtle">Configured devices: <strong>${total}</strong></div>
      ${blocks}
    `;
  }

  _renderDiscoveryCandidates() {
    const header = `
      <div class="row-between">
        <h3>Discovered devices (automatic discovery)</h3>
        <div class="actions">
          <button id="show_activation_discovery" type="button" ${this._loadingActivation ? "disabled" : ""}>${this._loadingActivation ? "Refreshing..." : "Refresh results"}</button>
          <button id="show_activation_discovery_clear" type="button" ${this._loadingActivation ? "disabled" : ""}>Clear list</button>
        </div>
      </div>
    `;

    if (!this._result) {
      return `
        <section class="panel result">
          ${header}
          <p class="subtle">No results available yet. Trigger devices physically, then press "Refresh results".</p>
        </section>
      `;
    }

    const entries = this._candidateEntries();
    const selected = entries.filter((entry) => entry.selected).length;

    const summary = `
      <p class="subtle">
        Gateway: <code>${this._esc(this._result.gateway)}</code> |
        new: lights <strong>${this._result.new_light?.length || 0}</strong>,
        cover <strong>${this._result.new_cover?.length || 0}</strong>,
        climate <strong>${this._result.new_climate?.length || 0}</strong>,
        power <strong>${this._result.new_power?.length || 0}</strong>
      </p>
    `;

    if (entries.length === 0) {
      return `
        <section class="panel result">
          ${header}
          ${summary}
          <p class="subtle">No new devices to import. Detected endpoints are either already configured or not yet activated.</p>
        </section>
      `;
    }

    const rows = entries
      .map((entry) => {
        let options = "-";
        if (entry.platform === "light") {
          options = `
            <label class="inline-check"><input type="checkbox" data-candidate-id="${this._esc(entry.id)}" data-candidate-field="dimmable" data-candidate-type="bool" ${entry.dimmable ? "checked" : ""}/> dimmable</label>
          `;
        }
        if (entry.platform === "sensor") {
          options = `
            <select data-candidate-id="${this._esc(entry.id)}" data-candidate-field="class">
              <option value="power" ${entry.class === "power" ? "selected" : ""}>power</option>
              <option value="energy" ${entry.class === "energy" ? "selected" : ""}>energy</option>
              <option value="temperature" ${entry.class === "temperature" ? "selected" : ""}>temperature</option>
              <option value="illuminance" ${entry.class === "illuminance" ? "selected" : ""}>illuminance</option>
            </select>
          `;
        }
        if (entry.platform === "climate") {
          options = `
            <div class="inline-flags">
              <label class="inline-check"><input type="checkbox" data-candidate-id="${this._esc(entry.id)}" data-candidate-field="heat" data-candidate-type="bool" ${entry.heat ? "checked" : ""}/> heat</label>
              <label class="inline-check"><input type="checkbox" data-candidate-id="${this._esc(entry.id)}" data-candidate-field="cool" data-candidate-type="bool" ${entry.cool ? "checked" : ""}/> cool</label>
              <label class="inline-check"><input type="checkbox" data-candidate-id="${this._esc(entry.id)}" data-candidate-field="fan" data-candidate-type="bool" ${entry.fan ? "checked" : ""}/> fan</label>
              <label class="inline-check"><input type="checkbox" data-candidate-id="${this._esc(entry.id)}" data-candidate-field="standalone" data-candidate-type="bool" ${entry.standalone ? "checked" : ""}/> standalone</label>
            </div>
          `;
        }

        return `
          <tr>
            <td>
              <input type="checkbox" data-candidate-id="${this._esc(entry.id)}" data-candidate-field="selected" data-candidate-type="bool" ${entry.selected ? "checked" : ""}/>
            </td>
            <td><code>${this._esc(entry.platform)}</code></td>
            <td><code>${this._esc(entry.address)}</code></td>
            <td><input type="text" data-candidate-id="${this._esc(entry.id)}" data-candidate-field="key" value="${this._esc(entry.key)}"/></td>
            <td><input type="text" data-candidate-id="${this._esc(entry.id)}" data-candidate-field="name" value="${this._esc(entry.name)}"/></td>
            <td>${options}</td>
          </tr>
        `;
      })
      .join("");

    return `
      <section class="panel result">
        ${header}
        ${summary}
        <div class="subtle">Selezionati per import: <strong>${selected}</strong> / ${entries.length}</div>
        <table>
          <thead>
            <tr><th></th><th>Type</th><th>Address</th><th>Key</th><th>Name</th><th>Options</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="actions">
          <button id="import_selected_candidates" type="button" ${this._savingConfig ? "disabled" : ""}>${this._savingConfig ? "Importing..." : "Import selected into configuration"}</button>
        </div>
      </section>
    `;
  }

  _render() {
    const loadingGateways = this._loadingGateways ? "disabled" : "";
    const configDisabled = this._savingConfig || this._loadingGateways ? "disabled" : "";
    const manualPlatform = this._state.manual_platform;
    const addressLabel = manualPlatform === "climate" ? "Zone" : "Where";

    const sensorClassField =
      manualPlatform === "sensor"
        ? `
              <label>Sensor class
                <select id="manual_sensor_class" ${configDisabled}>
                  <option value="power" ${this._state.manual_sensor_class === "power" ? "selected" : ""}>power</option>
                  <option value="temperature" ${this._state.manual_sensor_class === "temperature" ? "selected" : ""}>temperature</option>
                  <option value="energy" ${this._state.manual_sensor_class === "energy" ? "selected" : ""}>energy</option>
                  <option value="illuminance" ${this._state.manual_sensor_class === "illuminance" ? "selected" : ""}>illuminance</option>
                </select>
              </label>
          `
        : "";

    const manualFlags =
      manualPlatform === "light"
        ? `
            <div class="checks">
              <label><input id="manual_dimmable" type="checkbox" ${this._state.manual_dimmable ? "checked" : ""} ${configDisabled} /> Dimmable</label>
            </div>
          `
        : manualPlatform === "climate"
          ? `
            <div class="checks">
              <label><input id="manual_heat" type="checkbox" ${this._state.manual_heat ? "checked" : ""} ${configDisabled} /> Heat</label>
              <label><input id="manual_cool" type="checkbox" ${this._state.manual_cool ? "checked" : ""} ${configDisabled} /> Cool</label>
              <label><input id="manual_fan" type="checkbox" ${this._state.manual_fan ? "checked" : ""} ${configDisabled} /> Fan</label>
              <label><input id="manual_standalone" type="checkbox" ${this._state.manual_standalone ? "checked" : ""} ${configDisabled} /> Standalone</label>
            </div>
          `
          : "";

    const errorBlock = this._error ? `<div class="error">${this._esc(this._error)}</div>` : "";
    const noticeBlock = this._notice ? `<div class="notice">${this._esc(this._notice)}</div>` : "";
    const logoUrl = "/api/myhome/panel/bticino-logo.svg";

    this.innerHTML = `
      <style>
        :host {
          display: block;
          min-height: 100%;
          background: var(--primary-background-color);
          color: var(--primary-text-color);
          font-family: var(--paper-font-body1_-_font-family, "Segoe UI", sans-serif);
        }
        .wrap {
          max-width: 1080px;
          margin: 18px auto 30px;
          padding: 14px;
        }
        .brand {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 12px;
          padding: 8px 0;
        }
        .brand-logo {
          width: 110px;
          height: auto;
          display: block;
        }
        .brand-title {
          font-size: 1.1rem;
          font-weight: 600;
          margin: 0;
          line-height: 1.2;
        }
        .panel {
          border: 1px solid var(--divider-color);
          background: var(--card-background-color);
          padding: 12px;
          margin-bottom: 12px;
        }
        .panel h3 {
          margin: 0 0 10px;
          font-size: 1rem;
        }
        details {
          border: 1px solid var(--divider-color);
          padding: 10px;
        }
        summary {
          cursor: pointer;
          font-weight: 600;
          user-select: none;
        }
        details[open] summary {
          margin-bottom: 10px;
        }
        .subpanel {
          border: 1px solid var(--divider-color);
          padding: 10px;
          margin-top: 10px;
        }
        .subpanel h4 {
          margin: 0 0 8px;
          font-size: 0.92rem;
          text-transform: uppercase;
          letter-spacing: 0.03em;
        }
        form {
          margin: 0;
        }
        .grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 10px;
          margin-bottom: 10px;
        }
        .checks {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 8px;
          margin-bottom: 10px;
        }
        label {
          display: flex;
          flex-direction: column;
          gap: 5px;
          font-size: 0.9rem;
        }
        .checks label,
        .inline-check {
          flex-direction: row;
          align-items: center;
          gap: 8px;
        }
        .inline-flags {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .detail-list {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
        .detail-chip {
          border: 1px solid var(--divider-color);
          padding: 1px 4px;
          font-size: 0.78rem;
          background: var(--card-background-color);
        }
        select,
        input[type="number"],
        input[type="text"] {
          border: 1px solid var(--divider-color);
          padding: 7px;
          font: inherit;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          min-width: 0;
        }
        .actions {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          margin-top: 8px;
        }
        .row-between {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 8px;
        }
        button {
          border: 1px solid var(--divider-color);
          background: var(--card-background-color);
          color: var(--primary-text-color);
          padding: 8px 10px;
          font: inherit;
          cursor: pointer;
        }
        button[type="submit"] {
          border-color: var(--primary-color);
          color: var(--primary-color);
        }
        button.danger {
          border-color: #cc6666;
          color: #a33;
        }
        button[disabled] {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .subtle {
          color: var(--secondary-text-color);
          font-size: 0.86rem;
          margin: 6px 0;
        }
        .error {
          border: 1px solid #cf6d6d;
          background: #f9ecec;
          color: #7a1e1e;
          padding: 10px;
          margin-bottom: 10px;
        }
        .notice {
          border: 1px solid #8bb78b;
          background: #ecf8ec;
          color: #245a24;
          padding: 10px;
          margin-bottom: 10px;
        }
        table {
          width: 100%;
          border-collapse: collapse;
          margin-top: 8px;
        }
        th,
        td {
          border-bottom: 1px solid var(--divider-color);
          text-align: left;
          padding: 7px 6px;
          vertical-align: top;
          font-size: 0.88rem;
        }
        th {
          font-size: 0.82rem;
          color: var(--secondary-text-color);
          text-transform: uppercase;
        }
      </style>

      <div class="wrap">
        <div class="brand">
          <img class="brand-logo" src="${logoUrl}" alt="bticino" />
          <h2 class="brand-title">bticino MyHome Unofficial Integration</h2>
        </div>

        <section class="panel">
          <div class="row-between">
            <h3>Automatic discovery</h3>
            <button id="reload_gateways" type="button" ${loadingGateways}>Reload gateways</button>
          </div>
          <div class="grid">
            <label>Gateway
              <select id="gateway" ${loadingGateways}>${this._renderGatewayOptions()}</select>
            </label>
          </div>
          <p class="subtle">Passive collection is always enabled. Devices are detected only when they are actually triggered (physically or by other apps).</p>
        </section>

        ${errorBlock}
        ${noticeBlock}
        ${this._renderDiscoveryCandidates()}

        <section class="panel">
          <div class="row-between">
            <h3>Device Configuration</h3>
            <button id="reload_config" type="button" ${this._loadingConfig ? "disabled" : ""}>Reload</button>
          </div>
          ${this._renderConfigDevices()}
        </section>

        <section class="panel">
          <details id="manual_section" ${this._state.manual_section_open ? "open" : ""}>
            <summary>Add device manually</summary>
            <form id="manual_device_form">
              <div class="grid">
                <label>Platform
                  <select id="manual_platform" ${configDisabled}>
                    <option value="light" ${this._state.manual_platform === "light" ? "selected" : ""}>light</option>
                    <option value="cover" ${this._state.manual_platform === "cover" ? "selected" : ""}>cover</option>
                    <option value="climate" ${this._state.manual_platform === "climate" ? "selected" : ""}>climate</option>
                    <option value="sensor" ${this._state.manual_platform === "sensor" ? "selected" : ""}>sensor</option>
                  </select>
                </label>
                <label>Key (optional)
                  <input id="manual_key" type="text" value="${this._esc(this._state.manual_key)}" ${configDisabled} />
                </label>
                <label>Name
                  <input id="manual_name" type="text" value="${this._esc(this._state.manual_name)}" ${configDisabled} />
                </label>
                <label>${addressLabel}
                  <input id="manual_address" type="text" value="${this._esc(this._state.manual_address)}" ${configDisabled} />
                </label>
                ${sensorClassField}
              </div>
              <p class="subtle">Platform: <code>${manualPlatform}</code> | required field: <code>${manualPlatform === "climate" ? "zone" : "where"}</code></p>
              ${manualFlags}
              <div class="actions">
                <button type="submit" ${configDisabled}>${this._savingConfig ? "Saving..." : "Save device"}</button>
              </div>
            </form>
          </details>
        </section>
      </div>
    `;

    this._bindEvents();
  }
}

customElements.define("myhome-discovery-panel", MyHOMEDiscoveryPanel);

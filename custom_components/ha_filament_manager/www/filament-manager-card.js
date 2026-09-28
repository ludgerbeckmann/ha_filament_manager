/**
 * Filament Manager overview card.
 *
 * A dependency-free Lovelace card that auto-discovers every spool created by
 * the Filament Manager integration (via the entity/device registries already
 * present on `hass`) and renders remaining amount, material and color at a
 * glance - no YAML configuration required.
 */

const PLATFORM = "ha_filament_manager";

const COLOR_SWATCHES = {
  schwarz: "#111111",
  weiss: "#f5f5f5",
  "weiß": "#f5f5f5",
  grau: "#9e9e9e",
  silber: "#c0c0c0",
  rot: "#e53935",
  blau: "#1e88e5",
  gruen: "#43a047",
  "grün": "#43a047",
  gelb: "#fdd835",
  orange: "#fb8c00",
  lila: "#8e24aa",
  pink: "#d81b60",
  braun: "#6d4c41",
  transparent: "transparent",
  gold: "#c9a227",
};

function swatchFor(colorName) {
  if (!colorName) return "#9e9e9e";
  const key = colorName.trim().toLowerCase();
  return COLOR_SWATCHES[key] || "#9e9e9e";
}

function percentTone(percent) {
  if (percent === null || Number.isNaN(percent)) return "var(--secondary-text-color)";
  if (percent < 20) return "var(--error-color, #db4437)";
  if (percent < 50) return "var(--warning-color, #ff9800)";
  return "var(--success-color, #43a047)";
}

class FilamentManagerCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
  }

  set hass(hass) {
    this._hass = hass;
    this._renderIfReady();
  }

  getCardSize() {
    const data = this._data || { boxes: [], ungrouped: [] };
    const rows = data.boxes.reduce((sum, box) => sum + 1 + box.spools.length, 0) + data.ungrouped.length;
    return Math.max(1, rows) + 1;
  }

  static getStubConfig() {
    return {};
  }

  static getConfigElement() {
    return document.createElement("filament-manager-card-editor");
  }

  connectedCallback() {
    this._renderIfReady();
  }

  _renderIfReady() {
    if (!this._hass) return;
    const data = this._collectData(this._hass);
    // Avoid tearing down/rebuilding the DOM on every state tick when
    // nothing relevant changed.
    const signature = JSON.stringify(data);
    if (signature === this._lastSignature) return;
    this._lastSignature = signature;
    this._data = data;
    this._render(data);
  }

  /**
   * Collects every spool and filament box created by this integration,
   * grouping spools under the box they're assigned to (if any). A device is
   * recognised as a box, rather than a spool, by not having a `number.*`
   * entity - only spools have an editable remaining-weight number.
   */
  _collectData(hass) {
    const entities = hass.entities || {};
    const devices = hass.devices || {};
    const stateOf = (entityId) => (entityId ? hass.states[entityId] : undefined);

    const byDevice = {};
    for (const entry of Object.values(entities)) {
      if (entry.platform !== PLATFORM || !entry.device_id) continue;
      (byDevice[entry.device_id] = byDevice[entry.device_id] || []).push(entry);
    }

    const readHumidity = (entries) => {
      const binarySensorEntry = entries.find((e) => e.entity_id.startsWith("binary_sensor."));
      const binaryState = stateOf(binarySensorEntry && binarySensorEntry.entity_id);
      return {
        // Prefer the linked humidity sensor itself (shows the actual
        // reading and its history) over our on/off binary_sensor as the tap
        // target.
        humidityEntityId: binaryState ? binaryState.attributes.source_entity_id || binaryState.entity_id : null,
        humidityValue:
          binaryState && typeof binaryState.attributes.current_humidity === "number"
            ? binaryState.attributes.current_humidity
            : null,
        humidityAlert: binaryState ? binaryState.state === "on" : false,
        hasHumiditySensor: !!binarySensorEntry,
      };
    };

    const boxes = {};
    for (const [deviceId, entries] of Object.entries(byDevice)) {
      if (entries.some((e) => e.entity_id.startsWith("number."))) continue;
      const device = devices[deviceId];
      boxes[deviceId] = {
        deviceId,
        name: (device && (device.name_by_user || device.name)) || "Filamentbox",
        spools: [],
        ...readHumidity(entries),
      };
    }

    const ungrouped = [];
    for (const [deviceId, entries] of Object.entries(byDevice)) {
      const numberEntry = entries.find((e) => e.entity_id.startsWith("number."));
      if (!numberEntry) continue;

      const device = devices[deviceId];
      const sensorEntries = entries.filter((e) => e.entity_id.startsWith("sensor."));

      let percentState;
      let materialState;
      let colorState;
      for (const entry of sensorEntries) {
        const state = stateOf(entry.entity_id);
        if (!state) continue;
        if (state.attributes.unit_of_measurement === "%") {
          percentState = state;
        } else if (state.attributes.total_weight_g !== undefined) {
          materialState = state;
        } else {
          colorState = state;
        }
      }

      const numberState = stateOf(numberEntry.entity_id);
      const percent = percentState ? Number(percentState.state) : null;

      const spool = {
        deviceId,
        name: (device && (device.name_by_user || device.name)) || "Spule",
        material: materialState ? materialState.state : null,
        color: colorState ? colorState.state : null,
        percent: percent !== null && !Number.isNaN(percent) ? percent : null,
        remaining: numberState ? numberState.state : null,
        unit: numberState ? numberState.attributes.unit_of_measurement : "g",
        // The number entity is editable, so it's the more useful tap target
        // than the (read-only) percentage sensor - fall back to it if for
        // some reason the number entity is missing.
        primaryEntityId: numberEntry.entity_id,
        ...readHumidity(entries),
      };

      const boxId = device && device.via_device_id;
      if (boxId && boxes[boxId]) {
        boxes[boxId].spools.push(spool);
      } else {
        ungrouped.push(spool);
      }
    }

    const boxList = Object.values(boxes).filter((box) => box.spools.length > 0);
    boxList.forEach((box) => box.spools.sort((a, b) => a.name.localeCompare(b.name)));
    boxList.sort((a, b) => a.name.localeCompare(b.name));
    ungrouped.sort((a, b) => a.name.localeCompare(b.name));

    return { boxes: boxList, ungrouped };
  }

  _openMoreInfo(entityId) {
    if (!entityId) return;
    const event = new CustomEvent("hass-more-info", {
      bubbles: true,
      composed: true,
      detail: { entityId },
    });
    this.dispatchEvent(event);
  }

  _renderSpoolRow(spool, { indent = false } = {}) {
    const percentLabel = spool.percent !== null ? `${spool.percent}%` : "–";
    const tone = percentTone(spool.percent);
    const barWidth = spool.percent !== null ? Math.max(0, Math.min(100, spool.percent)) : 0;
    const weightLabel = spool.remaining !== null ? `${spool.remaining} ${spool.unit}` : "–";
    const progressSub = `${percentLabel} · ${weightLabel}`;

    const humidityValueLabel = spool.humidityValue !== null ? `${spool.humidityValue}%` : "–";
    const humidityColumn = spool.hasHumiditySensor
      ? `<div class="humidity-col" data-entity="${spool.humidityEntityId || ""}">
           <ha-icon
             class="humidity-badge ${spool.humidityAlert ? "alert" : ""}"
             icon="${spool.humidityAlert ? "mdi:water-alert" : "mdi:water-check"}"
             title="${spool.humidityAlert ? "Luftfeuchtigkeit zu hoch" : "Luftfeuchtigkeit OK"}"
           ></ha-icon>
           <span class="humidity-value ${spool.humidityAlert ? "alert" : ""}">${humidityValueLabel}</span>
         </div>`
      : "";

    return `
      <div class="row ${indent ? "boxed" : ""}" data-entity="${spool.primaryEntityId || ""}">
        <span class="swatch" style="background:${swatchFor(spool.color)}" title="${spool.color || ""}"></span>
        <div class="info">
          <div class="name">${spool.name}</div>
          <div class="meta">${[spool.material, spool.color].filter(Boolean).join(" · ") || "&nbsp;"}</div>
        </div>
        <div class="progress-col">
          <div class="track"><div class="fill" style="width:${barWidth}%;background:${tone}"></div></div>
          <span class="progress-sub" style="color:${tone}">${progressSub}</span>
        </div>
        ${humidityColumn}
      </div>
    `;
  }

  _renderBoxSection(box) {
    const humidityValueLabel = box.humidityValue !== null ? `${box.humidityValue}%` : "–";
    const humidityBadge = box.hasHumiditySensor
      ? `<span class="box-humidity ${box.humidityAlert ? "alert" : ""}">
           <ha-icon icon="${box.humidityAlert ? "mdi:water-alert" : "mdi:water-check"}"></ha-icon>
           ${humidityValueLabel}
         </span>`
      : "";

    return `
      <div class="box-header" data-entity="${box.humidityEntityId || ""}">
        <ha-icon class="box-icon" icon="mdi:archive-outline"></ha-icon>
        <span class="box-name">${box.name}</span>
        ${humidityBadge}
      </div>
      ${box.spools.map((spool) => this._renderSpoolRow(spool, { indent: true })).join("")}
    `;
  }

  _render(data) {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }

    const title = this._config.title !== undefined ? this._config.title : "Filament Manager";

    const boxSections = data.boxes.map((box) => this._renderBoxSection(box)).join("");
    const ungroupedRows = data.ungrouped.map((spool) => this._renderSpoolRow(spool)).join("");
    const rows =
      boxSections || ungroupedRows
        ? `<div class="rows">${boxSections}${ungroupedRows}</div>`
        : `<div class="empty">Keine Filamentspulen gefunden. Über "Integration hinzufügen" → "Filament Manager" anlegen.</div>`;

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        .header { font-size: 1.2em; font-weight: 500; margin-bottom: 12px; color: var(--primary-text-color); }
        .row {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 8px 0;
          border-top: 1px solid var(--divider-color);
          cursor: pointer;
        }
        .rows > *:first-child { border-top: none; margin-top: 0; }
        .row.boxed { padding-left: 24px; }
        .box-header {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 8px 0 4px;
          margin-top: 4px;
          border-top: 1px solid var(--divider-color);
          color: var(--secondary-text-color);
          font-weight: 500;
          cursor: pointer;
        }
        .box-icon { --mdc-icon-size: 18px; }
        .box-name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .box-humidity { display: flex; align-items: center; gap: 4px; font-size: 0.85em; flex: none; }
        .box-humidity ha-icon { --mdc-icon-size: 16px; }
        .box-humidity.alert { color: var(--error-color, #db4437); }
        .swatch {
          width: 16px;
          height: 16px;
          border-radius: 50%;
          border: 1px solid var(--divider-color);
          flex: none;
        }
        .info { flex: 1 1 auto; min-width: 0; }
        .name {
          color: var(--primary-text-color);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .meta { color: var(--secondary-text-color); font-size: 0.85em; }
        .progress-col {
          display: flex;
          flex-direction: column;
          align-items: stretch;
          gap: 4px;
          width: 40%;
          flex: none;
        }
        .track {
          height: 6px;
          border-radius: 3px;
          background: var(--divider-color);
          overflow: hidden;
        }
        .fill { height: 100%; border-radius: 3px; }
        .progress-sub { font-size: 0.8em; text-align: left; }
        .humidity-col {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 2px;
          flex: none;
          cursor: pointer;
        }
        .humidity-badge { --mdc-icon-size: 20px; color: var(--secondary-text-color); }
        .humidity-badge.alert { color: var(--error-color, #db4437); }
        .humidity-value { font-size: 0.75em; color: var(--secondary-text-color); }
        .humidity-value.alert { color: var(--error-color, #db4437); }
        .empty { color: var(--secondary-text-color); padding: 8px 0; }
      </style>
      <ha-card>
        ${title ? `<div class="header">${title}</div>` : ""}
        ${rows}
      </ha-card>
    `;

    // The humidity column opens its own entity and must stop the click from
    // also bubbling to the row (which would otherwise open the spool's
    // remaining-weight entity instead).
    this.shadowRoot.querySelectorAll(".humidity-col[data-entity]").forEach((column) => {
      const entityId = column.getAttribute("data-entity");
      if (!entityId) return;
      column.addEventListener("click", (event) => {
        event.stopPropagation();
        this._openMoreInfo(entityId);
      });
    });

    this.shadowRoot.querySelectorAll(".row[data-entity]").forEach((row) => {
      const entityId = row.getAttribute("data-entity");
      if (!entityId) return;
      row.addEventListener("click", () => this._openMoreInfo(entityId));
    });

    // A box header opens its shared humidity sensor's detail view.
    this.shadowRoot.querySelectorAll(".box-header[data-entity]").forEach((header) => {
      const entityId = header.getAttribute("data-entity");
      if (!entityId) return;
      header.addEventListener("click", () => this._openMoreInfo(entityId));
    });
  }
}

customElements.define("filament-manager-card", FilamentManagerCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "filament-manager-card",
  name: "Filament Manager",
  description: "Übersicht aller Filamentspulen (Füllstand, Material, Farbe, Luftfeuchtigkeit).",
  preview: false,
});

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char])
  );
}

/**
 * Minimal visual editor: just the (optional) card title, so Lovelace's
 * "Visual editor not supported" fallback notice no longer shows up. Uses
 * <ha-textfield>, which the frontend has already registered globally by the
 * time a card editor can open - no import needed.
 */
class FilamentManagerCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    if (!this._config) return;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }

    this.shadowRoot.innerHTML = `
      <style>
        .form { padding: 16px 0; }
        ha-textfield { display: block; }
      </style>
      <div class="form">
        <ha-textfield
          label="Titel (leer lassen für „Filament Manager“)"
          value="${escapeHtml(this._config.title || "")}"
        ></ha-textfield>
      </div>
    `;

    const field = this.shadowRoot.querySelector("ha-textfield");
    field.addEventListener("input", (event) => this._titleChanged(event));
  }

  _titleChanged(event) {
    const value = event.target.value;
    const newConfig = { ...this._config };
    if (value) {
      newConfig.title = value;
    } else {
      delete newConfig.title;
    }
    this._config = newConfig;

    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: { config: newConfig },
        bubbles: true,
        composed: true,
      })
    );
  }
}

customElements.define("filament-manager-card-editor", FilamentManagerCardEditor);

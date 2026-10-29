/**
 * Filament Manager overview card.
 *
 * A dependency-free Lovelace card that auto-discovers every spool created by
 * the Filament Manager integration (via the entity/device registries already
 * present on `hass`) and renders remaining amount, material and color at a
 * glance - no YAML configuration required.
 */

const PLATFORM = "ha_filament_manager";

function esc(value) {
  return String(value === null || value === undefined ? "" : value).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

const COLOR_SWATCHES = {
  schwarz: "#111111",
  weiss: "#f5f5f5",
  "weiß": "#f5f5f5",
  grau: "#9e9e9e",
  silber: "#c0c0c0",
  rot: "#e53935",
  blau: "#1e88e5",
  himmelblau: "#4fc3f7",
  gruen: "#43a047",
  "grün": "#43a047",
  meeresgruen: "#2e8b57",
  "meeresgrün": "#2e8b57",
  gelb: "#fdd835",
  orange: "#fb8c00",
  lila: "#8e24aa",
  pink: "#d81b60",
  braun: "#6d4c41",
  holzfarbe: "#c19a6b",
  beige: "#e8dcc4",
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
  constructor() {
    super();
    // Boxes the viewer has toggled by hand (device id -> collapsed?), which
    // wins over the card's `collapse_boxes` default. A collapsed box hides
    // its spools and shows only the header row (name + a small dot per
    // spool's color). UI-only state, deliberately not part of
    // `_data`/`_lastSignature` and lost on reload - the config default is
    // what applies again then.
    this._boxToggles = new Map();
    // Edit mode (the pencil in the header) shows the management actions: load
    // a spool into the printer, move, delete, add. UI state only.
    this._editMode = false;
    this._modalEl = null;
  }

  /** Managing spools needs an admin (the services are not otherwise restricted). */
  _canManage() {
    return !(this._hass && this._hass.user && this._hass.user.is_admin === false);
  }

  setConfig(config) {
    const previous = this._config;
    this._config = config || {};
    if (!previous) return;
    if (Boolean(previous.collapse_boxes) !== Boolean(this._config.collapse_boxes)) {
      // The default changed (e.g. in the visual editor): apply it to every box.
      this._boxToggles.clear();
    }
    if (
      previous.group_by !== this._config.group_by ||
      Boolean(previous.only_in_printer) !== Boolean(this._config.only_in_printer) ||
      Boolean(previous.dark_background) !== Boolean(this._config.dark_background) ||
      Boolean(previous.collapse_boxes) !== Boolean(this._config.collapse_boxes)
    ) {
      this._lastSignature = undefined;
      this._renderIfReady();
    }
  }

  /** "box" (default), "material" or "none"; anything else counts as "box". */
  _groupBy() {
    const value = this._config && this._config.group_by;
    return value === "material" || value === "none" ? value : "box";
  }

  /**
   * Turns the collected spools into what is drawn: header groups (a box, or a
   * material) plus loose rows, honouring `group_by` and `only_in_printer`.
   * Spools outside any box stay loose in box mode.
   */
  _layout(data) {
    const wanted = (spool) => !(this._config && this._config.only_in_printer) || spool.inPrinter;
    const mode = this._groupBy();
    const byName = (a, b) => a.name.localeCompare(b.name);
    const spools = data.spools.filter(wanted);

    if (mode === "none") {
      return { groups: [], loose: [...spools].sort(byName) };
    }
    if (mode === "material") {
      const groups = new Map();
      for (const spool of spools) {
        const name = spool.material || "–";
        if (!groups.has(name)) {
          groups.set(name, { key: `material:${name}`, name, icon: "mdi:spool", spools: [], hasHumiditySensor: false });
        }
        groups.get(name).spools.push(spool);
      }
      const list = [...groups.values()].sort(byName);
      list.forEach((group) => group.spools.sort(byName));
      return { groups: list, loose: [] };
    }
    const groups = new Map();
    const loose = [];
    for (const spool of spools) {
      const box = spool.boxId && data.boxes[spool.boxId];
      if (!box) {
        loose.push(spool);
        continue;
      }
      if (!groups.has(box.deviceId)) {
        groups.set(box.deviceId, { ...box, key: box.deviceId, icon: "mdi:archive-outline", spools: [] });
      }
      groups.get(box.deviceId).spools.push(spool);
    }
    const list = [...groups.values()].sort(byName);
    list.forEach((group) => group.spools.sort(byName));
    return { groups: list, loose: loose.sort(byName) };
  }

  _isBoxCollapsed(deviceId) {
    return this._boxToggles.has(deviceId)
      ? this._boxToggles.get(deviceId)
      : Boolean(this._config && this._config.collapse_boxes);
  }

  set hass(hass) {
    this._hass = hass;
    this._renderIfReady();
  }

  getCardSize() {
    const { groups, loose } = this._layout(this._data || { boxes: {}, spools: [] });
    const rows =
      groups.reduce(
        (sum, group) => sum + (this._isBoxCollapsed(group.key) ? 1 : 1 + group.spools.length),
        0
      ) + loose.length;
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
      // A spool can own several binary sensors (low stock, in printer); the
      // humidity one is the one that knows its source sensor.
      const binaryState = entries
        .filter((e) => e.entity_id.startsWith("binary_sensor."))
        .map((e) => stateOf(e.entity_id))
        .find((state) => state && "source_entity_id" in state.attributes);
      // A spool that gets assigned to a filament box leaves its own,
      // now-superseded humidity alert entity registered but no longer live
      // (state "unavailable", no attributes) until the integration is
      // reloaded/updated - treat that the same as "no sensor" rather than
      // showing a stale/broken badge.
      const isLive = !!binaryState;
      return {
        // Prefer the linked humidity sensor itself (shows the actual
        // reading and its history) over our on/off binary_sensor as the tap
        // target.
        humidityEntityId: isLive ? binaryState.attributes.source_entity_id || binaryState.entity_id : null,
        humidityValue:
          isLive && typeof binaryState.attributes.current_humidity === "number"
            ? binaryState.attributes.current_humidity
            : null,
        humidityAlert: isLive ? binaryState.state === "on" : false,
        hasHumiditySensor: isLive,
      };
    };

    const boxes = {};
    for (const [deviceId, entries] of Object.entries(byDevice)) {
      if (entries.some((e) => e.entity_id.startsWith("number."))) continue;
      const device = devices[deviceId];
      boxes[deviceId] = {
        deviceId,
        name: (device && (device.name_by_user || device.name)) || "Filamentbox",
        ...readHumidity(entries),
      };
    }

    const spools = [];
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

      // The "in printer" sensor belongs to spools coupled to an AMS slot; it
      // is recognised by its translation key, or - when the registry does
      // not expose it - by the slot attribute it carries while available.
      const printerEntry = entries.find(
        (e) =>
          e.entity_id.startsWith("binary_sensor.") &&
          (e.translation_key === "in_printer" ||
            (stateOf(e.entity_id) && "ams_slot" in stateOf(e.entity_id).attributes))
      );
      const printerState = stateOf(printerEntry && printerEntry.entity_id);

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
        hasPrinter: !!printerEntry,
        inPrinter: !!printerState && printerState.state === "on",
        amsSlot: printerState && printerState.attributes.ams_slot ? printerState.attributes.ams_slot : null,
        ...readHumidity(entries),
      };

      const boxId = device && device.via_device_id;
      spool.boxId = boxId && boxes[boxId] ? boxId : null;
      spool.boxName = spool.boxId ? boxes[boxId].name : null;
      spools.push(spool);
    }

    return { boxes, spools };
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

  _renderSpoolRow(spool, { indent = false, showBox = false } = {}) {
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

    const printerBadge = spool.inPrinter
      ? `<ha-icon
           class="printer-badge"
           icon="mdi:printer-3d"
           title="Im Drucker${spool.amsSlot ? ` (${spool.amsSlot})` : ""}"
         ></ha-icon>`
      : "";
    const metaText =
      [spool.material, spool.color, showBox ? spool.boxName : null].filter(Boolean).join(" · ") || "&nbsp;";

    const swatchColor = swatchFor(spool.color);
    const isSwatchTransparent = swatchColor === "transparent";

    return `
      <div class="row ${indent ? "boxed" : ""}" data-entity="${spool.primaryEntityId || ""}">
        <span
          class="swatch ${isSwatchTransparent ? "transparent" : ""}"
          style="${isSwatchTransparent ? "" : `background:${swatchColor}`}"
          title="${spool.color || ""}"
        ></span>
        <div class="info">
          <div class="name">${spool.name}</div>
          <div class="meta">${metaText}</div>
        </div>
        ${printerBadge}
        <div class="progress-col">
          <div class="track"><div class="fill" style="width:${barWidth}%;background:${tone}"></div></div>
          <span class="progress-sub" style="color:${tone}">${progressSub}</span>
        </div>
        ${humidityColumn}
        ${this._editMode && this._canManage() ? this._renderSpoolActions(spool) : ""}
      </div>
    `;
  }

  _renderSpoolActions(spool) {
    return `<div class="actions">
      <ha-icon data-action="load" data-device="${esc(spool.deviceId)}" icon="${spool.inPrinter ? "mdi:printer-3d-nozzle" : "mdi:printer-3d"}" title="In den Drucker laden / herausnehmen"></ha-icon>
      <ha-icon data-action="move" data-device="${esc(spool.deviceId)}" icon="mdi:swap-horizontal" title="In andere Box verschieben"></ha-icon>
      <ha-icon data-action="delete" data-device="${esc(spool.deviceId)}" icon="mdi:delete-outline" title="Spule löschen"></ha-icon>
    </div>`;
  }

  _renderBoxSection(box) {
    const isCollapsed = this._isBoxCollapsed(box.key);
    const showBox = this._groupBy() === "material";

    // Whole percent, in a fixed-width slot: sensors report anything from "50"
    // to "37.47", which would otherwise shift the color dots left and right
    // from box to box. The exact value is in the sensor's detail dialog.
    const humidityValueLabel = box.humidityValue !== null ? `${Math.round(box.humidityValue)}%` : "–";
    const humidityBadge = box.hasHumiditySensor
      ? `<span class="box-humidity ${box.humidityAlert ? "alert" : ""}" data-entity="${box.humidityEntityId || ""}">
           <ha-icon icon="${box.humidityAlert ? "mdi:water-alert" : "mdi:water-check"}"></ha-icon>
           <span class="box-humidity-value">${humidityValueLabel}</span>
         </span>`
      : "";

    // Collapsed: a small dot per spool stands in for the hidden rows, so the
    // box's contents are still visible at a glance.
    const spoolSwatches = isCollapsed
      ? `<div class="box-swatches">
           ${box.spools
             .map((spool) => {
               const color = swatchFor(spool.color);
               const isTransparent = color === "transparent";
               return `<span
                 class="mini-swatch ${isTransparent ? "transparent" : ""}"
                 style="${isTransparent ? "" : `background:${color}`}"
                 title="${spool.name}"
               ></span>`;
             })
             .join("")}
         </div>`
      : "";

    return `
      <div
        class="box-header"
        data-toggle-box="${box.key}"
        title="${isCollapsed ? "Spulen anzeigen" : "Spulen ausblenden"}"
      >
        <ha-icon
          class="box-toggle"
          icon="${isCollapsed ? "mdi:chevron-right" : "mdi:chevron-down"}"
        ></ha-icon>
        <ha-icon class="box-icon" icon="${box.icon}"></ha-icon>
        <span class="box-name">${box.name}</span>
        ${spoolSwatches}
        ${humidityBadge}
        ${
          this._editMode && this._canManage() && box.icon === "mdi:archive-outline"
            ? `<ha-icon class="box-add" data-action="add" data-box="${esc(box.key)}" icon="mdi:plus" title="Spule in dieser Box anlegen"></ha-icon>`
            : ""
        }
      </div>
      ${isCollapsed ? "" : box.spools.map((spool) => this._renderSpoolRow(spool, { indent: true, showBox })).join("")}
    `;
  }

  _renderHeader(title) {
    const manage = this._canManage();
    if (!title && !manage) return "";
    const toggle = manage
      ? `<ha-icon
           class="edit-toggle ${this._editMode ? "active" : ""}"
           icon="${this._editMode ? "mdi:check" : "mdi:pencil"}"
           data-action="toggle-edit"
           title="${this._editMode ? "Bearbeiten beenden" : "Spulen verwalten"}"
         ></ha-icon>`
      : "";
    return `<div class="header"><span>${esc(title)}</span>${toggle}</div>`;
  }

  _render(data) {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }

    const title = this._config.title !== undefined ? this._config.title : "Filament Manager";

    const { groups, loose } = this._layout(data);
    const boxSections = groups.map((group) => this._renderBoxSection(group)).join("");
    const ungroupedRows = loose
      .map((spool) => this._renderSpoolRow(spool, { showBox: this._groupBy() === "none" }))
      .join("");
    const rows =
      boxSections || ungroupedRows
        ? `<div class="rows">${boxSections}${ungroupedRows}</div>`
        : `<div class="empty">${
            data.spools.length
              ? "Keine Spule im Drucker."
              : 'Keine Filamentspulen gefunden. Über "Integration hinzufügen" → "Filament Manager" anlegen.'
          }</div>`;

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        /* Like the Bambu Lab cards: a black card with light text, whatever the theme. */
        ha-card.dark {
          --ha-card-background: #101114;
          --card-background-color: #101114;
          --primary-text-color: #ffffff;
          --secondary-text-color: #aeb2bb;
          --divider-color: rgba(255, 255, 255, 0.16);
          background: #101114;
          color: #ffffff;
        }
        .header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          font-size: 1.2em;
          font-weight: 500;
          margin-bottom: 12px;
          color: var(--primary-text-color);
        }
        .edit-toggle, .actions ha-icon, .box-add { cursor: pointer; color: var(--secondary-text-color); }
        .edit-toggle { --mdc-icon-size: 22px; }
        .edit-toggle.active { color: var(--primary-color); }
        .actions { display: flex; gap: 6px; flex: none; }
        .actions ha-icon { --mdc-icon-size: 20px; }
        .actions ha-icon:hover, .box-add:hover { color: var(--primary-color); }
        .box-add { --mdc-icon-size: 20px; flex: none; }
        .add-btn, .modal button {
          font: inherit;
          cursor: pointer;
          border-radius: 8px;
          border: 1px solid var(--divider-color);
          background: transparent;
          color: var(--primary-text-color);
          padding: 8px 14px;
        }
        .add-btn { margin-top: 12px; width: 100%; color: var(--primary-color); }
        .modal-backdrop {
          position: fixed;
          inset: 0;
          z-index: 20;
          display: flex;
          align-items: center;
          justify-content: center;
          background: rgba(0, 0, 0, 0.5);
        }
        .modal {
          box-sizing: border-box;
          width: min(420px, calc(100vw - 32px));
          max-height: calc(100vh - 32px);
          overflow: auto;
          padding: 20px;
          border-radius: 12px;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color);
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        }
        .modal h3 { margin: 0 0 12px; font-size: 1.1em; font-weight: 500; }
        .modal p { margin: 0 0 12px; color: var(--secondary-text-color); }
        .modal label { display: block; margin: 10px 0 4px 2px; font-size: 12px; color: var(--secondary-text-color); }
        .modal select, .modal input {
          box-sizing: border-box;
          width: 100%;
          height: 44px;
          padding: 0 12px;
          font: inherit;
          color: var(--primary-text-color);
          background: var(--secondary-background-color, rgba(0, 0, 0, 0.06));
          border: none;
          border-bottom: 1px solid var(--secondary-text-color);
          border-radius: 4px 4px 0 0;
        }
        .modal .buttons { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-top: 16px; }
        .modal button.primary { background: var(--primary-color); border-color: var(--primary-color); color: #fff; }
        .modal button.danger { background: var(--error-color, #db4437); border-color: var(--error-color, #db4437); color: #fff; }
        .modal .error { margin-top: 12px; color: var(--error-color, #db4437); }
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
        .box-toggle { --mdc-icon-size: 20px; flex: none; }
        .box-icon { --mdc-icon-size: 18px; }
        .box-name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .box-swatches { display: flex; align-items: center; gap: 3px; margin-right: 6px; flex: none; }
        .mini-swatch {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          border: 1px solid var(--divider-color);
          flex: none;
        }
        .mini-swatch.transparent {
          background-color: #fff;
          background-image:
            linear-gradient(45deg, #bbb 25%, transparent 25%),
            linear-gradient(-45deg, #bbb 25%, transparent 25%),
            linear-gradient(45deg, transparent 75%, #bbb 75%),
            linear-gradient(-45deg, transparent 75%, #bbb 75%);
          background-size: 4px 4px;
          background-position: 0 0, 0 2px, 2px -2px, -2px 0;
        }
        .box-humidity { display: flex; align-items: center; gap: 4px; font-size: 0.85em; flex: none; }
        .box-humidity ha-icon { --mdc-icon-size: 16px; }
        .box-humidity-value { min-width: 4ch; text-align: right; font-variant-numeric: tabular-nums; }
        .box-humidity.alert { color: var(--error-color, #db4437); }
        .swatch {
          width: 16px;
          height: 16px;
          border-radius: 50%;
          border: 1px solid var(--divider-color);
          flex: none;
        }
        /* Checkerboard pattern, like graphics programs use to mark
           transparency, instead of a plain (indistinguishable) circle. */
        .swatch.transparent {
          background-color: #fff;
          background-image:
            linear-gradient(45deg, #bbb 25%, transparent 25%),
            linear-gradient(-45deg, #bbb 25%, transparent 25%),
            linear-gradient(45deg, transparent 75%, #bbb 75%),
            linear-gradient(-45deg, transparent 75%, #bbb 75%);
          background-size: 6px 6px;
          background-position: 0 0, 0 3px, 3px -3px, -3px 0;
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
        .printer-badge { --mdc-icon-size: 20px; color: var(--primary-color); flex: none; }
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
      <ha-card class="${this._config.dark_background ? "dark" : ""}">
        ${this._renderHeader(title)}
        ${rows}
        ${this._editMode && this._canManage() ? `<button class="add-btn" data-action="add">+ Spule anlegen</button>` : ""}
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

    // Clicking a box header (name, icon, dots) collapses/expands its spools.
    this.shadowRoot.querySelectorAll(".box-header[data-toggle-box]").forEach((header) => {
      const boxId = header.getAttribute("data-toggle-box");
      header.addEventListener("click", () => {
        this._boxToggles.set(boxId, !this._isBoxCollapsed(boxId));
        this._render(this._data);
      });
    });

    // The box's humidity badge opens the shared humidity sensor's detail
    // view instead, and must stop the click from also toggling the header.
    this.shadowRoot.querySelectorAll(".box-humidity[data-entity]").forEach((badge) => {
      const entityId = badge.getAttribute("data-entity");
      if (!entityId) return;
      badge.addEventListener("click", (event) => {
        event.stopPropagation();
        this._openMoreInfo(entityId);
      });
    });

    // Edit mode: the pencil, the per-row actions, the "+" buttons.
    this.shadowRoot.querySelectorAll("[data-action]").forEach((element) => {
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        const action = element.getAttribute("data-action");
        if (action === "toggle-edit") {
          this._editMode = !this._editMode;
          this._render(this._data);
          return;
        }
        this._openModal(action, {
          device: element.getAttribute("data-device"),
          box: element.getAttribute("data-box"),
        });
      });
    });

    // A dialog that is open survives re-renders (and keeps what was typed).
    if (this._modalEl) this.shadowRoot.appendChild(this._modalEl);
  }

  // ------------------------------------------------------------------ dialogs

  _spoolByDevice(deviceId) {
    return (this._data ? this._data.spools : []).find((spool) => spool.deviceId === deviceId);
  }

  _boxList() {
    const boxes = this._data ? Object.values(this._data.boxes) : [];
    return boxes.sort((a, b) => a.name.localeCompare(b.name));
  }

  _closeModal() {
    if (this._modalEl) this._modalEl.remove();
    this._modalEl = null;
  }

  async _call(service, data) {
    await this._hass.callService(PLATFORM, service, data);
  }

  /** Build a dialog; `fields` is HTML, `actions` a list of {label, kind, run(modal)}. */
  _showModal(title, intro, fields, actions) {
    this._closeModal();
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `<div class="modal">
      <h3>${esc(title)}</h3>
      ${intro ? `<p>${esc(intro)}</p>` : ""}
      ${fields}
      <div class="error" hidden></div>
      <div class="buttons">
        <button data-modal="cancel">Abbrechen</button>
        ${actions.map((a, i) => `<button class="${a.kind || ""}" data-modal="${i}">${esc(a.label)}</button>`).join("")}
      </div>
    </div>`;
    const modal = backdrop.querySelector(".modal");
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) this._closeModal();
    });
    backdrop.querySelector('[data-modal="cancel"]').addEventListener("click", () => this._closeModal());
    actions.forEach((action, index) => {
      backdrop.querySelector(`[data-modal="${index}"]`).addEventListener("click", async () => {
        const errorBox = backdrop.querySelector(".error");
        errorBox.hidden = true;
        try {
          await action.run(modal);
          this._closeModal();
        } catch (err) {
          errorBox.textContent = (err && (err.message || err.error)) || String(err);
          errorBox.hidden = false;
        }
      });
    });
    this._modalEl = backdrop;
    this.shadowRoot.appendChild(backdrop);
  }

  _boxOptions(selected, exclude) {
    return this._boxList()
      .filter((box) => box.deviceId !== exclude)
      .map((box) => `<option value="${esc(box.deviceId)}" ${box.deviceId === selected ? "selected" : ""}>${esc(box.name)}</option>`)
      .join("");
  }

  async _openModal(kind, { device, box }) {
    const spool = device ? this._spoolByDevice(device) : null;
    if (kind === "delete" && spool) {
      this._showModal(
        "Spule löschen",
        `„${spool.name}“ wirklich löschen? Die Entitäten und der Verlauf der Spule gehen verloren.`,
        "",
        [{ label: "Löschen", kind: "danger", run: () => this._call("remove_spool", { device_id: device }) }]
      );
    } else if (kind === "move" && spool) {
      const others = this._boxOptions(null, spool.boxId);
      if (!others) {
        this._showModal("Spule verschieben", "Es gibt keine andere Filamentbox.", "", []);
        return;
      }
      this._showModal(
        "In andere Box verschieben",
        `„${spool.name}“ behält Entitäten, Verlauf und Restmenge.`,
        `<label for="box">Zielbox</label><select id="box">${others}</select>`,
        [
          {
            label: "Verschieben",
            kind: "primary",
            run: (m) => this._call("move_spool", { device_id: device, box_device_id: m.querySelector("#box").value }),
          },
        ]
      );
    } else if (kind === "load" && spool) {
      let slots = [];
      try {
        slots = (await this._hass.callWS({ type: `${PLATFORM}/options` })).slots;
      } catch (err) {
        slots = [];
      }
      const hass = this._hass;
      const options = slots
        .map((slot) => {
          const state = hass.states[slot];
          const label = (state && (state.attributes.friendly_name || slot)) || slot;
          const content = state && state.attributes.name ? ` – ${state.attributes.name}` : state ? ` – ${state.state}` : "";
          const taken = this._data.spools.find((s) => s.amsSlot === slot && s.deviceId !== device);
          return `<option value="${esc(slot)}" ${spool.amsSlot === slot ? "selected" : ""}>${esc(label + content + (taken ? ` (jetzt: ${taken.name})` : ""))}</option>`;
        })
        .join("");
      const actions = [];
      if (options) {
        actions.push({
          label: "In den Drucker laden",
          kind: "primary",
          run: (m) => this._call("load_spool", { device_id: device, slot: m.querySelector("#slot").value }),
        });
      }
      if (spool.inPrinter || spool.amsSlot) {
        actions.push({ label: "Aus dem Drucker nehmen", run: () => this._call("unload_spool", { device_id: device }) });
      }
      this._showModal(
        "Spule in den Drucker",
        options
          ? `„${spool.name}“ einem AMS-Slot zuordnen. Die Spule, die bisher in diesem Slot war, wird herausgenommen.`
          : "Keine AMS-Slots gefunden (Integration Bambu Lab nötig).",
        options ? `<label for="slot">AMS-Slot</label><select id="slot">${options}</select>` : "",
        actions
      );
    } else if (kind === "add") {
      let choices = { materials: [], colors: [], manufacturers: [], diameters: ["1.75"] };
      try {
        choices = await this._hass.callWS({ type: `${PLATFORM}/options` });
      } catch (err) {
        /* the lists are only suggestions */
      }
      const list = (id, items) => `<datalist id="${id}">${items.map((i) => `<option value="${esc(i)}"></option>`).join("")}</datalist>`;
      const boxes = this._boxOptions(box || null, null);
      if (!boxes) {
        this._showModal("Spule anlegen", "Lege zuerst eine Filamentbox an.", "", []);
        return;
      }
      this._showModal(
        "Spule anlegen",
        "",
        `<label for="box">Box</label><select id="box">${boxes}</select>
         <label for="material">Material</label><input id="material" list="materials" autocomplete="off" />
         <label for="color">Farbe</label><input id="color" list="colors" autocomplete="off" />
         <label for="manufacturer">Hersteller (optional)</label><input id="manufacturer" list="manufacturers" autocomplete="off" />
         <label for="diameter">Durchmesser</label><select id="diameter">${choices.diameters.map((d) => `<option value="${esc(d)}">${esc(d)} mm</option>`).join("")}</select>
         <label for="name">Name (leer = automatisch)</label><input id="name" autocomplete="off" />
         <label for="total">Gesamtgewicht in g (leer = Vorschlag)</label><input id="total" type="number" min="0" />
         <label for="remaining">Restgewicht in g (leer = voll)</label><input id="remaining" type="number" min="0" />
         ${list("materials", choices.materials)}${list("colors", choices.colors)}${list("manufacturers", choices.manufacturers)}`,
        [
          {
            label: "Anlegen",
            kind: "primary",
            run: (m) => {
              const value = (id) => m.querySelector(`#${id}`).value.trim();
              if (!value("material") || !value("color")) throw new Error("Material und Farbe angeben.");
              const data = {
                box_device_id: value("box"),
                material: value("material"),
                color: value("color"),
                manufacturer: value("manufacturer"),
                diameter: value("diameter"),
              };
              if (value("name")) data.name = value("name");
              if (value("total")) data.total_weight = Number(value("total"));
              if (value("remaining")) data.remaining_weight = Number(value("remaining"));
              return this._call("add_spool", data);
            },
          },
        ]
      );
    }
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

/**
 * Minimal visual editor: the (optional) card title, grouping, whether groups
 * start collapsed and the in-printer filter, so Lovelace's
 * "Visual editor not supported" fallback notice no longer shows up. Uses a
 * plain native <input> styled to match Home Assistant: <ha-textfield> is only
 * registered once some other part of the frontend has loaded it, so relying
 * on it can leave the editor rendering an empty, unusable form.
 *
 * The shadow DOM is built exactly once and the field's value is only synced
 * afterwards (skipped while it has focus). Rebuilding the whole form's
 * innerHTML on every keystroke - which setConfig() receives right back from
 * Lovelace after each config-changed event - would otherwise steal focus
 * from the field after every single character, making the title appear
 * impossible to edit.
 */
class FilamentManagerCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._renderOrSync();
  }

  set hass(hass) {
    this._hass = hass;
  }

  connectedCallback() {
    this._renderOrSync();
  }

  _renderOrSync() {
    if (!this._config) return;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this._renderShell();
    }
    this._syncField();
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>
        .form { padding: 16px 0; }
        label {
          display: block;
          font-size: 12px;
          margin: 0 0 4px 4px;
          color: var(--secondary-text-color);
        }
        label.spaced { margin-top: 16px; }
        select {
          box-sizing: border-box;
          width: 100%;
          height: 56px;
          padding: 0 12px;
          font: inherit;
          font-size: 16px;
          color: var(--primary-text-color);
          background: var(--input-fill-color, var(--secondary-background-color, rgba(0, 0, 0, 0.06)));
          border: none;
          border-bottom: 1px solid var(--input-idle-line-color, var(--secondary-text-color));
          border-radius: 4px 4px 0 0;
        }
        input[type="text"] {
          box-sizing: border-box;
          width: 100%;
          height: 56px;
          padding: 0 16px;
          font: inherit;
          font-size: 16px;
          color: var(--primary-text-color);
          background: var(--input-fill-color, var(--secondary-background-color, rgba(0, 0, 0, 0.06)));
          border: none;
          border-bottom: 1px solid var(--input-idle-line-color, var(--secondary-text-color));
          border-radius: 4px 4px 0 0;
          outline: none;
        }
        input[type="text"]:hover { border-bottom-color: var(--primary-text-color); }
        input[type="text"]:focus {
          border-bottom: 2px solid var(--primary-color);
          padding-bottom: 1px;
        }
        .option {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-top: 16px;
          padding: 0 4px;
          color: var(--primary-text-color);
          cursor: pointer;
        }
        .option input {
          width: 18px;
          height: 18px;
          margin: 0;
          padding: 0;
          accent-color: var(--primary-color);
          cursor: pointer;
        }
      </style>
      <div class="form">
        <label for="title">Titel (leer lassen für „Filament Manager“)</label>
        <input id="title" type="text" autocomplete="off" />
        <label for="group_by" class="spaced">Gruppieren nach</label>
        <select id="group_by">
          <option value="box">Filamentbox</option>
          <option value="material">Material</option>
          <option value="none">Nicht gruppieren</option>
        </select>
        <label class="option">
          <input id="collapse" type="checkbox" />
          Gruppen standardmäßig eingeklappt anzeigen
        </label>
        <label class="option">
          <input id="only_in_printer" type="checkbox" />
          Nur Spulen im Drucker anzeigen
        </label>
        <label class="option">
          <input id="dark_background" type="checkbox" />
          Dunklen Hintergrund verwenden (wie die Bambu-Lab-Karten)
        </label>
      </div>
    `;

    this.shadowRoot.querySelector("#title").addEventListener("input", (event) => {
      this._updateConfig("title", event.target.value || undefined);
    });
    this.shadowRoot.querySelector("#collapse").addEventListener("change", (event) => {
      this._updateConfig("collapse_boxes", event.target.checked || undefined);
    });
    this.shadowRoot.querySelector("#only_in_printer").addEventListener("change", (event) => {
      this._updateConfig("only_in_printer", event.target.checked || undefined);
    });
    this.shadowRoot.querySelector("#dark_background").addEventListener("change", (event) => {
      this._updateConfig("dark_background", event.target.checked || undefined);
    });
    this.shadowRoot.querySelector("#group_by").addEventListener("change", (event) => {
      this._updateConfig("group_by", event.target.value === "box" ? undefined : event.target.value);
    });
  }

  _syncField() {
    const field = this.shadowRoot.querySelector("#title");
    const desired = this._config.title || "";
    if (this.shadowRoot.activeElement !== field && field.value !== desired) {
      field.value = desired;
    }
    this.shadowRoot.querySelector("#collapse").checked = Boolean(this._config.collapse_boxes);
    this.shadowRoot.querySelector("#only_in_printer").checked = Boolean(this._config.only_in_printer);
    this.shadowRoot.querySelector("#dark_background").checked = Boolean(this._config.dark_background);
    this.shadowRoot.querySelector("#group_by").value = ["material", "none"].includes(this._config.group_by)
      ? this._config.group_by
      : "box";
  }

  /** Set (or, for `undefined`, remove) one config key and tell Lovelace. */
  _updateConfig(key, value) {
    const newConfig = { ...this._config };
    if (value === undefined) {
      delete newConfig[key];
    } else {
      newConfig[key] = value;
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

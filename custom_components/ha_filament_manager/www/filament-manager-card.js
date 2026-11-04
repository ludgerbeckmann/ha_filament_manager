/**
 * Filament Manager card.
 *
 * A dependency-free Lovelace card for the Filament Manager inventory: boxes,
 * the spools in them (remaining amount, material, color, humidity, printer
 * status) and the stock of sealed spools. The integration pushes a snapshot of
 * the inventory over the websocket (see websocket.py); no YAML configuration
 * is required. The pencil in the header switches on the edit mode, in which
 * spools and boxes are added, edited, moved, loaded into the printer and
 * removed through the integration's services.
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
  blau: "#2a45c0", // royal blue
  cyan: "#00bcd4",
  magenta: "#d4189a",
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
    // What the integration last sent (boxes, spools, AMS slots); see websocket.py.
    this._snapshot = null;
    this._unsubscribe = null;
    // Groups the viewer has toggled by hand (key -> collapsed?), which wins over
    // the card's `collapse_boxes` default. UI-only state, lost on reload.
    this._boxToggles = new Map();
    // Edit mode (the pencil in the header) shows the management actions.
    this._editMode = false;
    this._modalEl = null;
    this._optionsPromise = null;
  }

  // ------------------------------------------------------------------ config

  setConfig(config) {
    const previous = this._config;
    this._config = config || {};
    if (!previous) return;
    if (Boolean(previous.collapse_boxes) !== Boolean(this._config.collapse_boxes)) {
      this._boxToggles.clear(); // the default changed: apply it to every group
    }
    if (
      previous.group_by !== this._config.group_by ||
      Boolean(previous.only_in_printer) !== Boolean(this._config.only_in_printer) ||
      previous.appearance !== this._config.appearance ||
      Boolean(previous.dark_background) !== Boolean(this._config.dark_background) ||
      Boolean(previous.collapse_boxes) !== Boolean(this._config.collapse_boxes) ||
      previous.show_stock !== this._config.show_stock
    ) {
      this._lastSignature = undefined;
      this._renderIfReady();
    }
  }

  static getStubConfig() {
    return {};
  }

  static getConfigElement() {
    return document.createElement("filament-manager-card-editor");
  }

  /** "box" (default), "material" or "none"; anything else counts as "box". */
  _groupBy() {
    const value = this._config && this._config.group_by;
    return value === "material" || value === "none" ? value : "box";
  }

  /**
   * The colour scheme of the card: "dark" or "light" to force one, null to
   * follow the Home Assistant theme (the default). `appearance: system` follows
   * the device's setting; `dark_background: true` is the old spelling of `dark`.
   */
  _scheme() {
    const config = this._config || {};
    const appearance = config.appearance || (config.dark_background ? "dark" : "theme");
    if (appearance === "dark" || appearance === "light") return appearance;
    if (appearance === "system") {
      return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    return null;
  }

  _showStock() {
    return !(this._config && (this._config.show_stock === false || this._config.only_in_printer));
  }

  _isCollapsed(key) {
    return this._boxToggles.has(key) ? this._boxToggles.get(key) : Boolean(this._config && this._config.collapse_boxes);
  }

  /** Managing needs an admin (the services are not otherwise restricted). */
  _canManage() {
    return !(this._hass && this._hass.user && this._hass.user.is_admin === false);
  }

  // -------------------------------------------------------------- connection

  set hass(hass) {
    this._hass = hass;
    this._subscribe();
    this._renderIfReady();
  }

  connectedCallback() {
    this._subscribe();
    // "System" follows the device: draw again when its light/dark setting changes.
    if (window.matchMedia && !this._schemeQuery) {
      this._schemeQuery = window.matchMedia("(prefers-color-scheme: dark)");
      this._onSchemeChange = () => this._renderIfReady();
      this._schemeQuery.addEventListener("change", this._onSchemeChange);
    }
    this._renderIfReady();
  }

  disconnectedCallback() {
    if (this._schemeQuery) {
      this._schemeQuery.removeEventListener("change", this._onSchemeChange);
      this._schemeQuery = null;
    }
    const unsubscribe = this._unsubscribe;
    this._unsubscribe = null;
    if (unsubscribe) unsubscribe.then((unsub) => unsub()).catch(() => {});
  }

  /** Follow the inventory: the integration pushes a snapshot after every change. */
  _subscribe() {
    if (this._unsubscribe || !this._hass || !this.isConnected || !this._hass.connection) return;
    this._unsubscribe = this._hass.connection
      .subscribeMessage(
        (snapshot) => {
          this._snapshot = snapshot;
          this._error = null;
          this._lastSignature = undefined;
          this._renderIfReady();
        },
        { type: `${PLATFORM}/subscribe` }
      )
      .catch((err) => {
        this._unsubscribe = null;
        this._error = (err && err.message) || "Keine Verbindung zum Filament Manager.";
        this._lastSignature = undefined;
        this._renderIfReady();
        throw err;
      });
    this._unsubscribe.catch(() => {});
  }

  getCardSize() {
    const data = this._data;
    if (!data) return 2;
    const { groups, loose, stock } = this._layout(data);
    const rows =
      groups.reduce((sum, group) => sum + (this._isCollapsed(group.key) ? 1 : 1 + group.spools.length), 0) +
      loose.length +
      (stock.length ? 1 + stock.length : 0);
    return Math.max(1, rows) + 1;
  }

  _renderIfReady() {
    if (!this._hass || !this._config) return;
    const data = this._collectData();
    // Avoid tearing down/rebuilding the DOM on every state tick when nothing relevant changed.
    const signature = JSON.stringify([data, this._error, this._scheme()]);
    if (signature === this._lastSignature) return;
    this._lastSignature = signature;
    this._data = data;
    this._render(data);
  }

  // -------------------------------------------------------------------- data

  /** The snapshot, enriched with the live humidity of every box (those states change all the time). */
  _collectData() {
    const snapshot = this._snapshot;
    if (!snapshot) return null;
    const states = this._hass.states || {};

    const boxes = {};
    for (const box of snapshot.boxes) {
      const sensor = box.humidity_sensor ? states[box.humidity_sensor] : undefined;
      const value = sensor ? Number(sensor.state) : NaN;
      const alert = box.alert_entity ? states[box.alert_entity] : undefined;
      boxes[box.id] = {
        ...box,
        hasHumidity: !!box.humidity_sensor,
        humidityValue: Number.isFinite(value) ? value : null,
        humidityAlert: !!alert && alert.state === "on",
      };
    }
    const spools = snapshot.spools.map((spool) => ({
      ...spool,
      boxName: spool.box_id && boxes[spool.box_id] ? boxes[spool.box_id].name : null,
    }));
    return { boxes, spools, slots: snapshot.slots || [], cloud: snapshot.cloud, print: snapshot.print_notification, alerts: snapshot.alerts };
  }

  /**
   * What is drawn: header groups (a box, or a material) plus loose rows, the
   * stock of sealed spools, honouring `group_by` and `only_in_printer`.
   */
  _layout(data) {
    const byName = (a, b) => a.name.localeCompare(b.name);
    const onlyPrinter = Boolean(this._config && this._config.only_in_printer);
    const inBoxes = data.spools.filter((spool) => !spool.sealed && (!onlyPrinter || spool.in_printer));
    const stock = this._showStock() ? data.spools.filter((spool) => spool.sealed).sort(byName) : [];
    const mode = this._groupBy();

    if (mode === "none") return { groups: [], loose: [...inBoxes].sort(byName), stock };

    const groups = new Map();
    for (const spool of inBoxes) {
      const box = data.boxes[spool.box_id];
      const key = mode === "material" ? `material:${spool.material || "–"}` : spool.box_id;
      if (!groups.has(key)) {
        groups.set(
          key,
          mode === "material"
            ? { key, name: spool.material || "–", icon: "mdi:spool", spools: [], isBox: false }
            : { ...box, key, icon: "mdi:archive-outline", spools: [], isBox: true }
        );
      }
      groups.get(key).spools.push(spool);
    }
    // In box mode empty boxes show up too (they can be filled or removed), unless a filter hides spools.
    if (mode === "box" && !onlyPrinter) {
      for (const box of Object.values(data.boxes)) {
        if (!groups.has(box.id)) groups.set(box.id, { ...box, key: box.id, icon: "mdi:archive-outline", spools: [], isBox: true });
      }
    }
    const list = [...groups.values()].sort(byName);
    list.forEach((group) => group.spools.sort(byName));
    return { groups: list, loose: [], stock };
  }

  _openMoreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } }));
  }

  // ---------------------------------------------------------------- rendering

  /** "PLA Matte", "PETG CF (Kohlefaser)": the material with its variant, if any. */
  _materialLabel(spool) {
    return [spool.material, spool.variant].filter(Boolean).join(" ");
  }

  _swatch(spool, size = "") {
    const color = swatchFor(spool.color);
    const transparent = color === "transparent";
    return `<span class="${size}swatch ${transparent ? "transparent" : ""}" style="${transparent ? "" : `background:${color}`}" title="${esc(spool.color)}"></span>`;
  }

  _actions(...buttons) {
    return `<div class="actions">${buttons
      .map(([action, icon, title, id]) => `<ha-icon data-action="${action}" data-id="${esc(id)}" icon="${icon}" title="${esc(title)}"></ha-icon>`)
      .join("")}</div>`;
  }

  _renderSpoolRow(spool, data, { indent = false, showBox = false } = {}) {
    const percent = spool.percent;
    const tone = percentTone(percent);
    const barWidth = percent !== null ? Math.max(0, Math.min(100, percent)) : 0;
    const progressSub = `${percent !== null ? `${percent}%` : "–"} · ${spool.remaining_weight} g`;
    const box = data.boxes[spool.box_id];

    // In material/flat lists the humidity of the spool's box is shown per row.
    const humidity =
      showBox && box && box.hasHumidity
        ? `<div class="humidity-col" data-entity="${esc(box.humidity_sensor)}">
             <ha-icon class="humidity-badge ${box.humidityAlert ? "alert" : ""}" icon="${box.humidityAlert ? "mdi:water-alert" : "mdi:water-check"}" title="${box.humidityAlert ? "Luftfeuchtigkeit zu hoch" : "Luftfeuchtigkeit OK"}"></ha-icon>
             <span class="humidity-value ${box.humidityAlert ? "alert" : ""}">${box.humidityValue !== null ? `${box.humidityValue}%` : "–"}</span>
           </div>`
        : "";
    const printer = spool.in_printer
      ? `<ha-icon class="printer-badge" icon="mdi:printer-3d" title="Im Drucker${spool.ams_slot ? ` (${esc(spool.ams_slot)})` : ""}"></ha-icon>`
      : "";
    const meta = [this._materialLabel(spool), spool.color, showBox ? spool.boxName : null].filter(Boolean).join(" · ") || "&nbsp;";
    const edit = this._editMode && this._canManage();

    return `
      <div class="row ${indent ? "boxed" : ""} ${edit ? "edit" : ""}" data-entity="${esc(spool.entity_id)}">
        ${this._swatch(spool)}
        <div class="info">
          <div class="name">${esc(spool.name)}</div>
          <div class="meta">${esc(meta)}</div>
        </div>
        ${printer}
        <div class="progress-col">
          <div class="track"><div class="fill" style="width:${barWidth}%;background:${tone}"></div></div>
          <span class="progress-sub" style="color:${tone}">${esc(progressSub)}</span>
        </div>
        ${humidity}
        ${
          edit
            ? this._actions(
                ["load", spool.in_printer ? "mdi:printer-3d-nozzle" : "mdi:printer-3d", "In den Drucker laden / herausnehmen", spool.id],
                ["move", "mdi:swap-horizontal", "In andere Box verschieben", spool.id],
                ["edit-spool", "mdi:pencil-outline", "Spule bearbeiten", spool.id],
                ["delete-spool", "mdi:delete-outline", "Spule löschen", spool.id]
              )
            : ""
        }
      </div>`;
  }

  /** Identical sealed spools (same name, maker, material, colour, diameter, weight) are shown as one line. */
  _stockGroups(stock) {
    const groups = new Map();
    for (const spool of stock) {
      const key = [spool.name, spool.manufacturer, spool.material, spool.variant, spool.color, spool.diameter, spool.total_weight].join("|");
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(spool);
    }
    return [...groups.values()];
  }

  _renderStockRow(spools) {
    const edit = this._editMode && this._canManage();
    const first = spools[0];
    const last = spools[spools.length - 1];
    const meta = [this._materialLabel(first), first.color, first.manufacturer, `${first.total_weight} g`].filter(Boolean).join(" · ");
    const actions =
      spools.length === 1
        ? this._actions(
            ["open", "mdi:package-variant", "Spule öffnen (in eine Box legen)", first.id],
            ["edit-spool", "mdi:pencil-outline", "Spule bearbeiten", first.id],
            ["delete-spool", "mdi:delete-outline", "Spule löschen", first.id]
          )
        : this._actions(
            ["open", "mdi:package-variant", "Eine Rolle öffnen (in eine Box legen)", first.id],
            ["add-sealed", "mdi:plus", "Eine weitere Rolle hinzufügen", first.id],
            ["delete-spool", "mdi:minus", "Eine Rolle entfernen", last.id]
          );
    return `
      <div class="row boxed stock-row ${edit ? "edit" : ""}">
        ${this._swatch(first)}
        <div class="info">
          <div class="name">${spools.length > 1 ? `${spools.length} × ` : ""}${esc(first.name)}</div>
          <div class="meta">${esc(meta)}</div>
        </div>
        <span class="sealed-badge">verschlossen</span>
        ${edit ? actions : ""}
      </div>`;
  }

  /** The header row of a group (box, material) or of the stock, with its dots when collapsed. */
  _renderGroup(group, data) {
    const collapsed = this._isCollapsed(group.key);
    const showBox = this._groupBy() !== "box";
    const edit = this._editMode && this._canManage();

    const humidityValue = group.humidityValue !== null && group.humidityValue !== undefined ? `${Math.round(group.humidityValue)}%` : "–";
    const humidity =
      group.isBox && group.hasHumidity
        ? `<span class="box-humidity ${group.humidityAlert ? "alert" : ""}" data-entity="${esc(group.humidity_sensor)}">
             <ha-icon icon="${group.humidityAlert ? "mdi:water-alert" : "mdi:water-check"}"></ha-icon>
             <span class="box-humidity-value">${humidityValue}</span>
           </span>`
        : "";
    const dots = collapsed
      ? `<div class="box-swatches">${group.spools.map((spool) => this._swatch(spool, "mini-")).join("")}</div>`
      : "";
    const limit = group.isBox && group.spool_limit ? ` (${group.spools.length}/${group.spool_limit})` : "";
    const boxActions =
      edit && group.isBox
        ? this._actions(
            ["edit-box", "mdi:cog-outline", "Box bearbeiten", group.id],
            ...(group.count === 0 ? [["delete-box", "mdi:delete-outline", "Box löschen", group.id]] : [])
          )
        : "";

    return `
      <div class="box-header ${edit ? "edit" : ""}" data-toggle-box="${esc(group.key)}" title="${collapsed ? "Spulen anzeigen" : "Spulen ausblenden"}">
        <ha-icon class="box-toggle" icon="${collapsed ? "mdi:chevron-right" : "mdi:chevron-down"}"></ha-icon>
        <ha-icon class="box-icon" icon="${group.icon}"></ha-icon>
        <span class="box-name">${esc(group.name)}${esc(limit)}</span>
        ${dots}
        ${humidity}
        ${boxActions}
      </div>
      ${collapsed ? "" : group.spools.map((spool) => this._renderSpoolRow(spool, data, { indent: true, showBox })).join("")}
      ${!collapsed && !group.spools.length ? `<div class="empty-group">Keine Spulen</div>` : ""}
    `;
  }

  _renderStock(stock) {
    const collapsed = this._isCollapsed("stock");
    // One dot per colour, however many spools there are of it.
    const colours = [...new Map(stock.map((spool) => [(spool.color || "").toLowerCase(), spool])).values()];
    const dots = collapsed ? `<div class="box-swatches">${colours.map((spool) => this._swatch(spool, "mini-")).join("")}</div>` : "";
    return `
      <div class="box-header" data-toggle-box="stock" title="${collapsed ? "Vorrat anzeigen" : "Vorrat ausblenden"}">
        <ha-icon class="box-toggle" icon="${collapsed ? "mdi:chevron-right" : "mdi:chevron-down"}"></ha-icon>
        <ha-icon class="box-icon" icon="mdi:package-variant-closed"></ha-icon>
        <span class="box-name">Vorrat (${stock.length})</span>
        ${dots}
      </div>
      ${collapsed ? "" : this._stockGroups(stock).map((spools) => this._renderStockRow(spools)).join("")}
    `;
  }

  _renderHeader(title) {
    const manage = this._canManage();
    if (!title && !manage) return "";
    const toggle = manage
      ? `<ha-icon class="edit-toggle ${this._editMode ? "active" : ""}" icon="${this._editMode ? "mdi:check" : "mdi:pencil"}" data-action="toggle-edit" title="${this._editMode ? "Bearbeiten beenden" : "Spulen verwalten"}"></ha-icon>`
      : "";
    return `<div class="header"><span>${esc(title)}</span>${toggle}</div>`;
  }

  _render(data) {
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const title = this._config.title !== undefined ? this._config.title : "Filament Manager";

    let body;
    if (this._error) {
      body = `<div class="empty">${esc(this._error)}</div>`;
    } else if (!data) {
      body = `<div class="empty">Lade …</div>`;
    } else {
      const { groups, loose, stock } = this._layout(data);
      const parts = [
        ...groups.map((group) => this._renderGroup(group, data)),
        ...loose.map((spool) => this._renderSpoolRow(spool, data, { showBox: true })),
        ...(stock.length ? [this._renderStock(stock)] : []),
      ];
      body = parts.length
        ? `<div class="rows">${parts.join("")}</div>`
        : `<div class="empty">${
            data.spools.length
              ? "Keine Spule im Drucker."
              : 'Noch keine Filamentspulen. Mit dem Stift-Symbol oben rechts eine Box und Spulen anlegen.'
          }</div>`;
    }
    const buttons =
      this._editMode && this._canManage() && data
        ? `<div class="add-row"><button class="add-btn" data-action="add-spool">Spule anlegen</button><button class="add-btn" data-action="add-box">Box anlegen</button></div>
           <div class="add-row">
             ${data.alerts ? `<button class="add-btn" data-action="alerts">Warnungen</button>` : ""}
             ${data.print ? `<button class="add-btn" data-action="print-notification">Druck-Benachrichtigung${data.print.enabled ? " (aktiv)" : ""}</button>` : ""}
           </div>`
        : "";

    this.shadowRoot.innerHTML = `
      <style>

        ha-card { padding: 16px; }
        /* Like the Bambu Lab cards: a black card with light text, whatever the theme. */
        .scheme-dark {
          --ha-card-background: #1c1c1c;
          --card-background-color: #1c1c1c;
          --primary-text-color: #ffffff;
          --secondary-text-color: #a0a0a0;
          --divider-color: rgba(255, 255, 255, 0.12);
          --secondary-background-color: #2c2c2c;
          color-scheme: dark;
        }
        .scheme-light {
          --ha-card-background: #ffffff;
          --card-background-color: #ffffff;
          --primary-text-color: #212121;
          --secondary-text-color: #727272;
          --divider-color: #e0e0e0;
          --secondary-background-color: rgba(0, 0, 0, 0.06);
          color-scheme: light;
        }
        ha-card.scheme-dark, ha-card.scheme-light {
          background: var(--ha-card-background);
          color: var(--primary-text-color);
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
        .edit-toggle, .actions ha-icon { cursor: pointer; color: var(--secondary-text-color); }
        .edit-toggle { --mdc-icon-size: 22px; }
        .edit-toggle.active { color: var(--primary-color); }
        .actions { display: flex; gap: 6px; flex: none; }
        .actions ha-icon { --mdc-icon-size: 20px; }
        .actions ha-icon:hover { color: var(--primary-color); }
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
      
        .empty-group { color: var(--secondary-text-color); padding: 4px 0 8px 24px; font-size: 0.9em; }
        .sealed-badge { color: var(--secondary-text-color); font-size: 0.8em; border: 1px solid var(--divider-color); border-radius: 10px; padding: 1px 8px; flex: none; }
        .rows { container-type: inline-size; }
        /* Narrow cards (a phone): in the edit mode the progress bar and the actions get their own lines. */
        @container (max-width: 560px) {
          .row.edit { flex-wrap: wrap; row-gap: 8px; }
          .row.edit .info { flex: 1 1 0; min-width: 60%; }
          .row.edit .sealed-badge { order: 5; margin-right: auto; }
          .row.edit .progress-col { order: 5; flex: 1 1 0; width: auto; min-width: 130px; }
          .row.edit .actions { order: 6; flex: none; margin-left: auto; gap: 10px; }
          .row.edit .actions ha-icon, .box-header.edit .actions ha-icon { --mdc-icon-size: 24px; }
          .box-header.edit { flex-wrap: wrap; row-gap: 4px; }
          .box-header.edit .box-swatches { display: none; }
          .box-header.edit .actions { gap: 10px; margin-left: auto; }
        }
        /* Black and dark spools must stay visible on a dark card. */
        .scheme-dark .swatch, .scheme-dark .mini-swatch { border-color: rgba(255, 255, 255, 0.55); }
        .add-row { display: flex; gap: 8px; }
        .add-row .add-btn { flex: 1 1 0; }
        .modal .checks { display: flex; flex-direction: column; gap: 2px; }
        .modal label.check { display: flex; align-items: center; gap: 8px; margin: 8px 0 0 2px; font-size: 14px; color: var(--primary-text-color); }
        .modal label.check input { width: 18px; height: 18px; flex: none; accent-color: var(--primary-color); }
        .modal input[hidden], .modal div[hidden] { display: none; }

      </style>
      <ha-card class="${this._scheme() ? `scheme-${this._scheme()}` : ""}">
        ${this._renderHeader(title)}
        ${body}
        ${buttons}
      </ha-card>
    `;

    // Rows open the spool's remaining-weight entity; the humidity badges their sensor.
    this.shadowRoot.querySelectorAll(".row[data-entity], .humidity-col[data-entity], .box-humidity[data-entity]").forEach((element) => {
      const entityId = element.getAttribute("data-entity");
      if (!entityId) return;
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        this._openMoreInfo(entityId);
      });
    });

    // Clicking a header (name, icon, dots) collapses/expands its spools.
    this.shadowRoot.querySelectorAll(".box-header[data-toggle-box]").forEach((header) => {
      const key = header.getAttribute("data-toggle-box");
      header.addEventListener("click", () => {
        this._boxToggles.set(key, !this._isCollapsed(key));
        this._render(this._data);
      });
    });

    // Edit mode: the pencil, the row actions, the add buttons.
    this.shadowRoot.querySelectorAll("[data-action]").forEach((element) => {
      element.addEventListener("click", (event) => {
        event.stopPropagation();
        const action = element.getAttribute("data-action");
        if (action === "toggle-edit") {
          this._editMode = !this._editMode;
          if (this._editMode) this._loadOptions();
          this._render(this._data);
          return;
        }
        this._openDialog(action, element.getAttribute("data-id"));
      });
    });

    // A dialog that is open survives re-renders (and keeps what was typed).
    if (this._modalEl) {
      this._modalEl.className = `modal-backdrop ${this._scheme() ? `scheme-${this._scheme()}` : ""}`;
      this.shadowRoot.appendChild(this._modalEl);
    }
  }

  // ------------------------------------------------------------------ dialogs

  /** The dialogs' choices; fetched when the edit mode starts, so the dialogs open at once. */
  _loadOptions() {
    this._optionsPromise = this._hass
      .callWS({ type: `${PLATFORM}/options` })
      .catch(() => ({ materials: [], colors: [], manufacturers: [], diameters: ["1.75"] }));
    return this._optionsPromise;
  }

  async _call(service, data) {
    await this._hass.callService(PLATFORM, service, data);
  }

  _closeModal() {
    if (this._modalEl) this._modalEl.remove();
    this._modalEl = null;
  }

  /** The service errors of this integration, in German (the server's text is English). */
  _errorText(err) {
    const messages = {
      box_full: "Diese Filamentbox ist bereits voll.",
      box_not_empty: "In dieser Filamentbox liegen noch Spulen.",
      box_required: "Bitte eine Box wählen.",
      limit_below_count: "In der Box liegen schon mehr Spulen als dieses Limit erlaubt.",
      name_required: "Bitte einen Namen eingeben.",
      spool_sealed: "Die Spule ist verschlossen – erst in eine Box öffnen.",
      spool_not_found: "Die Spule wurde nicht gefunden.",
      box_not_found: "Die Filamentbox wurde nicht gefunden.",
      slot_unknown: "Das ist kein AMS-Slot der Bambu-Lab-Integration.",
      remaining_exceeds_total: "Das Restgewicht darf nicht größer als das Gesamtgewicht sein.",
    };
    if (err && messages[err.translation_key]) return messages[err.translation_key];
    const text = (err && (err.message || err.error)) || String(err);
    return text.replace(/^Validation error:\s*/, "");
  }

  /** Build a dialog; `actions` is a list of {label, busy, kind, run(modal)}. */
  _showModal(title, intro, fields, actions) {
    this._closeModal();
    const backdrop = document.createElement("div");
    backdrop.className = `modal-backdrop ${this._scheme() ? `scheme-${this._scheme()}` : ""}`;
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
      if (event.target === backdrop && !backdrop.dataset.busy) this._closeModal();
    });
    backdrop.querySelector('[data-modal="cancel"]').addEventListener("click", () => {
      if (!backdrop.dataset.busy) this._closeModal();
    });
    const buttons = [...backdrop.querySelectorAll("button")];
    actions.forEach((action, index) => {
      const button = backdrop.querySelector(`[data-modal="${index}"]`);
      button.addEventListener("click", async () => {
        if (backdrop.dataset.busy) return; // a second click must not start the action twice
        const errorBox = backdrop.querySelector(".error");
        errorBox.hidden = true;
        backdrop.dataset.busy = "1";
        buttons.forEach((b) => (b.disabled = true));
        button.textContent = `${action.busy || action.label} …`;
        try {
          await action.run(modal);
          this._closeModal();
        } catch (err) {
          delete backdrop.dataset.busy;
          buttons.forEach((b) => (b.disabled = false));
          button.textContent = action.label;
          errorBox.textContent = this._errorText(err);
          errorBox.hidden = false;
        }
      });
    });
    this._modalEl = backdrop;
    this.shadowRoot.appendChild(backdrop);
    return modal;
  }

  /** A dropdown with the known choices plus "own value", which reveals a text field. */
  _choiceField(id, label, items, { selected = "", optional = false } = {}) {
    const known = items.includes(selected) || (optional && !selected);
    const options = [
      ...(optional ? [`<option value="" ${selected ? "" : "selected"}>–</option>`] : []),
      ...items.map((item) => `<option value="${esc(item)}" ${item === selected ? "selected" : ""}>${esc(item)}</option>`),
      `<option value="__custom__" ${selected && !known ? "selected" : ""}>Eigene Eingabe …</option>`,
    ].join("");
    return `<label for="${id}">${esc(label)}</label>
      <select id="${id}" data-choice>${options}</select>
      <input id="${id}-custom" placeholder="${esc(label)}" autocomplete="off" value="${selected && !known ? esc(selected) : ""}" ${selected && !known ? "" : "hidden"} />`;
  }

  _wireChoices(modal) {
    modal.querySelectorAll("select[data-choice]").forEach((select) => {
      const custom = modal.querySelector(`#${select.id}-custom`);
      select.addEventListener("change", () => {
        custom.hidden = select.value !== "__custom__";
        if (!custom.hidden) custom.focus();
      });
    });
  }

  _choiceValue(modal, id) {
    const select = modal.querySelector(`#${id}`);
    return select.value === "__custom__" ? modal.querySelector(`#${id}-custom`).value.trim() : select.value;
  }

  /** A list of checkboxes (e.g. the notification targets); `modal.querySelectorAll('[name=id]:checked')` reads it back. */
  _checkList(id, label, items, selected, labels = {}) {
    const all = [...new Set([...items, ...selected])];
    if (!all.length) return "";
    const name = (entityId) =>
      labels[entityId] || (this._hass.states[entityId] && this._hass.states[entityId].attributes.friendly_name) || entityId;
    return `<label>${esc(label)}</label>
      <div class="checks">${all
        .map(
          (entityId) =>
            `<label class="check"><input type="checkbox" name="${id}" value="${esc(entityId)}" ${selected.includes(entityId) ? "checked" : ""} /> ${esc(name(entityId))}</label>`
        )
        .join("")}</div>`;
  }

  _checked(modal, id) {
    return [...modal.querySelectorAll(`[name="${id}"]:checked`)].map((input) => input.value);
  }

  _notifyTargets() {
    return Object.keys(this._hass.states).filter((entityId) => entityId.startsWith("notify."));
  }

  _isFull(box) {
    return box.spool_limit && this._data.spools.filter((spool) => spool.box_id === box.id).length >= box.spool_limit;
  }

  /** The boxes with room left (a box that is full takes no more spools). */
  _boxOptions(selected, exclude) {
    return Object.values(this._data.boxes)
      .sort((a, b) => a.name.localeCompare(b.name))
      .filter((box) => box.id !== exclude && !this._isFull(box))
      .map((box) => `<option value="${esc(box.id)}" ${box.id === selected ? "selected" : ""}>${esc(box.name)}</option>`)
      .join("");
  }

  async _openDialog(kind, id) {
    if (!this._optionsPromise) this._loadOptions();
    const data = this._data;
    const spool = data.spools.find((item) => item.id === id);
    const box = data.boxes[id];

    if (kind === "delete-spool" && spool) {
      this._showModal(
        spool.sealed ? "Rolle entfernen" : "Spule löschen",
        spool.sealed
          ? `Eine verschlossene Rolle „${spool.name}“ aus dem Vorrat entfernen?`
          : `„${spool.name}“ wirklich löschen? Die Entitäten und der Verlauf der Spule gehen verloren.`,
        "",
        [
          { label: spool.sealed ? "Entfernen" : "Löschen", busy: "Wird gelöscht", kind: "danger", run: () => this._call("remove_spool", { spool: id }) },
        ]
      );
    } else if (kind === "add-sealed" && spool) {
      // One more of the same sealed spool: no dialog, the plus is enough.
      this._call("add_spool", {
        name: spool.name,
        material: spool.material,
        color: spool.color,
        manufacturer: spool.manufacturer,
        diameter: spool.diameter,
        total_weight: spool.total_weight,
      }).catch((err) => this._showModal("Hinzufügen nicht möglich", this._errorText(err), "", []));
    } else if (kind === "alerts" && data.alerts) {
      this._dialogAlerts(data.alerts);
    } else if (kind === "delete-box" && box) {
      this._showModal("Box löschen", `Die leere Box „${box.name}“ wirklich löschen?`, "", [
        { label: "Löschen", busy: "Wird gelöscht", kind: "danger", run: () => this._call("remove_box", { box: id }) },
      ]);
    } else if ((kind === "move" || kind === "open") && spool) {
      const options = this._boxOptions(null, spool.box_id);
      const opening = kind === "open";
      if (!options) {
        this._showModal(opening ? "Spule öffnen" : "Spule verschieben", "Es gibt keine Filamentbox mit freiem Platz.", "", []);
        return;
      }
      this._showModal(
        opening ? "Spule öffnen" : "In andere Box verschieben",
        opening ? `„${spool.name}“ aus dem Vorrat nehmen und in eine Box legen.` : `„${spool.name}“ behält Entitäten, Verlauf und Restmenge.`,
        `<label for="box">${opening ? "Box" : "Zielbox"}</label><select id="box">${options}</select>`,
        [
          {
            label: opening ? "Öffnen" : "Verschieben",
            busy: opening ? "Wird geöffnet" : "Wird verschoben",
            kind: "primary",
            run: (m) => this._call(opening ? "open_spool" : "move_spool", { spool: id, box: m.querySelector("#box").value }),
          },
        ]
      );
    } else if (kind === "load" && spool) {
      this._dialogLoad(spool, data);
    } else if (kind === "add-spool") {
      await this._dialogAddSpool(data);
    } else if (kind === "edit-spool" && spool) {
      await this._dialogEditSpool(spool, data);
    } else if (kind === "add-box") {
      this._dialogBox(null, data);
    } else if (kind === "edit-box" && box) {
      this._dialogBox(box, data);
    } else if (kind === "print-notification" && data.print) {
      this._dialogPrintNotification(data.print);
    }
  }

  /** Where warnings go: one setting for all boxes (humidity) and spools (low stock). */
  _dialogAlerts(alerts) {
    this._showModal(
      "Warnungen",
      "Wohin Feuchtewarnungen (Boxen) und Bestandswarnungen (Spulen) gesendet werden – eine Einstellung für alle.",
      `${
        this._notifyTargets().length || alerts.targets.length
          ? this._checkList("targets", "Benachrichtigen", this._notifyTargets(), alerts.targets)
          : "<p>Keine Notify-Entitäten gefunden.</p>"
      }
       <label class="check"><input type="checkbox" id="persistent" ${alerts.persistent ? "checked" : ""} /> Dauerhafte Benachrichtigung in Home Assistant anzeigen</label>`,
      [
        {
          label: "Speichern",
          busy: "Wird gespeichert",
          kind: "primary",
          run: (m) =>
            this._call("set_alert_notifications", {
              notify_targets: this._checked(m, "targets"),
              persistent_notification: m.querySelector("#persistent").checked,
            }),
        },
      ]
    );
  }

  /** The Live Activity for Bambu Lab prints: printer, targets (Companion apps), what to show. */
  _dialogPrintNotification(print) {
    const printers = print.printers || [];
    const chosen = print.printer || (printers[0] && printers[0].serial) || "";
    const printerOptions = printers
      .map((p) => `<option value="${esc(p.serial)}" ${p.serial === chosen ? "selected" : ""}>${esc(p.name)}</option>`)
      .join("");
    // "mobile_app_iphone_ludger" -> "iphone ludger"
    const labels = Object.fromEntries(
      print.notify_services.map((name) => [name, name.replace(/^mobile_app_/, "").replace(/_/g, " ")])
    );
    const save = (m) =>
      this._call("set_print_notification", {
        enabled: m.querySelector("#enabled").checked,
        printer: printerOptions ? m.querySelector("#printer").value : "",
        targets: this._checked(m, "targets"),
        name: m.querySelector("#name").value.trim(),
        url: m.querySelector("#url").value.trim(),
        show_filament: m.querySelector("#show_filament").checked,
        countdown: m.querySelector("#countdown").checked,
      });
    const defaultName = (printers.find((p) => p.serial === chosen) || printers[0] || {}).name || "";
    this._showModal(
      "Druck-Benachrichtigung",
      "Zeigt den Fortschritt eines Bambu-Lab-Drucks als Live Activity auf iPhone/iPad (Live-Update bei Android) und meldet das Ende des Drucks.",
      `<label class="check"><input type="checkbox" id="enabled" ${print.enabled ? "checked" : ""} /> Aktiv</label>
       ${
         printerOptions
           ? `<label for="printer">Drucker</label><select id="printer">${printerOptions}</select>`
           : `<p>Keine Bambu-Lab-Drucker gefunden (Integration ha-bambulab nötig).</p>`
       }
       ${
         print.notify_services.length || print.targets.length
           ? this._checkList("targets", "Ziele (Companion-Apps)", print.notify_services, print.targets, labels)
           : `<p>Keine Companion-App gefunden (notify.mobile_app_…).</p>`
       }
       <label for="name">Anzeigename (leer = ${esc(defaultName || "Name des Druckers")})</label>
       <input id="name" autocomplete="off" placeholder="${esc(defaultName)}" value="${esc(print.name || "")}" />
       <label for="url">Beim Antippen öffnen (optional, z. B. /dashboard-3d-drucker)</label>
       <input id="url" autocomplete="off" value="${esc(print.url)}" />
       <label class="check"><input type="checkbox" id="countdown" ${print.countdown !== false ? "checked" : ""} /> Restzeit als laufenden Countdown zeigen (wie die Bambu-App)</label>
       <label class="check"><input type="checkbox" id="show_filament" ${print.show_filament ? "checked" : ""} /> Verwendete Spule nennen</label>`,
      [
        { label: "Speichern", busy: "Wird gespeichert", kind: "primary", run: save },
        {
          label: "Speichern und testen",
          busy: "Wird gesendet",
          run: async (m) => {
            await save(m);
            await this._call("test_print_notification", {});
          },
        },
      ]
    );
  }

  _dialogLoad(spool, data) {
    const hass = this._hass;
    const options = data.slots
      .map((slot) => {
        const state = hass.states[slot];
        const label = (state && (state.attributes.friendly_name || slot)) || slot;
        const content = state && state.attributes.name ? ` – ${state.attributes.name}` : state ? ` – ${state.state}` : "";
        const taken = data.spools.find((s) => s.ams_slot === slot && s.id !== spool.id);
        return `<option value="${esc(slot)}" ${spool.ams_slot === slot ? "selected" : ""}>${esc(label + content + (taken ? ` (jetzt: ${taken.name})` : ""))}</option>`;
      })
      .join("");
    const actions = [];
    if (options) {
      actions.push({
        label: "In den Drucker laden",
        busy: "Wird geladen",
        kind: "primary",
        run: (m) => this._call("load_spool", { spool: spool.id, slot: m.querySelector("#slot").value }),
      });
    }
    if (spool.ams_slot) {
      actions.push({ label: "Aus dem Drucker nehmen", busy: "Wird herausgenommen", run: () => this._call("unload_spool", { spool: spool.id }) });
    }
    this._showModal(
      "Spule in den Drucker",
      options
        ? `„${spool.name}“ einem AMS-Slot zuordnen. Die Spule, die bisher in diesem Slot war, wird herausgenommen.`
        : "Keine AMS-Slots gefunden (Integration Bambu Lab nötig).",
      options ? `<label for="slot">AMS-Slot</label><select id="slot">${options}</select>` : "",
      actions
    );
  }

  async _dialogAddSpool(data) {
    const choices = await this._optionsPromise;
    const first = choices.default_suggestion || {};
    const boxes = this._boxOptions(null, null);
    const modal = this._showModal(
      "Spule anlegen",
      "",
      `<label for="box">Ablage</label>
       <select id="box">${boxes}<option value="">Vorrat (verschlossen)</option></select>
       ${this._choiceField("material", "Material", choices.materials, { selected: choices.default_material })}
       ${this._choiceField("variant", "Variante, z. B. Matte, CF (optional)", choices.variants || [], { optional: true })}
       ${this._choiceField("color", "Farbe", choices.colors, { selected: choices.default_color })}
       ${this._choiceField("manufacturer", "Hersteller", choices.manufacturers, { selected: choices.manufacturers[0] || "" })}
       <label for="diameter">Durchmesser</label><select id="diameter">${(choices.diameters || ["1.75"]).map((d) => `<option value="${esc(d)}">${esc(d)} mm</option>`).join("")}</select>
       <label for="name">Name</label><input id="name" autocomplete="off" value="${esc(first.name || "")}" />
       <label for="total">Gesamtgewicht in g</label><input id="total" type="number" min="0" value="${esc(first.total_weight || "")}" />
       <div id="remaining-row"><label for="remaining">Restgewicht in g</label><input id="remaining" type="number" min="0" value="${esc(first.total_weight || "")}" /></div>`,
      [
        {
          label: "Anlegen",
          busy: "Wird angelegt",
          kind: "primary",
          run: (m) => {
            const value = (id) => m.querySelector(`#${id}`).value.trim();
            const material = this._choiceValue(m, "material");
            const color = this._choiceValue(m, "color");
            const manufacturer = this._choiceValue(m, "manufacturer");
            if (!material || !color || !manufacturer) throw new Error("Material, Farbe und Hersteller angeben.");
            const request = { material, color, manufacturer, diameter: value("diameter") };
            const variant = this._choiceValue(m, "variant");
            if (variant) request.variant = variant;
            if (value("box")) request.box = value("box");
            if (value("name")) request.name = value("name");
            if (value("total")) request.total_weight = Number(value("total"));
            if (value("box") && value("remaining")) request.remaining_weight = Number(value("remaining"));
            return this._call("add_spool", request);
          },
        },
      ]
    );
    this._wireChoices(modal);
    this._wireSuggestions(modal);
    // A sealed spool is full: no remaining weight to enter.
    const toggleRemaining = () => (modal.querySelector("#remaining-row").hidden = !modal.querySelector("#box").value);
    modal.querySelector("#box").addEventListener("change", toggleRemaining);
    toggleRemaining();
  }

  /**
   * Name, total and remaining weight are pre-filled with what the setup
   * suggests and follow the choices above - until they are edited by hand.
   */
  _wireSuggestions(modal, { weights = true } = {}) {
    const field = (id) => modal.querySelector(`#${id}`);
    ["name", ...(weights ? ["total", "remaining"] : [])].forEach((id) => {
      field(id).addEventListener("input", () => {
        field(id).dataset.touched = "1";
        // The remaining weight follows the total until it is set by hand.
        if (id === "total" && !field("remaining").dataset.touched) field("remaining").value = field("total").value;
      });
    });
    let latest = 0;
    const refresh = async () => {
      const request = ++latest;
      const material = this._choiceValue(modal, "material");
      const variant = this._choiceValue(modal, "variant");
      const color = this._choiceValue(modal, "color");
      const manufacturer = this._choiceValue(modal, "manufacturer");
      if (!material || !color || !manufacturer) return;
      let suggestion;
      try {
        suggestion = await this._hass.callWS({ type: `${PLATFORM}/suggest`, material, variant, color, manufacturer });
      } catch (err) {
        return;
      }
      if (request !== latest) return; // a newer choice is already on its way
      if (!field("name").dataset.touched) field("name").value = suggestion.name;
      if (weights && !field("total").dataset.touched) {
        field("total").value = suggestion.total_weight;
        if (!field("remaining").dataset.touched) field("remaining").value = suggestion.total_weight;
      }
    };
    ["material", "variant", "color", "manufacturer"].forEach((id) => {
      field(id).addEventListener("change", refresh);
      field(`${id}-custom`).addEventListener("input", refresh);
    });
  }

  async _dialogEditSpool(spool, data) {
    const choices = await this._optionsPromise;
    const hass = this._hass;
    const number = (value) => (value === null || value === undefined ? "" : value);
    const cloud = data.cloud
      ? `<label for="cloud_spool">Bambu-Cloud-Spule (– = automatisch per RFID)</label>
         <select id="cloud_spool"><option value="">–</option>${data.cloud
           .map((item) => `<option value="${esc(item.id)}" ${item.id === spool.cloud_spool ? "selected" : ""}>${esc(item.label)}</option>`)
           .join("")}</select>
         <label class="check"><input type="checkbox" id="cloud_sync" ${spool.cloud_sync ? "checked" : ""} /> Restmenge aus der Cloud übernehmen</label>`
      : "";
    const ams = spool.ams_slot
      ? `<label class="check"><input type="checkbox" id="ams_sync" ${spool.ams_sync ? "checked" : ""} /> Restmenge aus dem AMS übernehmen (nur Spulen mit RFID)</label>`
      : "";
    // The name follows the choices as long as it still is the suggested one (not an individual name).
    let followsSuggestion = false;
    try {
      const current = await this._hass.callWS({
        type: `${PLATFORM}/suggest`,
        material: spool.material,
        variant: spool.variant || "",
        color: spool.color,
        manufacturer: spool.manufacturer,
      });
      followsSuggestion = current.name === spool.name;
    } catch (err) {
      /* then the name stays as it is */
    }
    const modal = this._showModal(
      "Spule bearbeiten",
      "",
      `<label for="name">Name</label><input id="name" autocomplete="off" value="${esc(spool.name)}" />
       ${this._choiceField("material", "Material", choices.materials, { selected: spool.material })}
       ${this._choiceField("variant", "Variante, z. B. Matte, CF (optional)", choices.variants || [], { optional: true, selected: spool.variant || "" })}
       ${this._choiceField("color", "Farbe", choices.colors, { selected: spool.color })}
       ${this._choiceField("manufacturer", "Hersteller", choices.manufacturers, { selected: spool.manufacturer })}
       <label for="diameter">Durchmesser</label><select id="diameter">${(choices.diameters || ["1.75"])
         .map((d) => `<option value="${esc(d)}" ${d === spool.diameter ? "selected" : ""}>${esc(d)} mm</option>`)
         .join("")}</select>
       <label for="total">Gesamtgewicht in g</label><input id="total" type="number" min="0" value="${esc(spool.total_weight)}" />
       <label for="low">Bestandswarnung unter … % (leer = aus)</label><input id="low" type="number" min="0" max="100" value="${esc(number(spool.low_stock_threshold))}" />
       ${ams}${cloud}`,
      [
        {
          label: "Speichern",
          busy: "Wird gespeichert",
          kind: "primary",
          run: (m) => {
            const value = (id) => m.querySelector(`#${id}`).value.trim();
            const material = this._choiceValue(m, "material");
            const color = this._choiceValue(m, "color");
            const manufacturer = this._choiceValue(m, "manufacturer");
            if (!value("name") || !material || !color || !manufacturer) throw new Error("Name, Material, Farbe und Hersteller angeben.");
            const request = {
              spool: spool.id,
              name: value("name"),
              material,
              color,
              manufacturer,
              variant: this._choiceValue(m, "variant"),
              diameter: value("diameter"),
              low_stock_threshold: value("low") === "" ? "" : Number(value("low")),
            };
            if (value("total")) request.total_weight = Number(value("total"));
            if (m.querySelector("#ams_sync")) request.ams_sync = m.querySelector("#ams_sync").checked;
            if (m.querySelector("#cloud_spool")) {
              request.cloud_spool = value("cloud_spool");
              request.cloud_sync = m.querySelector("#cloud_sync").checked;
            }
            return this._call("update_spool", request);
          },
        },
      ]
    );
    this._wireChoices(modal);
    this._wireSuggestions(modal, { weights: false });
    if (!followsSuggestion) modal.querySelector("#name").dataset.touched = "1"; // an individual name stays
  }

  _dialogBox(box, data) {
    const hass = this._hass;
    const sensors = Object.keys(hass.states).filter(
      (entityId) => entityId.startsWith("sensor.") && hass.states[entityId].attributes.device_class === "humidity"
    );
    if (box && box.humidity_sensor && !sensors.includes(box.humidity_sensor)) sensors.push(box.humidity_sensor);
    const sensorOptions = sensors
      .sort()
      .map((entityId) => {
        const name = hass.states[entityId] ? hass.states[entityId].attributes.friendly_name || entityId : entityId;
        return `<option value="${esc(entityId)}" ${box && box.humidity_sensor === entityId ? "selected" : ""}>${esc(name)}</option>`;
      })
      .join("");
    const number = (value) => (value === null || value === undefined ? "" : value);
    this._showModal(
      box ? "Box bearbeiten" : "Box anlegen",
      "",
      `<label for="name">Name</label><input id="name" autocomplete="off" value="${esc(box ? box.name : "")}" />
       <label for="sensor">Luftfeuchtigkeitssensor (optional)</label>
       <select id="sensor"><option value="">–</option>${sensorOptions}</select>
       <label for="max">Maximale Luftfeuchtigkeit in % (leer = automatisch${box ? `, aktuell ${box.effective_humidity_max} %` : ""})</label>
       <input id="max" type="number" min="0" max="100" value="${esc(number(box && box.humidity_max))}" />
       <label for="delay">Warnen erst nach … Minuten (leer = automatisch${box ? `, aktuell ${box.effective_humidity_delay}` : ""})</label>
       <input id="delay" type="number" min="0" value="${esc(number(box && box.humidity_delay))}" />
       <label for="limit">Maximale Spulenanzahl (leer = unbegrenzt)</label>
       <input id="limit" type="number" min="1" value="${esc(number(box && box.spool_limit))}" />
       `,
      [
        {
          label: box ? "Speichern" : "Anlegen",
          busy: box ? "Wird gespeichert" : "Wird angelegt",
          kind: "primary",
          run: (m) => {
            const value = (id) => m.querySelector(`#${id}`).value.trim();
            if (!value("name")) throw new Error("Bitte einen Namen eingeben.");
            const request = {
              name: value("name"),
              humidity_sensor: value("sensor"),
              humidity_max: value("max") === "" ? "" : Number(value("max")),
              humidity_delay: value("delay") === "" ? "" : Number(value("delay")),
              spool_limit: value("limit") === "" ? "" : Number(value("limit")),
            };
            return box ? this._call("update_box", { box: box.id, ...request }) : this._call("add_box", request);
          },
        },
      ]
    );
  }
}

customElements.define("filament-manager-card", FilamentManagerCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "filament-manager-card",
  name: "Filament Manager",
  description: "Filamentboxen, Spulen und Vorrat verwalten (Füllstand, Material, Farbe, Luftfeuchtigkeit, Drucker).",
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
          <input id="show_stock" type="checkbox" />
          Vorrat (verschlossene Spulen) anzeigen
        </label>
        <label for="appearance" class="spaced">Darstellung</label>
        <select id="appearance">
          <option value="theme">Wie das Theme von Home Assistant (Standard)</option>
          <option value="light">Hell</option>
          <option value="dark">Dunkel (wie die Bambu-Lab-Karten)</option>
          <option value="system">Wie die Einstellung des Geräts (System)</option>
        </select>
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
    this.shadowRoot.querySelector("#show_stock").addEventListener("change", (event) => {
      this._updateConfig("show_stock", event.target.checked ? undefined : false);
    });
    this.shadowRoot.querySelector("#appearance").addEventListener("change", (event) => {
      const config = { ...this._config };
      delete config.dark_background; // replaced by `appearance`
      this._config = config;
      this._updateConfig("appearance", event.target.value === "theme" ? undefined : event.target.value);
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
    this.shadowRoot.querySelector("#appearance").value =
      this._config.appearance || (this._config.dark_background ? "dark" : "theme");
    this.shadowRoot.querySelector("#show_stock").checked = this._config.show_stock !== false;
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

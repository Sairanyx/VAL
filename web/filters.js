// What the operator wants to see. One set of filters for the frames, labels, Map, Objects panel,
// BIM mode, clicks and alerts, so they can't disagree. Val sets the same filters by voice.
import { CONDITION_GROUPS, TYPE_GROUPS, hex } from "./colors.js";

const STORE_KEY = "viewer-filters";
export const ALERT_LEVELS = {
  off: { text: "Off", states: [] },
  attention: { text: "Attention only", states: ["attention_required"] },
  degraded: { text: "Attention and degraded", states: ["attention_required", "degraded"] },
  all: { text: "All", states: ["attention_required", "degraded", "watch"] },
};
const MOBILITY = { any: "Any", movable: "Movable", fixed: "Fixed" };
const KNOWN_LABELS = new Set(TYPE_GROUPS.flatMap((group) => group.labels));

export function typesOf(object) {
  const label = object.asset.label;
  const record = object.condition?.asset_class ?? "";
  const found = TYPE_GROUPS.filter(
    (group) => group.labels.includes(label) || (group.record && record.match(group.record)),
  ).map((group) => group.key);
  if (!KNOWN_LABELS.has(label)) found.push("other");
  return found;
}

export function setupFilters({ ui, objects, onChange }) {
  const state = {
    types: new Set(), // empty means every type
    conditions: new Set(), // empty means every condition
    mobility: "any",
    alerts: "attention",
  };

  try {
    const saved = JSON.parse(localStorage.getItem(STORE_KEY) ?? "{}");
    if (ALERT_LEVELS[saved.alerts]) state.alerts = saved.alerts;
  } catch {
    // A convenience only: the default is fine.
  }

  const isActive = () =>
    state.types.size > 0 || state.conditions.size > 0 || state.mobility !== "any";

  function passes(object) {
    if (state.types.size && !typesOf(object).some((key) => state.types.has(key))) return false;
    if (state.conditions.size) {
      const condition = object.condition?.condition_state ?? "none";
      if (!state.conditions.has(condition)) return false;
    }
    if (state.mobility !== "any" && object.asset.mobility !== state.mobility) return false;
    return true;
  }

  const alertStates = () => ALERT_LEVELS[state.alerts].states;

  async function refreshConditions() {
    const reply = await fetch("/api/assets")
      .then((response) => (response.ok ? response.json() : null))
      .catch(() => null);
    if (!reply) return;
    const byId = new Map(reply.assets.map((asset) => [asset.object_id, asset.condition ?? null]));
    for (const object of objects) object.condition = byId.get(object.asset.object_id) ?? null;
    render();
  }

  function chip(text, active, color, count, onClick) {
    const button = document.createElement("button");
    button.className = `filter-chip${active ? " on" : ""}`;
    button.setAttribute("aria-pressed", String(active));
    if (color !== undefined) {
      const swatch = document.createElement("i");
      swatch.style.background = hex(color);
      button.append(swatch);
    }
    button.append(count === undefined ? text : `${text} ${count}`);
    button.onclick = onClick;
    return button;
  }

  function toggle(set, key) {
    if (set.has(key)) set.delete(key);
    else set.add(key);
    changed();
  }

  function render() {
    const here = objects.filter((object) => !object.gone);
    const types = TYPE_GROUPS.map((group) => {
      const count = here.filter((object) => typesOf(object).includes(group.key)).length;
      if (!count) return null;
      return chip(group.text, state.types.has(group.key), group.color, count, () =>
        toggle(state.types, group.key),
      );
    });
    ui.types.replaceChildren(...types.filter(Boolean));
    ui.conditions.replaceChildren(
      ...CONDITION_GROUPS.map((group) => {
        const count = here.filter(
          (object) => (object.condition?.condition_state ?? "none") === group.key,
        ).length;
        return chip(group.text, state.conditions.has(group.key), group.color, count, () =>
          toggle(state.conditions, group.key),
        );
      }),
    );
    ui.mobility.replaceChildren(
      ...Object.entries(MOBILITY).map(([key, text]) =>
        chip(text, state.mobility === key, undefined, undefined, () => {
          state.mobility = key;
          changed();
        }),
      ),
    );
    ui.alerts.replaceChildren(
      ...Object.entries(ALERT_LEVELS).map(([key, level]) =>
        chip(level.text, state.alerts === key, undefined, undefined, () => {
          state.alerts = key;
          changed();
        }),
      ),
    );
    const shown = here.filter(passes).length;
    ui.count.textContent = `Showing ${shown} of ${here.length} objects`;
    const active = state.types.size + state.conditions.size + (state.mobility !== "any" ? 1 : 0);
    ui.button.textContent = active ? `Filters (${active})` : "Filters";
    ui.button.classList.toggle("active-filter", active > 0);
  }

  function changed() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({ alerts: state.alerts }));
    } catch {
      // A convenience only.
    }
    render();
    onChange?.();
  }

  function clear() {
    state.types.clear();
    state.conditions.clear();
    state.mobility = "any";
    changed();
  }

  // Replace what's shown, as asked for by voice. Unknown words have already been refused by then.
  function set({ types, conditions, mobility }) {
    if (types) state.types = new Set(types);
    if (conditions) state.conditions = new Set(conditions);
    if (mobility) state.mobility = mobility;
    changed();
  }

  function hideTypes(keys) {
    const start = state.types.size ? [...state.types] : TYPE_GROUPS.map((group) => group.key);
    state.types = new Set(start.filter((key) => !keys.includes(key)));
    changed();
  }

  function setAlerts(level) {
    if (!ALERT_LEVELS[level]) throw new Error(`Use one of ${Object.keys(ALERT_LEVELS).join(", ")}`);
    state.alerts = level;
    changed();
  }

  ui.clear.onclick = clear;
  ui.close.onclick = () => (ui.panel.hidden = true);
  ui.button.onclick = () => {
    ui.panel.hidden = !ui.panel.hidden;
    if (!ui.panel.hidden) refreshConditions();
  };
  render();
  refreshConditions();

  return { state, isActive, passes, alertStates, refreshConditions, clear, set, hideTypes, setAlerts };
}

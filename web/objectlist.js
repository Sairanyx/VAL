// Objects panel: a closable side list of the equipment, most important first, with each object's
// condition from the Excel pack. Tap a row to select the object and open its details.
//
// Importance: condition state, then urgency, then criticality, then the lowest health. Only objects
// linked to an Excel record have a condition; the rest of the detections can be shown below them.

const STATE_RANK = { attention_required: 3, degraded: 2, watch: 1, healthy: 0 };
const URGENCY_RANK = { high: 2, medium: 1, routine: 0 };
const STATE_TEXT = {
  attention_required: "Attention required",
  degraded: "Degraded",
  watch: "Watch",
  healthy: "Healthy",
};
const STATE_COLOR = {
  attention_required: "#ef4444",
  degraded: "#f59e0b",
  watch: "#eab308",
  healthy: "#22c55e",
};
const NO_RECORD_COLOR = "#6b7280";

function criticalityRank(text) {
  const letter = (text ?? "").trim()[0];
  return { A: 2, B: 1, C: 0 }[letter] ?? -1;
}

// Larger is more important. Objects without a record come last.
function importance(condition) {
  if (!condition) return [-1, -1, -1, 0];
  return [
    STATE_RANK[condition.condition_state] ?? 0,
    URGENCY_RANK[condition.urgency] ?? 0,
    criticalityRank(condition.criticality),
    100 - (condition.health_score ?? 100),
  ];
}

function compareImportance(a, b) {
  const x = importance(a.condition);
  const y = importance(b.condition);
  for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return y[i] - x[i];
  return 0;
}

function pretty(text) {
  return (text ?? "").toLowerCase().replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function setupObjectList({ panel, list, search, sort, unlinked, count, objects, nameOf, onSelect }) {
  const state = { open: false, rows: [] };

  async function load() {
    const reply = await fetch("/api/assets")
      .then((response) => (response.ok ? response.json() : null))
      .catch(() => null);
    const conditions = new Map((reply?.assets ?? []).map((a) => [a.object_id, a.condition]));
    state.rows = objects
      .filter((object) => !object.gone)
      .map((object) => ({ object, condition: conditions.get(object.asset.object_id) ?? null }));
  }

  function matches(row, wanted) {
    if (!wanted) return true;
    const a = row.object.asset;
    const c = row.condition ?? {};
    return [nameOf(row.object), a.label, a.object_id, c.asset_class, c.issue_summary, c.area_name]
      .filter(Boolean)
      .some((text) => text.toLowerCase().includes(wanted));
  }

  function render() {
    const wanted = search.value.trim().toLowerCase();
    const rows = state.rows
      .filter((row) => (unlinked.checked || row.condition) && matches(row, wanted))
      .sort((a, b) => {
        if (sort.value === "health") {
          return (a.condition?.health_score ?? 101) - (b.condition?.health_score ?? 101);
        }
        if (sort.value === "name") return nameOf(a.object).localeCompare(nameOf(b.object));
        return compareImportance(a, b);
      });
    count.textContent = `${rows.length} shown`;
    list.replaceChildren(...rows.map(rowElement));
  }

  function rowElement({ object, condition }) {
    const item = document.createElement("li");
    item.className = "object-row";
    const color = condition ? STATE_COLOR[condition.condition_state] : NO_RECORD_COLOR;
    item.style.setProperty("--state", color ?? NO_RECORD_COLOR);

    const head = document.createElement("div");
    head.className = "object-row-head";
    const dot = document.createElement("span");
    dot.className = "object-dot";
    const title = document.createElement("strong");
    title.textContent = nameOf(object);
    const kind = document.createElement("span");
    kind.className = "object-kind";
    kind.textContent = condition ? pretty(condition.asset_class) : pretty(object.asset.label);
    head.append(dot, title, kind);
    item.append(head);

    if (condition) {
      const health = document.createElement("div");
      health.className = "object-health";
      const bar = document.createElement("span");
      bar.style.width = `${Math.max(0, Math.min(100, condition.health_score ?? 0))}%`;
      const number = document.createElement("em");
      number.textContent = `Health ${condition.health_score ?? "?"}`;
      health.append(bar, number);

      const facts = document.createElement("div");
      facts.className = "object-facts";
      facts.textContent = [
        STATE_TEXT[condition.condition_state] ?? pretty(condition.condition_state),
        condition.urgency && `${pretty(condition.urgency)} urgency`,
        condition.criticality,
      ]
        .filter(Boolean)
        .join(" · ");

      const issue = document.createElement("div");
      issue.className = "object-issue";
      issue.textContent = condition.issue_summary ?? "";
      item.append(health, facts, issue);
    } else {
      const facts = document.createElement("div");
      facts.className = "object-facts";
      facts.textContent = "No Excel record: detected in the scan only";
      item.append(facts);
    }

    item.tabIndex = 0;
    item.onclick = () => onSelect(object);
    item.onkeydown = (event) => {
      if (event.key === "Enter") onSelect(object);
    };
    return item;
  }

  async function open() {
    state.open = true;
    panel.hidden = false;
    list.replaceChildren();
    count.textContent = "Loading...";
    await load(); // each time, as conditions and objects change
    render();
  }

  function close() {
    state.open = false;
    panel.hidden = true;
  }

  function toggle() {
    if (state.open) close();
    else open();
  }

  search.addEventListener("input", render);
  sort.addEventListener("change", render);
  unlinked.addEventListener("change", render);

  return { state, open, close, toggle };
}

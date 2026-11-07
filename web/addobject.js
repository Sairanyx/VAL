// Add an object the scan's detection missed: drag a box or tap it, check the proposal, and save.
// Code measures the object and a vision model may suggest a label. Nothing saves until confirmed.
import * as THREE from "three";

const TAP_SIZE = 12; // pixels: a smaller drag counts as a tap
const TAP_HALF = 70; // pixels around a tap to search for an object
const RESIZE_STEP = 1.15;
const PREVIEW_COLOR = 0xf59e0b;
const REST_COLOR = 0x38bdf8;
const LABELS = [
  "object",
  "cart",
  "box",
  "bucket",
  "barrel",
  "bag",
  "chair",
  "ladder",
  "tool",
  "pump",
  "motor",
  "valve",
  "pipe",
  "pipe fitting",
  "tank",
  "gauge",
  "sensor",
  "electrical cabinet",
  "control panel",
  "hose",
  "cable",
  "other",
];
const MOBILITY = ["unsure", "movable", "fixed"];

function fillSelect(select, options) {
  select.replaceChildren(
    ...options.map((value) => {
      const option = document.createElement("option");
      option.textContent = value;
      return option;
    }),
  );
}

export function setupAddObject({
  canvas,
  root,
  camera,
  render,
  ui,
  onSaved,
  onSplit,
  onCombine,
  onMessage,
}) {
  // `parent` is set while splitting an object, and `rest` then holds the part not selected.
  // `combining` holds the first of two objects being joined, until the second is chosen.
  const state = {
    active: false,
    proposal: null,
    start: null,
    parent: null,
    rest: null,
    combining: null,
    other: null,
  };
  const preview = new THREE.LineSegments(
    new THREE.BufferGeometry(),
    new THREE.LineBasicMaterial({ color: PREVIEW_COLOR, depthTest: false, transparent: true }),
  );
  preview.visible = false;
  preview.renderOrder = 11;
  root.add(preview);
  const restPreview = new THREE.LineSegments(
    new THREE.BufferGeometry(),
    new THREE.LineBasicMaterial({ color: REST_COLOR, depthTest: false, transparent: true }),
  );
  restPreview.visible = false;
  restPreview.renderOrder = 11;
  root.add(restPreview);
  fillSelect(ui.label, LABELS);
  fillSelect(ui.mobility, MOBILITY);
  fillSelect(ui.restLabel, LABELS);
  fillSelect(ui.restMobility, MOBILITY);

  function config() {
    const p = state.proposal;
    return {
      bbox_min: p.bbox_min,
      bbox_max: p.bbox_max,
      label: ui.label.value,
      label_confidence: p.label_confidence,
      label_source: ui.label.value === p.label ? p.label_source : "operator",
      mobility: ui.mobility.value,
      mobility_reason: ui.mobility.value === p.mobility ? p.mobility_reason : "set by operator",
      reason: p.reason,
      visible_text: p.visible_text,
      possible_tag: p.possible_tag,
    };
  }

  function drawBox(lines, box) {
    const min = new THREE.Vector3(...box.bbox_min);
    const max = new THREE.Vector3(...box.bbox_max);
    const size = max.clone().sub(min);
    lines.geometry.dispose();
    lines.geometry = new THREE.EdgesGeometry(new THREE.BoxGeometry(size.x, size.y, size.z));
    lines.position.copy(min).add(max).multiplyScalar(0.5);
    lines.visible = true;
  }

  function restConfig() {
    const rest = state.rest;
    return {
      bbox_min: rest.bbox_min,
      bbox_max: rest.bbox_max,
      label: ui.restLabel.value,
      label_confidence: rest.label_confidence,
      label_source: ui.restLabel.value === rest.label ? rest.label_source : "operator",
      mobility: ui.restMobility.value,
      mobility_reason:
        ui.restMobility.value === rest.mobility ? rest.mobility_reason : "set by operator",
      reason: rest.reason,
      visible_text: rest.visible_text,
      possible_tag: rest.possible_tag,
    };
  }

  function drawProposal() {
    drawBox(preview, state.proposal);
    if (state.rest) drawBox(restPreview, state.rest);
    const shown = state.rest ? { selected: config(), rest: restConfig() } : config();
    ui.config.textContent = JSON.stringify(shown, null, 1);
  }

  function finish() {
    state.active = false;
    state.proposal = null;
    state.parent = null;
    state.rest = null;
    state.combining = null;
    state.other = null;
    preview.visible = false;
    restPreview.visible = false;
    ui.restRow.hidden = true;
    ui.title.textContent = "Add object";
    ui.frame.hidden = true;
    ui.panel.hidden = true;
    canvas.style.cursor = "";
  }

  function showProposal(proposal) {
    state.proposal = proposal;
    if (!LABELS.includes(proposal.label)) {
      LABELS.push(proposal.label);
      fillSelect(ui.label, LABELS);
    }
    ui.label.value = proposal.label;
    ui.mobility.value = proposal.mobility;
    const notes = [`${proposal.splats.toLocaleString()} splats`];
    if (proposal.label_source !== "not suggested") notes.push(`Suggested: ${proposal.label}`);
    if (proposal.reason) notes.push(proposal.reason);
    if (proposal.visible_text) notes.push(`Text seen: ${proposal.visible_text}`);
    if (proposal.possible_tag) notes.push(`May be ${proposal.possible_tag}: not linked`);
    ui.notes.textContent = notes.join(" · ");
    const known = proposal.already_known;
    const more = known.length > 3 ? ` and ${known.length - 3} more` : "";
    ui.warning.textContent = known.length
      ? `Overlaps ${known.slice(0, 3).join(", ")}${more}: it may already exist, or the box is too big.`
      : "";
    ui.panel.hidden = false;
    drawProposal();
  }

  function setRest(rest) {
    state.rest = rest;
    if (!LABELS.includes(rest.label)) {
      LABELS.push(rest.label);
      fillSelect(ui.restLabel, LABELS);
    }
    ui.restLabel.value = rest.label;
    ui.restMobility.value = rest.mobility;
    ui.restRow.hidden = false;
    ui.title.textContent = "Split object";
  }

  // The rest of a split has no selection of its own, so take its place on screen from its box.
  function screenRectangle(box) {
    let left = 1;
    let top = 1;
    let right = 0;
    let bottom = 0;
    for (const x of [box.bbox_min[0], box.bbox_max[0]]) {
      for (const y of [box.bbox_min[1], box.bbox_max[1]]) {
        for (const z of [box.bbox_min[2], box.bbox_max[2]]) {
          const point = root.localToWorld(new THREE.Vector3(x, y, z)).project(camera);
          left = Math.min(left, (point.x + 1) / 2);
          right = Math.max(right, (point.x + 1) / 2);
          top = Math.min(top, (1 - point.y) / 2);
          bottom = Math.max(bottom, (1 - point.y) / 2);
        }
      }
    }
    return [Math.max(left, 0), Math.max(top, 0), Math.min(right, 1), Math.min(bottom, 1)];
  }

  async function suggestRest(image) {
    const [left, top, right, bottom] = screenRectangle(state.rest);
    if (right <= left || bottom <= top) return;
    try {
      const response = await fetch("/api/objects/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image, rectangle: [left, top, right, bottom] }),
      });
      if (!response.ok || !state.rest) return;
      const suggestion = await response.json();
      Object.assign(state.rest, suggestion);
      setRest(state.rest);
      drawProposal();
    } catch {
      // The operator can still choose: a suggestion is only ever a help.
    }
  }

  // Rays from the camera through the selection's corners, in scene coordinates.
  function selectionRays(left, top, right, bottom) {
    const origin = root.worldToLocal(camera.position.clone());
    const corners = [
      [left, top],
      [right, top],
      [right, bottom],
      [left, bottom],
    ].map(([x, y]) => {
      const ndc = new THREE.Vector3((x / innerWidth) * 2 - 1, -(y / innerHeight) * 2 + 1, 0.5);
      return root.worldToLocal(ndc.unproject(camera)).sub(origin).normalize().toArray();
    });
    return { origin: origin.toArray(), corners };
  }

  async function select(left, top, right, bottom) {
    camera.updateMatrixWorld();
    render(); // A screenshot needs a frame drawn in this same moment.
    const image = canvas.toDataURL("image/jpeg", 0.9);
    const body = {
      ...selectionRays(left, top, right, bottom),
      rectangle: [left / innerWidth, top / innerHeight, right / innerWidth, bottom / innerHeight],
      image,
    };
    onMessage("Measuring the selection...");
    try {
      const splitting = state.parent;
      const address = splitting
        ? `/api/objects/${encodeURIComponent(splitting.asset.object_id)}/split/propose`
        : "/api/objects/propose";
      const response = await fetch(address, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const reply = await response.json();
      if (!response.ok) throw new Error(reply.detail ?? `Backend error ${response.status}`);
      if (splitting) {
        setRest(reply.rest);
        showProposal({ ...reply.part, already_known: [] });
        onMessage("Orange is what you selected, and blue is the rest. Check both, then save");
        suggestRest(image);
      } else {
        showProposal(reply);
        onMessage("Check the orange box and the settings, then save");
      }
    } catch (error) {
      onMessage(`${state.parent ? "Couldn't split it" : "Couldn't add an object"}: ${error.message}`);
    }
  }

  canvas.addEventListener(
    "pointerdown",
    (event) => {
      if (!state.active || state.proposal) return;
      event.stopPropagation();
      event.preventDefault();
      state.start = { x: event.clientX, y: event.clientY };
      ui.frame.hidden = false;
    },
    true,
  );
  window.addEventListener(
    "pointermove",
    (event) => {
      if (!state.start) return;
      event.stopPropagation();
      ui.frame.style.left = `${Math.min(state.start.x, event.clientX)}px`;
      ui.frame.style.top = `${Math.min(state.start.y, event.clientY)}px`;
      ui.frame.style.width = `${Math.abs(event.clientX - state.start.x)}px`;
      ui.frame.style.height = `${Math.abs(event.clientY - state.start.y)}px`;
    },
    true,
  );
  window.addEventListener(
    "pointerup",
    (event) => {
      if (!state.start) return;
      event.stopPropagation();
      const { x, y } = state.start;
      state.start = null;
      ui.frame.hidden = true;
      const wide = Math.abs(event.clientX - x);
      const tall = Math.abs(event.clientY - y);
      if (wide < TAP_SIZE && tall < TAP_SIZE) {
        select(x - TAP_HALF, y - TAP_HALF, x + TAP_HALF, y + TAP_HALF);
      } else {
        select(
          Math.min(x, event.clientX),
          Math.min(y, event.clientY),
          Math.max(x, event.clientX),
          Math.max(y, event.clientY),
        );
      }
    },
    true,
  );

  function resize(factor) {
    const p = state.proposal;
    if (!p) return;
    const center = p.bbox_min.map((low, i) => (low + p.bbox_max[i]) / 2);
    p.bbox_min = p.bbox_min.map((low, i) => center[i] + (low - center[i]) * factor);
    p.bbox_max = p.bbox_max.map((high, i) => center[i] + (high - center[i]) * factor);
    drawProposal();
  }
  ui.bigger.onclick = () => resize(RESIZE_STEP);
  ui.smaller.onclick = () => resize(1 / RESIZE_STEP);
  ui.label.onchange = drawProposal;
  ui.mobility.onchange = drawProposal;
  ui.restLabel.onchange = drawProposal;
  ui.restMobility.onchange = drawProposal;
  ui.cancel.onclick = () => {
    finish();
    onMessage("Nothing added");
  };
  async function saveSplit() {
    const parent = state.parent;
    try {
      const response = await fetch("/api/changes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          op: "split",
          object_id: parent.asset.object_id,
          details: { parts: [config(), restConfig()] },
        }),
      });
      const change = await response.json();
      if (!response.ok) throw new Error(change.detail ?? `Backend error ${response.status}`);
      const parts = await Promise.all(
        change.parts.map(async (id) => (await fetch(`/api/assets/${encodeURIComponent(id)}`)).json()),
      );
      finish();
      await onSplit(parent, parts);
    } catch (error) {
      onMessage(`Couldn't split it: ${error.message}`);
    }
  }

  async function saveCombine() {
    const first = state.combining;
    const other = state.other;
    const { label, label_source, mobility, mobility_reason } = config();
    try {
      const response = await fetch("/api/changes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          op: "combine",
          object_id: first.asset.object_id,
          details: {
            other: other.asset.object_id,
            label,
            label_source,
            mobility,
            mobility_reason,
          },
        }),
      });
      const change = await response.json();
      if (!response.ok) throw new Error(change.detail ?? `Backend error ${response.status}`);
      const id = encodeURIComponent(change.parts[0]);
      const combined = await (await fetch(`/api/assets/${id}`)).json();
      finish();
      await onCombine(first, other, combined);
    } catch (error) {
      onMessage(`Couldn't combine them: ${error.message}`);
    }
  }

  // Both boxes together, for checking before saving. Mobility is only clear if both agree.
  function combineWith(other) {
    const first = state.combining;
    if (!first || other === first) return;
    state.other = other;
    const a = first.asset;
    const b = other.asset;
    const low = a.bbox_min.map((value, i) => Math.min(value, b.bbox_min[i]));
    const high = a.bbox_max.map((value, i) => Math.max(value, b.bbox_max[i]));
    const same = a.mobility === b.mobility;
    ui.title.textContent = "Combine objects";
    showProposal({
      bbox_min: low,
      bbox_max: high,
      label: a.label === "object" ? b.label : a.label,
      label_confidence: 0,
      label_source: "operator",
      mobility: same ? a.mobility : "unsure",
      mobility_reason: same ? (a.mobility_reason ?? "both agree") : "the two objects differ",
      reason: "",
      visible_text: "",
      possible_tag: null,
      splats: (a.splats ?? 0) + (b.splats ?? 0),
      already_known: [],
    });
    onMessage(`Check the orange box around ${a.object_id} and ${b.object_id}, then save`);
  }

  ui.save.onclick = async () => {
    if (state.combining) {
      await saveCombine();
      return;
    }
    if (state.parent) {
      await saveSplit();
      return;
    }
    const details = config();
    const position = details.bbox_min.map((low, i) => (low + details.bbox_max[i]) / 2);
    try {
      const response = await fetch("/api/changes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ op: "add", position, details }),
      });
      const change = await response.json();
      if (!response.ok) throw new Error(change.detail ?? `Backend error ${response.status}`);
      const saved = await fetch(`/api/assets/${encodeURIComponent(change.object_id)}`);
      finish();
      await onSaved(await saved.json());
    } catch (error) {
      onMessage(`Couldn't save: ${error.message}`);
    }
  };

  return {
    state,
    start() {
      state.active = true;
      canvas.style.cursor = "crosshair";
      onMessage("Drag a box around the object, or tap it");
    },
    // Split an object: the next selection picks out one part of it.
    startSplit(parent) {
      state.parent = parent;
      state.active = true;
      canvas.style.cursor = "crosshair";
      onMessage(`Drag a box around one part of ${parent.asset.object_id}`);
    },
    // Combine two objects: the next tap chooses the second one.
    startCombine(first) {
      state.combining = first;
      onMessage(`Tap the object to combine with ${first.asset.object_id}`);
    },
    combineWith,
    cancel: finish,
  };
}

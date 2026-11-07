// Add an object the scan's detection missed: drag a box or tap it, check the proposal, and save.
// Code measures the object and a vision model may suggest a label. Nothing saves until confirmed.
import * as THREE from "three";

const TAP_SIZE = 12; // pixels: a smaller drag counts as a tap
const TAP_HALF = 70; // pixels around a tap to search for an object
const RESIZE_STEP = 1.15;
const PREVIEW_COLOR = 0xf59e0b;
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

export function setupAddObject({ canvas, root, camera, render, ui, onSaved, onMessage }) {
  const state = { active: false, proposal: null, start: null };
  const preview = new THREE.LineSegments(
    new THREE.BufferGeometry(),
    new THREE.LineBasicMaterial({ color: PREVIEW_COLOR, depthTest: false, transparent: true }),
  );
  preview.visible = false;
  preview.renderOrder = 11;
  root.add(preview);
  fillSelect(ui.label, LABELS);
  fillSelect(ui.mobility, MOBILITY);

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

  function drawProposal() {
    const min = new THREE.Vector3(...state.proposal.bbox_min);
    const max = new THREE.Vector3(...state.proposal.bbox_max);
    const size = max.clone().sub(min);
    preview.geometry.dispose();
    preview.geometry = new THREE.EdgesGeometry(new THREE.BoxGeometry(size.x, size.y, size.z));
    preview.position.copy(min).add(max).multiplyScalar(0.5);
    preview.visible = true;
    ui.config.textContent = JSON.stringify(config(), null, 1);
  }

  function finish() {
    state.active = false;
    state.proposal = null;
    preview.visible = false;
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
      const response = await fetch("/api/objects/propose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const reply = await response.json();
      if (!response.ok) throw new Error(reply.detail ?? `Backend error ${response.status}`);
      showProposal(reply);
      onMessage("Check the orange box and the settings, then save");
    } catch (error) {
      onMessage(`Couldn't add an object: ${error.message}`);
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
  ui.cancel.onclick = () => {
    finish();
    onMessage("Nothing added");
  };
  ui.save.onclick = async () => {
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
    cancel: finish,
  };
}

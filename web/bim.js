// BIM mode: a simulated model of the room instead of the scan. Data: /bim.json from app/bim.
// Elements are drawn in scene coordinates inside `root`, like the scan, so moves and routes still
// line up. Solid elements have a fitted shape; see-through ones only have a bounding box.
import * as THREE from "three";

const CLASS_COLORS = {
  IfcWall: 0xc7cdd6,
  IfcSlab: 0x6b7280,
  IfcPump: 0xf59e0b,
  IfcTank: 0x22c55e,
  IfcValve: 0xa855f7,
  IfcPipeSegment: 0x3b82f6,
  IfcPipeFitting: 0x93c5fd,
  IfcCableSegment: 0xeab308,
  IfcElectricDistributionBoard: 0x14b8a6,
  IfcLightFixture: 0xfde68a,
  IfcSensor: 0xec4899,
  IfcFlowInstrument: 0xec4899,
  IfcFurniture: 0xb45309,
  IfcBuildingElementProxy: 0x9ca3af,
};
const FAULT_COLOR = 0xff2d2d;
const SELECTED_GLOW = 0x0891b2;
const ROOM = new Set(["IfcWall", "IfcSlab"]);

export async function setupBim({ root, renderer, objects, faultTag, floorY, onSelectObject }) {
  const response = await fetch("bim.json").catch(() => null);
  if (!response?.ok) return null;
  const model = await response.json();

  renderer.localClippingEnabled = true;
  const section = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1e6);
  const group = new THREE.Group();
  group.visible = false;
  root.add(group);

  const byId = new Map(objects.map((o) => [o.asset.object_id, o]));
  const items = [];
  const known = new Set();

  function addItem(element, object) {
    const fault = element.psets.Valmet_Mapping?.Tag === faultTag;
    const mesh = makeMesh(element, fault, section);
    group.add(mesh);
    const item = {
      element,
      object,
      mesh,
      home: mesh.position.clone(),
      volume: volume(element.geometry),
      solid: !mesh.material.transparent,
    };
    mesh.userData.item = item;
    items.push(item);
    known.add(object);
  }
  for (const element of model.elements) {
    addItem(element, element.object_id ? byId.get(element.object_id) : null);
  }

  // Objects added, split or combined in the viewer aren't in the file, so they get a plain box.
  function addMissing() {
    for (const object of objects) {
      if (!object.gone && !known.has(object)) addItem(plainElement(object), object);
    }
  }

  const state = { active: false, selected: null, isolated: false, hidden: new Set(), cut: null };
  const panel = document.getElementById("bim-panel");
  const props = document.getElementById("bim-props");
  buildFilters();
  wireControls();

  function buildFilters() {
    const counts = new Map();
    for (const { element } of items) counts.set(element.ifc_class, (counts.get(element.ifc_class) ?? 0) + 1);
    const list = document.getElementById("bim-classes");
    list.replaceChildren();
    for (const [cls, count] of [...counts].sort((a, b) => b[1] - a[1])) {
      const label = document.createElement("label");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = true;
      box.onchange = () => {
        if (box.checked) state.hidden.delete(cls);
        else state.hidden.add(cls);
      };
      const swatch = document.createElement("span");
      swatch.className = "swatch";
      swatch.style.background = `#${(CLASS_COLORS[cls] ?? 0x9ca3af).toString(16).padStart(6, "0")}`;
      label.append(box, swatch, `${cls.replace(/^Ifc/, "")} (${count})`);
      list.append(label);
    }
  }

  function wireControls() {
    document.getElementById("bim-isolate").onclick = () => {
      state.isolated = !state.isolated && Boolean(state.selected);
      document.getElementById("bim-isolate").textContent = state.isolated ? "Show all" : "Isolate";
    };
    const slider = document.getElementById("bim-section");
    const text = document.getElementById("bim-section-value");
    const max = Number(slider.max);
    slider.oninput = () => {
      const height = Number(slider.value);
      state.cut = height >= max ? null : height;
      text.textContent = state.cut === null ? "off" : `${height.toFixed(1)} m`;
    };
  }

  function setActive(on) {
    state.active = on;
    group.visible = on;
    panel.hidden = !on;
  }

  // Selecting from the scan side (panel, route, copilot) keeps the BIM selection in step.
  function selectObject(object) {
    addMissing();
    const item = object ? items.find((candidate) => candidate.object === object) : null;
    select(item, false);
  }

  function select(item, notify = true) {
    if (state.selected) state.selected.mesh.material.emissive.setHex(0x000000);
    state.selected = item;
    if (!item) {
      props.replaceChildren();
      return;
    }
    item.mesh.material.emissive.setHex(SELECTED_GLOW);
    showProperties(item.element);
    if (notify) onSelectObject(item.object ?? null);
  }

  function showProperties(element) {
    const rows = [
      ["IFC class", element.ifc_class],
      ["Predefined type", element.predefined_type],
      ["GlobalId", element.guid],
    ];
    const html = [`<h3>${escapeHtml(element.name)}</h3>`, table(rows)];
    for (const [name, values] of Object.entries(element.psets)) {
      const shown = Object.entries(values).filter(([, v]) => v !== null && v !== undefined);
      html.push(`<h4>${escapeHtml(name)}</h4>`, table(shown));
    }
    props.innerHTML = html.join("");
  }

  function visible(item) {
    if (state.hidden.has(item.element.ifc_class)) return false;
    if (item.object?.gone) return false;
    if (state.isolated && state.selected) {
      return item === state.selected || ROOM.has(item.element.ifc_class);
    }
    return true;
  }

  const offset = new THREE.Vector3();
  const floorWorld = new THREE.Vector3();
  function update() {
    if (!state.active) return;
    addMissing();
    for (const item of items) {
      item.mesh.visible = visible(item);
      if (item.object) {
        offset.set(...item.object.asset.center);
        item.mesh.position.copy(item.home).add(item.object.center).sub(offset);
      }
    }
    // The section keeps what is below a height above the floor, like a plan cut.
    if (state.cut === null) section.constant = 1e6;
    else {
      root.localToWorld(floorWorld.set(0, floorY, 0));
      section.constant = floorWorld.y + state.cut;
    }
  }

  // Equipment is preferred over walls and floor. See-through bounding boxes can overlap, so the
  // smallest one under the pointer wins, but nothing behind the first solid shape is picked.
  function pick(raycaster) {
    const meshes = items.filter((item) => item.mesh.visible).map((item) => item.mesh);
    const hits = raycaster
      .intersectObjects(meshes, false)
      .filter((hit) => state.cut === null || section.distanceToPoint(hit.point) >= 0)
      .map((hit) => hit.object.userData.item);
    const equipment = [];
    for (const item of hits) {
      if (ROOM.has(item.element.ifc_class)) continue;
      equipment.push(item);
      if (item.solid) break;
    }
    const pool = equipment.length ? equipment : hits.slice(0, 1);
    const item = pool.length ? pool.reduce((a, b) => (b.volume < a.volume ? b : a)) : null;
    select(item);
    return item;
  }

  return {
    state,
    setActive,
    update,
    pick,
    selectObject,
    elementCount: items.length,
  };
}

function plainElement(object) {
  const { label, object_id: id, bbox_min: first, bbox_max: second } = object.asset;
  const low = first.map((value, axis) => Math.min(value, second[axis]));
  const high = first.map((value, axis) => Math.max(value, second[axis]));
  return {
    guid: "none in the file",
    object_id: id,
    ifc_class: "IfcBuildingElementProxy",
    predefined_type: "NOTDEFINED",
    name: `${label} (${id})`,
    geometry: {
      type: "box",
      center: low.map((value, axis) => (value + high[axis]) / 2),
      axes: [
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
      ],
      size: low.map((value, axis) => Math.max(high[axis] - value, 0.01)),
    },
    psets: {
      Valmet_Identification: { ObjectId: id, DetectedLabel: label, IdentityConfirmed: false },
      Valmet_Geometry: { Source: "made in the viewer, bounding box" },
    },
  };
}

function makeMesh(element, fault, section) {
  const g = element.geometry;
  const fitted = element.psets.Valmet_Geometry?.Source?.startsWith("fitted");
  const room = ROOM.has(element.ifc_class);
  const material = new THREE.MeshStandardMaterial({
    color: fault ? FAULT_COLOR : (CLASS_COLORS[element.ifc_class] ?? 0x9ca3af),
    roughness: 0.8,
    metalness: 0.05,
    side: THREE.DoubleSide,
    clippingPlanes: [section],
    // Walls and boxes that are only bounding boxes stay see-through, so they don't pass as real.
    transparent: element.ifc_class === "IfcWall" || (!fitted && !room),
    opacity: element.ifc_class === "IfcWall" ? 0.18 : fitted || room ? 1 : 0.35,
    depthWrite: fitted || element.ifc_class === "IfcSlab",
  });
  let geometry;
  const mesh = new THREE.Mesh(undefined, material);
  if (g.type === "cylinder") {
    geometry = new THREE.CylinderGeometry(g.radius, g.radius, g.height, 32);
    const axis = new THREE.Vector3(...g.axis).normalize();
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), axis);
  } else {
    geometry = new THREE.BoxGeometry(...g.size);
    const [first, second, third] = g.axes.map((row) => new THREE.Vector3(...row));
    if (new THREE.Vector3().crossVectors(first, second).dot(third) < 0) third.negate();
    mesh.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(first, second, third));
  }
  mesh.geometry = geometry;
  mesh.position.set(...g.center);
  const edges = new THREE.LineSegments(
    new THREE.EdgesGeometry(geometry),
    new THREE.LineBasicMaterial({ color: 0x111827, transparent: true, opacity: 0.5, clippingPlanes: [section] }),
  );
  edges.raycast = () => {};
  mesh.add(edges);
  return mesh;
}

function volume(g) {
  if (g.type === "cylinder") return Math.PI * g.radius ** 2 * g.height;
  return g.size[0] * g.size[1] * g.size[2];
}

function table(rows) {
  const body = rows
    .map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(format(v))}</dd>`)
    .join("");
  return `<dl>${body}</dl>`;
}

function format(value) {
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  return String(value);
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

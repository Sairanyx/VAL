// BIM mode: a simulated model of the room instead of the scan. Data: /bim.json from app/bim, with
// meshes.bin (scan surface meshes) and bim/splats/ (each object's own scanned splats).
// Two looks: "real" shows the objects' true-colour splats in the estimated room, "model" shows
// their meshes coloured by IFC class. Meshes are also what taps hit, in both looks.
// Everything is in scene coordinates inside `root`, like the scan, so moves and routes line up.
import * as THREE from "three";
import { SplatMesh } from "@sparkjsdev/spark";

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
const SELECTED_TINT = 0x22d3ee;
const ROOM = new Set(["IfcWall", "IfcSlab"]);

export async function setupBim({
  root,
  renderer,
  objects,
  faultTag,
  floorY,
  onSelectObject,
  onMessage,
}) {
  const response = await fetch("bim.json").catch(() => null);
  if (!response?.ok) return null;
  const model = await response.json();
  // Without the meshes (an old server, or a partial copy), elements fall back to simple shapes.
  const meshData = model.meshes
    ? await loadMeshes(model.meshes).catch((err) => {
        console.error("BIM meshes failed to load", err);
        onMessage?.(`BIM scan meshes didn't load (${err.message}): restart make web`);
        return null;
      })
    : null;

  renderer.localClippingEnabled = true;
  const section = new THREE.Plane(new THREE.Vector3(0, -1, 0), 1e6);
  const group = new THREE.Group();
  group.visible = false;
  root.add(group);

  const byId = new Map(objects.map((o) => [o.asset.object_id, o]));
  const items = model.elements.map((element) => {
    const object = element.object_id ? byId.get(element.object_id) : null;
    const fault = element.psets.Valmet_Mapping?.Tag === faultTag;
    const mesh = makeMesh(element, fault, section, meshData);
    group.add(mesh);
    return {
      element,
      object,
      mesh,
      fault,
      home: mesh.position.clone(),
      volume: volume(element.geometry),
      solid: !mesh.material.transparent,
      splats: null,
    };
  });

  const hasSplats = items.some((item) => item.element.splats);
  const state = {
    active: false,
    look: hasSplats ? "real" : "model",
    selected: null,
    isolated: false,
    hidden: new Set(),
    cut: null,
  };
  // Objects that can't move share one splat file per IFC class; movable ones get their own.
  const splatGroups = new Map();
  let splatsLoaded = false;
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
    document.getElementById("bim-look").onclick = () =>
      setLook(state.look === "real" ? "model" : "real");
    document.getElementById("bim-isolate").onclick = () => {
      state.isolated = !state.isolated && Boolean(state.selected);
      if (state.isolated) ownSplats(state.selected);
      document.getElementById("bim-isolate").textContent = state.isolated ? "Show all" : "Isolate";
    };
    const slider = document.getElementById("bim-section");
    const text = document.getElementById("bim-section-value");
    const max = Number(slider.max);
    slider.oninput = () => {
      const height = Number(slider.value);
      state.cut = height >= max ? null : height;
      // Splats can't be cut, so a section switches to the model look.
      if (state.cut !== null && state.look === "real") setLook("model");
      text.textContent = state.cut === null ? "off" : `${height.toFixed(1)} m`;
    };
  }

  function loadSplats() {
    if (splatsLoaded || !hasSplats) return;
    splatsLoaded = true;
    for (const item of items) {
      const { element } = item;
      if (element.splat_group) {
        if (!splatGroups.has(element.splat_group)) {
          const mesh = new SplatMesh({ url: `bim/splats/${element.splat_group}`, lod: false });
          splatGroups.set(element.splat_group, { mesh, cls: element.ifc_class });
          root.add(mesh);
        }
      } else if (element.splats) {
        item.splats = new SplatMesh({ url: `bim/splats/${element.splats}`, lod: false });
        root.add(item.splats);
      }
    }
  }

  // An object's own file, for isolating one that otherwise shares a class file.
  function ownSplats(item) {
    if (!item.splats && item.element.splats) {
      item.splats = new SplatMesh({ url: `bim/splats/${item.element.splats}`, lod: false });
      root.add(item.splats);
    }
  }

  function setLook(look) {
    state.look = look === "real" && hasSplats ? "real" : "model";
    if (state.look === "real") loadSplats();
    document.getElementById("bim-look").textContent =
      state.look === "real" ? "Look: Real" : "Look: Model";
    for (const item of items) styleItem(item);
  }

  function setActive(on) {
    state.active = on;
    group.visible = on;
    panel.hidden = !on;
    if (on) setLook(state.look);
    else hideSplats();
  }

  function hideSplats() {
    for (const { mesh } of splatGroups.values()) mesh.visible = false;
    for (const item of items) if (item.splats) item.splats.visible = false;
  }

  // In the real look, meshes stay as invisible tap targets, except the selection, tinted.
  function styleItem(item) {
    const material = item.mesh.material;
    const real = state.look === "real" && Boolean(item.element.splats);
    const selected = item === state.selected;
    material.visible = !real || selected;
    if (real && selected) {
      material.color.setHex(SELECTED_TINT);
      material.transparent = true;
      material.opacity = 0.35;
      material.depthWrite = false;
      material.emissive.setHex(0x000000);
    } else {
      material.color.setHex(item.fault ? FAULT_COLOR : (CLASS_COLORS[item.element.ifc_class] ?? 0x9ca3af));
      material.transparent = item.baseTransparent;
      material.opacity = item.baseOpacity;
      material.depthWrite = item.baseDepthWrite;
      material.emissive.setHex(selected ? SELECTED_GLOW : 0x000000);
    }
    material.needsUpdate = true;
  }

  // Selecting from the scan side (panel, route, copilot) keeps the BIM selection in step.
  function selectObject(object) {
    const item = object ? items.find((candidate) => candidate.object === object) : null;
    select(item, false);
  }

  function select(item, notify = true) {
    const previous = state.selected;
    state.selected = item;
    if (previous) styleItem(previous);
    if (!item) {
      props.replaceChildren();
      return;
    }
    styleItem(item);
    if (state.isolated) ownSplats(item);
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
    const real = state.look === "real";
    for (const item of items) {
      item.mesh.visible = visible(item);
      if (item.object) {
        offset.set(...item.object.asset.center);
        item.mesh.position.copy(item.home).add(item.object.center).sub(offset);
        if (item.splats) {
          item.splats.position.copy(item.object.center).sub(offset);
          // Class files hold this object too, so its own file only shows on its own when isolated.
          const shared = Boolean(item.element.splat_group) && !state.isolated;
          item.splats.visible = real && item.mesh.visible && !shared;
        }
      }
    }
    for (const { mesh, cls } of splatGroups.values()) {
      mesh.visible = real && !state.isolated && !state.hidden.has(cls);
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

  for (const item of items) {
    item.mesh.userData.item = item;
    item.baseTransparent = item.mesh.material.transparent;
    item.baseOpacity = item.mesh.material.opacity;
    item.baseDepthWrite = item.mesh.material.depthWrite;
  }
  document.getElementById("bim-look").hidden = !hasSplats;
  return {
    state,
    setActive,
    setLook,
    update,
    pick,
    selectObject,
    elementCount: items.length,
  };
}

async function loadMeshes(info) {
  const response = await fetch(info.file);
  if (!response.ok) throw new Error(`${info.file}: HTTP ${response.status}`);
  const buffer = await response.arrayBuffer();
  return {
    vertices: new Float32Array(buffer, 0, info.vertices * 3),
    faces: new Uint32Array(buffer, info.vertices * 12, info.faces * 3),
  };
}

function scanGeometry(ref, data) {
  const [v0, vn] = ref.vertices;
  const [f0, fn] = ref.faces;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.BufferAttribute(data.vertices.slice(v0 * 3, (v0 + vn) * 3), 3),
  );
  geometry.setIndex(new THREE.BufferAttribute(data.faces.slice(f0 * 3, (f0 + fn) * 3), 1));
  geometry.computeVertexNormals();
  return geometry;
}

function makeMesh(element, fault, section, meshData) {
  const g = element.geometry;
  const scanned = Boolean(element.mesh && meshData);
  const fitted = scanned || element.psets.Valmet_Geometry?.Simplified?.startsWith("fitted");
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
  if (scanned) {
    // Mesh vertices are already in scene coordinates.
    geometry = scanGeometry(element.mesh, meshData);
    mesh.geometry = geometry;
    return mesh;
  } else if (g.type === "cylinder") {
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

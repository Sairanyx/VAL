// BIM mode: a simulated model of the room instead of the scan. Data: /bim.json from app/bim, with
// meshes.bin (scan surface meshes) and bim/splats/ (each object's own scanned splats).
// Three looks: "real" shows the objects' true-colour splats in the estimated room, "mesh" shows
// meshes built from those splats, and "box" the simple shapes: fitted boxes and cylinders, or
// bounding boxes. All but "real" are coloured by IFC class. Taps and hovering always use the simple shape.
// Everything is in scene coordinates inside `root`, like the scan, so moves and routes line up.
import * as THREE from "three";
import { SplatEdit, SplatEditSdf, SplatEditSdfType, SplatMesh } from "@sparkjsdev/spark";
import { CLASS_COLORS, FAULT_COLOR } from "./colors.js";
import { createHoverShell } from "./hover.js";
import { THIN_LABELS, pickFront } from "./pick.js";

const UP = new THREE.Vector3(0, 1, 0);
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
  const items = [];
  const known = new Set();
  let ready = false; // Objects found later are styled for the current look once it exists.

  function addItem(element, object) {
    const fault = element.psets.Valmet_Mapping?.Tag === faultTag;
    const scan = element.mesh && meshData ? makeMesh(element, fault, section, meshData) : null;
    const box = makeMesh(element, fault, section, null);
    const item = { element, object, fault, scan, box, mesh: scan ?? box, splats: null };
    for (const mesh of [scan, box].filter(Boolean)) {
      mesh.userData.item = item;
      mesh.userData.home = mesh.position.clone();
      mesh.userData.turn = mesh.quaternion.clone();
      const { transparent, opacity, depthWrite } = mesh.material;
      mesh.userData.base = { transparent, opacity, depthWrite };
      mesh.visible = mesh === item.mesh;
      group.add(mesh);
    }
    item.volume = volume(element.geometry);
    items.push(item);
    known.add(object);
    if (ready) styleItem(item);
  }
  for (const element of model.elements) {
    addItem(element, element.object_id ? byId.get(element.object_id) : null);
  }

  // Objects added, split or combined in the viewer aren't in the file, so they get a plain box.
  function addMissing() {
    for (const object of objects) {
      if (object.gone || known.has(object)) continue;
      const { duplicated_from: copied, combined_from: parts } = object.asset;
      const source = copied && items.find((item) => item.object?.asset.object_id === copied);
      if (source) addCopy(source, object);
      else addItem(plainElement(object), object);
      if (parts) {
        items.at(-1).combined = true;
        for (const item of items) {
          if (parts.includes(item.object?.asset.object_id)) item.owner = object;
        }
      }
    }
  }

  // A copy has everything its source has, drawn somewhere else, except its record link.
  function addCopy(source, object) {
    const { label, object_id: id } = object.asset;
    const { Valmet_Mapping, ...psets } = source.element.psets;
    addItem(
      {
        ...source.element,
        guid: "assigned on export",
        object_id: id,
        name: `${object.asset.name || label} (${id})`,
        splat_group: undefined,
        psets: {
          ...psets,
          Valmet_Identification: {
            ...psets.Valmet_Identification,
            ObjectId: id,
            IdentityConfirmed: false,
          },
        },
      },
      object,
    );
    const item = items.at(-1);
    item.origin = source.object.asset.center;
    ownSplats(item);
  }

  // Combined parts follow the object they became. Anything else that's gone isn't drawn.
  function ownerOf(item) {
    if (!item.object?.gone) return item.object;
    return item.owner && !item.owner.gone ? item.owner : null;
  }

  // Fixed objects share a file per class. One that's gone or follows another is cut out of it.
  const groupEdit = new SplatEdit({ sdfs: [] });
  function cutFromGroup(item, cut) {
    if (!item.element.splat_group || Boolean(item.cut) === cut) return;
    if (cut) {
      const { bbox_min: first, bbox_max: second } = item.object.asset;
      const low = new THREE.Vector3(...first).min(new THREE.Vector3(...second));
      const high = new THREE.Vector3(...first).max(new THREE.Vector3(...second));
      item.cut = new SplatEditSdf({ type: SplatEditSdfType.BOX, opacity: 0 });
      item.cut.position.copy(low).add(high).multiplyScalar(0.5);
      item.cut.scale.copy(high).sub(low);
      root.add(item.cut);
      groupEdit.addSdf(item.cut);
    } else {
      groupEdit.removeSdf(item.cut);
      root.remove(item.cut);
      item.cut = null;
    }
  }

  const hasSplats = items.some((item) => item.element.splats);
  const hasScan = items.some((item) => item.scan);
  const looks = [hasSplats && "real", hasScan && "mesh", "box"].filter(Boolean);
  const LOOK_NAMES = { real: "Real", mesh: "Mesh", box: "Box" };
  const state = {
    active: false,
    look: looks[0],
    selected: null,
    isolated: false,
    hidden: new Set(),
    cut: null,
    hovered: null,
  };
  ready = true;
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
      setLook(looks[(looks.indexOf(state.look) + 1) % looks.length]);
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
      // Splats can't be cut, so a section switches to the next look.
      if (state.cut !== null && state.look === "real") setLook(looks[1]);
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
          mesh.edits = [groupEdit];
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
    state.look = looks.includes(look) ? look : looks[0];
    if (state.look === "real") loadSplats();
    document.getElementById("bim-look").textContent = `Look: ${LOOK_NAMES[state.look]}`;
    for (const item of items) {
      const previous = item.mesh;
      item.mesh = state.look === "box" ? item.box : (item.scan ?? item.box);
      if (previous !== item.mesh) previous.visible = false;
      item.mesh.visible = visible(item);
      styleItem(item);
    }
  }

  function setActive(on) {
    state.active = on;
    group.visible = on;
    panel.hidden = !on;
    if (on) {
      setLook(state.look);
      chooseDownload();
    } else {
      hideSplats();
      hover(null);
    }
  }

  function hideSplats() {
    for (const { mesh } of splatGroups.values()) mesh.visible = false;
    for (const item of items) if (item.splats) item.splats.visible = false;
  }

  // In the real look, meshes stay as invisible tap targets, except the selection, tinted.
  function styleItem(item) {
    const mesh = item.mesh;
    const material = mesh.material;
    const base = mesh.userData.base;
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
      material.transparent = base.transparent;
      material.opacity = base.opacity;
      material.depthWrite = base.depthWrite;
      material.emissive.setHex(selected ? SELECTED_GLOW : 0x000000);
    }
    material.needsUpdate = true;
  }

  // The backend's copy shows the model as it stands now. Without one, there's still the built file.
  async function chooseDownload() {
    // The health check is cheap; /api/plan would build the whole floor layout just to answer.
    const reply = await fetch("/api/health").catch(() => null);
    document.getElementById("bim-download").href = reply?.ok ? "/api/plan/model.ifc" : "model.ifc";
  }

  // Selecting from the scan side (panel, route, copilot) keeps the BIM selection in step.
  function selectObject(object) {
    addMissing();
    const item = object ? items.find((candidate) => candidate.object === object) : null;
    select(item, false);
  }

  function select(item, notify = true) {
    const previous = state.selected;
    state.selected = item;
    if (previous) {
      // The shape not on show may still carry an old selection glow.
      for (const mesh of [previous.scan, previous.box].filter(Boolean)) {
        mesh.material.emissive.setHex(0x000000);
      }
      styleItem(previous);
    }
    if (!item) {
      props.replaceChildren();
      return;
    }
    styleItem(item);
    if (state.isolated) ownSplats(item);
    showProperties(item.element);
    if (notify) onSelectObject(item.object ? ownerOf(item) : null);
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
    if (item.object && !ownerOf(item)) return false;
    // A combined object is its parts, except in the Box look, where it's one box around them.
    if (item.combined && state.look !== "box" && !item.object.gone) return false;
    if (item.object?.gone && state.look === "box") return false;
    if (state.hidden.has(item.element.ifc_class)) return false;
    if (state.isolated && state.selected) {
      return item === state.selected || ROOM.has(item.element.ifc_class);
    }
    return true;
  }

  const offset = new THREE.Vector3();
  const spin = new THREE.Quaternion();
  const shift = new THREE.Vector3();
  const floorWorld = new THREE.Vector3();
  // Shapes follow their object's moves and turns.
  function placeShapes(item) {
    const owner = ownerOf(item);
    offset.set(...(item.origin ?? owner.asset.center));
    spin.setFromAxisAngle(UP, owner.yaw || 0);
    for (const mesh of [item.scan, item.box].filter(Boolean)) {
      shift.copy(mesh.userData.home).sub(offset).applyQuaternion(spin);
      mesh.position.copy(owner.center).add(shift);
      mesh.quaternion.copy(mesh.userData.turn).premultiply(spin);
    }
  }

  // Objects made after the model was built, by adding, splitting, or combining, get a plain box.
  function update() {
    if (!state.active) return;
    addMissing();
    const real = state.look === "real";
    for (const item of items) {
      item.mesh.visible = visible(item);
      const owner = ownerOf(item);
      if (item.object) cutFromGroup(item, Boolean(item.object.gone));
      if (item.object && !owner && item.splats) item.splats.visible = false;
      if (owner) {
        placeShapes(item);
        if (item.splats) {
          shift.copy(offset).negate().applyQuaternion(spin);
          item.splats.position.copy(owner.center).add(shift);
          item.splats.quaternion.copy(spin);
          // Class files hold this object too, so its own file only shows on its own when isolated.
          const shared = Boolean(item.element.splat_group) && !state.isolated && !item.object.gone;
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
    if (state.hovered && visible(state.hovered)) {
      shell.show(state.hovered.box.geometry, state.hovered.box.position, state.hovered.box.quaternion);
    } else if (state.hovered) shell.hide();
  }

  // Taps and hovering use each element's simple shape in every look, even when it isn't drawn:
  // scan meshes and splats have gaps, so a tap in the middle of a bucket could miss it.
  // Walls and the floor can't be picked, and among equipment the front shape wins (see pick.js).
  function candidate(raycaster) {
    const shown = items.filter((item) => visible(item));
    const inCut = (hit) => state.cut === null || section.distanceToPoint(hit.point) >= 0;
    const front = (list) =>
      pickFront(
        raycaster,
        list.map((item) => ({
          mesh: item.box,
          volume: item.volume,
          thin: THIN_LABELS.has(item.element.psets.Valmet_Identification?.DetectedLabel),
          surface: (rc) => surfaceAt(item, rc, inCut),
          item,
        })),
        inCut,
      )?.item ?? null;
    const equipment = shown.filter((item) => !ROOM.has(item.element.ifc_class));
    return front(equipment);
  }

  // Distance to an element's real surface along a ray: its fitted shape, or its scan mesh.
  function surfaceAt(item, raycaster, keep = () => true) {
    const fitted = !item.box.userData.base.transparent;
    const real = fitted ? item.box : item.scan;
    if (!real) return null;
    const hit = raycaster.intersectObject(real, false).find(keep);
    return hit ? hit.distance : null;
  }

  // The same, for the scan view, where shapes are only placed when needed.
  function surfaceDistance(object, raycaster) {
    const item = items.find((candidate) => candidate.object === object);
    if (!item || object.gone) return null;
    placeShapes(item);
    return surfaceAt(item, raycaster);
  }

  function pick(raycaster) {
    const item = candidate(raycaster);
    select(item);
    return item;
  }

  const shell = createHoverShell(root, [section]);

  // Pass a raycaster to hover what is under it, or null to clear. Returns the hovered item.
  function hover(raycaster) {
    const item = raycaster && state.active ? candidate(raycaster) : null;
    state.hovered = item;
    if (item && visible(item)) shell.show(item.box.geometry, item.box.position, item.box.quaternion);
    else shell.hide();
    return item;
  }

  // Outside BIM mode: outline an object's simple shape where the object stands now.
  function hoverObject(object) {
    if (state.active) return false;
    if (object && !object.gone) addMissing();
    const item = object && !object.gone ? items.find((c) => c.object === object) : null;
    if (!item) {
      shell.hide();
      return false;
    }
    placeShapes(item);
    shell.show(item.box.geometry, item.box.position, item.box.quaternion);
    return true;
  }

  document.getElementById("bim-look").hidden = looks.length < 2;
  return {
    items,
    state,
    setActive,
    setLook,
    update,
    pick,
    hover,
    hoverObject,
    // Whether an object's label belongs on screen, given isolating and hidden types.
    shows(object) {
      const item = items.find((candidate) => candidate.object === object);
      if (!item) return false;
      return visible(item) || (Boolean(item.combined) && !state.isolated);
    },
    surfaceDistance,
    selectObject,
    rename(object) {
      const item = items.find((candidate) => candidate.object === object);
      if (!item) return;
      const { name, label, object_id: id } = object.asset;
      item.element.name = `${name || label} (${id})`;
      if (state.selected === item) showProperties(item.element);
    },
    items, // For browser tests.
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

function plainElement(object) {
  const { name, label, object_id: id, bbox_min: first, bbox_max: second } = object.asset;
  const low = first.map((value, axis) => Math.min(value, second[axis]));
  const high = first.map((value, axis) => Math.max(value, second[axis]));
  return {
    guid: "assigned on export",
    object_id: id,
    ifc_class: "IfcBuildingElementProxy",
    predefined_type: "NOTDEFINED",
    name: `${name || label} (${id})`,
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

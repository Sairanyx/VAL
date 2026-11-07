// Clean "objects" view: fitted shapes over or instead of the scan, pull-apart, and moving objects.
// Data: /shapes.json (from app/extract/primitives.py). Without it, the viewer just shows the scan.
// Scene coordinates are used throughout, inside `root`, as in main.js.
import * as THREE from "three";
import { SplatEdit, SplatEditSdf, SplatEditSdfType, SplatMesh } from "@sparkjsdev/spark";

const APART_SCALE = 0.45; // How far objects move away from the room's center in the pulled-apart view.
const MIN_LIFT = 0.05;

const BLOCKED_COLOR = 0xff2d2d;

export async function setupObjects({
  root,
  scene,
  camera,
  canvas,
  splat,
  objects,
  floorY,
  onChange,
  checkMove,
  onMessage,
  onBlocked,
  onMoveCancelled,
}) {
  const shapes = await fetchShapes();
  const lights = addLights(scene);
  const group = new THREE.Group();
  root.add(group);
  const byId = new Map(objects.map((o) => [o.asset.object_id, o]));
  const items = [];
  for (const [id, shape] of Object.entries(shapes)) {
    const object = byId.get(id);
    if (!object || !shape.use_shape) continue;
    const mesh = makeMesh(shape);
    group.add(mesh);
    items.push({ object, mesh, home: mesh.position.clone(), moved: new THREE.Vector3() });
    object.shape = mesh;
  }

  // Objects cut out of the scan, so dragging one moves the real thing and not only its outline.
  const pieces = [];
  for (const id of await fetchPieces()) {
    const object = byId.get(id);
    if (!object) continue;
    object.piece = new SplatMesh({ url: `pieces/${id}.ply` });
    object.piece.edits = [];
    root.add(object.piece);
    pieces.push(object.piece);
  }

  // Any other movable object is cut out when first moved: the backend sends its splats, and the same
  // space is hidden in the scan, so that it isn't left behind as a ghost.
  const hidden = new SplatEdit({ sdfs: [] });
  splat.edits = [hidden];

  async function loadPiece(object) {
    const id = encodeURIComponent(object.asset.object_id);
    const response = await fetch(`/api/objects/${id}/home`);
    if (!response.ok) throw new Error(`Backend error ${response.status}`);
    const home = await response.json();
    const piece = new SplatMesh({ url: `/api/objects/${id}/splats.ply`, lod: false });
    piece.edits = [];
    await piece.initialized;
    if (object.gone) {
      piece.dispose();
      return;
    }
    const low = new THREE.Vector3(...home.bbox_min);
    const high = new THREE.Vector3(...home.bbox_max);
    // Stop just above the floor, which stays. A box's bottom often sits above an object's base.
    high.y = floorY - home.floor_margin;
    const space = new SplatEditSdf({ type: SplatEditSdfType.BOX, opacity: 0 });
    space.position.copy(low).add(high).multiplyScalar(0.5);
    space.scale.copy(high).sub(low);
    root.add(space);
    hidden.addSdf(space);
    piece.position.copy(object.center).sub(new THREE.Vector3(...home.center));
    piece.visible = splat.visible;
    root.add(piece);
    pieces.push(piece);
    object.piece = piece;
    object.hiddenSpace = space;
  }

  // Waits for an object's real splats. If they can't be loaded, it moves as an outline instead.
  function ensurePiece(object) {
    if (object.piece) return Promise.resolve();
    object.pieceLoading ??= loadPiece(object).catch((error) => {
      console.warn("Moving as an outline:", error.message);
      onMessage?.("Moving the outline only: the backend couldn't cut this object out of the scan");
    });
    return object.pieceLoading;
  }

  // For an object that's gone, split, or combined: show the scan as it was there again.
  function dropPiece(object) {
    if (!object.piece) return;
    if (!object.hiddenSpace) {
      object.piece.visible = false; // Cut in advance: the scan has no splats to bring back.
      return;
    }
    hidden.removeSdf(object.hiddenSpace);
    root.remove(object.hiddenSpace);
    root.remove(object.piece);
    pieces.splice(pieces.indexOf(object.piece), 1);
    object.piece.dispose();
    object.piece = null;
    object.hiddenSpace = null;
    object.pieceLoading = null;
  }

  function restorePiece(object) {
    if (object.piece && !object.hiddenSpace) object.piece.visible = splat.visible;
  }

  const roomCenter = new THREE.Vector3();
  objects.forEach((o) => roomCenter.add(o.center));
  if (objects.length) roomCenter.divideScalar(objects.length);

  const state = { view: "scan", apart: false, amount: 0, moving: null, changes: [] };
  const raycaster = new THREE.Raycaster();
  const floorPlane = new THREE.Plane();

  function applyView() {
    const clean = state.view === "objects" || state.view === "bim";
    splat.visible = !clean;
    for (const piece of pieces) piece.visible = splat.visible;
    group.visible = state.view === "both" || state.view === "objects";
    lights.visible = state.view !== "scan";
    for (const item of items) {
      item.mesh.material.transparent = state.view === "both";
      item.mesh.material.opacity = state.view === "both" ? 0.75 : 1;
    }
    scene.background = clean ? new THREE.Color(0x20242b) : null;
  }

  function placeAll() {
    const offset = new THREE.Vector3();
    for (const item of items) {
      offset.copy(item.home).sub(roomCenter).multiplyScalar(APART_SCALE * state.amount);
      offset.y = -Math.max(state.amount * MIN_LIFT, 0);
      item.mesh.position.copy(item.home).add(item.moved).add(offset);
      item.object.pick.position.copy(item.mesh.position);
    }
  }

  function setView(view) {
    state.view = view;
    applyView();
  }

  function setApart(on) {
    state.apart = on;
  }

  function update(dt) {
    const target = state.apart ? 1 : 0;
    if (state.amount !== target) {
      const step = Math.min(dt * 1.5, Math.abs(target - state.amount));
      state.amount += Math.sign(target - state.amount) * step;
      placeAll();
    }
  }

  // Points from the camera through a screen position onto the floor, in scene coordinates.
  function floorPoint(event) {
    const ndc = new THREE.Vector2(
      (event.clientX / window.innerWidth) * 2 - 1,
      -(event.clientY / window.innerHeight) * 2 + 1,
    );
    raycaster.setFromCamera(ndc, camera);
    const worldPoint = new THREE.Vector3(0, floorY, 0);
    root.localToWorld(worldPoint);
    floorPlane.setFromNormalAndCoplanarPoint(new THREE.Vector3(0, 1, 0), worldPoint);
    const hit = raycaster.ray.intersectPlane(floorPlane, new THREE.Vector3());
    return hit ? root.worldToLocal(hit) : null;
  }

  function startMove(object) {
    if (object.asset.mobility !== "movable") return false;
    const item = items.find((candidate) => candidate.object === object);
    ensurePiece(object);
    const start = object.center.clone();
    state.moving = { object, item, dragging: false, last: null, valid: start.clone(), start };
    return true;
  }

  // Show a bad spot in red: the moving box, and whatever is in its way.
  // Drawn over everything, because thin lines get lost among the splats.
  const marked = new Set();
  const warningFill = new THREE.MeshBasicMaterial({
    color: BLOCKED_COLOR,
    transparent: true,
    opacity: 0.3,
    depthTest: false,
  });
  function mark(object, red) {
    if (red && !marked.has(object)) {
      const material = object.box.material;
      object.normalColor = material.color.getHex();
      material.color.setHex(BLOCKED_COLOR);
      material.depthTest = false;
      object.box.renderOrder = 12;
      object.fill = new THREE.Mesh(object.pick.geometry, warningFill);
      object.fill.renderOrder = 12;
      object.box.add(object.fill);
      object.warning = true;
      marked.add(object);
    } else if (!red && marked.has(object)) {
      const material = object.box.material;
      material.color.setHex(object.normalColor);
      material.depthTest = true;
      object.box.renderOrder = 0;
      object.box.remove(object.fill);
      object.warning = false;
      marked.delete(object);
    }
    onBlocked?.(marked.size > 0);
  }
  function clearMarks() {
    for (const object of [...marked]) mark(object, false);
  }

  function showCheck(moving, result, spot) {
    clearMarks();
    if (result.ok) {
      moving.valid = spot;
      onMessage?.("Release to place it here");
      return;
    }
    mark(moving.object, true);
    for (const id of result.blockers ?? []) {
      const blocker = objects.find((candidate) => candidate.asset.object_id === id);
      if (blocker) mark(blocker, true);
    }
    onMessage?.(`Can't place it here. ${result.reason}`);
  }

  // One check at a time, and the latest spot next, so a slow backend can't fall behind.
  async function checkWhileDragging(moving) {
    if (moving.checking) {
      moving.checkAgain = true;
      return;
    }
    moving.checking = true;
    do {
      moving.checkAgain = false;
      // The pointer keeps moving during a check, so remember which spot the answer is about.
      const spot = moving.object.center.clone();
      const result = await checkMove(moving.object, spot.toArray());
      if (state.moving !== moving) break;
      showCheck(moving, result, spot);
    } while (moving.checkAgain);
    moving.checking = false;
  }

  function shiftObject(moving, delta) {
    const { object, item } = moving;
    object.box.position.add(delta);
    object.pick.position.add(delta);
    object.center.add(delta);
    object.piece?.position.add(delta);
    if (item) {
      item.moved.add(delta);
      placeAll();
    }
  }

  // Dragging is captured before the camera controls, so moving an object doesn't turn the view.
  canvas.addEventListener(
    "pointerdown",
    (event) => {
      if (!state.moving) return;
      event.stopPropagation();
      // Keeps the drag alive if the pointer leaves the canvas, such as over a panel.
      canvas.setPointerCapture(event.pointerId);
      state.moving.dragging = true;
      state.moving.last = floorPoint(event);
    },
    true,
  );
  canvas.addEventListener(
    "pointermove",
    (event) => {
      if (!state.moving?.dragging) return;
      event.stopPropagation();
      const point = floorPoint(event);
      if (!point || !state.moving.last) return;
      const delta = point.clone().sub(state.moving.last);
      delta.y = 0;
      shiftObject(state.moving, delta);
      state.moving.last = point;
      checkWhileDragging(state.moving);
    },
    true,
  );
  async function finishMove(event) {
    const moving = state.moving;
    if (!moving?.dragging) return;
    event.stopPropagation();
    state.moving = null;
    const { object } = moving;
    // The spot under the pointer now is what counts, not the last one checked.
    const result = await checkMove(object, object.center.toArray());
    clearMarks();
    if (!result.ok) {
      placeAt(object, moving.valid.toArray());
      onMessage?.(`Moved back to the last good spot. ${result.reason}`);
      if (moving.valid.distanceTo(moving.start) < 0.001) {
        onMoveCancelled?.(); // Nothing to save, but a live route may show where it was dragged.
        return;
      }
    }
    // Not rounded: this must be the spot that was checked, or the backend could refuse it.
    state.changes.push({
      op: "move",
      object_id: object.asset.object_id,
      position: object.center.toArray(),
    });
    onChange?.(state.changes);
  }
  canvas.addEventListener("pointerup", finishMove, true);
  canvas.addEventListener("pointercancel", finishMove, true);

  // Put an object where the backend says it is, such as after reloading the page.
  function placeAt(object, center) {
    const item = items.find((candidate) => candidate.object === object);
    const delta = new THREE.Vector3(...center).sub(object.center);
    shiftObject({ object, item }, delta);
  }

  function resetMoves() {
    for (const object of objects) {
      const item = items.find((candidate) => candidate.object === object);
      const home = new THREE.Vector3(...object.asset.center);
      const delta = home.clone().sub(object.center);
      object.box.position.add(delta);
      object.pick.position.add(delta);
      object.center.copy(home);
      object.piece?.position.set(0, 0, 0);
      if (item) {
        item.moved.set(0, 0, 0);
        object.pick.position.copy(item.home);
      }
    }
    placeAll();
    state.changes.length = 0;
    onChange?.(state.changes);
  }

  applyView();
  return {
    state,
    setView,
    setApart,
    update,
    startMove,
    resetMoves,
    placeAt,
    ensurePiece,
    dropPiece,
    restorePiece,
    shapeCount: items.length,
  };
}

async function fetchPieces() {
  try {
    const response = await fetch("pieces.json");
    return response.ok ? await response.json() : [];
  } catch {
    return [];
  }
}

async function fetchShapes() {
  try {
    const response = await fetch("shapes.json");
    return response.ok ? await response.json() : {};
  } catch {
    return {};
  }
}

function addLights(scene) {
  const lights = new THREE.Group();
  lights.add(new THREE.HemisphereLight(0xffffff, 0x60656e, 2.0));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(3, 6, 4);
  lights.add(sun);
  scene.add(lights);
  return lights;
}

// Lifts very dark scan colors, so shapes stay readable.
function shapeColor(rgb) {
  const color = new THREE.Color(...rgb);
  const hsl = {};
  color.getHSL(hsl);
  color.setHSL(hsl.h, hsl.s, Math.max(hsl.l, 0.25));
  return color;
}

function makeMesh(shape) {
  const material = new THREE.MeshStandardMaterial({
    color: shapeColor(shape.color),
    roughness: 0.75,
    metalness: 0.05,
    side: THREE.DoubleSide,
  });
  const center = new THREE.Vector3(...shape.center);
  if (shape.type === "cylinder") {
    const geometry = new THREE.CylinderGeometry(shape.radius, shape.radius, shape.height, 40);
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.copy(center);
    return mesh;
  }
  const [width, depth, height] = shape.size;
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, depth, height), material);
  const [first, second, third] = shape.axes.map((row) => new THREE.Vector3(...row));
  if (new THREE.Vector3().crossVectors(first, second).dot(third) < 0) third.negate();
  mesh.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(first, second, third));
  mesh.position.copy(center);
  return mesh;
}

// Clean "objects" view: fitted shapes over or instead of the scan, pull-apart, and moving/rotating objects.
// Data: /shapes.json (from app/extract/primitives.py). Without it, the viewer just shows the scan.
// Scene coordinates are used throughout, inside `root`, as in main.js.
import * as THREE from "three";
import { SplatEdit, SplatEditSdf, SplatEditSdfType, SplatMesh } from "@sparkjsdev/spark";

const APART_SCALE = 0.45; // How far objects move away from the room's center in the pulled-apart view.
const MIN_LIFT = 0.05;

const BLOCKED_COLOR = 0xff2d2d;

function grabbed(object, item, mode) {
  const start = object.center.clone();
  const startYaw = object.yaw || 0;
  return {
    object,
    item,
    dragging: false,
    last: null,
    mode,
    lastClientX: null,
    lastTouchAngle: null,
    start,
    startYaw,
    valid: start.clone(),
    validYaw: startYaw,
    saved: start.clone(), // Where the backend has it, so only real changes are recorded.
    savedYaw: startYaw,
  };
}

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
    items.push({
      object,
      mesh,
      home: mesh.position.clone(),
      baseQuaternion: mesh.quaternion.clone(),
      moved: new THREE.Vector3(),
    });
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
    // A copy shows its source's splats somewhere else, and the source stays in the scan.
    const source = object.asset.duplicated_from;
    const id = encodeURIComponent(source ?? object.asset.object_id);
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
    if (source) object.isCopy = true;
    else {
      const low = new THREE.Vector3(...home.bbox_min);
      const high = new THREE.Vector3(...home.bbox_max);
      // Stop just above the floor, which stays. A box's bottom often sits above an object's base.
      high.y = floorY - home.floor_margin;
      const space = new SplatEditSdf({ type: SplatEditSdfType.BOX, opacity: 0 });
      space.position.copy(low).add(high).multiplyScalar(0.5);
      space.scale.copy(high).sub(low);
      root.add(space);
      hidden.addSdf(space);
      object.hiddenSpace = space;
    }
    object.pieceHome = new THREE.Vector3(...home.center);
    piece.visible = splat.visible;
    root.add(piece);
    pieces.push(piece);
    object.piece = piece;
    updateObjectVisuals(object, null);
  }

  // Objects made from one cut out in advance show its splats until they all have their own, as the
  // scan has a hole there. Then it goes, or it would stay behind as a ghost.
  async function retireInherited(object) {
    for (const piece of object.inherited ?? []) {
      if (piece.retiring) continue;
      piece.retiring = true;
      await Promise.all(piece.heirs.map(ensurePiece));
      if (!piece.retiring) continue; // Undone in the meantime.
      if (piece.heirs.every((heir) => heir.piece || heir.gone)) {
        piece.dropped = true;
        piece.visible = false;
      } else piece.retiring = false;
    }
  }

  // Waits for an object's real splats. If they can't be loaded, it moves as an outline instead.
  function ensurePiece(object) {
    if (object.piece) return Promise.resolve();
    object.pieceLoading ??= loadPiece(object).catch((error) => {
      console.warn("Moving as an outline:", error.message);
      onMessage?.("Moving the outline only: the backend couldn't cut this object out of the scan");
    });
    object.pieceLoading.then(() => retireInherited(object));
    return object.pieceLoading;
  }

  function removePiece(object) {
    root.remove(object.piece);
    pieces.splice(pieces.indexOf(object.piece), 1);
    object.piece.dispose();
    object.piece = null;
    object.pieceLoading = null;
  }

  // For an object that's split or combined, or a copy that's gone: show the scan as it was again.
  // `heirs` are the objects made from it.
  function dropPiece(object, heirs = []) {
    if (!object.piece) return;
    if (!object.hiddenSpace && !object.isCopy) {
      // Cut in advance, so the scan has no splats to bring back.
      if (heirs.length) {
        object.piece.heirs = heirs;
        for (const heir of heirs) heir.inherited = [...(heir.inherited ?? []), object.piece];
      } else {
        object.piece.dropped = true;
        object.piece.visible = false;
      }
      return;
    }
    if (object.hiddenSpace) {
      hidden.removeSdf(object.hiddenSpace);
      root.remove(object.hiddenSpace);
      object.hiddenSpace = null;
    }
    removePiece(object);
  }

  // For a deleted object: its splats go too, and its space in the scan stays hidden until undone.
  async function erase(object) {
    const cutInAdvance = object.piece && !object.hiddenSpace && !object.isCopy;
    const isCopy = object.isCopy || object.asset.duplicated_from;
    dropPiece(object);
    if (!cutInAdvance && !isCopy) {
      const id = encodeURIComponent(object.asset.object_id);
      const reply = await fetch(`/api/objects/${id}/cover`).then((response) => response.json());
      object.erasedSpaces = (reply.boxes ?? []).map(({ bbox_min: low, bbox_max: high }) => {
        const first = new THREE.Vector3(...low);
        const second = new THREE.Vector3(...high);
        const space = new SplatEditSdf({ type: SplatEditSdfType.BOX, opacity: 0 });
        space.position.copy(first).add(second).multiplyScalar(0.5);
        space.scale.copy(second).sub(first);
        root.add(space);
        hidden.addSdf(space);
        return space;
      });
    }
    for (const piece of object.inherited ?? []) {
      if (piece.heirs.every((heir) => heir === object || heir.gone)) {
        piece.dropped = true;
        piece.visible = false;
      }
    }
  }

  function unerase(object) {
    for (const space of object.erasedSpaces ?? []) {
      hidden.removeSdf(space);
      root.remove(space);
    }
    object.erasedSpaces = null;
  }

  // `keepSplats`: only the object's info goes; the scan still shows it.
  function recordRemoval(object, keepSplats = false) {
    const change = { op: "remove", object_id: object.asset.object_id };
    if (keepSplats) change.details = { keep_splats: true };
    state.changes.push(change);
    onChange?.(state.changes);
  }

  // A copy looks like its source in every view, so it gets the source's fitted shape as well.
  function addCopy(object) {
    const sourceId = object.asset.duplicated_from;
    const shape = shapes[sourceId];
    const source = objects.find((candidate) => candidate.asset.object_id === sourceId);
    if (shape?.use_shape && source) {
      const mesh = makeMesh(shape);
      group.add(mesh);
      items.push({
        object,
        mesh,
        home: mesh.position.clone(),
        baseQuaternion: mesh.quaternion.clone(),
        moved: object.center.clone().sub(new THREE.Vector3(...source.asset.center)),
      });
      object.shape = mesh;
      placeAll();
    }
    return ensurePiece(object);
  }

  function restorePiece(object) {
    if (object.piece && !object.hiddenSpace) {
      object.piece.dropped = false;
      object.piece.retiring = false;
      object.piece.visible = splat.visible;
    }
  }

  const roomCenter = new THREE.Vector3();
  objects.forEach((o) => roomCenter.add(o.center));
  if (objects.length) roomCenter.divideScalar(objects.length);

  const state = { view: "scan", apart: false, amount: 0, moving: null, changes: [] };
  const raycaster = new THREE.Raycaster();
  const floorPlane = new THREE.Plane();
  const yAxis = new THREE.Vector3(0, 1, 0);

  function applyView() {
    const clean = state.view === "objects" || state.view === "bim";
    splat.visible = !clean;
    for (const piece of pieces) piece.visible = splat.visible && !piece.dropped;
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
    const rotQuat = new THREE.Quaternion();
    for (const item of items) {
      offset.copy(item.home).sub(roomCenter).multiplyScalar(APART_SCALE * state.amount);
      offset.y = -Math.max(state.amount * MIN_LIFT, 0);
      item.mesh.position.copy(item.home).add(item.moved).add(offset);
      rotQuat.setFromAxisAngle(yAxis, item.object.yaw || 0);
      item.mesh.quaternion.copy(item.baseQuaternion).premultiply(rotQuat);
      item.object.pick.position.copy(item.mesh.position);
      item.object.pick.rotation.y = item.object.yaw || 0;
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

  function showCheck(moving, result, spot, yaw) {
    clearMarks();
    if (result.ok) {
      moving.valid = spot;
      moving.validYaw = yaw;
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
      const yaw = moving.object.yaw || 0;
      const result = await checkMove(moving.object, spot.toArray(), yaw);
      // An answer that arrives after letting go is out of date, and finishDrag decides instead.
      if (state.moving !== moving || !moving.dragging) break;
      showCheck(moving, result, spot, yaw);
    } while (moving.checkAgain);
    moving.checking = false;
  }

  function updateObjectVisuals(object, item) {
    object.box.position.copy(object.center);
    object.pick.position.copy(object.center);
    object.box.rotation.y = object.yaw || 0;
    object.pick.rotation.y = object.yaw || 0;

    if (object.piece) {
      const home = object.pieceHome ?? new THREE.Vector3(...object.asset.center);
      const yaw = object.yaw || 0;
      object.piece.quaternion.setFromAxisAngle(yAxis, yaw);
      const rotatedHome = home.clone().applyAxisAngle(yAxis, yaw);
      object.piece.position.copy(object.center).sub(rotatedHome);
    }
    if (item) {
      placeAll();
    }
  }

  function startMove(object) {
    if (object.asset.mobility !== "movable") return false;
    const item = items.find((candidate) => candidate.object === object);
    ensurePiece(object); // so the real splats move, not just the frame
    state.moving = grabbed(object, item, "move");
    return true;
  }

  function startRotate(object) {
    if (object.asset.mobility !== "movable") return false;
    const item = items.find((candidate) => candidate.object === object);
    ensurePiece(object);
    state.moving = grabbed(object, item, "rotate");
    return true;
  }

  function setMode(mode) {
    if (state.moving) {
      state.moving.mode = mode;
    }
  }

  function shiftObject(moving, delta) {
    const { object, item } = moving;
    object.center.add(delta);
    if (item) {
      item.moved.add(delta);
    }
    updateObjectVisuals(object, item);
  }

  function rotateObject(moving, deltaYaw) {
    const { object, item } = moving;
    object.yaw = (object.yaw || 0) + deltaYaw;
    updateObjectVisuals(object, item);
  }

  function setObjectRotation(moving, yaw) {
    const { object, item } = moving;
    object.yaw = yaw;
    updateObjectVisuals(object, item);
  }

  async function turnObject(deltaAngle) {
    const moving = state.moving;
    if (!moving) return;
    rotateObject(moving, deltaAngle);
    if (await settle(moving)) recordChange(moving.object);
  }

  function finishManipulation() {
    clearMarks();
    state.moving = null;
  }

  function recordChange(object) {
    state.changes.push({
      op: "move",
      object_id: object.asset.object_id,
      // Not rounded: this must be the spot that was checked, or the backend could refuse it.
      position: object.center.toArray(),
      yaw: object.yaw || 0,
    });
    onChange?.(state.changes);
  }

  const activePointers = new Map();

  canvas.addEventListener(
    "pointerdown",
    (event) => {
      if (!state.moving) return;
      event.stopPropagation();
      canvas.setPointerCapture(event.pointerId);
      activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      state.moving.dragging = true;
      state.moving.last = floorPoint(event);
      state.moving.lastClientX = event.clientX;
      if (activePointers.size === 2) {
        const pts = Array.from(activePointers.values());
        state.moving.lastTouchAngle = Math.atan2(pts[1].y - pts[0].y, pts[1].x - pts[0].x);
      }
    },
    true,
  );

  canvas.addEventListener(
    "pointermove",
    (event) => {
      if (!state.moving?.dragging) return;
      event.stopPropagation();
      activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });

      // Multi-touch 2-finger twist on tablet
      if (activePointers.size >= 2) {
        const pts = Array.from(activePointers.values());
        const currentAngle = Math.atan2(pts[1].y - pts[0].y, pts[1].x - pts[0].x);
        if (state.moving.lastTouchAngle !== null) {
          const deltaAngle = currentAngle - state.moving.lastTouchAngle;
          rotateObject(state.moving, -deltaAngle);
        }
        state.moving.lastTouchAngle = currentAngle;
        return;
      }

      const point = floorPoint(event);
      const isRotating = state.moving.mode === "rotate" || event.shiftKey;

      if (isRotating) {
        let deltaYaw = 0;
        if (point && state.moving.last) {
          const center = state.moving.object.center;
          const v1 = state.moving.last.clone().sub(center);
          const v2 = point.clone().sub(center);
          v1.y = 0;
          v2.y = 0;
          if (v1.length() > 0.08 && v2.length() > 0.08) {
            const a1 = Math.atan2(v1.z, v1.x);
            const a2 = Math.atan2(v2.z, v2.x);
            let d = a2 - a1;
            while (d > Math.PI) d -= 2 * Math.PI;
            while (d < -Math.PI) d += 2 * Math.PI;
            deltaYaw = d;
          }
        }
        if (deltaYaw === 0 && state.moving.lastClientX !== null) {
          deltaYaw = -(event.clientX - state.moving.lastClientX) * 0.015;
        }
        if (deltaYaw !== 0) {
          rotateObject(state.moving, deltaYaw);
        }
      } else {
        if (point && state.moving.last) {
          const delta = point.clone().sub(state.moving.last);
          delta.y = 0;
          shiftObject(state.moving, delta);
        }
      }

      state.moving.last = point;
      state.moving.lastClientX = event.clientX;
      checkWhileDragging(state.moving);
    },
    true,
  );

  // Back to the last good spot and angle if this one is taken. Returns false if nothing changed.
  async function settle(moving) {
    const { object } = moving;
    // Where it is now is what counts, not the last one checked.
    const result = await checkMove(object, object.center.toArray(), object.yaw || 0);
    clearMarks();
    if (result.ok) {
      moving.valid = object.center.clone();
      moving.validYaw = object.yaw || 0;
      onMessage?.("Placed. Undo takes it back.");
    } else {
      placeAt(object, moving.valid.toArray(), moving.validYaw);
      onMessage?.(`Can't do that here: ${result.reason}. It's back where it was.`);
    }
    const changed =
      moving.valid.distanceTo(moving.saved) >= 0.001 || moving.validYaw !== moving.savedYaw;
    if (changed) {
      moving.saved = moving.valid.clone();
      moving.savedYaw = moving.validYaw;
    }
    return changed;
  }

  async function finishDrag(event) {
    activePointers.delete(event.pointerId);
    const moving = state.moving;
    if (activePointers.size < 2 && moving) moving.lastTouchAngle = null;
    if (activePointers.size === 0 && moving?.dragging) {
      event.stopPropagation();
      moving.dragging = false;
      if (await settle(moving)) recordChange(moving.object);
      else onMoveCancelled?.(); // Nothing to save, but a live route may show where it was dragged.
    }
  }
  canvas.addEventListener("pointerup", finishDrag, true);
  canvas.addEventListener("pointercancel", finishDrag, true);

  // Put an object where the backend says it is, such as after reloading the page.
  function placeAt(object, center, yaw = 0) {
    const item = items.find((candidate) => candidate.object === object);
    const delta = new THREE.Vector3(...center).sub(object.center);
    shiftObject({ object, item }, delta);
    setObjectRotation({ object, item }, yaw);
  }

  // Move or turn an object without dragging, such as by voice. Nothing changes if it doesn't fit.
  async function moveTo(object, center = object.center.toArray(), yaw = object.yaw || 0) {
    if (object.asset.mobility !== "movable") {
      return { ok: false, message: `${object.asset.object_id} can't be moved` };
    }
    const result = await checkMove(object, center, yaw);
    if (!result.ok) return { ok: false, message: result.reason };
    await ensurePiece(object);
    placeAt(object, center, yaw);
    recordChange(object);
    return { ok: true, message: "" };
  }

  // Raise (+) or lower (-) an object by `metres`, never below the floor. Dragging keeps the height.
  // The scan's +y points down, so raising lowers y. Checked and saved like any move.
  async function raise(object, metres) {
    const offset = object.center.y - object.asset.center[1];
    const bottom = object.asset.bbox_max[1] + offset; // the lowest point, as +y is down
    const room = bottom - floorY; // negative while above the floor
    const step = metres > 0 ? metres : Math.max(metres, room);
    if (Math.abs(step) < 0.005) return { ok: false, message: "It's already on the floor" };
    const center = object.center.clone();
    center.y -= step;
    return moveTo(object, center.toArray(), object.yaw || 0);
  }

  function resetMoves() {
    for (const object of objects) {
      const item = items.find((candidate) => candidate.object === object);
      const home = new THREE.Vector3(...object.asset.center);
      const delta = home.clone().sub(object.center);
      shiftObject({ object, item }, delta);
      setObjectRotation({ object, item }, 0);
      if (item) {
        item.moved.set(0, 0, 0);
      }
    }
    placeAll();
    state.changes.length = 0;
    onChange?.(state.changes);
  }

  applyView();
  return {
    state,
    erase,
    unerase,
    recordRemoval,
    addCopy,
    setView,
    setApart,
    update,
    startMove,
    startRotate,
    setMode,
    turnObject,
    finishManipulation,
    resetMoves,
    moveTo,
    raise,
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

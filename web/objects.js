// Clean "objects" view: fitted shapes over or instead of the scan, pull-apart, and moving/rotating objects.
// Data: /shapes.json (from app/extract/primitives.py). Without it, the viewer just shows the scan.
// Scene coordinates are used throughout, inside `root`, as in main.js.
import * as THREE from "three";
import { SplatMesh } from "@sparkjsdev/spark";

const APART_SCALE = 0.45; // How far objects move away from the room's center in the pulled-apart view.
const MIN_LIFT = 0.05;

export async function setupObjects({ root, scene, camera, canvas, splat, objects, floorY, onChange }) {
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
    root.add(object.piece);
    pieces.push(object.piece);
  }

  const roomCenter = new THREE.Vector3();
  objects.forEach((o) => roomCenter.add(o.center));
  if (objects.length) roomCenter.divideScalar(objects.length);

  const state = { view: "scan", apart: false, amount: 0, moving: null, changes: [] };
  const raycaster = new THREE.Raycaster();
  const floorPlane = new THREE.Plane();
  const yAxis = new THREE.Vector3(0, 1, 0);

  function applyView() {
    splat.visible = state.view !== "objects";
    for (const piece of pieces) piece.visible = splat.visible;
    group.visible = state.view !== "scan";
    lights.visible = group.visible;
    for (const item of items) {
      item.mesh.material.transparent = state.view === "both";
      item.mesh.material.opacity = state.view === "both" ? 0.75 : 1;
    }
    scene.background = state.view === "objects" ? new THREE.Color(0x20242b) : null;
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

  function updateObjectVisuals(object, item) {
    object.box.position.copy(object.center);
    object.pick.position.copy(object.center);
    object.box.rotation.y = object.yaw || 0;
    object.pick.rotation.y = object.yaw || 0;

    if (object.piece) {
      const home = new THREE.Vector3(...object.asset.center);
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
    state.moving = {
      object,
      item,
      dragging: false,
      last: null,
      mode: "move",
      lastClientX: null,
      lastTouchAngle: null,
    };
    return true;
  }

  function startRotate(object) {
    if (object.asset.mobility !== "movable") return false;
    const item = items.find((candidate) => candidate.object === object);
    state.moving = {
      object,
      item,
      dragging: false,
      last: null,
      mode: "rotate",
      lastClientX: null,
      lastTouchAngle: null,
    };
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

  function turnObject(deltaAngle) {
    if (!state.moving) return;
    rotateObject(state.moving, deltaAngle);
    recordChange(state.moving.object);
  }

  function finishManipulation() {
    if (state.moving) {
      recordChange(state.moving.object);
      state.moving = null;
    }
  }

  function recordChange(object) {
    state.changes.push({
      op: "move",
      object_id: object.asset.object_id,
      position: object.center.toArray().map((value) => Number(value.toFixed(3))),
      yaw: Number((object.yaw || 0).toFixed(4)),
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
    },
    true,
  );

  function finishDrag(event) {
    activePointers.delete(event.pointerId);
    if (activePointers.size < 2 && state.moving) {
      state.moving.lastTouchAngle = null;
    }
    if (activePointers.size === 0 && state.moving?.dragging) {
      event.stopPropagation();
      state.moving.dragging = false;
      recordChange(state.moving.object);
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
    setView,
    setApart,
    update,
    startMove,
    startRotate,
    setMode,
    turnObject,
    finishManipulation,
    resetMoves,
    placeAt,
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

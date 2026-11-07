// Clean "objects" view: fitted shapes over or instead of the scan, pull-apart, and moving objects.
// Data: /shapes.json (from app/extract/primitives.py). Without it, the viewer just shows the scan.
// Scene coordinates are used throughout, inside `root`, as in main.js.
import * as THREE from "three";

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
    items.push({ object, mesh, home: mesh.position.clone(), moved: new THREE.Vector3() });
    object.shape = mesh;
  }

  const roomCenter = new THREE.Vector3();
  objects.forEach((o) => roomCenter.add(o.center));
  if (objects.length) roomCenter.divideScalar(objects.length);

  const state = { view: "scan", apart: false, amount: 0, moving: null, changes: [] };
  const raycaster = new THREE.Raycaster();
  const floorPlane = new THREE.Plane();

  function applyView() {
    splat.visible = state.view !== "objects";
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
    state.moving = { object, item, dragging: false, last: null };
    return true;
  }

  function shiftObject(moving, delta) {
    const { object, item } = moving;
    object.box.position.add(delta);
    object.pick.position.add(delta);
    object.center.add(delta);
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
    },
    true,
  );
  canvas.addEventListener(
    "pointerup",
    (event) => {
      if (!state.moving) return;
      event.stopPropagation();
      const { object } = state.moving;
      state.changes.push({
        op: "move",
        object_id: object.asset.object_id,
        position: object.center.toArray().map((value) => Number(value.toFixed(3))),
      });
      state.moving = null;
      onChange?.(state.changes);
    },
    true,
  );

  function resetMoves() {
    for (const object of objects) {
      const item = items.find((candidate) => candidate.object === object);
      const home = new THREE.Vector3(...object.asset.center);
      const delta = home.clone().sub(object.center);
      object.box.position.add(delta);
      object.pick.position.add(delta);
      object.center.copy(home);
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
  return { state, setView, setApart, update, startMove, resetMoves, shapeCount: items.length };
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

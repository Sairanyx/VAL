// Alerts: equipment in a condition the operator chose (Filters panel, or by voice) gets a thin
// outline and a small plain label when within range. Conditions come from the Excel pack through
// /api/assets, the same data as the Objects panel.
import * as THREE from "three";

const RANGE = 4; // metres from the camera
const REFRESH_MS = 30000; // conditions change rarely; moves and deletes are read from the objects
const STATES = {
  attention_required: { color: 0xef4444, css: "red", text: "Attention required" },
  degraded: { color: 0xf59e0b, css: "yellow", text: "Degraded" },
  watch: { color: 0xeab308, css: "yellow", text: "Watch" },
};

export function setupAlerts({ root, camera, objects, layer, nameOf, onEnter, filters, isHidden }) {
  const conditions = new Map(); // object_id -> condition, for objects in an alert state
  const beacons = new Map(); // object -> { mesh, badge }
  const announced = new Set(); // objects already announced since they last left the range
  let lastFetch = -Infinity;
  const world = new THREE.Vector3();
  const top = new THREE.Vector3();
  const yAxis = new THREE.Vector3(0, 1, 0);

  async function refresh() {
    lastFetch = performance.now();
    const reply = await fetch("/api/assets")
      .then((response) => (response.ok ? response.json() : null))
      .catch(() => null);
    if (!reply) return;
    conditions.clear();
    for (const asset of reply.assets) {
      if (STATES[asset.condition?.condition_state]) conditions.set(asset.object_id, asset.condition);
    }
  }

  function beaconFor(object, state) {
    let beacon = beacons.get(object);
    if (beacon) return beacon;
    const a = object.asset;
    const size = new THREE.Vector3(
      Math.abs(a.bbox_max[0] - a.bbox_min[0]),
      Math.abs(a.bbox_max[1] - a.bbox_min[1]),
      Math.abs(a.bbox_max[2] - a.bbox_min[2]),
    ).addScalar(0.08); // a little larger than the object, so the glow surrounds it
    const geometry = new THREE.BoxGeometry(size.x, size.y, size.z);
    const mesh = new THREE.LineSegments(
      new THREE.EdgesGeometry(geometry),
      new THREE.LineBasicMaterial({ color: state.color, transparent: true, depthTest: false }),
    );
    mesh.renderOrder = 21;
    root.add(mesh);
    const badge = document.createElement("div");
    badge.className = `alert-badge ${state.css}`;
    layer.append(badge);
    beacon = { mesh, badge, height: size.y };
    beacons.set(object, beacon);
    return beacon;
  }

  function hide(object) {
    const beacon = beacons.get(object);
    if (!beacon) return;
    beacon.mesh.visible = false;
    beacon.badge.style.display = "none";
  }

  // Call before rendering.
  function update(now = performance.now()) {
    if (now - lastFetch > REFRESH_MS) refresh();
    const wanted = filters.alertStates();
    for (const object of objects) {
      const condition = conditions.get(object.asset.object_id);
      const show = condition && wanted.includes(condition.condition_state) && filters.passes(object);
      if (!show || object.gone || isHidden?.()) {
        hide(object);
        continue;
      }
      world.copy(object.center).applyMatrix4(root.matrixWorld);
      const distance = camera.position.distanceTo(world);
      if (distance > RANGE) {
        hide(object);
        announced.delete(object);
        continue;
      }
      const state = STATES[condition.condition_state];
      const beacon = beaconFor(object, state);
      beacon.mesh.visible = true;
      beacon.mesh.position.copy(object.center);
      beacon.mesh.quaternion.setFromAxisAngle(yAxis, object.yaw || 0);
      beacon.text = `${nameOf(object)}: ${state.text.toLowerCase()}`;
      if (!announced.has(object)) {
        announced.add(object);
        onEnter?.(object, state.text, distance);
      }
    }
  }

  // Call after rendering: puts each badge above its object, on screen.
  function placeBadges() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    for (const [object, beacon] of beacons) {
      if (!beacon.mesh.visible) continue;
      // Above the object's top; the scan's +y points down, so its top is at a smaller y.
      top.copy(object.center);
      top.y -= beacon.height / 2;
      top.applyMatrix4(root.matrixWorld).project(camera);
      const onScreen = top.z > 0 && top.z < 1 && Math.abs(top.x) <= 1 && Math.abs(top.y) <= 1;
      if (!onScreen) {
        beacon.badge.style.display = "none";
        continue;
      }
      beacon.badge.style.display = "block";
      if (beacon.badge.textContent !== beacon.text) beacon.badge.textContent = beacon.text;
      beacon.badge.style.transform = `translate(${((top.x + 1) / 2) * w}px, ${((1 - top.y) / 2) * h}px)`;
    }
  }

  refresh();
  return { update, placeBadges, refresh };
}

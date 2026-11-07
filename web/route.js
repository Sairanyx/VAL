// Routes from the backend: draw them on the floor, walk along them, and re-plan when objects move.
import * as THREE from "three";

const WALK_SPEED = 1.2; // metres per second
const TURN_RATE = 3; // how quickly the view turns towards where it's heading
const LINE_RADIUS = 0.035;
const LINE_LIFT = 0.03; // metres above the floor, so the line doesn't sink into it
const COLOR = 0x22d3ee;

async function callApi(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : `Backend error ${response.status}`;
    throw new Error(detail);
  }
  return data;
}

// Keep the path up to the viewing point, which lies on it.
function pathToViewPoint(path, viewFrom) {
  const points = path.map((p) => new THREE.Vector3(...p));
  const view = new THREE.Vector3(...viewFrom);
  let best = { distance: Infinity, index: 0 };
  const line = new THREE.Line3();
  const near = new THREE.Vector3();
  for (let i = 0; i + 1 < points.length; i++) {
    line.set(points[i], points[i + 1]);
    line.closestPointToPoint(view, true, near);
    const distance = near.distanceTo(view);
    if (distance < best.distance) best = { distance, index: i };
  }
  return [...points.slice(0, best.index + 1), view];
}

export function setupRoute({ root, camera, floorY, getEyeY, onMessage }) {
  const group = new THREE.Group();
  group.renderOrder = 10;
  root.add(group);
  // Drawn over everything: the route must stay readable when it passes behind machines.
  const material = new THREE.MeshBasicMaterial({
    color: COLOR,
    depthTest: false,
    transparent: true,
    opacity: 0.9,
  });
  const yAxis = new THREE.Vector3(0, 1, 0);
  const state = {
    target: null,
    route: null,
    start: null,
    profile: "person",
    walking: null,
    posted: 0,
  };

  function clearLine() {
    for (const child of [...group.children]) {
      child.geometry.dispose();
      group.remove(child);
    }
  }

  function draw(path) {
    clearLine();
    const points = path.map((p) => new THREE.Vector3(p[0], floorY - LINE_LIFT, p[2]));
    for (let i = 0; i + 1 < points.length; i++) {
      const delta = points[i + 1].clone().sub(points[i]);
      const piece = new THREE.Mesh(
        new THREE.CylinderGeometry(LINE_RADIUS, LINE_RADIUS, delta.length(), 8),
        material,
      );
      piece.position.copy(points[i]).addScaledVector(delta, 0.5);
      piece.quaternion.setFromUnitVectors(yAxis, delta.clone().normalize());
      group.add(piece);
    }
    const end = new THREE.Mesh(new THREE.RingGeometry(0.16, 0.24, 32), material);
    end.material.side = THREE.DoubleSide;
    end.position.copy(points.at(-1));
    end.rotation.x = Math.PI / 2;
    group.add(end);
  }

  function describe(route, name) {
    const reach = route.stop_distance === undefined ? "" : `, stops ${route.stop_distance.toFixed(1)} m away`;
    const fake = route.placeholder ? " (placeholder: no floor map loaded)" : "";
    return `${name}: ${route.length.toFixed(1)} m for a ${route.width ?? ""} m ${route.profile}${reach}${fake}`;
  }

  // Plan from where the viewer stands. Re-plans keep that start, so looking around from elsewhere
  // can't change the route. A refusal clears the line and shows the reason.
  async function plan(target, from = null) {
    state.walking = null;
    state.target = target;
    const start = from ?? root.worldToLocal(camera.position.clone());
    state.start = start;
    try {
      state.route = await callApi("/api/route", {
        start: start.toArray(),
        object_id: target.asset.object_id,
        profile: state.profile,
      });
    } catch (error) {
      state.route = null;
      clearLine();
      onMessage(`No route to ${target.name}: ${error.message}`);
      return null;
    }
    draw(state.route.path);
    onMessage(describe(state.route, target.name));
    return state.route;
  }

  function startWalking() {
    if (!state.route) return false;
    const end = state.route.view_from ?? state.route.path.at(-1);
    const points = pathToViewPoint(state.route.path, end);
    state.walking = { points, index: 0, along: 0 };
    return true;
  }

  function stopWalking() {
    state.walking = null;
  }

  function clear() {
    state.walking = null;
    state.route = null;
    state.target = null;
    clearLine();
  }

  // Send moves to the backend, which keeps the map's footprints, then re-plan the active route.
  async function syncChanges(changes) {
    try {
      if (!changes.length) {
        await callApi("/api/changes/reset");
      } else {
        for (const change of changes.slice(state.posted)) await callApi("/api/changes", change);
      }
      state.posted = changes.length;
    } catch (error) {
      onMessage(`Couldn't save the move: ${error.message}`);
      return;
    }
    if (state.target) await plan(state.target, state.start);
  }

  const look = new THREE.Matrix4();
  const wanted = new THREE.Quaternion();
  const here = new THREE.Vector3();
  const next = new THREE.Vector3();
  const focus = new THREE.Vector3();

  function faceTowards(point, dt) {
    look.lookAt(camera.position, point, camera.up);
    wanted.setFromRotationMatrix(look);
    camera.quaternion.slerp(wanted, 1 - Math.exp(-TURN_RATE * dt));
    camera.quaternion.normalize();
    return camera.quaternion.angleTo(wanted);
  }

  function update(dt) {
    const walking = state.walking;
    if (!walking) return;
    const eyeY = getEyeY();
    const last = walking.points.length - 1;
    focus.copy(state.target.center);
    root.localToWorld(focus);
    if (walking.index >= last) {
      // At the viewing point: finish turning towards the object.
      if (faceTowards(focus, dt) < 0.02) {
        state.walking = null;
        onMessage(`Arrived at ${state.target.name}`);
      }
      return;
    }
    let remaining = WALK_SPEED * dt;
    while (walking.index < last && remaining > 0) {
      const length = walking.points[walking.index].distanceTo(walking.points[walking.index + 1]);
      const left = length - walking.along;
      if (remaining < left) {
        walking.along += remaining;
        remaining = 0;
      } else {
        remaining -= left;
        walking.index += 1;
        walking.along = 0;
      }
    }
    if (walking.index < last) {
      const a = walking.points[walking.index];
      const b = walking.points[walking.index + 1];
      here.lerpVectors(a, b, walking.along / Math.max(a.distanceTo(b), 1e-6));
      next.copy(b);
    } else {
      here.copy(walking.points[last]);
      next.copy(focus);
    }
    root.localToWorld(here);
    camera.position.set(here.x, eyeY, here.z);
    if (walking.index < last) {
      root.localToWorld(next);
      next.y = eyeY;
      faceTowards(next, dt);
    }
  }

  function setProfile(profile) {
    state.profile = profile;
    return state.target ? plan(state.target, state.start) : null;
  }

  return { state, plan, startWalking, stopWalking, clear, syncChanges, setProfile, update };
}

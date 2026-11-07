// Walk mode keeps to the floor a person can use: the same floor map, body width and moved objects as
// routing (/api/plan/walkable), so you can't walk through walls or machines. Fly mode ignores it.
//
// Against an obstacle you slide along it, rather than stopping dead. Standing somewhere that isn't
// walkable (such as a start point outside the map) never traps you: you can walk out of it.

const REFRESH_MS = 4000; // moved, added and deleted objects change the walkable floor

export function setupWalkable({ root, camera }) {
  const state = { mask: null, rows: 0, cols: 0, x0: 0, z0: 0, cell: 1, changes: -1 };
  let lastFetch = 0;
  let fetching = false;
  let lastGood = null; // the camera's last position on walkable floor, in world coordinates

  async function refresh() {
    if (fetching) return;
    fetching = true;
    lastFetch = performance.now();
    try {
      const response = await fetch("/api/plan/walkable");
      if (!response.ok) return; // no floor map: walking stays free, as before
      const reply = await response.json();
      if (reply.axes?.[0] !== 0 || reply.axes?.[1] !== 2) return;
      if (reply.changes === state.changes && state.mask) return;
      state.mask = Uint8Array.from(atob(reply.mask), (c) => c.charCodeAt(0));
      [state.rows, state.cols] = reply.shape;
      [state.x0, state.z0] = reply.origin;
      state.cell = reply.cell;
      state.changes = reply.changes;
    } catch {
      // Keep the last mask; walking stays free until one loads.
    } finally {
      fetching = false;
    }
  }

  // Is this world position on walkable floor? Unknown means yes, so nothing breaks without a map.
  function walkable(position) {
    if (!state.mask) return true;
    const here = root.worldToLocal(position.clone());
    const i = Math.floor((here.x - state.x0) / state.cell);
    const j = Math.floor((here.z - state.z0) / state.cell);
    if (i < 0 || j < 0 || i >= state.rows || j >= state.cols) return false;
    const index = i * state.cols + j;
    return Boolean((state.mask[index >> 3] >> (7 - (index & 7))) & 1);
  }

  // Call after the camera has moved this frame, in Walk mode only.
  function keepOnFloor(now = performance.now()) {
    if (now - lastFetch > REFRESH_MS) refresh();
    if (!state.mask) return;
    const position = camera.position;
    if (walkable(position)) {
      lastGood = position.clone();
      return;
    }
    if (!lastGood || !walkable(lastGood)) return; // started off the map: let them walk onto it
    // Slide: keep whichever part of the step still lands on walkable floor.
    const alongX = lastGood.clone().setX(position.x);
    const alongZ = lastGood.clone().setZ(position.z);
    if (walkable(alongX)) position.copy(alongX);
    else if (walkable(alongZ)) position.copy(alongZ);
    else position.copy(lastGood);
  }

  // After jumping somewhere on purpose (Back to start, a finished route walk), start fresh.
  function forget() {
    lastGood = null;
  }

  refresh();
  return { refresh, keepOnFloor, forget, walkable };
}

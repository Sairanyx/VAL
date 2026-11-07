// Real walking on Android: WebXR with ARCore tracks the device, and the map moves with it.
// Needs Chrome on an ARCore-capable Android device, over HTTPS (`make web HTTPS=1`). iPhones have no
// WebXR AR, so they keep the step-based Phone mode instead.
//
// Calibration: where the device is, and the way it faces, when tracking starts become the scene's
// start point and the start direction. Start re-calibrates. Everything else (routes, labels,
// highlights) keeps working because it all reads the camera's position through `root`.
import * as THREE from "three";

const HANDHELD_HEIGHT = 1.4; // metres above the floor, if the device can't report the real floor

function yawOf(quaternion) {
  const forward = new THREE.Vector3(0, 0, -1).applyQuaternion(quaternion);
  return Math.atan2(-forward.x, -forward.z);
}

export async function xrSupported() {
  if (!navigator.xr || !window.isSecureContext) return false;
  return navigator.xr.isSessionSupported("immersive-ar").catch(() => false);
}

// `offset` is a group between the scene and `root`: tracking moves the whole map with it, so the
// device's real position lands in the right place. `getStart` returns the start point and floor
// height in the upright scene, before any offset.
export function setupWalkXR({ renderer, scene, camera, offset, getStart, onMessage }) {
  const state = { active: false, session: null, calibrateAt: 0, frames: 0, floorKnown: true };
  let savedBackground = null;

  async function start() {
    renderer.xr.enabled = true;
    const overlay = { optionalFeatures: ["dom-overlay"], domOverlay: { root: document.body } };
    let session;
    try {
      renderer.xr.setReferenceSpaceType("local-floor");
      session = await navigator.xr.requestSession("immersive-ar", {
        requiredFeatures: ["local-floor"],
        ...overlay,
      });
      state.floorKnown = true;
    } catch {
      // Some devices can't report the floor: assume the device is held at a normal height.
      renderer.xr.setReferenceSpaceType("local");
      session = await navigator.xr.requestSession("immersive-ar", overlay);
      state.floorKnown = false;
    }
    await renderer.xr.setSession(session);
    state.session = session;
    state.active = true;
    state.frames = 0;
    state.calibrateAt = 3; // the first frames can still have an old pose
    document.body.classList.add("xr");
    // Draw the map opaque, so the room replaces the camera picture.
    savedBackground = scene.background;
    scene.background = new THREE.Color(0x000000);
    session.addEventListener("end", stopped);
    onMessage("Tracking: walk and turn with the device. Start re-calibrates.");
  }

  function stopped() {
    state.active = false;
    state.session = null;
    renderer.xr.enabled = false;
    document.body.classList.remove("xr");
    scene.background = savedBackground;
    offset.matrix.identity();
    offset.matrixWorldNeedsUpdate = true;
    offset.updateMatrixWorld(true);
    onMessage("Tracking stopped");
  }

  function stop() {
    state.session?.end();
  }

  // Line up the map so the device's position and facing match the scene's start point and the
  // start direction (looking along -z). The device's real height above the floor is kept.
  function calibrate() {
    const { position, floorY } = getStart();
    const device = camera.position.clone();
    const deviceFloor = state.floorKnown ? 0 : device.y - HANDHELD_HEIGHT;
    const turn = new THREE.Matrix4().makeRotationY(yawOf(camera.quaternion));
    const toDevice = new THREE.Matrix4().makeTranslation(device.x, deviceFloor, device.z);
    const fromStart = new THREE.Matrix4().makeTranslation(-position.x, -floorY, -position.z);
    offset.matrixAutoUpdate = false;
    offset.matrix.copy(toDevice).multiply(turn).multiply(fromStart);
    offset.matrixWorldNeedsUpdate = true;
    offset.updateMatrixWorld(true);
  }

  return {
    state,
    start,
    stop,
    recenter() {
      if (state.active) state.calibrateAt = state.frames + 1;
    },
    // Call once per frame, after rendering, when the camera holds this frame's device pose.
    update() {
      if (!state.active) return;
      state.frames += 1;
      if (state.calibrateAt && state.frames >= state.calibrateAt) {
        state.calibrateAt = 0;
        calibrate();
      }
    },
  };
}

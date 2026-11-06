// Phone mode: turn the phone to look around, walk to move, or use the on-screen joystick.
// Works in any phone browser (iPhone Safari too). Sensors need HTTPS: run `make web HTTPS=1`.
//
// Walking is estimated by counting steps, so it only moves forward and drifts over longer walks.
// Press Start to put the camera back at the start and make the phone's current facing "forward".
import * as THREE from "three";

const STEP_LENGTH = 0.7; // metres per detected step
const WALK_SPEED = 1.4; // metres per second, to glide each step instead of jumping
const JOYSTICK_SPEED = 1.5; // metres per second at full deflection
const GRAVITY = 9.81;
const STEP_HIGH = 1.2; // a step peaks this far above gravity (m/s^2)...
const STEP_LOW = 0.3; // ...and must fall back below this before the next one counts
const STEP_MIN_MS = 300; // fastest step rate we accept

const Y = new THREE.Vector3(0, 1, 0);
const Z = new THREE.Vector3(0, 0, 1);
// The device's sensors measure the phone lying flat; this turns that into "looking out the back".
const BACK_CAMERA = new THREE.Quaternion(-Math.sqrt(0.5), 0, 0, Math.sqrt(0.5));

function deviceQuaternion(out, { alpha, beta, gamma }) {
  const d = THREE.MathUtils.degToRad;
  const screenAngle = d(screen.orientation?.angle ?? window.orientation ?? 0);
  out.setFromEuler(new THREE.Euler(d(beta), d(alpha), -d(gamma), "YXZ"));
  out.multiply(BACK_CAMERA);
  out.multiply(new THREE.Quaternion().setFromAxisAngle(Z, -screenAngle));
  return out;
}

function yawOf(q) {
  const f = new THREE.Vector3(0, 0, -1).applyQuaternion(q);
  return Math.atan2(-f.x, -f.z);
}

function flatForward(camera) {
  const f = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
  f.y = 0;
  return f.lengthSq() > 1e-6 ? f.normalize() : f.set(0, 0, -1);
}

export function setupPhone({ camera, button, joystick, onMessage }) {
  const device = new THREE.Quaternion();
  const yawFix = new THREE.Quaternion();
  let orientation = null; // latest sensor reading
  let recenter = true; // next reading sets "forward"
  let enabled = false;
  let steps = 0;
  let pending = 0; // metres still to glide from detected steps
  let smooth = GRAVITY;
  let armed = true;
  let lastStep = 0;
  const stick = new THREE.Vector2(); // joystick x = right, y = forward, each -1..1

  function onOrientation(e) {
    if (e.alpha !== null) orientation = { alpha: e.alpha, beta: e.beta, gamma: e.gamma };
  }

  function onMotion(e) {
    const a = e.accelerationIncludingGravity;
    if (!a || a.x === null) return;
    smooth = 0.8 * smooth + 0.2 * Math.hypot(a.x, a.y, a.z);
    if (armed && smooth > GRAVITY + STEP_HIGH && e.timeStamp - lastStep > STEP_MIN_MS) {
      armed = false;
      lastStep = e.timeStamp;
      pending += STEP_LENGTH;
      steps++;
    } else if (smooth < GRAVITY + STEP_LOW) {
      armed = true;
    }
  }

  async function enable() {
    if (!window.isSecureContext) {
      onMessage("Phone sensors need HTTPS. Start the server with: make web HTTPS=1");
      return false;
    }
    // iPhones ask the user first, and only from a button tap.
    for (const Sensor of [window.DeviceOrientationEvent, window.DeviceMotionEvent]) {
      if (typeof Sensor?.requestPermission === "function") {
        if ((await Sensor.requestPermission()) !== "granted") {
          onMessage("Motion access was denied. Allow it in the browser settings and reload.");
          return false;
        }
      }
    }
    window.addEventListener("deviceorientation", onOrientation);
    window.addEventListener("devicemotion", onMotion);
    recenter = true;
    return true;
  }

  function disable() {
    window.removeEventListener("deviceorientation", onOrientation);
    window.removeEventListener("devicemotion", onMotion);
    orientation = null;
    pending = 0;
  }

  button.onclick = async () => {
    if (enabled) {
      disable();
      enabled = false;
    } else {
      enabled = await enable();
      if (enabled) onMessage("Phone mode: turn to look, walk to move. Start re-centres.");
    }
    button.textContent = enabled ? "Phone on" : "Phone";
  };

  // Joystick: drag inside the circle. Works with or without phone mode.
  const knob = joystick.firstElementChild;
  let stickPointer = null;
  function moveStick(e) {
    const r = joystick.getBoundingClientRect();
    const half = r.width / 2;
    const v = new THREE.Vector2(e.clientX - r.left - half, e.clientY - r.top - half);
    if (v.length() > half) v.setLength(half);
    knob.style.transform = `translate(${v.x}px, ${v.y}px)`;
    stick.set(v.x / half, -v.y / half);
  }
  joystick.addEventListener("pointerdown", (e) => {
    stickPointer = e.pointerId;
    joystick.setPointerCapture(e.pointerId);
    moveStick(e);
  });
  joystick.addEventListener("pointermove", (e) => e.pointerId === stickPointer && moveStick(e));
  const release = (e) => {
    if (e.pointerId !== stickPointer) return;
    stickPointer = null;
    stick.set(0, 0);
    knob.style.transform = "";
  };
  joystick.addEventListener("pointerup", release);
  joystick.addEventListener("pointercancel", release);

  return {
    get enabled() {
      return enabled;
    },
    get steps() {
      return steps;
    },
    // Re-centre: the phone's current facing becomes the camera's facing at the start.
    recenter() {
      recenter = true;
      pending = 0;
    },
    // Call once per frame. Returns true if phone mode controlled the camera's rotation.
    update(dt) {
      if (enabled && orientation) {
        deviceQuaternion(device, orientation);
        if (recenter) {
          yawFix.setFromAxisAngle(Y, yawOf(camera.quaternion) - yawOf(device));
          recenter = false;
        }
        camera.quaternion.copy(yawFix).multiply(device);
      }
      const forward = flatForward(camera);
      const right = new THREE.Vector3().crossVectors(forward, Y);
      if (pending > 0) {
        const d = Math.min(pending, WALK_SPEED * dt);
        camera.position.addScaledVector(forward, d);
        pending -= d;
      }
      if (stick.lengthSq() > 0) {
        camera.position.addScaledVector(forward, stick.y * JOYSTICK_SPEED * dt);
        camera.position.addScaledVector(right, stick.x * JOYSTICK_SPEED * dt);
      }
      return enabled && orientation !== null;
    },
  };
}

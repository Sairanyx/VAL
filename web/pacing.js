// Decides when the room needs redrawing, and how sharply. Drawing millions of splats is what makes
// the viewer slow, so nothing is drawn while nothing changes, and it draws fewer pixels while moving
// on a device that can't keep up, then sharpens as soon as the view stops.
const IDLE_AFTER = 1500; // milliseconds without change before drawing slows down
const IDLE_EVERY = 500; // still drawn now and then, as files can finish loading at any time
const ANIMATED_EVERY = 66; // the route's moving arrows don't need a higher rate than this
const SHARPEN_AFTER = 250; // milliseconds after the view stops
const TUNE_EVERY = 500;
const TOO_SLOW = 36; // milliseconds a frame: under about 28 frames a second
const QUICK_ENOUGH = 24;
const STEP = 0.1;
const LOWEST_RES = 0.3;

export function setupPacing({ renderer, camera, baseRes, adaptive, isBusy, isDragging, isAnimated }) {
  const lowestScale = Math.min(1, Math.max(0.5, LOWEST_RES / baseRes));
  const position = camera.position.clone();
  const turn = camera.quaternion.clone();
  const stats = { draws: 0, skipped: 0, scale: 1 };
  let lastActive = performance.now();
  let lastMoved = 0;
  let lastDraw = 0;
  let lastTune = 0;
  let movingScale = 1;
  let frameTime = 0;
  let samples = 0;
  let moving = false;

  function wake() {
    lastActive = performance.now();
  }
  for (const name of ["pointerdown", "pointerup", "keydown", "wheel", "click", "resize"]) {
    window.addEventListener(name, wake, { passive: true });
  }

  function setScale(scale) {
    if (Math.abs(scale - stats.scale) < 0.01) return;
    stats.scale = scale;
    renderer.setPixelRatio(baseRes * scale);
  }

  function shouldDraw(now) {
    const moved =
      position.distanceToSquared(camera.position) > 1e-8 ||
      Math.abs(turn.dot(camera.quaternion)) < 1 - 1e-9;
    if (moved) {
      position.copy(camera.position);
      turn.copy(camera.quaternion);
    }
    moving = moved || isDragging();
    if (moving) lastMoved = now;
    if (moving || isBusy()) lastActive = now;

    if (adaptive) {
      if (moving) setScale(movingScale);
      else if (now - lastMoved > SHARPEN_AFTER) {
        setScale(1);
        samples = 0; // A sharp frame takes longer, and says nothing about the speed while moving.
      }
    }
    if (now - lastActive < IDLE_AFTER) return true;
    const draw = now - lastDraw >= (isAnimated() ? ANIMATED_EVERY : IDLE_EVERY);
    if (!draw) stats.skipped += 1;
    return draw;
  }

  function drew(now) {
    const gap = now - lastDraw;
    lastDraw = now;
    stats.draws += 1;
    if (!adaptive || !moving) return;
    samples += 1;
    if (samples < 3) return; // The first frames after a pause include the pause.
    frameTime = samples === 3 ? gap : frameTime * 0.8 + gap * 0.2;
    if (now - lastTune < TUNE_EVERY) return;
    if (frameTime > TOO_SLOW && movingScale > lowestScale) {
      movingScale = Math.max(lowestScale, movingScale - STEP);
    } else if (frameTime < QUICK_ENOUGH && movingScale < 1) {
      movingScale = Math.min(1, movingScale + STEP / 2);
    } else return;
    lastTune = now;
    setScale(movingScale);
  }

  return { stats, wake, shouldDraw, drew };
}

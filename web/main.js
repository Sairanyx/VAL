// Plant room viewer: walk through the splat scene like a camera feed, with object boxes and labels.
// Data: /scene.ply (Gaussian splat) and /assets.json (same format as fixtures/sample_assets.json),
// both served by web/serve.py.
import * as THREE from "three";
import { SparkControls, SparkRenderer, SplatMesh } from "@sparkjsdev/spark";
import { setupPhone } from "./phone.js";

const FAULT_TAG = "P-005"; // the pre-chosen faulty device (docs/PLAN.md)
const EYE_HEIGHT = 1.6; // metres above the floor in walk mode (scene units look close to metres)
const LABEL_RANGE = 10; // only label objects closer than this
const MAX_LABELS = 12;

// Speed settings, changeable in the URL without editing code, e.g. ?res=0.5&splats=300000
//   res     render resolution relative to the screen (default 1; 0.5 is about 4x fewer pixels)
//   lod     1 = level of detail on: far-away areas use fewer, bigger splats (default 1)
//   splats  how many splats LOD aims to draw per frame (default: Spark's choice for the device)
const params = new URLSearchParams(location.search);
const RES = Number(params.get("res") ?? 1);
const LOD = params.get("lod") !== "0";
const LOD_SPLATS = params.has("splats") ? Number(params.get("splats")) : undefined;

const $ = (id) => document.getElementById(id);
const canvas = $("view");

const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
// Rendering every splat at full high-DPI resolution is the main cost; 1 pixel per CSS pixel is enough.
renderer.setPixelRatio(RES);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(70, 1, 0.05, 200);
scene.add(new SparkRenderer({ renderer, lodSplatCount: LOD_SPLATS }));

// The scene's +y points down. Turn it upright once here, and put everything in scene
// coordinates inside `root`, so file coordinates can be used as they are.
const root = new THREE.Group();
root.rotation.x = Math.PI;
scene.add(root);

const controls = new SparkControls({ canvas });
const phone = setupPhone({
  camera,
  button: $("phone"),
  joystick: $("joystick"),
  onMessage: (msg) => ($("status").textContent = msg),
});
const raycaster = new THREE.Raycaster();
const objects = []; // { asset, box, pick, label, center }
let walk = true;
let eyeY = EYE_HEIGHT;
let startPos = new THREE.Vector3(0, EYE_HEIGHT, 0);

function resize() {
  const w = window.innerWidth;
  const h = window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);
resize();

function kind(asset) {
  if (asset.mapping?.tag === FAULT_TAG) return "fault";
  return asset.mapping ? "mapped" : "plain";
}
const COLORS = { fault: 0xff4d4f, mapped: 0x38bdf8, plain: 0xd1d5db };

function name(asset) {
  return asset.mapping?.tag ?? asset.label;
}

function addAsset(asset) {
  const min = new THREE.Vector3(...asset.bbox_min);
  const max = new THREE.Vector3(...asset.bbox_max);
  const size = max.clone().sub(min);
  const mid = min.clone().add(max).multiplyScalar(0.5);
  const geom = new THREE.BoxGeometry(size.x, size.y, size.z);

  const box = new THREE.LineSegments(
    new THREE.EdgesGeometry(geom),
    new THREE.LineBasicMaterial({ color: COLORS[kind(asset)] }),
  );
  box.position.copy(mid);
  root.add(box);

  // Invisible solid box, so taps and the crosshair can hit the object.
  const pick = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({ visible: false }));
  pick.position.copy(mid);
  pick.userData.index = objects.length;
  root.add(pick);

  const label = document.createElement("div");
  label.className = `label ${kind(asset)}`;
  $("labels").append(label);

  objects.push({ asset, box, pick, label, center: new THREE.Vector3(...asset.center) });
}

function showInfo(obj) {
  const a = obj.asset;
  const m = a.mapping;
  const rows = [
    ["Type", a.label],
    ["Label confidence", a.label_confidence?.toFixed(2)],
    ["Object", a.object_id],
    ["Tag", m?.tag ?? "not mapped"],
    ["Asset", m?.asset_id],
    ["Mapped by", m ? `${m.method}, confidence ${m.confidence}` : undefined],
  ].filter(([, v]) => v !== undefined);
  $("info-body").innerHTML =
    `<h2>${name(a)}${kind(a) === "fault" ? " — fault" : ""}</h2><dl>` +
    rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("") +
    "</dl>";
  $("info").hidden = false;
}
$("info-close").onclick = () => ($("info").hidden = true);

function hit(ndc) {
  raycaster.setFromCamera(ndc, camera);
  const hits = raycaster.intersectObjects(objects.map((o) => o.pick));
  return hits.length ? objects[hits[0].object.userData.index] : null;
}

// A short tap without dragging selects an object. Drags are camera movement.
let down = null;
canvas.addEventListener("pointerdown", (e) => (down = { x: e.clientX, y: e.clientY, t: e.timeStamp }));
canvas.addEventListener("pointerup", (e) => {
  if (!down) return;
  const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
  const quick = e.timeStamp - down.t < 300;
  down = null;
  if (moved > 8 || !quick) return;
  const ndc = new THREE.Vector2(
    (e.clientX / window.innerWidth) * 2 - 1,
    -(e.clientY / window.innerHeight) * 2 + 1,
  );
  const obj = hit(ndc);
  if (obj) showInfo(obj);
});

$("mode").onclick = () => {
  walk = !walk;
  $("mode").textContent = walk ? "Walk" : "Fly";
};
$("boxes").onclick = () => {
  const on = $("boxes").textContent === "Boxes off";
  objects.forEach((o) => (o.box.visible = on));
  $("boxes").textContent = on ? "Boxes on" : "Boxes off";
};
$("reset").onclick = () => {
  camera.position.copy(startPos);
  camera.quaternion.identity();
  phone.recenter();
};

// Draw a label over every object in front of the camera, like detections on a camera feed.
// Occlusion is ignored for now: an object behind a wall still gets a label.
const tmp = new THREE.Vector3();
function updateLabels() {
  const visible = [];
  for (const o of objects) {
    const world = root.localToWorld(tmp.copy(o.center));
    const dist = world.distanceTo(camera.position);
    const ndc = world.project(camera);
    const onScreen = ndc.z < 1 && Math.abs(ndc.x) <= 1 && Math.abs(ndc.y) <= 1;
    o.label.style.display = "none";
    if (onScreen && dist < LABEL_RANGE) visible.push({ o, dist, ndc: ndc.clone() });
  }
  visible.sort((a, b) => a.dist - b.dist);
  for (const { o, dist, ndc } of visible.slice(0, MAX_LABELS)) {
    o.label.style.display = "block";
    o.label.style.left = `${((ndc.x + 1) / 2) * window.innerWidth}px`;
    o.label.style.top = `${((1 - ndc.y) / 2) * window.innerHeight}px`;
    o.label.innerHTML = `${name(o.asset)} <small>${o.asset.label} · ${dist.toFixed(1)} m</small>`;
  }
  const looking = hit(new THREE.Vector2(0, 0));
  $("in-view").textContent =
    `${visible.length} object(s) in view` + (looking ? ` · looking at ${name(looking.asset)}` : "");
}

let frames = 0;
let lastFps = performance.now();
let lastFrame = performance.now();
function animate(now) {
  const dt = Math.min((now - lastFrame) / 1000, 0.1);
  lastFrame = now;
  // In phone mode the phone's rotation steers, so mouse/touch dragging must not fight it.
  if (!phone.enabled) controls.update(camera);
  phone.update(dt);
  if (walk) camera.position.y = eyeY;
  renderer.render(scene, camera);
  updateLabels();
  frames++;
  if (now - lastFps > 1000) {
    const fps = Math.round((frames * 1000) / (now - lastFps));
    $("stats").textContent = `${fps} fps` + (phone.enabled ? ` · ${phone.steps} steps` : "");
    frames = 0;
    lastFps = now;
  }
}

async function load() {
  const data = await (await fetch("assets.json")).json();
  data.assets.forEach(addAsset);

  // Floor and start are in scene coordinates; convert to the upright world.
  const floor = root.localToWorld(new THREE.Vector3(0, data.floor_y ?? 0, 0)).y;
  eyeY = floor + EYE_HEIGHT;
  const start = data.start ?? [0, data.floor_y ?? 0, 0];
  startPos = root.localToWorld(new THREE.Vector3(...start));
  startPos.y = eyeY;
  camera.position.copy(startPos);

  const splat = new SplatMesh({ url: "scene.ply", lod: LOD });
  root.add(splat);
  renderer.setAnimationLoop(animate);
  await splat.initialized;
  const count = splat.packedSplats?.numSplats || splat.splats?.numSplats; // 0 or missing with LOD
  $("status").textContent =
    `${data.assets.length} objects · ${count ? `${count.toLocaleString()} splats · ` : ""}` +
    `res ${RES}, LOD ${LOD ? "on" : "off"}${LOD_SPLATS ? ` (${LOD_SPLATS})` : ""} · ` +
    "drag to look, WASD to move";
}

load().catch((err) => {
  $("status").textContent = `Failed to load: ${err.message}`;
  console.error(err);
});

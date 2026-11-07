// One control for how the room is shown, from nothing to the real thing: darkness, simple BIM, blob
// BIM, point cloud, real view. It reuses BIM mode's looks and the scan, and frames and labels stay
// on the real view only.
import * as THREE from "three";
import { SplatMesh, dyno } from "@sparkjsdev/spark";

const POINT_SIZE = 0.005; // metres
const NAMES = {
  dark: "Darkness",
  box: "Simple BIM",
  mesh: "Blob BIM",
  points: "Point cloud",
  real: "Real view",
};
const IN_BIM = new Set(["box", "mesh"]);

export function setupViews({ root, bim, press, button, onChange }) {
  const available = ["dark", "box", "mesh", "points", "real"].filter(
    (stage) => !IN_BIM.has(stage) || bim?.looks.includes(stage),
  );
  const state = { stage: "real" };
  const shrink = dyno.dynoBlock({ gsplat: dyno.Gsplat }, { gsplat: dyno.Gsplat }, ({ gsplat }) => ({
    gsplat: dyno.combineGsplat({
      gsplat,
      scales: dyno.dynoVec3(new THREE.Vector3(POINT_SIZE, POINT_SIZE, POINT_SIZE)),
    }),
  }));

  // Every splat in the scan shrinks to a dot, so moved objects stay where they are.
  function showPoints(on) {
    root.traverse((node) => {
      if (!(node instanceof SplatMesh)) return;
      node.objectModifier = on ? shrink : undefined;
      node.updateGenerator();
    });
  }

  function set(stage) {
    if (!available.includes(stage)) throw new Error(`There's no ${stage} view here`);
    const before = state.stage;
    if (stage === before && IN_BIM.has(stage) === Boolean(bim?.state.active)) return;
    state.stage = stage;
    if (before === "points") showPoints(false);
    if (IN_BIM.has(stage) !== Boolean(bim?.state.active)) press("bim");
    if (IN_BIM.has(stage)) bim.setLook(stage);
    if (stage === "points") showPoints(true);
    root.visible = stage !== "dark";
    document.body.dataset.view = stage;
    button.textContent = `View: ${NAMES[stage]}`;
    onChange(stage, stage === "dark" ? "" : NAMES[stage]);
  }

  function next() {
    // The BIM button can have changed things since.
    if (bim?.state.active && !IN_BIM.has(state.stage)) state.stage = bim.state.look;
    else if (!bim?.state.active && IN_BIM.has(state.stage)) state.stage = "real";
    set(available[(available.indexOf(state.stage) + 1) % available.length]);
  }

  button.textContent = `View: ${NAMES.real}`;
  button.onclick = next;
  return {
    state,
    available,
    set,
    next,
    // Just the room, without frames and labels.
    isQuiet: () => state.stage !== "real" || Boolean(bim?.state.active),
  };
}

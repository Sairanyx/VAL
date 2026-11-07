import * as THREE from "three";
import { SplatMesh } from "@sparkjsdev/spark";

// Separate segmented splats, not a volume mask: neighbouring surfaces inside the box stay normal.
export function setupHighlight({ root, objectLayer, onMessage }) {
  let selected = null;
  let overlay = null;
  let request = 0;
  const home = new THREE.Vector3();
  const yAxis = new THREE.Vector3(0, 1, 0);
  let manifests;

  function disposeOverlay() {
    if (!overlay) return;
    root.remove(overlay);
    overlay.dispose();
    overlay = null;
  }

  async function select(object) {
    const token = ++request;
    selected = object;
    disposeOverlay();
    if (!object) return;
    try {
      manifests ??= fetch("highlights.json").then(async (response) => {
        if (response.status === 404) return null;
        if (!response.ok) throw new Error(`Highlight manifest: HTTP ${response.status}`);
        return response.json();
      });
      const manifest = await manifests;
      if (token !== request || !object) return;
      if (!manifest?.[object.asset.object_id]) {
        onMessage("No segmented highlight for this object. Run make highlights; new objects need segmentation.");
        return;
      }
      const candidate = new SplatMesh({
        url: `highlights/${encodeURIComponent(object.asset.object_id)}.ply`,
        lod: false,
      });
      try {
        await candidate.initialized;
      } catch (error) {
        candidate.dispose();
        throw error;
      }
      if (token !== request) {
        candidate.dispose();
        return;
      }
      overlay = candidate;
      home.set(...object.asset.center);
      root.add(overlay);
      update();
    } catch (error) {
      manifests = undefined;
      console.error("Object highlight failed", error);
      if (token === request) onMessage(`Object highlight failed: ${error.message}`);
    }
  }

  function update() {
    if (!overlay || !selected) return;
    overlay.visible = objectLayer()?.state.view !== "objects" && !selected.gone;
    const yaw = selected.yaw || 0;
    overlay.quaternion.setFromAxisAngle(yAxis, yaw);
    const rotatedHome = home.clone().applyAxisAngle(yAxis, yaw);
    overlay.position.copy(selected.center).sub(rotatedHome);
  }

  return { select, update, hasSurface: (object) => selected === object && Boolean(overlay?.visible) };
}

// A faint shell and outline of the shape under the mouse, so it's clear what a tap would pick.
// Used in the scan view and in BIM mode. Shapes are given in the parent's coordinates.
import * as THREE from "three";

const HOVER_COLOR = 0xe0f2fe;

export function createHoverShell(parent, clippingPlanes = []) {
  const fill = new THREE.MeshBasicMaterial({
    color: HOVER_COLOR,
    transparent: true,
    opacity: 0.12,
    depthWrite: false,
    side: THREE.DoubleSide,
    clippingPlanes,
  });
  const line = new THREE.LineBasicMaterial({
    color: HOVER_COLOR,
    transparent: true,
    opacity: 0.8,
    depthTest: false,
    clippingPlanes,
  });
  const mesh = new THREE.Mesh(undefined, fill);
  const edges = new THREE.LineSegments(undefined, line);
  mesh.add(edges);
  mesh.renderOrder = edges.renderOrder = 10;
  mesh.raycast = edges.raycast = () => {};
  mesh.visible = false;
  parent.add(mesh);
  // Only sharp edges, so a cylinder shows its rims and outline, not every side face.
  const edgeCache = new WeakMap();

  function show(geometry, position, quaternion) {
    if (mesh.geometry !== geometry) {
      mesh.geometry = geometry;
      if (!edgeCache.has(geometry)) edgeCache.set(geometry, new THREE.EdgesGeometry(geometry, 20));
      edges.geometry = edgeCache.get(geometry);
    }
    mesh.position.copy(position);
    mesh.quaternion.copy(quaternion);
    mesh.visible = true;
  }

  function hide() {
    mesh.visible = false;
  }

  return { show, hide, get visible() { return mesh.visible; } };
}

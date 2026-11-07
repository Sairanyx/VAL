// The service worker or robot walking the route: the camera follows behind it. Simple on purpose:
// a figure in hi-vis, or a low robot, sized to the body the route was planned for.
import * as THREE from "three";

const HI_VIS = 0xff7a1a;
const HELMET = 0xf5f5f0;
const DARK = 0x2b3038;
const STRIPE = 0xe8ff5a;

function part(geometry, color, y, parent) {
  const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ color }));
  mesh.position.y = y;
  parent.add(mesh);
  return mesh;
}

function makePerson() {
  const figure = new THREE.Group();
  part(new THREE.CapsuleGeometry(0.1, 0.62, 4, 10), DARK, 0.46, figure); // legs
  part(new THREE.CapsuleGeometry(0.19, 0.38, 4, 12), HI_VIS, 1.08, figure);
  part(new THREE.CylinderGeometry(0.195, 0.195, 0.05, 14), STRIPE, 1.12, figure);
  part(new THREE.SphereGeometry(0.115, 14, 10), 0xd9b08c, 1.54, figure);
  part(new THREE.SphereGeometry(0.13, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2), HELMET, 1.57, figure);
  return figure;
}

function makeRobot() {
  const figure = new THREE.Group();
  part(new THREE.BoxGeometry(0.3, 0.14, 0.42), DARK, 0.1, figure);
  part(new THREE.BoxGeometry(0.24, 0.16, 0.3), HI_VIS, 0.25, figure);
  const mast = part(new THREE.CylinderGeometry(0.018, 0.018, 0.22, 8), DARK, 0.44, figure);
  mast.position.z = 0.08;
  const camera = part(new THREE.BoxGeometry(0.09, 0.05, 0.05), HELMET, 0.56, figure);
  camera.position.z = 0.08;
  return figure;
}

export function setupAvatar({ parent }) {
  const bodies = { person: makePerson(), robot: makeRobot() };
  for (const body of Object.values(bodies)) {
    body.visible = false;
    body.renderOrder = 11;
    parent.add(body);
  }
  let current = bodies.person;

  function place(profile, position, facing) {
    current.visible = false;
    current = bodies[profile] ?? bodies.person;
    current.visible = true;
    current.position.copy(position);
    if (facing) current.rotation.y = Math.atan2(facing.x, facing.z);
  }

  function hide() {
    current.visible = false;
  }

  return { place, hide, isShown: () => current.visible, position: () => current.position };
}

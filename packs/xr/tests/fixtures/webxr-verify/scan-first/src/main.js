import * as THREE from 'three';
import { VRButton } from 'three/addons/webxr/VRButton.js';

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.xr.enabled = true;
document.body.appendChild(renderer.domElement);
document.body.appendChild(VRButton.createButton(renderer));

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.1, 100);
scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 2));

const pier = new THREE.Mesh(new THREE.BoxGeometry(2, 0.2, 12), new THREE.MeshStandardMaterial({ color: 0x8b6b4a }));
pier.position.set(0, -0.1, -6);
scene.add(pier);

const controller = renderer.xr.getController(0);
controller.addEventListener('select', () => {
  pier.material.color.offsetHSL(0.05, 0, 0);
});
scene.add(controller);

// Changed: moved the render call into a function so the stats panel can wrap it.
function frame() {
  renderer.render(scene, camera);
  window.requestAnimationFrame(frame);
}
frame();

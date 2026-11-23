import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 0.1, 100);
camera.position.set(2, 1.5, 3);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.outputEncoding = THREE.sRGBEncoding;
renderer.setSize(innerWidth, innerHeight);
document.body.appendChild(renderer.domElement);

scene.add(new THREE.AmbientLight(0xffffff, 0.4));
const sun = new THREE.DirectionalLight(0xffffff, 1.2);
sun.position.set(3, 5, 2);
scene.add(sun);

new GLTFLoader().load('/models/vase.glb', (gltf) => scene.add(gltf.scene));
const controls = new OrbitControls(camera, renderer.domElement);

renderer.setAnimationLoop(() => {
  controls.update();
  renderer.render(scene, camera);
});

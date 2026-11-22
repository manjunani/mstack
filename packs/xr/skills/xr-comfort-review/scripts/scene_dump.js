/*
 * mstack xr-comfort-review: dump the UI of a running three.js scene for comfort.py.
 *
 * Run it in the page (browser console, or your browser tool's evaluate step) while the XR camera or the
 * normal camera stands where the user's head would be. Mark the objects to measure in your own code:
 *   mesh.userData.mstackUi = { name: 'main menu', textHeight: 0.024, interactive: true };
 * textHeight is the height of one line of text in metres, in the object's own units before scaling.
 *
 *   const dump = mstackSceneDump(scene, renderer.xr.isPresenting ? renderer.xr.getCamera() : camera, THREE);
 *   copy(JSON.stringify(dump))      // save as scene_dump.json
 *
 * Sizes come from the world bounding box, so parent scaling is included. "head_locked" is true when the
 * object is a child of the camera. Nothing is changed in the scene.
 */
function mstackSceneDump(scene, camera, THREE) {
  camera.updateMatrixWorld(true);
  scene.updateMatrixWorld(true);
  var head = new THREE.Vector3(), forward = new THREE.Vector3();
  camera.getWorldPosition(head);
  camera.getWorldDirection(forward);
  var scale = new THREE.Vector3(), elements = [];
  scene.traverse(function (obj) {
    var ui = obj.userData && obj.userData.mstackUi;
    if (!ui) return;
    var box = new THREE.Box3().setFromObject(obj), centre = new THREE.Vector3(), size = new THREE.Vector3();
    box.getCenter(centre); box.getSize(size);
    obj.getWorldScale(scale);
    var dims = [size.x, size.y, size.z].sort(function (a, b) { return b - a; });
    var locked = false;
    for (var p = obj.parent; p; p = p.parent) { if (p === camera) { locked = true; break; } }
    elements.push({
      name: ui.name || obj.name || obj.uuid,
      position: [centre.x, centre.y, centre.z],
      size: [dims[0], dims[1]],
      text_height: typeof ui.textHeight === 'number' ? ui.textHeight * Math.abs(scale.y) : null,
      has_text: typeof ui.textHeight === 'number' || !!ui.hasText,
      head_locked: locked,
      interactive: !!ui.interactive
    });
  });
  return { tool: 'mstack xr-comfort-review dump', head: { position: [head.x, head.y, head.z], forward: [forward.x, forward.y, forward.z] }, elements: elements };
}
if (typeof module !== 'undefined' && module.exports) module.exports = mstackSceneDump;

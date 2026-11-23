import 'aframe';

// Paintings are added from a list so the curator can edit one file.
const paintings = ['dunes', 'harbour', 'orchard'];
paintings.forEach((name, i) => {
  const frame = document.createElement('a-plane');
  frame.setAttribute('position', `${i * 1.5 - 1.5} 1.6 -4`);
  frame.setAttribute('src', `/art/${name}.jpg`);
  document.querySelector('a-scene').appendChild(frame);
});

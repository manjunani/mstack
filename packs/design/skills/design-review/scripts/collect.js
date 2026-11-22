// mstack page snapshot collector, format 1 (see references/snapshot-format.md).
// This file is one expression. Evaluate it in the page and it returns one "view":
// the visible text and controls at the current viewport, theme and state.
//   Playwright:      const view = await page.evaluate(fs.readFileSync('collect.js', 'utf8'));
//   Browser tool:    run the file's text as JavaScript and save the returned object as JSON.
//   Console (paste): copy(JSON.stringify( <this file's text> ))
// Label the capture first when the theme or state is not the default:
//   window.__mstackView = { theme: 'dark', state: 'empty cart' };
// It reads the page and changes nothing. It sends nothing anywhere.
(() => {
  const label = window.__mstackView || {};
  const MAX_ELEMENTS = 2000;
  const root = document.documentElement;
  const NAME_FROM_CONTENT = new Set(['button', 'link', 'heading', 'tab', 'menuitem', 'option', 'checkbox', 'radio', 'switch', 'cell', 'columnheader', 'rowheader', 'tooltip', 'treeitem']);
  const INTERACTIVE_ROLES = new Set(['button', 'link', 'textbox', 'searchbox', 'combobox', 'listbox', 'checkbox', 'radio', 'switch', 'slider', 'spinbutton', 'tab', 'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option', 'treeitem']);
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const round = (n) => Math.round(n * 10) / 10;

  let probe = null;
  const rgba = (value) => {
    const m = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/.exec(value || '');
    if (m) {
      const a = m[4] === undefined ? 1 : (m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]));
      return [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3]), a];
    }
    try { // any other colour syntax: let the browser paint it and read the pixel back
      probe = probe || Object.assign(document.createElement('canvas'), { width: 1, height: 1 }).getContext('2d', { willReadFrequently: true });
      probe.clearRect(0, 0, 1, 1);
      probe.fillStyle = '#000';
      probe.fillStyle = value;
      probe.fillRect(0, 0, 1, 1);
      const d = probe.getImageData(0, 0, 1, 1).data;
      return [d[0], d[1], d[2], d[3] / 255];
    } catch (e) {
      return null;
    }
  };
  const css = (c) => (c[3] >= 1 ? `rgb(${Math.round(c[0])}, ${Math.round(c[1])}, ${Math.round(c[2])})` : `rgba(${Math.round(c[0])}, ${Math.round(c[1])}, ${Math.round(c[2])}, ${Math.round(c[3] * 1000) / 1000})`);

  // The colour behind an element's text: its own and its ancestors' background colours, composited.
  // An image or gradient in the way, or a dark browser canvas, makes the result unknown.
  const backdrop = (el) => {
    const layers = [];
    let known = true;
    let solid = false;
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const cs = getComputedStyle(node);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') { known = false; break; }
      const c = rgba(cs.backgroundColor);
      if (c && c[3] > 0) {
        layers.push(c);
        if (c[3] >= 1) { solid = true; break; }
      }
    }
    let base = [255, 255, 255];
    if (!solid && known && /dark/.test(getComputedStyle(root).colorScheme || '') && matchMedia('(prefers-color-scheme: dark)').matches) known = false;
    for (let i = layers.length - 1; i >= 0; i -= 1) {
      const c = layers[i];
      base = [0, 1, 2].map((k) => c[k] * c[3] + base[k] * (1 - c[3]));
    }
    return { color: css([base[0], base[1], base[2], 1]), known };
  };

  const opacityOf = (el) => {
    let o = 1;
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) o *= parseFloat(getComputedStyle(node).opacity || '1');
    return o;
  };

  const implicitRole = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'a' || tag === 'area') return el.hasAttribute('href') ? 'link' : '';
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'select') return el.multiple ? 'listbox' : 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'img') return el.getAttribute('alt') === '' ? 'presentation' : 'img';
    if (/^h[1-6]$/.test(tag)) return 'heading';
    if (tag === 'input') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      return { button: 'button', submit: 'button', reset: 'button', image: 'button', checkbox: 'checkbox', radio: 'radio', range: 'slider', number: 'spinbutton', search: 'searchbox', hidden: '' }[t] ?? 'textbox';
    }
    return { nav: 'navigation', main: 'main', dialog: 'dialog', li: 'listitem', th: 'columnheader', td: 'cell', label: '', p: '', option: 'option' }[tag] || '';
  };

  const nameOf = (el, role) => {
    const tag = el.tagName.toLowerCase();
    const ids = clean(el.getAttribute('aria-labelledby')).split(' ').filter(Boolean);
    if (ids.length) {
      const t = clean(ids.map((id) => (document.getElementById(id) || {}).textContent || '').join(' '));
      if (t) return [t, 'aria-labelledby'];
    }
    const aria = clean(el.getAttribute('aria-label'));
    if (aria) return [aria, 'aria-label'];
    if (el.labels && el.labels.length) {
      const t = clean(Array.from(el.labels).map((l) => l.textContent).join(' '));
      if (t) return [t, 'label'];
    }
    if (tag === 'img' || tag === 'area' || (tag === 'input' && el.type === 'image')) {
      const alt = clean(el.getAttribute('alt'));
      if (alt) return [alt, 'alt'];
    }
    if (tag === 'input' && ['button', 'submit', 'reset'].includes(el.type)) return [clean(el.value) || el.type, 'value'];
    if (tag === 'svg') {
      const t = el.querySelector(':scope > title');
      if (t && clean(t.textContent)) return [clean(t.textContent), 'title element'];
    }
    if (NAME_FROM_CONTENT.has(role) || tag === 'label' || tag === 'legend' || tag === 'caption') {
      let t = clean(el.innerText === undefined ? el.textContent : el.innerText);
      if (!t) {
        t = clean(Array.from(el.querySelectorAll('img[alt], [aria-label], svg > title')).map((n) => n.getAttribute('alt') || n.getAttribute('aria-label') || n.textContent).join(' '));
      }
      if (t) return [t, 'content'];
    }
    const title = clean(el.getAttribute('title'));
    if (title) return [title, 'title'];
    const placeholder = clean(el.getAttribute('placeholder'));
    if (placeholder) return [placeholder, 'placeholder'];
    return ['', ''];
  };

  const selectorOf = (el) => {
    const parts = [];
    for (let node = el; node && node.nodeType === 1 && node !== root && parts.length < 4; node = node.parentElement) {
      if (node.id) { parts.unshift('#' + CSS.escape(node.id)); break; }
      let part = node.tagName.toLowerCase();
      const classes = Array.from(node.classList).slice(0, 2).map((c) => '.' + CSS.escape(c)).join('');
      part += classes;
      const twins = node.parentElement ? Array.from(node.parentElement.children).filter((s) => s.tagName === node.tagName) : [];
      if (twins.length > 1) part += `:nth-of-type(${twins.indexOf(node) + 1})`;
      parts.unshift(part);
    }
    return parts.join(' > ');
  };

  const view = {
    viewport: { width: window.innerWidth, height: window.innerHeight },
    theme: label.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'),
    state: label.state || 'default',
    url: location.href,
    title: document.title,
    captured: new Date().toISOString(),
    collector: 'mstack collect.js 1',
    document: { scrollWidth: root.scrollWidth, clientWidth: root.clientWidth, scrollHeight: root.scrollHeight },
    elements: [],
    skipped: 0,
  };

  for (const el of document.body ? document.body.querySelectorAll('*') : []) {
    const tag = el.tagName.toLowerCase();
    if (['script', 'style', 'noscript', 'template', 'head', 'meta', 'link', 'br', 'wbr', 'path', 'g', 'defs'].includes(tag)) continue;
    if (el.closest('svg') && tag !== 'svg') continue;
    const ownText = clean(Array.from(el.childNodes).filter((n) => n.nodeType === 3).map((n) => n.textContent).join(' '));
    const explicit = clean(el.getAttribute('role'));
    const role = explicit || implicitRole(el);
    const native = (tag === 'a' && el.hasAttribute('href')) || ['button', 'select', 'textarea', 'summary'].includes(tag) || (tag === 'input' && el.type !== 'hidden');
    const interactive = native || INTERACTIVE_ROLES.has(role) || el.hasAttribute('onclick');
    const picture = tag === 'img' || role === 'img' || (tag === 'svg' && !el.closest('a, button, [role=button], [role=link]'));
    if (!ownText && !interactive && !picture) continue;
    const cs = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    if (cs.display === 'none' || cs.visibility !== 'visible' || (rect.width === 0 && rect.height === 0)) continue;
    const opacity = opacityOf(el);
    if (opacity === 0) continue;
    if (view.elements.length >= MAX_ELEMENTS) { view.skipped += 1; continue; }

    const [name, nameFrom] = nameOf(el, role);
    const color = rgba(cs.color) || [0, 0, 0, 1];
    const back = backdrop(el);
    const item = {
      selector: selectorOf(el),
      tag,
      role,
      name,
      text: ownText.slice(0, 300),
      box: { x: round(rect.left + window.scrollX), y: round(rect.top + window.scrollY), width: round(rect.width), height: round(rect.height) },
      color: css([color[0], color[1], color[2], color[3] * opacity]),
      background: back.color,
      backgroundKnown: back.known,
      fontSize: round(parseFloat(cs.fontSize) || 0),
      fontWeight: parseInt(cs.fontWeight, 10) || 400,
      fontFamily: cs.fontFamily,
    };
    if (nameFrom) item.nameFrom = nameFrom;
    if (interactive) item.interactive = true;
    if (!el.disabled && el.tabIndex >= 0 && (native || el.hasAttribute('tabindex') || el.isContentEditable)) item.focusable = true;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') item.disabled = true;
    if (cs.display === 'inline' && interactive && el.parentElement && clean(el.parentElement.textContent).length > clean(el.textContent).length) item.inline = true;
    if (tag === 'a' && el.hasAttribute('href')) item.href = el.getAttribute('href');
    if (el.getAttribute('placeholder')) item.placeholder = clean(el.getAttribute('placeholder'));
    if (el.getAttribute('aria-hidden') === 'true' || role === 'presentation' || role === 'none' || (tag === 'img' && el.getAttribute('alt') === '')) item.decorative = true;
    if (cs.backgroundImage && cs.backgroundImage.includes('gradient')) item.backgroundImage = cs.backgroundImage.slice(0, 200);
    if ((rect.width <= 1 && rect.height <= 1) || /inset\(50%\)|rect\(0(px)?[, ]+0(px)?[, ]+0(px)?[, ]+0(px)?\)/.test(cs.clipPath + ' ' + cs.clip)) item.visuallyHidden = true;

    if (ownText && !item.visuallyHidden) {
      const cutX = el.scrollWidth > el.clientWidth + 1 && /hidden|clip/.test(cs.overflowX);
      const cutY = el.scrollHeight > el.clientHeight + 1 && /hidden|clip/.test(cs.overflowY);
      if (cutX || cutY) {
        const clamp = cs.webkitLineClamp && cs.webkitLineClamp !== 'none';
        if (cs.textOverflow === 'ellipsis' || clamp) item.truncated = clamp ? 'line clamp' : 'ellipsis';
        else item.clipped = true;
      }
    }
    if (!item.visuallyHidden) {
      for (let p = el.parentElement; p && p !== document.body && p !== root; p = p.parentElement) {
        const ps = getComputedStyle(p);
        const flow = ps.overflowX + ' ' + ps.overflowY;
        if (/auto|scroll/.test(flow) && (p.scrollWidth > p.clientWidth + 1 || p.scrollHeight > p.clientHeight + 1)) { item.inScroller = true; break; }
        if (/hidden|clip/.test(flow)) {
          const pr = p.getBoundingClientRect();
          if (rect.right > pr.right + 1 || rect.bottom > pr.bottom + 1 || rect.left < pr.left - 1 || rect.top < pr.top - 1) { item.clippedBy = selectorOf(p); break; }
        }
      }
    }
    view.elements.push(item);
  }
  return view;
})()

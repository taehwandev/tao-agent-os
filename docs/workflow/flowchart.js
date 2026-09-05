import { flowchartModel } from './flowchart-model.js';

// A responsive edge layer uses percentage x coordinates; HTML labels do not scale.
export function renderFlowchart(container, route, language, page) {
  const model = flowchartModel(route, language);
  const html = (tag, className, text) => {
    const element = page.createElement(tag);
    element.className = className;
    if (text) element.textContent = text;
    return element;
  };
  const svg = (tag, attributes) => {
    const element = page.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
    return element;
  };
  const legend = html('div', 'flowchart-key');
  ['terminal', 'process', 'decision'].forEach((type, i) => {
    const item = html('span', `flowchart-key-${type}`, model.legend[i]);
    legend.append(item);
  });
  const canvas = html('div', 'flowchart-canvas');
  canvas.setAttribute('aria-hidden', 'true');
  const accessible = html('ol', 'flowchart-accessible');
  canvas.style.height = `${model.height}px`;
  const lines = svg('svg', { viewBox: `0 0 100 ${model.height}`, preserveAspectRatio: 'none', 'aria-hidden': 'true', class: 'flowchart-lines' });
  canvas.append(lines);
  model.edges.forEach(edge => {
    const from = model.nodes.find(n => n.id === edge.from);
    const to = model.nodes.find(n => n.id === edge.to);
    accessible.append(html('li', '', `${from.label} → ${to.label}${edge.label ? ` (${edge.label})` : ''}`));
    const sameLane = from.x === to.x;
    const direction = to.y > from.y ? 1 : -1;
    const start = sameLane ? [from.x, from.y + direction * from.height / 2]
      : [from.x + (to.x > from.x ? 1 : -1) * from.width / 2, from.y];
    const end = sameLane ? [to.x, to.y - direction * to.height / 2]
      : [to.x + (to.x > from.x ? -1 : 1) * to.width / 2, to.y];
    // The recovery edge takes the gap between lanes, never crossing an action.
    const bend = edge.kind === 'retry' ? 55 : (start[0] + end[0]) / 2;
    const d = `M ${start.join(' ')} H ${bend} V ${end[1]} H ${end[0]}`;
    lines.append(svg('path', { d, class: `flowchart-edge ${edge.kind}`, 'data-from': edge.from, 'data-to': edge.to }));
    const arrow = html('span', 'flowchart-arrow', sameLane ? (direction > 0 ? '▼' : '▲') : (to.x > from.x ? '▶' : '◀'));
    arrow.setAttribute('aria-hidden', 'true');
    arrow.style.left = `${end[0]}%`; arrow.style.top = `${end[1]}px`;
    canvas.append(arrow);
    if (edge.label) {
      const label = html('span', `flowchart-edge-label ${edge.kind}`, edge.label);
      label.style.left = `${sameLane ? start[0] : bend}%`;
      label.style.top = `${sameLane ? (start[1] + end[1]) / 2 : (start[1] + end[1]) / 2 - 14}px`;
      label.setAttribute('aria-label', `${from.label} → ${to.label}: ${edge.label}`);
      canvas.append(label);
    }
  });
  model.nodes.forEach(n => {
    const shape = html('div', `flowchart-node flowchart-${n.type}`, '');
    shape.dataset.node = n.id;
    shape.style.left = `${n.x}%`; shape.style.top = `${n.y}px`;
    shape.style.width = `${n.width}%`; shape.style.height = `${n.height}px`;
    shape.append(html('span', 'flowchart-node-label', n.label));
    canvas.append(shape);
  });
  if (route === 'change') {
    const note = html('span', 'flowchart-recovery-note', language === 'ko'
      ? '안전하고 승인된 수정만, 한 번까지' : 'One attempt, only if safe and authorized');
    canvas.append(note);
    accessible.append(html('li', '', note.textContent));
  }
  container.replaceChildren(legend, canvas, accessible);
  return model.legend[3];
}

const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { pathToFileURL } = require('node:url');
const { test } = require('node:test');

// A small DOM boundary for route/localization logic, not a layout/browser test.
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.dataset = {}; this.style = {}; this.events = {}; this.text = ''; }
  set textContent(value) { this.text = value; this.children = []; }
  get textContent() { return this.text + this.children.map(child => child.textContent).join(' '); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.text = ''; this.children = children; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(name, callback) { this.events[name] = callback; }
}

function createPage(language = 'en') {
  return {
    documentElement: { lang: language }, events: {},
    createElement(tag) { return new Element(tag); },
    createElementNS(namespace, tag) { return new Element(tag); },
    addEventListener(name, callback) { this.events[name] = callback; }
  };
}

function descendants(element, predicate) {
  return element.children.flatMap(child => [
    ...(predicate(child) ? [child] : []), ...descendants(child, predicate)
  ]);
}

const base = resolve(__dirname, '../docs/workflow');
const modules = Promise.all([
  import(pathToFileURL(resolve(base, 'map.js'))),
  import(pathToFileURL(resolve(base, 'content.js')))
]);

test('renders four route controls and a complete default code-change path', async () => {
  const [{ mountWorkflow }, { workflowContent }] = await modules;
  const root = new Element('div');
  mountWorkflow(root, createPage());
  const buttons = descendants(root, e => e.tagName === 'button');
  assert.equal(buttons.length, 4);
  assert.equal(buttons.find(b => b.attributes['aria-pressed'] === 'true').dataset.workflow, 'change');
  assert.equal(descendants(root, e => e.className === 'workflow-step').length, workflowContent.en.routes.change.steps.length);
  assert.match(root.textContent, /Run the VibeGuard audit/);
});

test('every route selection updates ordered stages, source, and pressed state in both languages', async () => {
  const [{ mountWorkflow }, { workflowContent }] = await modules;
  for (const lang of ['en', 'ko']) {
    const root = new Element('div');
    mountWorkflow(root, createPage(lang));
    const buttons = descendants(root, e => e.tagName === 'button');
    for (const button of buttons) {
      button.events.click();
      const route = workflowContent[lang].routes[button.dataset.workflow];
      assert.ok(root.textContent.includes(route.summary));
      assert.deepEqual(descendants(root, e => e.className === 'workflow-step').map(e => e.children[1].textContent), route.steps.map(s => s[0]));
      assert.equal(buttons.filter(b => b.attributes['aria-pressed'] === 'true').length, 1);
      assert.equal(button.attributes['aria-pressed'], 'true');
      assert.ok(descendants(root, e => e.tagName === 'a')[0].href.endsWith(route.source));
    }
  }
});

test('language changes preserve route selection and the control nodes', async () => {
  const [{ mountWorkflow }, { workflowContent }] = await modules;
  const root = new Element('div'); const page = createPage();
  mountWorkflow(root, page);
  const buttons = descendants(root, e => e.tagName === 'button');
  const cleanup = buttons.find(b => b.dataset.workflow === 'cleanup');
  cleanup.events.click();
  page.events['tao:language']({ detail: { language: 'ko' } });
  assert.equal(cleanup.textContent, workflowContent.ko.routes.cleanup.name);
  assert.equal(cleanup.attributes['aria-pressed'], 'true');
  assert.equal(descendants(root, e => e.tagName === 'button')[0], buttons[0]);
  assert.ok(root.textContent.includes(workflowContent.ko.routes.cleanup.output));
  page.events['tao:language']({ detail: { language: 'unknown' } });
  assert.equal(cleanup.textContent, workflowContent.en.routes.cleanup.name);
});

test('controls use native buttons and details with a labeled ordered sequence', async () => {
  const [{ mountWorkflow }] = await modules;
  const root = new Element('div'); mountWorkflow(root, createPage());
  for (const button of descendants(root, e => e.tagName === 'button')) {
    assert.equal(button.type, 'button'); assert.equal(button.attributes['aria-controls'], 'workflow-stages');
  }
  assert.equal(descendants(root, e => e.tagName === 'details').length, 2);
  assert.equal(descendants(root, e => e.tagName === 'summary').length, 2);
  assert.ok(descendants(root, e => e.id === 'workflow-stages')[0].attributes['aria-label']);
  assert.equal(descendants(root, e => e.attributes.role === 'status').length, 1);
  assert.doesNotThrow(() => mountWorkflow(null, createPage()));
});

test('all diagrams have explicit, reachable decision branches and readable terminal nodes', async () => {
  const { flowchartModel } = await import(pathToFileURL(resolve(base, 'flowchart-model.js')));
  const [{ mountWorkflow }] = await modules;
  for (const language of ['en', 'ko']) {
    for (const route of ['analysis', 'change', 'commit', 'cleanup']) {
      const chart = flowchartModel(route, language);
      const ids = new Set(chart.nodes.map(n => n.id));
      assert.equal(ids.size, chart.nodes.length);
      const visited = new Set(['start']);
      for (let i = 0; i < chart.nodes.length; i++) {
        for (const edge of chart.edges) {
          assert.ok(ids.has(edge.from) && ids.has(edge.to));
          if (visited.has(edge.from)) visited.add(edge.to);
        }
      }
      assert.deepEqual(visited, ids);
      for (const node of chart.nodes) {
        const outgoing = chart.edges.filter(e => e.from === node.id);
        if (node.type === 'decision') {
          assert.deepEqual(outgoing.map(e => e.label).sort(), language === 'ko' ? ['아니오', '예'] : ['NO', 'YES']);
        }
        if (!outgoing.length) assert.equal(node.type, 'terminal');
        assert.ok(node.x - node.width / 2 >= 0 && node.x + node.width / 2 <= 100);
        assert.ok(node.y - node.height / 2 >= 0 && node.y + node.height / 2 <= chart.height);
      }
      const root = new Element('div'); mountWorkflow(root, createPage(language));
      descendants(root, e => e.tagName === 'button').find(b => b.dataset.workflow === route).events.click();
      assert.equal(descendants(root, e => e.tagName === 'path').length, chart.edges.length);
      assert.deepEqual(descendants(root, e => e.dataset.node).map(e => e.dataset.node), chart.nodes.map(n => n.id));
      assert.equal(descendants(root, e => e.className === 'flowchart-arrow').length, chart.edges.length);
      const accessible = descendants(root, e => e.className === 'flowchart-accessible')[0];
      assert.equal(accessible.tagName, 'ol');
      for (const edge of chart.edges) {
        const from = chart.nodes.find(n => n.id === edge.from);
        const to = chart.nodes.find(n => n.id === edge.to);
        assert.ok(accessible.textContent.includes(`${from.label} → ${to.label}${edge.label ? ` (${edge.label})` : ''}`));
      }
    }
  }
});

test('recovery returns to verification, while cleanup never enters implementation', async () => {
  const { flowchartModel } = await import(pathToFileURL(resolve(base, 'flowchart-model.js')));
  const change = flowchartModel('change', 'en');
  assert.deepEqual(change.edges.filter(e => e.kind === 'retry').map(e => [e.from, e.to]), [['repair', 'test']]);
  assert.ok(change.edges.some(e => e.from === 'recover' && e.to === 'stop' && e.label === 'NO'));
  const cleanup = flowchartModel('cleanup', 'en');
  assert.ok(!cleanup.nodes.some(n => ['test', 'edit', 'review'].includes(n.id)));
  assert.ok(cleanup.edges.some(e => e.from === 'merged' && e.to === 'unmerged' && e.label === 'NO'));
  assert.ok(cleanup.edges.some(e => e.from === 'clean' && e.to === 'dirty' && e.label === 'NO'));
});

test('language coverage and rule links stay aligned', async () => {
  const [, { workflowContent }] = await modules;
  assert.deepEqual(Object.keys(workflowContent.en), Object.keys(workflowContent.ko));
  for (const key of ['analysis', 'change', 'commit', 'cleanup']) {
    const en = workflowContent.en.routes[key], ko = workflowContent.ko.routes[key];
    assert.deepEqual(Object.keys(en), Object.keys(ko));
    assert.equal(en.steps.length, ko.steps.length);
    assert.equal(en.source, ko.source);
    assert.ok(readFileSync(resolve(__dirname, '..', en.source), 'utf8').length);
  }
});

import { workflowContent } from "./content.js";
import { renderFlowchart } from "./flowchart.js";

function stageItems(route, node) {
  return route.steps.map(([title, description], index) => {
    const item = node("li", "workflow-step");
    const number = node("span", "workflow-number", String(index + 1).padStart(2, "0"));
    number.setAttribute("aria-hidden", "true");
    item.append(number, node("h3", "", title), node("p", "", description));
    return item;
  });
}

// One presentation owner. This diagram never starts a workflow or reads run data.
export function mountWorkflow(root, page = document) {
  if (!root) return;
  let selected = "change";
  let language = page.documentElement.lang === "ko" ? "ko" : "en";

  const node = (tag, className, text) => {
    const element = page.createElement(tag);
    if (className) element.className = className;
    if (text) element.textContent = text;
    return element;
  };
  const entry = node("ol", "workflow-entry");
  const decision = node("p", "workflow-decision");
  const controls = node("div", "workflow-choices");
  controls.setAttribute("role", "group");
  const body = node("div", "workflow-route");
  const summary = node("p", "workflow-summary");
  summary.setAttribute("role", "status");
  const example = node("p", "workflow-example");
  const steps = node("ol", "workflow-steps");
  const chart = node("div", "workflow-chart");
  chart.setAttribute("role", "group");
  const stageDetails = node("details", "workflow-stage-details");
  const stageTitle = node("summary");
  stageDetails.append(stageTitle, steps);
  const outcome = node("div", "workflow-outcome");
  const details = node("details", "workflow-exception");
  const detailTitle = node("summary");
  const detailBody = node("p");
  const source = node("a", "workflow-source");
  const legend = node("p", "workflow-legend");
  details.append(detailTitle, detailBody);
  body.append(summary, example, chart, stageDetails, outcome, details, source);
  root.replaceChildren(entry, decision, controls, body, legend);

  const buttons = Object.keys(workflowContent.en.routes).map((key) => {
    const button = node("button", "workflow-choice");
    button.type = "button";
    button.dataset.workflow = key;
    button.setAttribute("aria-controls", "workflow-stages");
    button.addEventListener("click", () => {
      selected = key;
      render();
    });
    controls.append(button);
    return button;
  });
  chart.id = "workflow-stages";
  function render() {
    const copy = workflowContent[language];
    const route = copy.routes[selected];
    entry.setAttribute("aria-label", copy.entryLabel);
    entry.replaceChildren(...copy.entry.map((label) => node("li", "", label)));
    decision.textContent = copy.decision;
    controls.setAttribute("aria-label", copy.label);
    buttons.forEach((button) => {
      const key = button.dataset.workflow;
      button.textContent = copy.routes[key].name;
      button.setAttribute("aria-pressed", String(key === selected));
    });
    summary.textContent = route.summary;
    example.replaceChildren(node("span", "", copy.example), node("q", "", route.example));
    chart.setAttribute("aria-label", route.name);
    stageTitle.textContent = renderFlowchart(chart, selected, language, page);
    steps.setAttribute("aria-label", route.name);
    steps.replaceChildren(...stageItems(route, node));
    outcome.replaceChildren(node("h3", "", copy.output), node("p", "", route.output));
    detailTitle.textContent = copy.exception;
    detailBody.textContent = route.exception;
    source.textContent = `${copy.source} ↗`;
    source.href = `https://github.com/taehwandev/tao-agent-os/blob/main/${route.source}`;
    legend.replaceChildren(node("code", "", route.command), node("span", "", copy.legend));
  }
  page.addEventListener("tao:language", (event) => {
    language = event.detail?.language === "ko" ? "ko" : "en";
    render();
  });
  render();
}

if (typeof document !== "undefined") mountWorkflow(document.getElementById("workflow-map"));

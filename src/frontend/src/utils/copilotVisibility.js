export const NARROW_VIEWPORT_QUERY = "(max-width: 768px)";

function hasClosest(node) {
  return Boolean(node) && typeof node.closest === "function";
}

function resolveElement(node) {
  if (!node) return null;
  if (hasClosest(node)) return node;
  if (node.parentElement && hasClosest(node.parentElement)) return node.parentElement;
  if (node.parentNode && node.parentNode !== node) return resolveElement(node.parentNode);
  return null;
}

export function isNarrowViewport(win = globalThis.window) {
  if (!win || typeof win.matchMedia !== "function") return false;
  return win.matchMedia(NARROW_VIEWPORT_QUERY).matches;
}

export function isCopilotOrTriggerElement(node) {
  const element = resolveElement(node);
  if (!element) return false;
  return Boolean(element.closest(".copilot-drawer") || element.closest(".copilot-trigger"));
}

export function isCopilotInteractionEvent(event) {
  if (event && typeof event.composedPath === "function") {
    const path = event.composedPath();
    if (Array.isArray(path) && path.some((node) => isCopilotOrTriggerElement(node))) return true;
  }
  return isCopilotOrTriggerElement(event?.target);
}

function hasResolvableEventNode(event) {
  if (event && typeof event.composedPath === "function") {
    const path = event.composedPath();
    if (Array.isArray(path) && path.some((node) => Boolean(resolveElement(node)))) return true;
  }
  return Boolean(resolveElement(event?.target));
}

export function shouldCollapseCopilotOnGlobalInteraction({ collapsed, narrowViewport, event }) {
  if (collapsed) return false;
  if (!narrowViewport) return false;
  if (!hasResolvableEventNode(event)) return false;
  if (isCopilotInteractionEvent(event)) return false;
  return true;
}

export function createCopilotAutoCollapseHandler({
  isCollapsed,
  isNarrowViewport,
  collapse,
  ignoreViewport = false,
} = {}) {
  const readCollapsed = typeof isCollapsed === "function" ? isCollapsed : () => true;
  const readNarrowViewport = typeof isNarrowViewport === "function" ? isNarrowViewport : () => false;
  const collapseCopilot = typeof collapse === "function" ? collapse : () => {};

  return function onGlobalInteraction(event) {
    const shouldCollapse = shouldCollapseCopilotOnGlobalInteraction({
      collapsed: Boolean(readCollapsed()),
      narrowViewport: ignoreViewport ? true : Boolean(readNarrowViewport()),
      event,
    });
    if (!shouldCollapse) return false;
    collapseCopilot();
    return true;
  };
}

import test from "node:test";
import assert from "node:assert/strict";
import {
  createCopilotAutoCollapseHandler,
  shouldCollapseCopilotOnGlobalInteraction,
} from "./copilotVisibility.js";

function mockNode(matchSelectors = []) {
  return {
    closest(selector) {
      return matchSelectors.includes(selector) ? { selector } : null;
    },
  };
}

function mockEvent({ target = null, path = null } = {}) {
  const event = { target };
  if (Array.isArray(path)) {
    event.composedPath = () => path;
  }
  return event;
}

test("collapses only when copilot is open, on narrow viewport, and click is outside", () => {
  const event = mockEvent({ target: mockNode([]) });
  const shouldCollapse = shouldCollapseCopilotOnGlobalInteraction({
    collapsed: false,
    narrowViewport: true,
    event,
  });

  assert.equal(shouldCollapse, true);
});

test("does not collapse when clicking inside drawer", () => {
  const event = mockEvent({ target: mockNode([".copilot-drawer"]) });
  const shouldCollapse = shouldCollapseCopilotOnGlobalInteraction({
    collapsed: false,
    narrowViewport: true,
    event,
  });

  assert.equal(shouldCollapse, false);
});

test("does not collapse when composedPath includes copilot trigger", () => {
  const triggerNode = mockNode([".copilot-trigger"]);
  const event = mockEvent({
    target: null,
    path: [{}, triggerNode, {}],
  });
  const shouldCollapse = shouldCollapseCopilotOnGlobalInteraction({
    collapsed: false,
    narrowViewport: true,
    event,
  });

  assert.equal(shouldCollapse, false);
});

test("does not collapse when target is text node inside drawer", () => {
  const textNodeInsideDrawer = {
    parentElement: mockNode([".copilot-drawer"]),
  };
  const event = mockEvent({ target: textNodeInsideDrawer });
  const shouldCollapse = shouldCollapseCopilotOnGlobalInteraction({
    collapsed: false,
    narrowViewport: true,
    event,
  });

  assert.equal(shouldCollapse, false);
});

test("does not collapse when event target is unknown", () => {
  const event = mockEvent({ target: null });
  const shouldCollapse = shouldCollapseCopilotOnGlobalInteraction({
    collapsed: false,
    narrowViewport: true,
    event,
  });

  assert.equal(shouldCollapse, false);
});

test("does not collapse when already collapsed", () => {
  const event = mockEvent({ target: mockNode([]) });
  const shouldCollapse = shouldCollapseCopilotOnGlobalInteraction({
    collapsed: true,
    narrowViewport: true,
    event,
  });

  assert.equal(shouldCollapse, false);
});

test("does not collapse on desktop viewport", () => {
  const event = mockEvent({ target: mockNode([]) });
  const shouldCollapse = shouldCollapseCopilotOnGlobalInteraction({
    collapsed: false,
    narrowViewport: false,
    event,
  });

  assert.equal(shouldCollapse, false);
});

test("auto-collapse handler closes copilot on narrow outside interaction", () => {
  let collapsed = false;
  let collapseCalls = 0;
  const handler = createCopilotAutoCollapseHandler({
    isCollapsed: () => collapsed,
    isNarrowViewport: () => true,
    collapse: () => {
      collapseCalls += 1;
      collapsed = true;
    },
  });

  const consumed = handler(mockEvent({ target: mockNode([]) }));

  assert.equal(consumed, true);
  assert.equal(collapseCalls, 1);
  assert.equal(collapsed, true);
});

test("auto-collapse handler ignores interaction inside trigger", () => {
  let collapseCalls = 0;
  const handler = createCopilotAutoCollapseHandler({
    isCollapsed: () => false,
    isNarrowViewport: () => true,
    collapse: () => {
      collapseCalls += 1;
    },
  });

  const consumed = handler(mockEvent({ target: mockNode([".copilot-trigger"]) }));

  assert.equal(consumed, false);
  assert.equal(collapseCalls, 0);
});

test("auto-collapse handler can collapse even when viewport is wide", () => {
  let collapseCalls = 0;
  const handler = createCopilotAutoCollapseHandler({
    isCollapsed: () => false,
    isNarrowViewport: () => false,
    ignoreViewport: true,
    collapse: () => {
      collapseCalls += 1;
    },
  });

  const consumed = handler(mockEvent({ target: mockNode([]) }));

  assert.equal(consumed, true);
  assert.equal(collapseCalls, 1);
});

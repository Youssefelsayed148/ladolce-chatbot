import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement scrollIntoView (MessageList calls it to autoscroll).
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

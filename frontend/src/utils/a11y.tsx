import React from "react";

/**
 * Small shared accessibility primitives for the core review loop.
 * Deliberately tiny: helpers, not a framework.
 */

export function isVisible(element: HTMLElement) {
  let node: HTMLElement | null = element;
  while (node) {
    const style = getComputedStyle(node);
    if (style.display === "none" || style.visibility === "hidden") return false;
    node = node.parentElement;
  }
  return true;
}

const FOCUSABLE_SELECTORS = [
  "a[href]",
  "button:not([disabled])",
  'input:not([disabled]):not([type="hidden"])',
  "select:not([disabled])",
  "textarea:not([disabled])",
  'video[controls]',
  "summary",
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable="true"]',
].join(", ");

/**
 * Keep Tab / Shift+Tab inside `container`. Complements `inert` isolation:
 * inert removes the background from the accessibility tree and focus order,
 * the trap guards keyboard traversal in the active surface itself.
 * Returns true when the event was handled (wrapped around the boundary).
 */
export function trapTabKey(
  container: HTMLElement,
  event: KeyboardEvent,
): boolean {
  if (event.key !== "Tab") return false;
  const focusable = Array.from(
    container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTORS),
  ).filter(
    (element) =>
      isVisible(element) &&
      !element.matches(":disabled") &&
      !element.closest("[hidden], [inert]") &&
      element.getAttribute("aria-hidden") !== "true",
  );
  if (focusable.length === 0) {
    event.preventDefault();
    container.focus();
    return true;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const active = container.ownerDocument.activeElement;
  const outside = !container.contains(active);
  if (event.shiftKey && (outside || active === container || active === first)) {
    event.preventDefault();
    last.focus();
    return true;
  }
  if (!event.shiftKey && (outside || active === container || active === last)) {
    event.preventDefault();
    first.focus();
    return true;
  }
  return false;
}

/** Visually hidden, screen-reader-only text. */
export function VisuallyHidden({ children }: { children: React.ReactNode }) {
  return <span className="sr-only">{children}</span>;
}

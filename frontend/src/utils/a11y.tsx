import React from "react";

/**
 * Small shared accessibility primitives for the core review loop.
 * Deliberately tiny: helpers, not a framework.
 */

/**
 * Apply `inert` to everything that is NOT on the ancestor chain of the
 * given container (siblings at every level up to document.body).
 *
 * This makes the rest of the page — sidebars, mobile navigation, the
 * Library mounted beneath a full-viewport dialog — unreachable for focus,
 * pointer events and assistive technology, matching the visual model of a
 * modal review surface. Previously-inert elements are preserved exactly
 * and restored on cleanup.
 */
export function inertExcept(container: HTMLElement): () => void {
  const restore: Array<[Element, boolean]> = [];
  const apply = (element: Element) => {
    const previouslyInert = element.hasAttribute("inert");
    if (!previouslyInert) element.setAttribute("inert", "");
    restore.push([element, previouslyInert]);
  };
  let node: Element | null = container;
  while (node && node !== document.body) {
    const parent: Element | null = node.parentElement;
    if (!parent) break;
    const current: Element = node;
    Array.from(parent.children).forEach((child) => {
      if (child !== current) apply(child);
    });
    node = parent;
  }
  return () => {
    for (const [element, previouslyInert] of restore.reverse()) {
      if (!previouslyInert) element.removeAttribute("inert");
    }
  };
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
      !element.hasAttribute("disabled") &&
      !element.closest("[hidden]") &&
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
  if (event.shiftKey && (outside || active === first)) {
    event.preventDefault();
    last.focus();
    return true;
  }
  if (!event.shiftKey && (outside || active === last)) {
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

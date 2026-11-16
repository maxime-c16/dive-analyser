// Node ≥26 ships native `globalThis.localStorage`/`sessionStorage` accessors
// that return undefined/in-memory stand-ins unless `--localstorage-file` is
// set (plus an ExperimentalWarning on first read). Their mere presence makes
// vitest's environment whitelist treat them as "already on the global" and
// drop jsdom's storage objects from the test context. Consequences on node 26
// dev boxes: localStorage reads give undefined ("Cannot read properties of
// undefined (reading 'setItem')") and sessionStorage is a native object whose
// prototype is not the jsdom `Storage` the rest follows (spies miss it).
// Hosted CI (node 20) is unaffected; this keeps local dev honest.
//
// Re-defining both per setup run with the *current* file's jsdom window
// storage restores node-20 behavior and keeps per-file isolation (each setup
// run rebinds that file's fresh window). We never touch the native accessors,
// so no warning noise leaks into output.
const jsdomRoot = globalThis as { jsdom?: { window?: unknown } } | undefined
const win = (jsdomRoot?.jsdom?.window ?? null) as
  | { localStorage?: unknown; sessionStorage?: unknown }
  | null
if (win) {
  const globals = globalThis as Record<string, unknown>
  if (win.localStorage != null) {
    Object.defineProperty(globals, 'localStorage', {
      value: win.localStorage,
      configurable: true,
      writable: true,
    })
  }
  if (win.sessionStorage != null) {
    Object.defineProperty(globals, 'sessionStorage', {
      value: win.sessionStorage,
      configurable: true,
      writable: true,
    })
  }
}

// A short-lived handoff from navigation intent to the destination, not a
// general response cache. Normal visits/refetches always hit the server.
const entries = new Map<string, { expires: number; promise: Promise<unknown> }>();
const TTL = 10_000;
const MAX_ENTRIES = 12;

export function clearIntentData() {
  entries.clear();
}

export function warmIntentData<T>(key: string, load: () => Promise<T>) {
  for (const [id, entry] of entries) {
    if (entry.expires <= Date.now()) entries.delete(id);
  }
  if (entries.has(key)) return;
  if (entries.size >= MAX_ENTRIES) entries.delete(entries.keys().next().value!);
  const entry = { expires: Date.now() + TTL, promise: load() };
  entries.set(key, entry);
  void entry.promise.catch(() => {
    if (entries.get(key) === entry) entries.delete(key);
  });
}

export function takeIntentData<T>(key: string, load: () => Promise<T>): Promise<T> {
  const entry = entries.get(key);
  entries.delete(key);
  if (!entry || entry.expires <= Date.now()) return load();
  // A failed speculative request must not poison an actual navigation.
  return (entry.promise as Promise<T>).catch(load);
}

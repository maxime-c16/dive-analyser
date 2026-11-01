/**
 * Library figure-name search.
 *
 * The Library stores dive codes, not names: the human name ("Back dive
 * tuck", "Plongeon arrière groupé") is derived per-code by the naming
 * catalog in i18n/diveNames. Captions are often empty, which is why a name
 * like "back dive" returned nothing (discovery report 2026-11-01). This
 * module inverts the catalog: figure words → candidate codes, so a search
 * can run against the WHOLE authorized scope through the API's bounded
 * `code_filter` instead of only the loaded page.
 *
 * Matching is exact folded word equality (accent-free, singular/plural
 * folded), in BOTH languages, so a French or English figure word works
 * whatever the interface language. Words outside the catalog are caption
 * search words and stay with the API's phrase matching.
 */

import { diveCodeName } from "../i18n/diveNames";

export type NameSearch = {
  /** unused: no catalog word in the query (phrase search only, as before) */
  /** match: codes covers the words the catalog recognized */
  /** unsupported: a recognized word alone is too broad (rotation families); the query falls back to phrase search, consistently on client and API */
  status: "unused" | "match" | "unsupported";
  codes: string[];
};

/**
 * Largest single-word family in the catalog (~1000 rotating codes) equals
 * the API's `code_filter` cap; beyond it the name criterion would be less
 * selective than "no name criterion", so it degrades deliberately.
 */
const NAME_CODE_LIMIT = 1024;

type Index = Map<string, string[]>;

let index: Index | null = null;

function fold(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

/** Fold a query/catalog word for matching: accent-free + singular/plural. */
function foldWord(value: string): string {
  const folded = fold(value);
  return folded.length >= 5 && folded.endsWith("s") ? folded.slice(0, -1) : folded;
}

function tokenizeName(name: string): string[] {
  return fold(name)
    .match(/[a-z0-9½]+/g)
    ?.map(foldWord)
    .filter((word) => word.length >= 2) ?? [];
}

function buildIndex(): Index {
  const map: Index = new Map();
  const codes: string[] = [];
  for (let group = 1; group <= 4; group += 1) {
    for (const flying of [0, 1]) {
      for (let rotations = 1; rotations <= 8; rotations += 1) {
        for (const position of ["A", "B", "C", "D"]) {
          codes.push(`${group}${flying}${rotations}${position}`);
        }
      }
    }
  }
  for (let direction = 1; direction <= 4; direction += 1) {
    for (let rotations = 1; rotations <= 8; rotations += 1) {
      for (let twists = 1; twists <= 8; twists += 1) {
        for (const position of ["A", "B", "C", "D"]) {
          codes.push(`5${direction}${rotations}${twists}${position}`);
        }
      }
    }
  }
  for (let direction = 1; direction <= 4; direction += 1) {
    for (let rotations = 1; rotations <= 8; rotations += 1) {
      for (const position of ["A", "B", "C", "D"]) {
        codes.push(`6${direction}${rotations}${position}`);
      }
    }
  }
  const add = (token: string, code: string) => {
    const list = map.get(token);
    if (list) list.push(code);
    else map.set(token, [code]);
  };
  for (const code of codes) {
    for (const language of ["fr", "en"] as const) {
      const name = diveCodeName(code, language);
      if (name === code) continue; // unrecognized structure: no name to match
      for (const token of tokenizeName(name)) add(token, code);
    }
  }
  return map;
}

function catalogIndex(): Index {
  return (index ??= buildIndex());
}

/**
 * Interpret the free-text part of a Library search as figure-name words.
 * Returns the intersected candidate codes when the catalog can answer, or a
 * status the caller mirrors in the client filter and the API call.
 */
export function nameSearchCodes(text: string): NameSearch {
  const words = fold(text).match(/[a-z0-9½]+/g);
  if (!words || words.length === 0) return { status: "unused", codes: [] };
  const map = catalogIndex();
  let running: string[] | null = null;
  for (const raw of words) {
    const token = foldWord(raw);
    if (token.length < 2) continue;
    const hits = map.get(token);
    if (!hits) continue; // caption-search word, not a figure name
    if (running === null) {
      running = [...hits];
      if (running.length > NAME_CODE_LIMIT) return { status: "unsupported", codes: [] };
    } else {
      const picks: string[] = running.filter((code) => hits.includes(code));
      running = picks;
      if (picks.length === 0) return { status: "match", codes: [] };
    }
  }
  if (running === null) return { status: "unused", codes: [] };
  return { status: "match", codes: running };
}

/** For tests: the whole token → codes index (avoid in production paths). */
export function nameSearchIndexForTests(): Index {
  return catalogIndex();
}

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../../reader/assets/reader.js");

test("catalog filters combine level, type, and exact tags", () => {
  const entry = { level: "N3", type: "grammar", tags: ["接续", "易混"] };
  assert.equal(core.catalogEntryMatches(entry, { level: "N3", type: "grammar", tag: "接续" }), true);
  assert.equal(core.catalogEntryMatches(entry, { level: "N2", type: "grammar", tag: "接续" }), false);
  assert.equal(core.catalogEntryMatches(entry, { level: "N3", type: "draft", tag: "接续" }), false);
  assert.equal(core.catalogEntryMatches(entry, { level: "N3", type: "grammar", tag: "语义" }), false);
  assert.equal(
    core.catalogEntryMatches({ level: "", type: "document", tags: [] }, { level: "__unmarked__", type: "", tag: "" }),
    true
  );
});

test("displayed page hash catches a site switch before the first manifest request", () => {
  const next = { version: "v2", pages: { "library/card/": "hash-v2" } };
  assert.equal(core.decideReaderUpdate("hash-v1", "library/card/", "", next, ""), "stale");
  assert.equal(core.decideReaderUpdate("hash-v1", "library/card/", "", { version: "v2", pages: {} }, ""), "deleted");
});

test("a stale or deleted current page remains sticky across later generations", () => {
  const third = { version: "v3", pages: { "library/card/": "hash-v1", "library/other/": "changed" } };
  assert.equal(core.decideReaderUpdate("hash-v1", "library/card/", "v2", third, "stale"), "stale");
  assert.equal(core.decideReaderUpdate("hash-v1", "library/card/", "v2", third, "deleted"), "deleted");
});

test("deletion supersedes an already sticky stale-page state", () => {
  const deleted = { version: "v3", pages: { "library/other/": "changed" } };
  assert.equal(core.decideReaderUpdate("hash-v1", "library/card/", "v2", deleted, "stale"), "deleted");
});

test("installing an instant-navigation page clears the old toast and sticky state", () => {
  const oldElement = { id: "old" };
  const nextElement = { id: "next" };
  const nextPage = { element: nextElement, pageKey: "library/next/", pageHash: "next", generation: "v2" };
  let removedToasts = 0;
  const transitioned = core.installPageLifecycle(
    { element: oldElement, pageKey: "library/old/", pageHash: "old", generation: "v1" },
    nextPage,
    "stale",
    () => { removedToasts += 1; }
  );
  assert.equal(transitioned.changed, true);
  assert.equal(transitioned.stickyState, "");
  assert.equal(transitioned.pageState, nextPage);
  assert.equal(removedToasts, 1);

  const unchanged = core.installPageLifecycle(nextPage, nextPage, "stale", () => { removedToasts += 1; });
  assert.equal(unchanged.changed, false);
  assert.equal(unchanged.stickyState, "stale");
  assert.equal(removedToasts, 1);
});

test("only an unchanged displayed page auto reloads for another-page generation", () => {
  const next = { version: "v2", pages: { "library/card/": "same", "library/other/": "changed" } };
  assert.equal(core.decideReaderUpdate("same", "library/card/", "v1", next, ""), "reload");
  assert.equal(core.decideReaderUpdate("same", "library/card/", "", next, ""), "baseline");
  assert.equal(core.decideReaderUpdate("same", "library/card/", "v2", next, ""), "none");
});

test("scheduled scroll snapshots keep the old pathname and offset", () => {
  const snapshot = core.captureScrollSnapshot("/library/old/", 321.5);
  assert.deepEqual(snapshot, { key: "jlpt-reader-scroll:/library/old/", value: "321.5" });
});

test("continue reading accepts only routes present in the current manifest", () => {
  const pages = { "./": "catalog", "library/kept/": "hash" };
  assert.equal(core.validContinuePath("/library/kept/", pages), "/library/kept/");
  assert.equal(core.validContinuePath("/library/deleted/", pages), "");
  assert.equal(core.validContinuePath("//attacker.example/", pages), "");
  assert.equal(core.validContinuePath("https://attacker.example/", pages), "");
  assert.equal(core.validContinuePath("/", pages), "");
});

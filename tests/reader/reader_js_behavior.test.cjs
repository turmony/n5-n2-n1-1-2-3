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

test("local full-text search matches contiguous Japanese and Chinese substrings", () => {
  const corpus = core.buildSearchCorpus([
    { location: "library/grammar/N2-G-0010/#核心", title: "～までに", text: "表示截止时限" }
  ]);
  const entry = {
    route: "/library/grammar/N2-G-0010/",
    title: "N2-G-0010｜～までに",
    level: "N2",
    type: "grammar",
    tags: ["时间"]
  };
  const filters = { level: "", type: "", tag: "" };

  assert.equal(core.catalogEntryMatchesSearch(entry, filters, "までに", corpus), true);
  assert.equal(core.catalogEntryMatchesSearch(entry, filters, "截止时限", corpus), true);
  assert.equal(core.catalogEntryMatchesSearch(entry, filters, "不存在", corpus), false);
});

test("local full-text search includes catalog tags and normalizes whitespace", () => {
  const entry = {
    route: "/library/grammar/N2-G-0010/",
    title: "N2-G-0010｜～までに",
    level: "N2",
    type: "grammar",
    tags: ["时间", "截止 时限"]
  };
  assert.equal(core.catalogEntryMatchesSearch(entry, {}, "时间", {}), true);
  assert.equal(core.catalogEntryMatchesSearch(entry, {}, "截止时限", {}), true);
  assert.equal(core.catalogEntryMatchesSearch(entry, {}, "　 ", {}), true);
});

test("search route normalization joins section hashes and percent-encoded routes", () => {
  assert.equal(
    core.normalizeSearchRoute("library/%E8%AF%AD%E6%B3%95/card/#section"),
    "/library/语法/card/"
  );
  assert.equal(core.normalizeSearchRoute("/library/card/index.html?x=1#part"), "/library/card/");
  assert.equal(core.normalizeSearchRoute("https://attacker.example/card/"), "");
  const corpus = core.buildSearchCorpus([
    { location: "library/card/#one", title: "一", text: "までに" },
    { location: "/library/card/#two", title: "二", text: "截止时限" }
  ]);
  assert.match(corpus["/library/card/"], /までに/);
  assert.match(corpus["/library/card/"], /截止时限/);
});

test("catalog DOM mapping keeps the local relative route instead of browser-expanded origin", () => {
  const link = {
    textContent: "N2-G-0010｜～までに",
    href: "http://192.168.1.42:8765/library/card/",
    getAttribute: (name) => name === "href" ? "library/card/" : null
  };
  const entry = core.catalogEntryFromNode({
    dataset: { level: "N2", type: "grammar", tags: "时间" },
    querySelector: () => link
  });
  assert.equal(entry.route, "library/card/");
  assert.equal(
    core.catalogEntryMatchesSearch(
      entry,
      { level: "N2", type: "grammar", tag: "时间" },
      "までに",
      core.buildSearchCorpus([{ location: "library/card/#core", text: "までに" }])
    ),
    true
  );
});

test("full-text results combine with level type and exact tag filters", () => {
  const corpus = core.buildSearchCorpus([
    { location: "/library/card/", title: "～までに", text: "截止时限" }
  ]);
  const entry = {
    route: "/library/card/",
    title: "N2-G-0010｜～までに",
    level: "N2",
    type: "grammar",
    tags: ["时间"]
  };
  assert.equal(
    core.catalogEntryMatchesSearch(entry, { level: "N2", type: "grammar", tag: "时间" }, "截止时限", corpus),
    true
  );
  assert.equal(
    core.catalogEntryMatchesSearch(entry, { level: "N3", type: "grammar", tag: "时间" }, "截止时限", corpus),
    false
  );
  assert.equal(
    core.catalogEntryMatchesSearch(entry, { level: "N2", type: "draft", tag: "时间" }, "截止时限", corpus),
    false
  );
  assert.equal(
    core.catalogEntryMatchesSearch(entry, { level: "N2", type: "grammar", tag: "其他" }, "截止时限", corpus),
    false
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

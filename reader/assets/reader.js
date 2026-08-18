(function (root) {
  "use strict";

  const THEME_KEY = "jlpt-reader-theme";
  const FONT_KEY = "jlpt-reader-font-scale";
  const LAST_PAGE_KEY = "jlpt-reader-last-page";
  const SCROLL_KEY_PREFIX = "jlpt-reader-scroll:";
  const VERSION_POLL_INTERVAL_MS = 1000;
  const UNMARKED_LEVEL = "__unmarked__";
  const TYPE_LABELS = {
    grammar: "正式语法",
    draft: "草稿",
    "quiz-question": "测试题",
    "quiz-result": "测试报告",
    review: "复习记录",
    history: "修改历史",
    document: "其他"
  };

  function catalogEntryMatches(entry, filters) {
    const levelMatches = !filters.level ||
      (filters.level === UNMARKED_LEVEL ? !entry.level : entry.level === filters.level);
    const typeMatches = !filters.type || entry.type === filters.type;
    const tagMatches = !filters.tag || entry.tags.includes(filters.tag);
    return levelMatches && typeMatches && tagMatches;
  }

  function normalizeSearchText(value) {
    return String(value == null ? "" : value)
      .normalize("NFKC")
      .toLocaleLowerCase()
      .replace(/[\s\u200b-\u200d\ufeff]+/gu, "");
  }

  function normalizeSearchRoute(value) {
    if (typeof value !== "string" || !value) return "";
    let parsed;
    try {
      parsed = new URL(value, "https://reader.invalid/");
    } catch (_error) {
      return "";
    }
    if (parsed.origin !== "https://reader.invalid") return "";
    let pathname;
    try {
      pathname = decodeURIComponent(parsed.pathname);
    } catch (_error) {
      return "";
    }
    pathname = pathname.normalize("NFC").replace(/\/index\.html$/iu, "/");
    return pathname.startsWith("/") ? pathname : "";
  }

  function buildSearchCorpus(documents) {
    const corpus = Object.create(null);
    (Array.isArray(documents) ? documents : []).forEach(function (document) {
      if (!document || typeof document !== "object") return;
      const route = normalizeSearchRoute(document.location);
      if (!route) return;
      const tags = Array.isArray(document.tags) ? document.tags.join(" ") : document.tags || "";
      const text = normalizeSearchText([document.title || "", document.text || "", tags].join(" "));
      corpus[route] = corpus[route] ? `${corpus[route]}\u0000${text}` : text;
    });
    return corpus;
  }

  function catalogEntryMatchesSearch(entry, filters, query, corpus) {
    if (!catalogEntryMatches(entry, filters || {})) return false;
    const needle = normalizeSearchText(query);
    if (!needle) return true;
    const routeText = (corpus || {})[normalizeSearchRoute(entry.route)] || "";
    const localText = normalizeSearchText([
      entry.title || "",
      Array.isArray(entry.tags) ? entry.tags.join(" ") : ""
    ].join(" "));
    return routeText.includes(needle) || localText.includes(needle);
  }

  function decideReaderUpdate(displayedHash, pageKey, currentVersion, nextManifest, stickyState) {
    const nextHash = nextManifest.pages[pageKey];
    if (displayedHash && nextHash === undefined) return "deleted";
    if (stickyState === "stale" || stickyState === "deleted") return stickyState;
    if (displayedHash && displayedHash !== nextHash) return "stale";
    if (!currentVersion) return "baseline";
    if (currentVersion === nextManifest.version) return "none";
    return "reload";
  }

  function installPageLifecycle(currentPageState, nextPageState, stickyState, removeToast) {
    if (nextPageState.element === currentPageState.element) {
      return { changed: false, pageState: currentPageState, stickyState: stickyState };
    }
    removeToast();
    return { changed: true, pageState: nextPageState, stickyState: "" };
  }

  function captureScrollSnapshot(pathname, offset) {
    return { key: `${SCROLL_KEY_PREFIX}${pathname}`, value: String(offset) };
  }

  function validContinuePath(pathname, pages) {
    if (typeof pathname !== "string" || !pathname.startsWith("/") || pathname.startsWith("//")) return "";
    const parsed = new URL(pathname, "https://reader.invalid/");
    if (parsed.origin !== "https://reader.invalid" || parsed.search || parsed.hash) return "";
    const key = parsed.pathname === "/" ? "./" : parsed.pathname.slice(1);
    if (key === "./" || !Object.prototype.hasOwnProperty.call(pages, key)) return "";
    return parsed.pathname;
  }

  const core = {
    VERSION_POLL_INTERVAL_MS: VERSION_POLL_INTERVAL_MS,
    catalogEntryMatches: catalogEntryMatches,
    normalizeSearchText: normalizeSearchText,
    normalizeSearchRoute: normalizeSearchRoute,
    buildSearchCorpus: buildSearchCorpus,
    catalogEntryMatchesSearch: catalogEntryMatchesSearch,
    catalogEntryFromNode: catalogEntryFromNode,
    decideReaderUpdate: decideReaderUpdate,
    installPageLifecycle: installPageLifecycle,
    captureScrollSnapshot: captureScrollSnapshot,
    validContinuePath: validContinuePath
  };
  root.JlptReaderCore = core;
  if (typeof module === "object" && module.exports) module.exports = core;
  if (typeof window === "undefined" || typeof document === "undefined") return;

  const themeQuery = window.matchMedia("(prefers-color-scheme: dark)");

  if ("scrollRestoration" in history) history.scrollRestoration = "manual";

  function applyTheme(mode) {
    const selected = ["system", "light", "dark"].includes(mode) ? mode : "system";
    localStorage.setItem(THEME_KEY, selected);
    const dark = selected === "dark" ||
      (selected === "system" && themeQuery.matches);
    document.body.setAttribute("data-md-color-scheme", dark ? "slate" : "default");
  }

  function followSystemTheme() {
    if ((localStorage.getItem(THEME_KEY) || "system") === "system") applyTheme("system");
  }
  if (themeQuery.addEventListener) themeQuery.addEventListener("change", followSystemTheme);
  else themeQuery.addListener(followSystemTheme);

  function saveScrollSnapshot(snapshot) {
    sessionStorage.setItem(snapshot.key, snapshot.value);
  }

  function saveScrollPosition() {
    saveScrollSnapshot(captureScrollSnapshot(location.pathname, window.scrollY));
  }

  let jlptScrollTimer;
  let jlptPendingScroll;
  function scheduleScrollSave() {
    window.clearTimeout(jlptScrollTimer);
    jlptPendingScroll = captureScrollSnapshot(location.pathname, window.scrollY);
    jlptScrollTimer = window.setTimeout(function () {
      saveScrollSnapshot(jlptPendingScroll);
      jlptPendingScroll = undefined;
    }, 150);
  }

  function flushScheduledScroll() {
    window.clearTimeout(jlptScrollTimer);
    if (jlptPendingScroll) saveScrollSnapshot(jlptPendingScroll);
    jlptPendingScroll = undefined;
  }

  function restoreScrollPosition() {
    const key = `${SCROLL_KEY_PREFIX}${location.pathname}`;
    const value = sessionStorage.getItem(key);
    if (value !== null) requestAnimationFrame(function () { window.scrollTo(0, Number(value)); });
  }

  function catalogEntryFromNode(entry) {
    const link = entry.querySelector("a[href]");
    return {
      level: entry.dataset.level || "",
      type: entry.dataset.type || "",
      tags: (entry.dataset.tags || "").split(/\s+/).filter(Boolean),
      title: link ? link.textContent || "" : "",
      route: link ? link.getAttribute("href") || "" : ""
    };
  }

  function applyCatalogFilters(entries, level, type, tag, query, corpus) {
    let visible = 0;
    entries.forEach(function (entry) {
      const matches = catalogEntryMatchesSearch(
        catalogEntryFromNode(entry),
        { level: level, type: type, tag: tag },
        query,
        corpus
      );
      entry.hidden = !matches;
      if (matches) visible += 1;
    });
    return visible;
  }

  function showUpdateToast(message, action, actionText) {
    const previous = document.querySelector(".jlpt-update-toast");
    if (previous) previous.remove();
    const toast = document.createElement("button");
    toast.type = "button";
    toast.className = "jlpt-update-toast";
    toast.textContent = `${message}，${actionText || "点此刷新"}`;
    toast.setAttribute("aria-live", "polite");
    toast.addEventListener("click", action, { once: true });
    document.body.appendChild(toast);
  }

  function addSelect(container, labelText, options, selected, onChange) {
    const label = document.createElement("label");
    label.append(document.createTextNode(`${labelText} `));
    const select = document.createElement("select");
    select.setAttribute("aria-label", labelText);
    options.forEach(function (option) {
      select.add(new Option(option[1], option[0], false, option[0] === selected));
    });
    select.addEventListener("change", function () { onChange(select.value); });
    label.appendChild(select);
    container.appendChild(label);
  }

  let jlptPageState = { element: null, pageKey: "", pageHash: "", generation: "" };
  let jlptStickyUpdate = "";

  function readPageState() {
    const element = document.querySelector(".jlpt-page-state");
    return {
      element: element,
      pageKey: element ? element.dataset.pageKey || "" : "",
      pageHash: element ? element.dataset.pageHash || "" : "",
      generation: element ? element.dataset.generation || "" : ""
    };
  }

  function saveBeforeLinkNavigation(event) {
    const target = event.target && event.target.closest ? event.target.closest("a[href]") : null;
    if (!target) return;
    flushScheduledScroll();
    saveScrollPosition();
  }

  function saveBeforePageHide() {
    flushScheduledScroll();
    saveScrollPosition();
  }

  function updateContinueReading(pages) {
    const previous = document.querySelector("[data-jlpt-continue]");
    if (previous) previous.remove();
    const stored = localStorage.getItem(LAST_PAGE_KEY) || "";
    const validPath = validContinuePath(stored, pages);
    if (!validPath) {
      if (stored) localStorage.removeItem(LAST_PAGE_KEY);
      return;
    }
    const controls = document.querySelector(".jlpt-reader-controls");
    if (!controls || jlptPageState.pageKey !== "./") return;
    const link = document.createElement("a");
    link.href = validPath;
    link.dataset.jlptContinue = "";
    link.textContent = "继续上次阅读";
    controls.appendChild(link);
  }

  function initializeReaderPage() {
    flushScheduledScroll();
    const nextPageState = readPageState();
    const lifecycle = installPageLifecycle(jlptPageState, nextPageState, jlptStickyUpdate, function () {
      const toast = document.querySelector(".jlpt-update-toast");
      if (toast) toast.remove();
    });
    jlptPageState = lifecycle.pageState;
    jlptStickyUpdate = lifecycle.stickyState;
    if (lifecycle.changed) {
      window.jlptManifest = undefined;
    }
    applyTheme(localStorage.getItem(THEME_KEY) || "system");
    document.documentElement.dataset.jlptFont = localStorage.getItem(FONT_KEY) || "medium";
    if (jlptPageState.pageKey && jlptPageState.pageKey !== "./") {
      localStorage.setItem(LAST_PAGE_KEY, location.pathname);
    }
    restoreScrollPosition();
    window.removeEventListener("scroll", scheduleScrollSave);
    window.addEventListener("scroll", scheduleScrollSave, { passive: true });
    window.removeEventListener("pagehide", saveBeforePageHide);
    window.addEventListener("pagehide", saveBeforePageHide);
    document.removeEventListener("click", saveBeforeLinkNavigation, true);
    document.addEventListener("click", saveBeforeLinkNavigation, true);
    const previousControls = document.querySelector(".jlpt-reader-controls");
    if (previousControls) previousControls.remove();
    const controls = document.createElement("div");
    controls.className = "jlpt-reader-controls";
    controls.setAttribute("role", "group");
    controls.setAttribute("aria-label", "阅读设置");
    addSelect(
      controls,
      "主题",
      [["system", "跟随系统"], ["light", "浅色"], ["dark", "深色"]],
      localStorage.getItem(THEME_KEY) || "system",
      applyTheme
    );
    addSelect(
      controls,
      "字号",
      [["small", "小"], ["medium", "中"], ["large", "大"]],
      localStorage.getItem(FONT_KEY) || "medium",
      function (value) {
        localStorage.setItem(FONT_KEY, value);
        document.documentElement.dataset.jlptFont = value;
      }
    );
    if (jlptPageState.pageKey === "./") {
      let level = "";
      let type = "";
      let tag = "";
      let query = "";
      let corpus = Object.create(null);
      let searchReady = false;
      let searchTimer;
      const entries = Array.from(document.querySelectorAll(".jlpt-catalog-entry"));
      const searchControl = document.querySelector("[data-jlpt-fulltext]");
      const searchInput = searchControl ? searchControl.querySelector("#jlpt-fulltext-query") : null;
      const searchStatus = searchControl ? searchControl.querySelector("#jlpt-fulltext-status") : null;
      function renderCatalog() {
        const visible = applyCatalogFilters(entries, level, type, tag, query, corpus);
        if (searchStatus && searchReady) {
          searchStatus.textContent = query
            ? (visible ? `找到 ${visible} 项匹配资料。` : "未找到匹配资料。")
            : `全文索引已载入；当前显示 ${visible} 项资料。`;
        }
      }
      const levels = Array.from(new Set(entries.map(function (node) { return node.dataset.level; }).filter(Boolean))).sort();
      const hasUnmarkedLevel = entries.some(function (node) { return !node.dataset.level; });
      const types = Array.from(new Set(entries.map(function (node) { return node.dataset.type; }).filter(Boolean))).sort();
      const tags = Array.from(new Set(entries.flatMap(function (node) {
        return (node.dataset.tags || "").split(/\s+/).filter(Boolean);
      }))).sort();
      addSelect(
        controls,
        "等级",
        [["", "全部"]]
          .concat(levels.map(function (value) { return [value, value]; }))
          .concat(hasUnmarkedLevel ? [[UNMARKED_LEVEL, "未标记"]] : []),
        "",
        function (value) { level = value; renderCatalog(); }
      );
      addSelect(
        controls,
        "类型",
        [["", "全部"]].concat(types.map(function (value) { return [value, TYPE_LABELS[value] || value]; })),
        "",
        function (value) { type = value; renderCatalog(); }
      );
      addSelect(
        controls,
        "标签",
        [["", "全部"]].concat(tags.map(function (value) { return [value, value]; })),
        "",
        function (value) { tag = value; renderCatalog(); }
      );
      if (searchControl && searchInput && searchStatus) {
        searchControl.addEventListener("submit", function (event) { event.preventDefault(); });
        searchInput.addEventListener("input", function () {
          window.clearTimeout(searchTimer);
          searchTimer = window.setTimeout(function () {
            query = searchInput.value;
            renderCatalog();
          }, 180);
        });
        fetch(new URL("/search/search_index.json", window.location.origin), { cache: "no-store" })
          .then(function (response) {
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response.json();
          })
          .then(function (index) {
            if (!searchControl.isConnected || jlptPageState.pageKey !== "./") return;
            if (!index || !Array.isArray(index.docs)) throw new Error("invalid search index");
            corpus = buildSearchCorpus(index.docs);
            searchReady = true;
            searchInput.disabled = false;
            searchStatus.textContent = `全文索引已载入；当前显示 ${entries.length} 项资料。`;
            renderCatalog();
          })
          .catch(function () {
            if (!searchControl.isConnected || jlptPageState.pageKey !== "./") return;
            searchInput.disabled = true;
            searchStatus.textContent = "全文索引载入失败；等级、类型和标签筛选仍可使用。";
          });
      }
    }
    const content = document.querySelector(".md-content__inner");
    if (content) content.prepend(controls);
  }

  async function checkReaderVersion() {
    const response = await fetch(new URL("/reader-version.json", window.location.origin), { cache: "no-store" });
    if (!response.ok) return;
    const next = await response.json();
    const decision = decideReaderUpdate(
      jlptPageState.pageHash,
      jlptPageState.pageKey,
      jlptPageState.generation,
      next,
      jlptStickyUpdate
    );
    window.jlptManifest = next;
    updateContinueReading(next.pages);
    if (decision === "baseline" || decision === "none") {
      jlptPageState.generation = next.version;
      return;
    }
    if (decision === "reload") {
      saveScrollPosition();
      location.reload();
      return;
    }
    const previousSticky = jlptStickyUpdate;
    jlptStickyUpdate = decision;
    jlptPageState.generation = next.version;
    if (previousSticky === decision) return;
    if (decision === "deleted") {
      showUpdateToast(
        "当前资料已删除；返回目录后将不再显示",
        function () { location.assign("/"); },
        "点此返回目录"
      );
    } else {
      showUpdateToast("当前资料已更新", function () {
        saveScrollPosition();
        location.reload();
      });
    }
  }

  document$.subscribe(function () { initializeReaderPage(); });
  window.setInterval(function () {
    checkReaderVersion().catch(function () {});
  }, VERSION_POLL_INTERVAL_MS);
}(typeof globalThis !== "undefined" ? globalThis : this));

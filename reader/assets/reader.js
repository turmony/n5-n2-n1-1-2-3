(function (root) {
  "use strict";

  const THEME_KEY = "jlpt-reader-theme";
  const FONT_KEY = "jlpt-reader-font-scale";
  const LAST_PAGE_KEY = "jlpt-reader-last-page";
  const SCROLL_KEY_PREFIX = "jlpt-reader-scroll:";
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

  function decideReaderUpdate(displayedHash, pageKey, currentVersion, nextManifest, stickyState) {
    if (stickyState === "stale" || stickyState === "deleted") return stickyState;
    const nextHash = nextManifest.pages[pageKey];
    if (displayedHash && nextHash === undefined) return "deleted";
    if (displayedHash && displayedHash !== nextHash) return "stale";
    if (!currentVersion) return "baseline";
    if (currentVersion === nextManifest.version) return "none";
    return "reload";
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
    catalogEntryMatches: catalogEntryMatches,
    decideReaderUpdate: decideReaderUpdate,
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

  function applyCatalogFilters(level, type, tag) {
    document.querySelectorAll(".jlpt-catalog-entry").forEach(function (entry) {
      const entryData = {
        level: entry.dataset.level || "",
        type: entry.dataset.type || "",
        tags: (entry.dataset.tags || "").split(/\s+/).filter(Boolean)
      };
      entry.hidden = !catalogEntryMatches(entryData, { level: level, type: type, tag: tag });
    });
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
    if (nextPageState.element !== jlptPageState.element) {
      jlptPageState = nextPageState;
      jlptStickyUpdate = "";
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
      const entries = Array.from(document.querySelectorAll(".jlpt-catalog-entry"));
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
        function (value) { level = value; applyCatalogFilters(level, type, tag); }
      );
      addSelect(
        controls,
        "类型",
        [["", "全部"]].concat(types.map(function (value) { return [value, TYPE_LABELS[value] || value]; })),
        "",
        function (value) { type = value; applyCatalogFilters(level, type, tag); }
      );
      addSelect(
        controls,
        "标签",
        [["", "全部"]].concat(tags.map(function (value) { return [value, value]; })),
        "",
        function (value) { tag = value; applyCatalogFilters(level, type, tag); }
      );
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
    const wasSticky = jlptStickyUpdate;
    jlptStickyUpdate = decision;
    jlptPageState.generation = next.version;
    if (wasSticky) return;
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
  window.setInterval(function () { checkReaderVersion().catch(function () {}); }, 3000);
}(typeof globalThis !== "undefined" ? globalThis : this));

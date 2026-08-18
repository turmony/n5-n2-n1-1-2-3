(function () {
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

  function saveScrollPosition() {
    sessionStorage.setItem(`${SCROLL_KEY_PREFIX}${location.pathname}`, String(window.scrollY));
  }

  let jlptScrollTimer;
  function scheduleScrollSave() {
    window.clearTimeout(jlptScrollTimer);
    jlptScrollTimer = window.setTimeout(saveScrollPosition, 150);
  }

  function restoreScrollPosition() {
    const key = `${SCROLL_KEY_PREFIX}${location.pathname}`;
    const value = sessionStorage.getItem(key);
    if (value !== null) requestAnimationFrame(function () { window.scrollTo(0, Number(value)); });
  }

  function applyCatalogFilters(level, type) {
    document.querySelectorAll(".jlpt-catalog-entry").forEach(function (entry) {
      const levelMatches = !level ||
        (level === UNMARKED_LEVEL ? !entry.dataset.level : entry.dataset.level === level);
      const typeMatches = !type || entry.dataset.type === type;
      entry.hidden = !(levelMatches && typeMatches);
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

  function initializeReaderPage() {
    applyTheme(localStorage.getItem(THEME_KEY) || "system");
    document.documentElement.dataset.jlptFont = localStorage.getItem(FONT_KEY) || "medium";
    if (location.pathname !== "/") localStorage.setItem(LAST_PAGE_KEY, location.pathname);
    restoreScrollPosition();
    window.removeEventListener("scroll", scheduleScrollSave);
    window.addEventListener("scroll", scheduleScrollSave, { passive: true });
    window.removeEventListener("pagehide", saveScrollPosition);
    window.addEventListener("pagehide", saveScrollPosition);
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
    if (location.pathname === "/") {
      let level = "";
      let type = "";
      const entries = Array.from(document.querySelectorAll(".jlpt-catalog-entry"));
      const levels = Array.from(new Set(entries.map(function (node) { return node.dataset.level; }).filter(Boolean))).sort();
      const hasUnmarkedLevel = entries.some(function (node) { return !node.dataset.level; });
      const types = Array.from(new Set(entries.map(function (node) { return node.dataset.type; }).filter(Boolean))).sort();
      addSelect(
        controls,
        "等级",
        [["", "全部"]]
          .concat(levels.map(function (value) { return [value, value]; }))
          .concat(hasUnmarkedLevel ? [[UNMARKED_LEVEL, "未标记"]] : []),
        "",
        function (value) { level = value; applyCatalogFilters(level, type); }
      );
      addSelect(
        controls,
        "类型",
        [["", "全部"]].concat(types.map(function (value) { return [value, TYPE_LABELS[value] || value]; })),
        "",
        function (value) { type = value; applyCatalogFilters(level, type); }
      );
      const lastPage = localStorage.getItem(LAST_PAGE_KEY);
      if (lastPage && lastPage !== "/") {
        const link = document.createElement("a");
        link.href = lastPage;
        link.textContent = "继续上次阅读";
        controls.appendChild(link);
      }
    }
    const content = document.querySelector(".md-content__inner");
    if (content) content.prepend(controls);
  }

  async function checkReaderVersion() {
    const response = await fetch(new URL("/reader-version.json", window.location.origin), { cache: "no-store" });
    if (!response.ok) return;
    const next = await response.json();
    const pageMeta = document.querySelector('meta[name="jlpt-page-key"]');
    const pageKey = pageMeta ? pageMeta.content : "";
    if (!window.jlptManifest) {
      window.jlptManifest = next;
      return;
    }
    if (window.jlptManifest.version === next.version) return;
    const oldHash = window.jlptManifest.pages[pageKey];
    const newHash = next.pages[pageKey];
    window.jlptManifest = next;
    if (oldHash && newHash === undefined) {
      showUpdateToast(
        "当前资料已删除；返回目录后将不再显示",
        function () { location.assign("/"); },
        "点此返回目录"
      );
    } else if (oldHash !== newHash) {
      showUpdateToast("当前资料已更新", function () {
        saveScrollPosition();
        location.reload();
      });
    } else {
      saveScrollPosition();
      location.reload();
    }
  }

  document$.subscribe(function () { initializeReaderPage(); });
  window.setInterval(function () { checkReaderVersion().catch(function () {}); }, 3000);
}());

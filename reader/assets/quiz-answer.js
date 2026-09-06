(function (root) {
  "use strict";

  const DRAFT_PREFIX = "jlpt-quiz-draft:";
  let activeQuizScrollCleanup = null;

  function createQuizState(questions) {
    const answers = {};
    for (const question of questions) {
      answers[question.number] = { kind: question.kind, options: question.options, value: "", uncertain: false };
    }
    return { answers };
  }

  function selectChoice(state, number, option) {
    const answer = state.answers[number];
    if (!answer) return;
    const digit = String(option);
    if (answer.kind === "choice") {
      answer.value = answer.value === digit ? "" : digit;
      return;
    }
    const position = answer.value.indexOf(digit);
    if (position !== -1) {
      answer.value = answer.value.slice(0, position) + answer.value.slice(position + 1);
      return;
    }
    // 满员后继续点击无效果，用户需先撤回已选数字
    if (answer.value.length < answer.options) answer.value += digit;
  }

  function toggleUncertain(state, number) {
    const answer = state.answers[number];
    if (answer) answer.uncertain = !answer.uncertain;
  }

  // 调用方（DOM 层）保证试卷至少一题；服务端也会兜底拒绝空答案列表
  function isComplete(state) {
    return Object.values(state.answers).every((answer) => answer.value.length > 0);
  }

  function answeredCount(state) {
    return Object.values(state.answers).filter((answer) => answer.value.length > 0).length;
  }

  function questionProgress(state, numbers, currentNumber) {
    return numbers.map((number) => {
      const answer = state.answers[number];
      return {
        number: number,
        answered: Boolean(answer && answer.value),
        current: number === currentNumber,
        uncertain: Boolean(answer && answer.uncertain),
      };
    });
  }

  function questionProgressLabel(progress) {
    const labels = [`第 ${progress.number} 题`];
    if (progress.current) labels.push("当前题");
    if (progress.answered) labels.push("已答");
    if (progress.uncertain) labels.push("标记不确定");
    return labels.length === 1 ? `跳转到${labels[0]}` : labels.join("，");
  }

  function currentQuestionNumber(positions) {
    let number = positions.length ? positions[0].number : 0;
    positions.forEach((position) => {
      if (position.top <= 132) number = position.number;
    });
    return number;
  }

  function replaceScrollListener(previousCleanup, target, listener) {
    if (typeof previousCleanup === "function") previousCleanup();
    if (typeof listener !== "function") return null;
    target.addEventListener("scroll", listener, { passive: true });
    return function () {
      target.removeEventListener("scroll", listener);
    };
  }

  function buildPayload(state, paper) {
    const numbers = Object.keys(state.answers).map(Number).sort((a, b) => a - b);
    return {
      paper: paper,
      answers: numbers.map((number) => ({
        number: number,
        value: state.answers[number].value,
        uncertain: state.answers[number].uncertain,
      })),
    };
  }

  function serializeDraft(state) {
    return JSON.stringify(state.answers);
  }

  function restoreDraft(state, raw) {
    let saved;
    try {
      saved = JSON.parse(raw);
    } catch (error) {
      return;
    }
    if (!saved || typeof saved !== "object") return;
    for (const number of Object.keys(state.answers)) {
      const entry = saved[number];
      if (!entry || typeof entry.value !== "string" || typeof entry.uncertain !== "boolean") continue;
      state.answers[number].value = entry.value;
      state.answers[number].uncertain = entry.uncertain;
    }
  }

  function draftKey(paper) {
    return DRAFT_PREFIX + paper;
  }

  const core = {
    DRAFT_PREFIX,
    createQuizState,
    selectChoice,
    toggleUncertain,
    isComplete,
    answeredCount,
    questionProgress,
    questionProgressLabel,
    currentQuestionNumber,
    replaceScrollListener,
    buildPayload,
    serializeDraft,
    restoreDraft,
    draftKey
  };
  root.JlptQuizAnswerCore = core;
  if (typeof module === "object" && module.exports) module.exports = core;
  if (typeof window === "undefined" || typeof document === "undefined") return;

  function initQuizPage() {
    activeQuizScrollCleanup = core.replaceScrollListener(activeQuizScrollCleanup, window, null);
    const marker = document.querySelector(".jlpt-quiz-state");
    if (!marker) return;
    let config;
    try {
      config = JSON.parse(marker.dataset.quizState);
    } catch (error) {
      return;
    }
    if (config.answered) return;

    const state = core.createQuizState(config.questions);
    const draft = window.localStorage.getItem(core.draftKey(config.paper));
    if (draft) core.restoreDraft(state, draft);

    const article = document.querySelector("article.md-content__inner, .md-content");
    if (!article) return;
    // 幂等守卫：防止 document$ 重复触发导致按钮/工具条叠加
    if (article.querySelector(".jlpt-quiz-bar")) return;

    const questionHeadings = article.querySelectorAll("h3, h4, h5");
    const byNumber = {};
    for (const heading of questionHeadings) {
      const match = heading.textContent.match(/^\s*(\d+)[\.．]/);
      if (match) byNumber[Number(match[1])] = heading;
    }

    const progressRail = document.createElement("nav");
    progressRail.className = "jlpt-quiz-progress";
    progressRail.setAttribute("aria-label", "题号进度");
    const progressLabel = document.createElement("span");
    progressLabel.className = "jlpt-quiz-progress__label";
    progressLabel.textContent = "题号";
    const progressList = document.createElement("div");
    progressList.className = "jlpt-quiz-progress__list";
    progressRail.append(progressLabel, progressList);
    marker.insertAdjacentElement("afterend", progressRail);

    // 选项 OL 不一定紧邻标题（阅读/对话题中间隔有正文段落），
    // 向后遍历到下一个题目标题或 h2 部分标题为止，取区间内首个 OL；
    // 阅读器插件会把源文件 #### 降级渲染为 h5，因此匹配范围含 h5
    function findOptionsList(heading) {
      let node = heading.nextElementSibling;
      while (node) {
        const tag = node.tagName;
        if (tag === "H2") return null;
        if ((tag === "H3" || tag === "H4" || tag === "H5") && /^\s*\d+[\.．]/.test(node.textContent)) return null;
        if (tag === "OL") return node;
        node = node.nextElementSibling;
      }
      return null;
    }

    function persist() {
      try {
        window.localStorage.setItem(core.draftKey(config.paper), core.serializeDraft(state));
      } catch (error) {
        /* 存储不可用时作答仍然可用 */
      }
      refreshSubmitButton();
    }

    config.questions.forEach((question) => {
      const heading = byNumber[question.number];
      if (!heading) return;
      const list = findOptionsList(heading);
      if (!list) return;
      const items = Array.from(list.children);
      items.forEach((item, index) => {
        const option = index + 1;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "jlpt-quiz-option";
        button.textContent = item.textContent;
        button.addEventListener("click", () => {
          core.selectChoice(state, question.number, option);
          paint();
          persist();
        });
        item.textContent = "";
        item.appendChild(button);
      });
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "jlpt-quiz-uncertain";
      toggle.textContent = "标记不确定";
      toggle.addEventListener("click", () => {
        core.toggleUncertain(state, question.number);
        paint();
        persist();
      });
      list.insertAdjacentElement("afterend", toggle);
      question._elements = { items, toggle };
      const progressButton = document.createElement("a");
      progressButton.className = "jlpt-quiz-progress__item";
      progressButton.href = `#${heading.id}`;
      progressButton.textContent = String(question.number);
      progressButton.setAttribute("aria-label", `跳转到第 ${question.number} 题`);
      progressList.appendChild(progressButton);
      question._elements.progress = progressButton;
    });

    function paint() {
      const progress = core.questionProgress(state, config.questions.map((question) => question.number), currentNumber);
      config.questions.forEach((question) => {
        const answer = state.answers[question.number];
        const elements = question._elements;
        if (!elements) return;
        elements.items.forEach((item, index) => {
          const digit = String(index + 1);
          const button = item.querySelector("button");
          button.classList.remove("selected", "ordered");
          if (answer.kind === "choice") {
            if (answer.value === digit) button.classList.add("selected");
          } else {
            const position = answer.value.indexOf(digit);
            if (position !== -1) {
              button.classList.add("ordered");
              button.dataset.order = String(position + 1);
            } else {
              delete button.dataset.order;
            }
          }
        });
        elements.toggle.classList.toggle("active", answer.uncertain);
        const itemState = progress.find((item) => item.number === question.number);
        if (elements.progress && itemState) {
          elements.progress.classList.toggle("answered", itemState.answered);
          elements.progress.classList.toggle("current", itemState.current);
          elements.progress.classList.toggle("uncertain", itemState.uncertain);
          elements.progress.setAttribute("aria-label", core.questionProgressLabel(itemState));
          if (itemState.current) elements.progress.setAttribute("aria-current", "step");
          else elements.progress.removeAttribute("aria-current");
        }
      });
    }

    let currentNumber = config.questions[0] ? config.questions[0].number : 0;

    function refreshCurrentQuestion() {
      const positions = config.questions.flatMap((question) => {
        const heading = byNumber[question.number];
        return heading ? [{ number: question.number, top: heading.getBoundingClientRect().top }] : [];
      });
      const nextNumber = core.currentQuestionNumber(positions);
      if (nextNumber !== currentNumber) {
        currentNumber = nextNumber;
        paint();
      }
    }

    const bar = document.createElement("div");
    bar.className = "jlpt-quiz-bar";
    const progress = document.createElement("span");
    const submit = document.createElement("button");
    submit.type = "button";
    submit.className = "jlpt-quiz-submit";
    submit.textContent = "提交答案";
    submit.addEventListener("click", () => submitAnswers());
    bar.appendChild(progress);
    bar.appendChild(submit);
    article.appendChild(bar);

    function refreshSubmitButton() {
      const total = config.questions.length;
      progress.textContent = `已答 ${core.answeredCount(state)}/${total}`;
      submit.disabled = !core.isComplete(state);
    }

    function submitAnswers() {
      if (!core.isComplete(state)) return;
      const summary = `共 ${config.questions.length} 题已全部作答，确认提交？`;
      if (!window.confirm(summary)) return;
      submit.disabled = true;
      window.fetch("/reader/submit-answers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(core.buildPayload(state, config.paper)),
      }).then((response) => {
          function succeed() {
            window.localStorage.removeItem(core.draftKey(config.paper));
            window.alert("答案已保存，页面即将更新为只读版本。");
            window.location.reload();
          }
          function fail(message) {
            window.alert(message);
            submit.disabled = false;
          }
          // 2xx 但 body 非 JSON 也按成功处理；非 2xx 且 body 解析失败时报状态码
          return response.json()
            .then((body) => {
              if (response.ok) succeed();
              else fail("提交失败：" + (body.error || "未知错误"));
            })
            .catch(() => {
              if (response.ok) succeed();
              else fail("提交失败：" + response.status);
            });
        })
        .catch(() => {
          window.alert("提交失败：网络错误，已选答案仍保留在本页。");
          submit.disabled = false;
        });
    }

    paint();
    refreshSubmitButton();
    refreshCurrentQuestion();
    activeQuizScrollCleanup = core.replaceScrollListener(
      activeQuizScrollCleanup,
      window,
      refreshCurrentQuestion,
    );
  }

  document$.subscribe(function () { initQuizPage(); });
}(typeof globalThis !== "undefined" ? globalThis : this));

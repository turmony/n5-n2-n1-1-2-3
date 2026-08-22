(function (root) {
  "use strict";

  const DRAFT_PREFIX = "jlpt-quiz-draft:";

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
    // 满员后继续点击被忽略，需先撤回（有意交互，DOM 层给视觉反馈）
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
    buildPayload,
    serializeDraft,
    restoreDraft,
    draftKey
  };
  root.JlptQuizAnswerCore = core;
  if (typeof module === "object" && module.exports) module.exports = core;
}(typeof globalThis !== "undefined" ? globalThis : this));

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../../reader/assets/quiz-answer.js");

test("choice selection toggles a single option", () => {
  const state = core.createQuizState([{ number: 1, kind: "choice", options: 4 }]);
  core.selectChoice(state, 1, 2);
  assert.equal(state.answers[1].value, "2");
  core.selectChoice(state, 1, 2);
  assert.equal(state.answers[1].value, "");
  core.selectChoice(state, 1, 3);
  core.selectChoice(state, 1, 4);
  assert.equal(state.answers[1].value, "4");
});

test("ordering selection appends in click order and retracts without renumbering", () => {
  const state = core.createQuizState([{ number: 3, kind: "ordering", options: 4 }]);
  core.selectChoice(state, 3, 2);
  core.selectChoice(state, 3, 3);
  core.selectChoice(state, 3, 1);
  assert.equal(state.answers[3].value, "231");
  core.selectChoice(state, 3, 2);
  assert.equal(state.answers[3].value, "31");
});

test("submission payload covers every question with uncertainty flags", () => {
  const state = core.createQuizState([
    { number: 1, kind: "choice", options: 4 },
    { number: 2, kind: "ordering", options: 4 },
  ]);
  core.selectChoice(state, 1, 4);
  core.toggleUncertain(state, 1);
  core.selectChoice(state, 2, 2);
  core.selectChoice(state, 2, 3);
  core.selectChoice(state, 2, 1);
  core.selectChoice(state, 2, 4);
  assert.equal(core.isComplete(state), true);
  assert.deepEqual(core.buildPayload(state, "paper.md"), {
    paper: "paper.md",
    answers: [
      { number: 1, value: "4", uncertain: true },
      { number: 2, value: "2314", uncertain: false },
    ],
  });
});

test("incomplete state cannot be submitted", () => {
  const state = core.createQuizState([{ number: 1, kind: "choice", options: 4 }]);
  assert.equal(core.isComplete(state), false);
});

test("drafts serialize and restore exactly", () => {
  const state = core.createQuizState([{ number: 1, kind: "choice", options: 4 }]);
  core.selectChoice(state, 1, 2);
  core.toggleUncertain(state, 1);
  const draft = core.serializeDraft(state);
  const restored = core.createQuizState([{ number: 1, kind: "choice", options: 4 }]);
  core.restoreDraft(restored, draft);
  assert.equal(restored.answers[1].value, "2");
  assert.equal(restored.answers[1].uncertain, true);
});

test("draft keys are isolated per paper", () => {
  assert.equal(core.draftKey("a.md"), "jlpt-quiz-draft:a.md");
  assert.notEqual(core.draftKey("a.md"), core.draftKey("b.md"));
});

test("restoreDraft ignores invalid payloads without throwing or mutating state", () => {
  for (const raw of ["not-json", "null", "42", "[1]"]) {
    const state = core.createQuizState([{ number: 1, kind: "choice", options: 4 }]);
    core.selectChoice(state, 1, 2);
    core.restoreDraft(state, raw);
    assert.equal(state.answers[1].value, "2", `raw=${raw}`);
    assert.equal(state.answers[1].uncertain, false, `raw=${raw}`);
  }
});

test("ordering append stops at the option count", () => {
  const state = core.createQuizState([{ number: 1, kind: "ordering", options: 2 }]);
  core.selectChoice(state, 1, 1);
  core.selectChoice(state, 1, 2);
  core.selectChoice(state, 1, 3);
  assert.equal(state.answers[1].value, "12");
});

test("payload orders question numbers numerically", () => {
  const state = core.createQuizState([
    { number: 12, kind: "choice", options: 4 },
    { number: 2, kind: "choice", options: 4 },
  ]);
  core.selectChoice(state, 2, 1);
  core.selectChoice(state, 12, 3);
  assert.deepEqual(
    core.buildPayload(state, "paper.md").answers.map((entry) => entry.number),
    [2, 12]
  );
});

test("answeredCount counts only answered questions", () => {
  const state = core.createQuizState([
    { number: 1, kind: "choice", options: 4 },
    { number: 2, kind: "choice", options: 4 },
  ]);
  core.selectChoice(state, 1, 3);
  assert.equal(core.answeredCount(state), 1);
});

test("question progress derives answered, current, and uncertain states", () => {
  const state = core.createQuizState([
    { number: 1, kind: "choice", options: 4 },
    { number: 2, kind: "choice", options: 4 },
    { number: 3, kind: "choice", options: 4 },
  ]);
  core.selectChoice(state, 1, 2);
  core.selectChoice(state, 2, 3);
  core.toggleUncertain(state, 2);

  assert.deepEqual(core.questionProgress(state, [1, 2, 3], 3), [
    { number: 1, answered: true, current: false, uncertain: false },
    { number: 2, answered: true, current: false, uncertain: true },
    { number: 3, answered: false, current: true, uncertain: false },
  ]);
});

test("question progress labels expose current, answered, and uncertain states", () => {
  assert.equal(
    core.questionProgressLabel({ number: 2, answered: true, current: true, uncertain: true }),
    "第 2 题，当前题，已答，标记不确定"
  );
  assert.equal(
    core.questionProgressLabel({ number: 3, answered: false, current: false, uncertain: false }),
    "跳转到第 3 题"
  );
});

test("scrolling back above all questions resets progress to the first question", () => {
  assert.equal(core.currentQuestionNumber([{ number: 1, top: -200 }, { number: 2, top: 100 }]), 2);
  assert.equal(core.currentQuestionNumber([{ number: 1, top: 200 }, { number: 2, top: 500 }]), 1);
  assert.equal(core.currentQuestionNumber([]), 0);
});

test("replacing the quiz scroll listener removes the previous page listener", () => {
  const calls = [];
  const target = {
    addEventListener: (_name, handler) => calls.push(["add", handler]),
    removeEventListener: (_name, handler) => calls.push(["remove", handler]),
  };
  const first = () => {};
  const second = () => {};

  const firstCleanup = core.replaceScrollListener(null, target, first);
  const secondCleanup = core.replaceScrollListener(firstCleanup, target, second);
  secondCleanup();

  assert.deepEqual(calls, [
    ["add", first],
    ["remove", first],
    ["add", second],
    ["remove", second],
  ]);
});

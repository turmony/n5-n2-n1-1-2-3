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

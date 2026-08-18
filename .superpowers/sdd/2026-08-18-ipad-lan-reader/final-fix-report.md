# Final review fix-wave report

Date: 2026-08-18

Branch: `codex/ipad-lan-reader`

Fix base: `b019f5d`

This wave verified and fixed all nine findings from the whole-branch review. All
tests used disposable directories and loopback-only test servers. No real
firewall or network configuration, shortcut creation, GUI automation, or iPad
operation was performed. The learner source library was treated as read-only.

## Behavioral TDD evidence

### 1. In-flight Windows shutdown

RED:

- `test_stop_waits_for_an_inflight_response_to_release_its_site_lease` held an
  HTTP response inside a deterministic lease and showed that `stop()` returned
  while the response worker and lease were still active.
- `test_stop_retries_only_the_temporary_cleanup_that_failed` showed that a
  first `PermissionError` made temporary cleanup unreachable on a second
  `stop()` call.
- `test_launcher_destroys_the_window_even_when_stop_cleanup_raises` showed that
  launcher teardown could skip window destruction.

GREEN:

- The HTTP server now uses non-daemon request workers and the standard
  `block_on_close` join, so server shutdown waits for every streaming response
  and site lease to end.
- Controller shutdown serializes concurrent callers, forgets each resource
  only after that resource closes successfully, and retains a failed cleanup
  for an idempotent retry.
- Launcher destruction is in a `finally` path.
- Focused server tests: 10 passed. Controller tests after the complete wave: 26
  passed.

### 2. NTFS junction and resolved-root containment

RED:

- A temporary Windows NTFS junction made a supported file outside the source
  root visible to discovery.
- A portable directory-symlink case covered the same containment boundary.

GREEN:

- Discovery prunes symlink, junction, and other reparse-point directories.
- Every walked directory, supported file, and final file read is resolved and
  required to remain under the resolved source root.
- The junction test creates only disposable directories and data.
- Focused source/watcher tests: 17 passed at the item boundary.

### 3. Initial-build watcher gap

RED:

- A deterministic build callback edited a source after the initial build had
  read it but before watcher startup; the original post-build baseline missed
  the change.

GREEN:

- The controller captures the source snapshot before the first build and seeds
  the watcher with that snapshot. Startup polling therefore observes and
  rebuilds the intervening edit.
- The behavioral test records two builds: the original content followed by the
  edit made during the first build.

### 4. Useful, de-duplicated catalog titles

RED:

- Real quiz-shaped metadata rendered an ID twice and ignored `prompt`.
- Long prompts were not bounded.
- History headings and explicit ID-prefixed titles received repeated level/ID
  prefixes.

GREEN:

- Quiz questions use `prompt` when no explicit title exists; catalog titles
  normalize layout whitespace, preserve the Japanese ideographic answer blank,
  and truncate to 80 characters at a Unicode character boundary.
- Source ID, JLPT level, and date prefixes are added only when the title does
  not already begin with that identity.
- Real-library audit: 541 pages, 90 quiz pages, zero `ID｜ID` quiz titles, 9
  history pages, and zero repeated history level prefixes. A representative
  result is `N5-Q-0001｜昨日泊まったホテルは駅から遠くて、あまり便利（　）。`.

### 5. Abandoned temporary sessions

RED:

- No owned-session abstraction or next-start stale cleanup existed.

GREEN:

- Each `jlpt-reader-*` session holds an external sibling ownership lock for its
  full lifetime. The implementation uses `msvcrt.locking` on Windows and
  `fcntl.flock` on POSIX, allowing the owned directory itself to be removed on
  Windows after cleanup starts.
- A next start removes only unlocked, marker-bearing, resolved direct children
  with the exact reader prefix. It skips active, unowned, symlink, junction,
  unresolved, and outside-root candidates. Diagnostics are bounded to eight
  errors.
- A cross-process behavioral test proves that an abandoned child-process
  session is collected while a live session is preserved. Focused session
  tests: 3 passed.

### 6. Structured `source` metadata

RED:

- Actual object/list source values were omitted from rendered metadata.

GREEN:

- Nested mappings are flattened with deterministic case-folded key ordering,
  lists retain order, and scalar values have stable readable forms. HTML
  escaping remains at the render boundary.
- Hostile markup remains escaped in the generated metadata block.
- Real-library audit found and rendered all 227 structured source fields. A
  representative value is `lesson: N5 第一个语法；material: 学习者提供的课程截图与学习笔记`.

### 7. Grammar fallback

RED:

- Missing or malformed metadata under `grammar/` classified as `document`.

GREEN:

- `grammar/` is now the fallback classification when no valid explicit type
  exists. A valid explicit type still wins.

### 8. Refused activation candidate cleanup

RED:

- Under a persistent retired-generation `rmtree` failure, five rebuild attempts
  performed six total builds and left never-activated candidates accumulating.

GREEN:

- `SiteStore.prepare()` owns the contained-path and cleanup-capacity preflight.
  `SiteStore.discard()` owns retirement of a built candidate that activation
  refused. The controller uses both APIs and keeps the last-good generation.
- In the repeated-failure test only three builds occur (one active plus two
  refused candidates); later attempts are blocked before creating a directory,
  the active page remains readable, the session directory count remains three,
  and two bounded cleanup errors remain available for diagnostics.

### 9. Steady-state update latency

Profile and RED evidence:

- Two unprofiled shipped-library full builds before optimization took 15.292 s
  and 15.135 s. The review measurement was 13.754 s.
- A profiled full build took 43.053 s under instrumentation; repeated Material
  navigation/template rendering dominated (about 24 s cumulative), followed by
  per-page sanitization (about 6.3 s cumulative).
- The first incremental test failed because `build_site` had no
  `previous_site` path. Controller wiring then failed with observed reuse inputs
  `[None, None]` instead of `[None, current]`.
- A named non-default MkDocs config change incorrectly reused two pages. Default
  watcher settling at 0.5 s and a one-second browser generation poll also had
  explicit failing tests before the cadence change.

GREEN implementation and correctness boundaries:

- A rebuild copies the immutable active generation to a new candidate (ordinary
  copies, never hard links), hashes current source content, and asks MkDocs to
  render only changed virtual pages.
- Reuse is allowed only when source routes/titles/IDs/types, the exact named
  MkDocs configuration, packaged assets, and theme overrides have matching
  fingerprints. Structural, navigation, or presentation changes clean the
  candidate and perform a full rebuild.
- Incremental search merges unchanged documents from the prior complete index
  with the newly rendered documents. Reused HTML receives only its two exact
  generation markers; a hostile identical string in learner content is not
  replaced.
- Behavioral coverage proves one-page reuse with complete search, source
  generation immutability, full fallback after a named-config change, and stale
  route/search removal after a source deletion.
- The default source polling and settle periods are now 0.5 s each. The browser
  checks the generation manifest every 1.0 s.

Measurements on a disposable byte-for-byte clone of the real 541-source
library:

| Measurement | Result |
| --- | ---: |
| Full build during the first post-change benchmark | 14.610 s |
| Initial incremental implementation, one body edit | 3.119 s |
| Optimized exact-marker incremental build, one body edit | **2.413 s** |
| Rendered pages | 1 |
| Reused pages (including catalog) | 541 |
| Manifest pages | 542 |
| Search documents | 3,790 |
| Generated files | 592 |
| Raw `.md` / `.jsonl` outputs | 0 |

With the measured 2.413 s build, the configured 0.5–1.0 s watcher detection
window, and the 0–1.0 s browser polling phase, the expected steady-state
edit-to-visible range is approximately **2.9–4.4 seconds**, excluding unusual
machine scheduling or storage contention. This is a modeled bound from measured
build time and configured polling periods; no physical iPad timing was performed
in this restricted fix wave.

## Final verification evidence

- Full Python suite: `python -m unittest discover -s tests -v` — 133 passed in
  21.937 s in the final pre-commit run.
- Node behavior suite: 14 passed.
- Repository validation: successful (`资料库结构有效`).
- Real shipped-config full build: 14.916 s; 541 supported sources; 542 manifest
  pages; 542 HTML pages; 592 generated files; `reader.css`, `reader.js`, and the
  search index present; zero raw Markdown/JSONL outputs.
- Real learner-source state: all 541 supported files had identical size,
  nanosecond mtime, and SHA-256 before and after the shipped build.
- `python -m compileall -q src tests`: passed.
- `git diff --check`: passed (only the repository's expected Git line-ending
  conversion notices were printed).

## Residuals and scope boundary

There is no known code blocker from the nine findings. The only unmeasured part
is physical iPad/browser latency, intentionally excluded by the task boundary.
No requirement was weakened or silently changed.

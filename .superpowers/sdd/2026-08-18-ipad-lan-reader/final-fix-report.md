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

## Additional scoped shutdown repair wave

Base commit: `9e7e4438fb7cd2cc1e9d182027f0d9979bc63900`

This follow-up was explicitly limited to the two remaining Important shutdown
findings. It performed no firewall/network inspection or mutation, shortcut or
GUI action, or learner-source edit.

### A. A non-reading client cannot hold shutdown indefinitely

Root cause and RED evidence:

- A real loopback client requested a sparse 32 MiB generated file with both
  sides' socket buffers constrained to 4 KiB, then stopped reading. The handler
  entered a real `SiteStore` lease and remained in the socket write.
- Before the fix, `ReadOnlyServer.stop()` did not finish within the test's 1.0 s
  bound. It finished only after the test closed the client socket.
- Instrumentation showed listener shutdown completing at about 0.5 s with one
  active request, followed by an active-socket close that still left
  `server_close()` blocked. Python's socket object deferred the underlying
  Winsock close because the handler's `makefile()` streams retained I/O
  references.
- A first minimal `shutdown()` plus ordinary `socket.close()` implementation
  therefore remained RED. This evidence rejected a timeout-based workaround.

GREEN implementation:

- The threaded server registers every accepted request socket before its worker
  starts and unregisters it only after the worker exits.
- After the listener thread has stopped, explicit server shutdown calls
  `shutdown(SHUT_RDWR)`, detaches each active socket, and closes the raw socket
  handle with the platform-aware `socket.close(fd)`. This interrupts a pending
  Winsock send without setting any timeout during normal iPad reads.
- `server_close()` then joins all request workers. Only after their handlers
  leave the lease can controller cleanup remove the site generation.
- An abort before response headers is treated as normal explicit shutdown; the
  handler does not attempt a second 404 write to the already detached socket or
  emit a worker traceback.
- The real stalled-client test is GREEN within the 1.0 s bound without client
  cooperation, observes lease exit, and removes the generation. The companion
  in-flight test proves shutdown still waits for a handler that has not yet left
  its lease, even though that handler's client connection is explicitly
  aborted.

### B. Double-rebind cleanup retains retry ownership

Root cause and RED evidence:

- `_fail_closed_after_rebind()` copied the watcher/server/store/session
  references and set every controller ownership field to `None` before calling
  cleanup.
- With a deterministic Windows-like `PermissionError` on the first session
  cleanup, the RED test observed one cleanup call but
  `controller._temporary is None`; a subsequent `stop()` had nothing to retry.

GREEN implementation:

- Normal stop and double-rebind failure now share one owned-resource cleanup
  routine. It closes in dependency order (server, store, session) and clears
  each controller field only after that resource's operation succeeds.
- The already-stopped pre-rebind server is committed without a redundant stop.
  Network-visible state is marked stopped before cleanup, so a cleanup error
  cannot advertise a dead endpoint.
- The behavioral test observes the first cleanup call fail while the session
  reference and directory remain owned; watcher, server, and store—whose
  cleanup succeeded—are cleared. A second `stop()` makes cleanup call two,
  removes the directory, clears the session reference, and publishes one
  coherent stopped state.

### Follow-up verification

- Focused server/controller/launcher/session selection: 41 passed in 8.545 s.
- Full Python suite: 135 passed in 21.073 s.
- Node behavior suite: 14 passed in 82.503 ms.
- `python -m compileall -q src tests`: passed.
- `git diff --check`: passed, with only expected line-ending notices.
- Repository validation: passed (`资料库结构有效`).
- Proportionate real shipped-config build: 12.437 s; 541 supported sources;
  542 manifest pages; 542 HTML pages; 592 files; assets and search present; no
  raw Markdown/JSONL output.
- All 541 supported learner sources had identical size, nanosecond mtime, and
  SHA-256 before and after that build.

No blocker or known residual remains within this two-finding scope. Physical
iPad behavior was not exercised, as required by the task boundary.

## Scoped shutdown repair round 2

Base commit: `29657f056e56cbcbaa3ee129eb87d8a814dfed1d`

This second review repair was limited to quiet, bounded explicit shutdown of
connections that have not supplied a complete HTTP request. It performed no
firewall or network inspection/mutation, GUI automation, shortcut action, or
learner-source edit.

### Root cause and RED evidence

- `BaseHTTPRequestHandler` reads the request line and headers during handler
  construction. An `OSError` from those reads therefore occurs before the
  generated-site handler enters `_serve` and its response-I/O exception seam.
- `ThreadingMixIn.process_request_thread` catches that escaped error and invokes
  the server's inherited default `handle_error`, which prints a traceback.
- A real loopback behavioral test opened three simultaneous accepted clients:
  one sent no bytes, one sent only `GET /`, and one sent a complete request line
  plus an incomplete header block. It then called explicit server stop while
  all three workers were blocked in pre-request reads.
- Before the production edit, the two-test RED run had one expected failure in
  1.529 s: bounded stop and worker cleanup completed, but the silence assertion
  captured 5,238 characters of default traceback output. The companion test
  passed, proving an injected unexpected `OSError` while the server was still
  running used the real default error-reporting path.

### GREEN implementation

- The threaded server records exactly which currently tracked request sockets
  were selected by its explicit `abort_active_requests` operation before it
  interrupts them.
- Its server-level `handle_error` suppresses only an `OSError` for one of those
  explicitly aborted sockets. Every other failure delegates to the inherited
  reporter; the live unexpected-`OSError` regression still observes both the
  traceback and exception message.
- Active and aborted tracking entries are removed together when a request
  worker exits or worker startup fails, so shutdown state does not retain
  socket objects.
- The real three-client test is GREEN, enforces stop completion in less than
  1.0 s without any client closing first, observes an empty active-worker set,
  captures no stderr, and then removes the site session successfully.

### Round-2 verification

- Focused RED/GREEN pair: 2 passed in 1.527 s after the fix.
- Focused server/controller suites: 40 passed in 10.100 s.
- Full Python suite: 137 passed in 24.266 s.
- Node behavior suite: 14 passed in 94.570 ms.
- `python -m compileall -q src tests`: passed.
- Repository validation: passed (`资料库结构有效`).
- `git diff --check`: passed, with only expected line-ending notices.
- The shipped-config build and learner-source immutability measurement were not
  repeated because this round changes only the HTTP shutdown/error-reporting
  lifecycle. The full Python run includes the committed read-only build and
  real HTTP end-to-end tests; no build, discovery, metadata, or source code was
  changed.

No blocker or known residual remains within this single shutdown finding. An
independent scoped re-review is still required; this report does not claim
approval.

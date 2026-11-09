# Changelog

## 0.2.2 · WASAPI / start-only benchmark — 2026-11-09

- Verify official Qt/PySide binary provenance; ship original LGPL/GPL/third-party notices, an offline license entry and a companion corresponding-source archive with rebuild/replacement instructions.
- License the original KeepQuiet implementation under MIT; retain independent third-party licenses.

- Report cancelled mode restarts as mode-switch cancellation, preserving the benchmark cancellation message for actual measurements.
- Keep the custom editor visible during processing-chain restarts; temporarily disable controls and respect user-initiated close.

- Expose only WASAPI endpoints; remove MME and DirectSound aliases.
- Benchmark on explicit Start or manual retest. Mode/filter restarts reuse the current run route, preserving mute and monitor without remeasurement.
- Reject a reused route if device IDs change; a fresh Start always measures again.


## 0.2.2 · battle-fix5 — 2026-11-09

Initial prepared repository snapshot of the locally validated Windows application. The binary/package version remains 0.2.2; battle-fix5 identifies this revision.

- Local enrolled-speaker extraction with three presets and custom settings.
- Independent raw-microphone electrical battle effect with a locked red selector.
- Benchmark and confirm a route before every start; synchronize progress and results.
- Stop, remeasure and restart when changing a mode or filter; preserve mute and active monitoring.
- Validate damaged JSON and malformed fields, back up originals and retain valid settings.
- Correct battle-mode manual benchmarking and distinguish failed online driver checks.
- Report monitor errors without stopping the main virtual output.
- Compact black/white UI, footer CPU meter, tray operation and device identity persistence.
- Remove unused cache reads, obsolete direct mode switching, duplicate route ordering and unused imports.

Local checks: 114 tests and 66 native UI checks. Real game load and long-duration audio validation remain separate.

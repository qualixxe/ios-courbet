# Working on ios-courbet

- Read `docs/PORT_STATUS.md` first (what is done, what is untested, what is
  blocked), then `docs/COURBET_HARDWARE.md` for every device constant and its
  source. `NOTES-sweet.md` is the ios-sweet engineering log — useful history, but
  it describes **sweet**, not courbet.
- This is a *port*, not a fork: the base is
  https://github.com/dipa-studio/ios-sweet (read-only clone in
  `ios-sweet-upstream`). Prefer minimal, device-specific edits over rewrites so
  that upstream fixes can still be merged.
- Keep the `SWEET` platform identifiers (`ARM64_BOARD_CONFIG_SWEET`,
  `xiaomi,sweet`, `sweet-fbcon`, `SWEETXNU`, `tools/sweet-*`). They name the
  SM7150 XNU port, not the Redmi Note 10 Pro; renaming them churns ~40 patches.
  The ADT carries `xiaomi,courbet` first and `xiaomi,sweet` second so that
  `SweetPlatformExpert` still binds. Do not "fix" this.
- Every hardware value belongs in `docs/COURBET_HARDWARE.md` **with its source**
  (DTB property, kernel source file, line). Distinguish *verified from the device
  tree*, *derived*, and *guessed* — the memory numbers in particular are partly
  derived. Do not turn a guess into a comment that reads like a fact.
- `research/` and `src/` are git-ignored: device dumps, decompiled DTs, Xiaomi
  kernel sources, Apple artifacts. Keep them out of git; extract the facts into
  `docs/` instead.
- Update the active handoff in `NOTES.md` after each milestone and before stopping.
  Record commits, CI run IDs, exact build/boot results and unfinished work.
  Distinguish observations from guesses.
- Commit completed changes. Use `gh` for GitHub Actions builds and logs; the `xnu`
  workflow runs on macOS. Local single-file cross-compiles are useful before
  spending a CI run.
- Device bring-up uses temporary `fastboot boot` images. Preserve the Android
  installation and partition backups. The ios-sweet approval (2026-10-15) was for
  **sweet**; confirm again with the user before any destructive step on courbet,
  and never touch bootloaders, recovery, modem, `persist` or the backups.
- The known code-change surface for this port so far:
  `tools/mkadt.py`, `shim/loader.c`, `shim/fdt.{c,h}`, `shim/shim.c`,
  `shim/console.h`, `shim/build.sh`, `tools/mkpayload.py` (docstring),
  `xnu/patches/0060`, `0062`, `0063`.
  Reproduce those edits with `research/apply_port_edits.py` +
  `research/fix_touch_rails.py`; validate the patch chain with
  `research/verify_patches.py`.

# Port status — ios-sweet → courbet

Legend: **done** = applied and locally verified · **todo** = written but never run ·
**blocked** = needs hardware/CI we do not have here.

## M — milestones

| # | Milestone | State | Evidence / next action |
| --- | --- | --- | --- |
| M0 | Read ios-sweet (`README`, `AGENTS.md`, `site/porting.html`, `NOTES-sweet.md`) | **done** | clone `ios-sweet-upstream` @ `45263be`, read-only |
| M1 | Collect courbet facts from real DTB/DTBO + `courbet-r-oss` sources | **done** | `docs/COURBET_HARDWARE.md` |
| M2 | Port scaffold: tree copied, device layer edited | **done** | this repo |
| M3 | Patch chain still applies after the edits | **done** | `python research/verify_patches.py` → `668 lines, chain OK` |
| M4 | ADT builder produces a valid courbet ADT | **done** | `mkadt.py --highmem --mem 6\|8` → 10 112 B, `dram-size 0xfcb00000` / `0x17cb00000`, root `compatible` = `D22AP, iPhone10,3, xiaomi,courbet, xiaomi,sweet, qcom,sm7150, AppleARM` |
| M5 | Build XNU with `MACHINE_CONFIG=SWEET` | **done** | run `40185740338` (`9ca3baf`) → `success`, 82/82 patches applied (`expected=82 applied=82 skipped=0`, `all 82 ios-courbet patches applied`); banner `xnu-8796.141.3`, `CURRENT_MACHINE_CONFIG=SWEET`, artifact `xnu-kernel`. The **first** run `40173726660` (`afb307b`) was green *but* silently skipped `0063` (`corrupt patch at line 27`) — see M5b. |
| M5b | CI must fail when one of our patches is skipped | **done, proven both ways** | step `Verify ios-courbet patches applied` after `Build`. Replaying its rule on run #1's log gives `expected=81 applied=80 skipped=1` → fails; on run #2 it gives `81/81/0` → passes. blacktop's own four patches (`TrustCache`, `iobuffermemd_monterey`, `skywalk_sonoma`, `syntax_checker_sonoma`) are skipped on every run and are deliberately not counted. |
| M6 | Build the shim (`shim/build.sh`) | **done** | run `40177122514` (`0d6750a`) → `success`: cross-compiles with `gcc-aarch64-linux-gnu`, links with no absolute relocations, packs a header-v2 boot.img and the round-trip check (`cmp` kernel/ramdisk/dtb) passes. The diagnostic image now also prints `RAMTOP` even without a payload. Needs `dtc` + a DTB; CI uses `tools/aosp/mkbootimg` (AOSP script, vendored, because `mkbootimg` is **not** on PyPI and not in apt). |
| M7 | `fastboot boot` the shim, confirm console output | **done** | Device boots both images. Shim console renders on the panel: `RAMTOP 0x1FCC00000` (6 GB, `--mem 6` correct), UFS milestone-5 probe (LUN0 GPT listed: super/logdump/mindump/rawdump/recovery/cache/exaid/cust/userdata ext4, `probe done, reset in ~3 min`). `courbet` branding visible in shim banner. |
| M8 | XNU boots to panic log / early console | **done, kernel reaches late `bsd_init`** | XNU console streams on the panel far past the milestone: `SWEET SURF/HID/CHRG/BATTERY/FB AppleCLCD 1080x2400 stride 4320`, SMP `cpu0 entered invtCPU (pmid=0xb0) IRQ=1`, SMC, MPC framework, ktriage, AMFI, Sandbox, caches, DLIL (gif0/stf0/lo0 threads scheduled), self-tests, `shm_region_init`-era output. **No panic seen. Kernel is alive** — vsync heartbeat (`0083`, `SWEET FB: tick N` every ~1 s) keeps counting after other output stalls, so the kernel is stuck in late `bsd_init` without dying. Stall location being pinned by `0084` (`DEBUG_BSDINIT 0→1` enables `bsd_init: calling …` step trace). |
| M9 | Display shows frames (command-mode risk) | **console confirmed** | Kernel kprintf output updates on the courbet panel live (photos 2026-10-25/26). iOS/compositor rendering still forward work; console proves frame path + D1. |
| M10 | Touch | **blocked** | see T1/T3 |
| M11 | iOS root in `userdata`, home screen | **flashed; phone panics after mount (pc unknown)** | `fastboot flash userdata rootfs-zero.simg` (12.15 GB zero-sparse DONT_CARE, 16 GB HFS+ from `rootfs.yml` run `40368757600`) SUCCEEDED 2026-10-27 with the user's explicit OK. Post-flash boot → **kernel data abort** (`caller 0xfffffe0007ad6418` = `_sleh_synchronous_sp1`; `handshake structure not initialized` = KDP line printed by every panic). `pc=`/FAR never captured — no photo; ring/sweetlog/disk have no panic text. Device later returned to Android → userdata reformatted → **re-flash needed**. Image-side suspects ruled out by direct analysis (journal/bitmap/btree layout consistent). **Next**: `research\flash-rootfs.bat` → `boot-xnu.bat` → photo → `symsweet.py 0x<pc>`. |
| M12 | QEMU reproduction harness (upstream's path: catch panics before the phone) | **done, green to PID 1** | QEMU 11.1.0 portable in `%TEMP%\opencode\qemu` (7-Zip-extracted, no admin). CI `qemu-root.yml` builds a 64 MB journaled HFS+ test root (`mkfs.hfsplus -s -J`, sig `HX` like the phone image; `/sbin/launchd` = sweet-init) — green run `40663084823`, image delivered via the `qemu-root-artifact` branch (Artifacts API needs a token we lack). `mkadt.py --qemu` + `mkpayload.py --ramdisk` + `qemu-sweet.py` (patched `425e291`: TCP QMP on Windows, no `AF_UNIX`). With the **flashed kernel `0e40d03c`** and the **phone cmdline** (incl. `wdt=-1`, which disables the sched-hygiene watchdog — its QEMU-only panic at `machine_routines_common.c:897` was the first run's failure): journal init → `hfs: mounted sweetroot` → full bsd_init → `load_init_program` → **`SWEET userspace: init running as PID 1`**, no panic. Read `research/qroot/fb.png` (serial stays empty — framebuffer is the console). Coverage gap: md0 ≠ UFS, empty root ≠ 16 GB catalog, sweet-init ≠ launchd/dyld/AMFI/IPv6. |
| M13 | Real-userland QEMU root (close the launchd/dyld gap) + fail-safe harness | **in flight** | `qemu-sweet.py --kernel` decodes the screen with a built-in Mach-O nm (no `llvm-nm`) and `--fail-on-panic` exits 0/2/3 (no panic / panic / undecodable) — the harness needs no eyeballing. `mkpayload.py` + `qemu-sweet.py` stream multi-GB ramdisks in 8 MiB chunks (before: ~12 GB RAM peak for a 6 GB image; rebuilt 64 MB payload proved SHA-identical). CI `qemu-fullroot.yml` builds a **6 GB lite root with the real iOS 16.7.16 userland** (real launchd, dyld + full shared cache, LaunchDaemons, /usr/lib{,exec}; frameworks/fonts/assets excluded — dyld serves them from the cache; cache `.symbols` excluded too), delivered as public **Release `qemu-fullroot`** (split parts, no token) with the build log on branch `qemu-fullroot-log`. Run 1 `40668334456` died on `No space left` at the cache `.symbols` → exclusion added (`tools/qemu-root-{excludes,sysos-excludes}.txt`, new `MKIOSROOT_*_EXCLUDE` vars in `mkiosroot.sh`). Local: `research\qemu-fullroot.bat [secs]` (ADT `--qemu --highmem --mem 8` → `-m 8G`). |

**The device has been flashed once (2026-10-27, user-approved) and panics
after the rootfs mount; QEMU reproduces the whole pre-userspace chain green to
PID 1 (M12).** See `NOTES.md` handoff 2026-10-28 for the run-by-run detail.

## D — display

| # | Item | State | Notes |
| --- | --- | --- | --- |
| D0 | FB base / size / stride correct for courbet | **done** | `0x9c000000`, 1080×2400, `cont_splash` `0x1700000` — verified in the courbet DTB |
| D1 | Command-mode panel picks up CPU framebuffer writes | **done** | courbet panels are `*_dsc_cmd` (TE on tlmm 10, reset PM6150L GPIO 9); sweet's was video-mode. Fix: `0082-sweet-command-mode-panel-refresh.patch` adds `*(volatile uint32_t *)0xae2204 = 1;` (SDE CTL_1 FLUSH, MDSS 0xae00000 + CTL_1 0x2200 + 0x4) inside `vsyncFired` after `fb->present(rec);`. **Verified on device**: console text streams and updates past the point where the untreated build froze (runs `40185740338`, `40355906491`; commits `9ca3baf`, `8ace5dc`). First successful boot could not scroll further only because the kernel stopped producing output — that was the M8 `bsd_init` stall, not a display defect. Stale note from stock: panel-specific nodes live in stock `dtbo.img` (`k9a_36_02_0a_mp_dsc_cmd`, `k9a_42_02_0b_mp_dsc_cmd`); not applied and not needed for the console path. |
| D2 | Panel ID detected at runtime | **todo** | stock cmdline has no `msm_drm.dsi_display0`; verify from the kernel log |

## T — touch

| # | Item | State | Notes |
| --- | --- | --- | --- |
| T0 | GPIO 6/7/8/9 (SE7 I²C, reset, IRQ) | **done** | verified identical to sweet |
| T1 | VDDIO switch moved 90 → 72 | **done** | `0060`, `0062` |
| T2 | Analog rail moved LDO11 3200 → LDO6 1648 | **done** | boot-arg `courbet_touch_mv=`; **voltage unverified**, see hardware doc §3 |
| T3 | ST FTS path (`st,fts` @ `0x49`) | **done in code, untested** | protocol matches sweet's existing `TOUCH_FTS` branch (chip-id `0xa3`/`0x9f` → `0x54:0x52`) |
| T4 | Goodix Berlin **SPI** (QUP SE4) | **not started** | needed only if the unit is the SPI variant — unknown until M7/T5. New GENI SPI driver + Berlin protocol = the largest remaining piece of work |
| T5 | Identify the unit's controller | **todo** | from Android: `adb shell dumpsys input \| grep -iE "fts\|goodix\|spits"` |
| T6 | Coordinate scaling / orientation | **todo** | I²C touch nodes report `0x437`×`0x923` (1080×2340) vs SPI nodes 1080×2400; check against the presented 1125×2436 iPhone X canvas |

## P — power / battery

| # | Item | State |
| --- | --- | --- |
| P0 | Battery capacity 5020 → 4250 in `0062` | **done** (6 occurrences) |
| P1 | `SweetBattery` SPMI observer on PM6150 QG | carried over, untested on courbet |
| P2 | `bq2597x` charger / 4480 mV termination | not implemented (charging read-only) |

## V — verification performed in this tree

```
python research/apply_port_edits.py      # shim/fdt.{c,h}, loader.c, shim.c, build.sh,
                                         # mkadt.py, mkpayload.py, 0062 comment, 0063 note
python research/fix_touch_rails.py       # 0060 + 0062: GPIO72, LDO6, 4250 mAh
python research/fix_hunks.py             # all 81 patches, two passes, 0 corrections
python research/verify_patches.py        # 0060 → 0062 → 0063 on sweet_touch.c: OK
python research/brace_check.py           # fdt.c/fdt.h/loader.c/shim.c balance
python tools/mkadt.py --highmem --mem 6  # ADT parses, dram-base/size correct
python tools/mkadt.py --highmem --mem 8  # same, 8 GB bank
```

The edit scripts are idempotent (they check the *result* text, not the anchor) and
exit 0 when re-run; `research/dedup_edits.py`, `fix_buildsh.py` and `tidy.py` exist
because the first version was not and left duplicate blocks in `shim/fdt.h`,
`shim/loader.c` and `shim/build.sh`. That was found and fixed — worth knowing that
`research/` scripts mutate the tree directly and are meant to be re-run.

`research/fix_hunks.py` now walks **all 81** `xnu/patches/*.patch` and re-counts
every hunk header (two passes: it exits 1 while it is still correcting something).
It caught `0063`'s stale `@@ -32,6 +32,11 @@` — the bug CI reported as
`corrupt patch at line 27`. Its own first version had a second bug (it appended
the corrected header but dropped the hunk body) and destroyed `0063`; that file
was restored from `ios-sweet-upstream/` and re-edited, after which:

```
fix_hunks.py  pass1  81 patch file(s) checked, 0 hunk header(s) corrected   exit 0
fix_hunks.py  pass2  81 patch file(s) checked, 0 hunk header(s) corrected   exit 0
verify_patches.py    bsd/dev/sweet_touch.c: 668 lines, chain OK             exit 0
```

`verify_patches.py` proves the `0060 → 0062 → 0063` chain on `sweet_touch.c` only;
it cannot prove the series applies to a pristine `xnu-8796` — CI does that, and now
`M5b` makes a skipped patch fail the run.

## Next concrete action

**Images are built and waiting for the phone** (see M7):

```
fastboot boot shim/out/shim-boot-courbet-diag.img     # 1st: RAMTOP + UFS probe + MMU
fastboot boot shim/out/shim-boot-courbet-xnu6g.img    # 2nd: same shim + XNU payload
```

1. The diagnostic image is the important one: it prints `RAMTOP` (settles `--mem 6`
   vs `8`), the UFS probe result, and the MMU/framebuffer lines, then resets after
   ~3 min. Film it or photograph the screen.
2. The XNU image carries an ADT built with `--mem 6`, which is safe on a 6 GB unit
   and works on an 8 GB one (the shim refuses a window larger than live RAM).
   Rebuild with `--mem 8` only after `RAMTOP` says 8 GB.
3. Identify the unit's touch controller (T5) — decides whether T4 is required.

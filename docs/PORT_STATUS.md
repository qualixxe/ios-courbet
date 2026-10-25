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
| M5 | Build XNU with `MACHINE_CONFIG=SWEET` | **done** | run `40175356689` (`0ddcae0`) → `success`, 6 min 39 s, and the log proves the series landed: `expected=81 applied=81 skipped=0`, `all 81 ios-courbet patches applied`; banner `xnu-8796.141.3`, `CURRENT_MACHINE_CONFIG=SWEET`, artifact `xnu-kernel`. The **first** run `40173726660` (`afb307b`) was green *but* silently skipped `0063` (`corrupt patch at line 27`) — see M5b. |
| M5b | CI must fail when one of our patches is skipped | **done, proven both ways** | step `Verify ios-courbet patches applied` after `Build`. Replaying its rule on run #1's log gives `expected=81 applied=80 skipped=1` → fails; on run #2 it gives `81/81/0` → passes. blacktop's own four patches (`TrustCache`, `iobuffermemd_monterey`, `skywalk_sonoma`, `syntax_checker_sonoma`) are skipped on every run and are deliberately not counted. |
| M6 | Build the shim (`shim/build.sh`) | **in progress** | new `shim` workflow (ubuntu-latest, `gcc-aarch64-linux-gnu` + pip `mkbootimg` + `dtc`) compiles, links, packs with a **stub** DTB and verifies the boot.img round-trips byte-for-byte. `build.sh` no longer needs gawk (`strtonum`) and no longer hard-requires a DTB/mkbootimg. A real boot.img still needs the stock `dtb.img` (device dump, not in git). |
| M7 | `fastboot boot` the shim, confirm console output | **blocked** | no device |
| M8 | XNU boots to panic log / early console | **blocked** | needs M7 |
| M9 | Display shows frames (command-mode risk) | **blocked** | see D1 |
| M10 | Touch | **blocked** | see T1/T3 |
| M11 | iOS root in `userdata`, home screen | **blocked** | needs M9 + M10 |

**Nothing has been flashed to a courbet device.** The XNU kernel builds in CI
(M5, all 81 patches applied); the shim has not been compiled in this tree yet (M6).

## D — display

| # | Item | State | Notes |
| --- | --- | --- | --- |
| D0 | FB base / size / stride correct for courbet | **done** | `0x9c000000`, 1080×2400, `cont_splash` `0x1700000` — verified in the courbet DTB |
| D1 | Command-mode panel picks up CPU framebuffer writes | **blocked** | courbet panels are `*_dsc_cmd` (TE on tlmm 10, reset PM6150L GPIO 9); sweet's was video-mode. **First boot to test:** does the splash keep updating? If it freezes, add a DSI refresh kick (IOMFB/kern_RequestPowerChange style — sweet already has this machinery in `0079`) |
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

1. Identify the unit's touch controller (T5) — decides whether T4 is required.
2. Build the shim (M6) in WSL: `shim/build.sh` with `DTB=` pointing at the stock
   `dtb.img`.
3. `fastboot boot` it (M7) — the console now also prints `RAMTOP`, which tells us the
   live RAM size and settles the `--mem` question in one shot.

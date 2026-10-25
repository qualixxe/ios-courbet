# Port status — ios-sweet → courbet

Legend: **done** = applied and locally verified · **todo** = written but never run ·
**blocked** = needs hardware/CI we do not have here.

## M — milestones

| # | Milestone | State | Evidence / next action |
| --- | --- | --- | --- |
| M0 | Read ios-sweet (`README`, `AGENTS.md`, `site/porting.html`, `NOTES-sweet.md`) | **done** | clone `ios-sweet-upstream` @ `45263be`, read-only |
| M1 | Collect courbet facts from real DTB/DTBO + `courbet-r-oss` sources | **done** | `docs/COURBET_HARDWARE.md` |
| M2 | Port scaffold: tree copied, device layer edited | **done** | this repo |
| M3 | Patch chain still applies after the edits | **done** | `python research/verify_patches.py` → `665 lines, chain OK` |
| M4 | ADT builder produces a valid courbet ADT | **done** | `mkadt.py --highmem --mem 6\|8` → 10 112 B, `dram-size 0xfcb00000` / `0x17cb00000`, root `compatible` = `D22AP, iPhone10,3, xiaomi,courbet, xiaomi,sweet, qcom,sm7150, AppleARM` |
| M5 | Build XNU with `MACHINE_CONFIG=SWEET` | **in progress** | run `40173726660` on https://github.com/qualixxe/ios-courbet/actions/runs/40173726660 (macos-14, triggered by the initial push). The first steps are the ones that matter: the patches are copied into blacktop's build script and applied to a clean `xnu-8796`. |
| M6 | Build the shim (`shim/build.sh`) | **todo** | needs `aarch64-linux-gnu-gcc` + `mkbootimg` (WSL or CI). Not compiled since the `fdt_memory_top` addition. |
| M7 | `fastboot boot` the shim, confirm console output | **blocked** | no device |
| M8 | XNU boots to panic log / early console | **blocked** | needs M7 |
| M9 | Display shows frames (command-mode risk) | **blocked** | see D1 |
| M10 | Touch | **blocked** | see T1/T3 |
| M11 | iOS root in `userdata`, home screen | **blocked** | needs M9 + M10 |

**Nothing has been flashed to a courbet device.** No build of the XNU kernel or of the
shim has been produced in this tree yet.

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
python research/fix_hunks.py             # recomputed the one hunk header that grew
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

Every hunk header in `0060`, `0062`, `0063` was re-counted and matches its body.
The verification is *per-file*: it reconstructs `bsd/dev/sweet_touch.c` from `0060`
and replays `0062`/`0063` on it. It does **not** prove the rest of the series applies
to a pristine `xnu-8796` — that only a real `git apply` in CI will.

## Next concrete action

1. Identify the unit's touch controller (T5) — decides whether T4 is required.
2. Push and run the `xnu` workflow (`MACHINE_CONFIG=SWEET`) to get M5, and confirm the
   full patch series applies to a clean `xnu-8796`. **This is the first thing that can
   fail and can be checked without hardware.**
3. Build the shim (M6) in WSL: `shim/build.sh` with `DTB=` pointing at the stock
   `dtb.img`.
4. `fastboot boot` it (M7) — the console now also prints `RAMTOP`, which tells us the
   live RAM size and settles the `--mem` question in one shot.

# ios-courbet — engineering log

Port of ios-sweet (iOS 16 XNU + iPhone X userland) from Redmi Note 10 Pro (`sweet`)
to Xiaomi Mi 11 Lite 4G (`courbet`). Upstream: https://github.com/dipa-studio/ios-sweet
(read-only clone `ios-sweet-upstream`, HEAD `45263be`). The old ios-sweet log is
`NOTES-sweet.md` — it describes **sweet**; treat its hardware facts as history.

## Handoff (2026-10-25) — port scaffold complete, nothing built or booted

**Where the tree is**

- `ios-courbet/` = full ios-sweet tree + courbet device layer + `research/` + `src/`.
- `ios-sweet-upstream/` = untouched upstream, keep it for diffing.
- `site/` still says ios-sweet everywhere — deliberately untouched for now.

**What was changed (and verified locally)**

1. `tools/mkadt.py`
   - `--mem 6|8` for the two RAM variants (`HIGH_MEM_SIZE_6G 0xfcc00000`,
     `HIGH_MEM_SIZE_8G 0x17cc00000`), default 6 GB.
   - root `compatible` = `D22AP, iPhone10,3, xiaomi,courbet, xiaomi,sweet,
     qcom,sm7150, AppleARM` (`xiaomi,sweet` must stay — `0016` matches on it).
   - `COURBET_ECID = 0x434f555242455400` ('COURBET\0'), firmware-version
     `courbet-shim`, SHA384 boot-manifest seeded with `courbet boot manifest`.
   - Usage now `mkadt.py OUT [--dump] [--qemu] [--highmem] [--mem 6|8]`.
   - Tested: 10 112 bytes, `dram-base 0x100000000`, `dram-size 0xfcb00000` (6 GB).
2. `shim/fdt.c` + `shim/fdt.h`: new `fdt_memory_top()` — walks the live `/memory`
   nodes (`#address-cells = #size-cells = 2`) and returns the top of RAM.
3. `shim/loader.c`: after `ENTRY`, prints `RAMTOP` and **refuses to boot** if
   `phys_base + mem_size + 0x100000 > ram_top` →
   `"payload RAM exceeds live RAM (mkadt --mem 6|8)"`. Turns a wrong `--mem`
   guess into a clean failure instead of corruption.
4. `shim/shim.c`: milestone strings now say `courbet`.
5. `shim/build.sh`: `DTB=${DTB:-../dtb/boot_unpacked/dtb}`, overridable.
6. `shim/console.h`: FB comment documents `0x9c000000` / `0x9d700000`.
7. `xnu/patches/0060`, `0062`: touch VDDIO switch **TLMM 90 → 72**; analog rail
   **PM6150L LDO11 @3200 → LDO6 @1648** (`ldoc11`→`ldoc6`, validation window
   1600…3400 mV), new boot-arg **`courbet_touch_mv=`**; battery **5020 → 4250 mAh**
   (6 sites); comment `qup11` → `SE7`.
8. `xnu/patches/0063`: header context updated to match (0062 changed that line) and
   a note that courbet's stock kernel compiles no I²C Goodix driver.
9. Docs: `README.md`, `docs/COURBET_HARDWARE.md`, `docs/PORT_STATUS.md`,
   `AGENTS.md`.

**Verification done here**

- `research/apply_port_edits.py`, `research/fix_touch_rails.py`,
  `research/fix_hunks.py` — the edits themselves (re-runnable, they skip if applied).
- `research/verify_patches.py` — reconstructs `bsd/dev/sweet_touch.c` from `0060`
  and replays `0062` → `0063`: **`665 lines, chain OK`**.
- Hunk headers re-counted for `0060`, `0062`, `0063`: all match their bodies
  (`0062 @@ -490,16 +491,31 @@` was corrected after the power block grew).
- `mkadt.py` run for both `--mem 6` and `--mem 8`.

**Not done / not verified**

- No XNU build (macOS CI), no shim compile (no `aarch64-linux-gnu-gcc` here), no
  `git apply` of the full 81-patch series against a clean `xnu-8796`, no device.
- **`courbet_touch_mv` default of 1648 mV is derived** from the DTB's
  `qcom,init-voltage = <0x192580>` for `pm6150l_l6`, because the stock ST driver only
  calls `regulator_enable()` and never sets a voltage. `regulator-min/max` are
  1 648 000…3 100 000, so 3000 mV is legal if touch stays dead.
- **8 GB upper bank `0x17cc00000` is derived** (2G + 8G − 0x3400000), not read off a
  live 8 GB unit. `0x3400000` top reserve is carried over from sweet.
- **Command-mode display** is the main unknown: courbet panels are `*_dsc_cmd`
  (TE tlmm 10, reset PM6150L GPIO 9); sweet was video-mode. If the splash freezes
  while the kernel runs, the fix is a DSI refresh kick (sweet already has IOMFB
  request machinery in `0079`).
- **Touch controller variant unknown.** courbet's defconfig compiles
  `CONFIG_TOUCHSCREEN_FTS=y` (I²C `0x49`, `st,fts`) and
  `CONFIG_TOUCHSCREEN_GOODIX_BRL=y` (SPI Berlin via `xiaomi-spits`). The I²C
  `goodix@5d` node has **no** enabled driver. Port implements FTS; SPI Berlin is
  unimplemented. Identify with `adb shell dumpsys input` on Android.
- T4 (SPI Goodix Berlin) is the largest remaining code item if the unit needs it.

**Next action (in order)**

1. Identify the touch controller (T5) — decides whether T4 is needed at all.
2. Run the `xnu` workflow with `MACHINE_CONFIG=SWEET` to confirm the patch series
   applies to a clean xnu-8796. First thing that can fail and is checkable
   without hardware.
3. Build the shim: `DTB=<stock dtb.img> shim/build.sh`.
4. `fastboot boot`; the new `RAMTOP` line gives the live RAM size and settles
   `--mem`.

**Conventions kept**

- `SWEET` platform identifiers stay (see `AGENTS.md`).
- Apple artifacts, device dumps and extracted vendor images stay out of git.

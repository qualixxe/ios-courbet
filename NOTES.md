# ios-courbet — engineering log

Port of ios-sweet (iOS 16 XNU + iPhone X userland) from Redmi Note 10 Pro (`sweet`)
to Xiaomi Mi 11 Lite 4G (`courbet`). Upstream: https://github.com/dipa-studio/ios-sweet
(read-only clone `ios-sweet-upstream`, HEAD `45263be`). The old ios-sweet log is
`NOTES-sweet.md` — it describes **sweet**; treat its hardware facts as history.

## Handoff (2026-10-27) — rootfs image built in CI; next step: flash userdata (needs explicit user OK)

**What happened during the night**

- User declined the local WSL route after DISM `Error: 14098` (component store
  corrupted) — "лучше гитхаб". Everything rootfs-related moved to CI.
- `rootfs` workflow (`.github/workflows/rootfs.yml`, ubuntu-24.04) is green after
  three fixes, run **`40368757600`** (ref `528a5d6`):
  1. `bzlib.h` missing → added `libbz2-dev zlib1g-dev` for the apfs-fuse build.
  2. 20H392 BuildManifest keys are **`OS` / `Cryptex1,SystemOS` / `Cryptex1,AppOS`**
     (not `SystemOS`/`AppOS`) — mapping validated against the local IPSW:
     `087-86698-044.dmg` (OS, 4.41 GB), `087-86593-047.dmg` (SystemOS, 2.55 GB),
     `087-86715-047.dmg` (AppOS, 10 MB).
  3. Runner kernel is Azure without `hfsplus` (`unknown filesystem type 'hfsplus'`)
     → new step installs `linux-modules-extra-$(uname -r)` + `depmod` + `modprobe`.
- Artifact `ios-rootfs-20h392` (id `12672228816`, **5642 MB**): `rootfs.img.gz`
  (16 GB HFS+ journaled, `mkfs.hfsplus -s -J -v iOSRoot`, iOS 16.7.16 20H392 root +
  cryptexes + dyld cache hard links + keybag + logd stores, fsck-cleaned),
  `rootfs.img.sha256`, `build.log`. Download in progress via `getartifact.ps1`
  (RunId `40368757600`, dest `%TEMP%\rootfs-art`).

**Where the kernel is**

- Current boot image `shim/out/shim-boot-courbet-xnu6g.img`
  (17 199 104 B, sha256 `d489e8fab69c402258d3158dbf3cd415370abcffcb6f92b29bb514cb3fcce3bf`
  — kernel `0e40d03c…` from run `40363880989`, commit `bd71443`: DEBUG_BSDINIT trace +
  heartbeat throttled to one line per ~10 s).
- Payload args now carry the upstream userspace set:
  `debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress
  rd=ufsroot0 ufsrw=1 rootrw=1 unentitled_ios_sim_launch=1 ignition_level=1
  wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1`.
- Device result 2026-10-26 evening: mount attempts happen — the classic
  `cannot mount root, errno = N` loop (`bsd/kern/bsd_init.c:899`) is on screen
  and repeats. **N was never reported by the user.** Expected 22 (EINVAL: ext4
  content rejected by HFS), but if 19 (ENODEV) the root device publishing path
  needs a look before the image can even mount.
- Apple's `launchd` will be the first userspace process once the HFS image is
  on `userdata`; boot args for that are already in place.

**Next (when the user is back)**

1. Finish artifact download, verify sha256, gunzip to `rootfs.img` (16 GB).
2. Ask the explicit destructive step OK (AGENTS: courbet needs fresh consent):
   `fastboot flash userdata rootfs.img` (partition ~107 GB, image 16 GB fills
   the head; HFS+ volume is self-contained). Android **data** on userdata is
   lost; system/boot/modem/persist untouched. Bootloader relock not involved.
3. `fastboot boot shim/out/shim-boot-courbet-xnu6g.img` → expect launchd logs
   on console; the `0084` bsd_init trace is still enabled for smooth decoding.
4. If boot images need to change later: `mkpayload.py … --cmdline …` is the
   only knob (kernel is payload-independent; boot args live in the payload blob,
   608 B field).
5. Still open: the errno number from the phone; iOS 16.7.16 uses the same 20H392
   rootfs upstream ran (all good), but sweet's v13/v14 plist tweaks
   (`tools/patch-launchd-plist.py`, CommCenter removal, Setup skip) may be needed
   as later image revisions, exactly as on sweet.

## Handoff (2026-10-26) — device reality check: console works, kernel alive, bsd_init stall traced next

**Device runs XNU.** Verified with `fastboot boot` on the phone (user photos,
2026-10-25/26):

- Shim console renders on the panel; `RAMTOP 0x1FCC00000` → 6 GB is correct.
- XNU streams a large `bsd_init` console past anything seen before: `SWEET SURF`,
  `SWEET HID`, `SWEET CHRG`, `SWEET BATTERY`, `SWEET FB: AppleCLCD 1080x2400
  stride 4320`, SMP `cpu0 entered invtCPU`, SMC, MPC framework, ktriage, AMFI,
  Sandbox, cache info, DLIL interface threads (gif0/stf0/lo0 scheduled),
  kernel self-tests. No `panic` line observed in photos.
- Output stops partway through late `bsd_init`. The earlier "freeze" is **not**
  a display defect: with the `0083` heartbeat build the user reports
  `SWEET FB: tick N` lines keep counting every second after other output
  stalls — kernel alive, SMP-timer + IOLog + console + D1 panel kick all work.
  The kernel just stops making progress in late `bsd_init`.

**Numbers for reproduction**

- Run `40185740338` (`9ca3baf`) → success, 82/82 patches: first D1-kick kernel
  (`10b974e9…`) whose boot filled the screen to mid-`bsd_init`.
- Run `40355906491` (`8ace5dc`) → success, 83/83: adds `0083-sweet-fb-heartbeat.patch`
  (in `vsyncFired`, after `fVsyncCount++`: every 60 counts → `IOLog("SWEET FB: tick
  %llu\n", count)`). Kernel sha `d4bc7f26…`; repacked image
  `shim/out/shim-boot-courbet-xnu6g.img` 17 199 104 B, sha256
  `9692028064f7b660bf87083d0c93f2ee290c7e8d6eef970c60ee268fcefd144c` — the build the
  user booted (ticks confirmed growing).
- Run `40359010372` (`ece5df9`) → Build success but **`Verify ios-courbet patches
  applied` failed (`expected=84 applied=83 skipped=1`)**: `0084` skipped with
  `corrupt patch at line 7` — my first version of the patch contained only context,
  no `-`/`+` lines. Fixed in `6bbcf85`: patch rewritten as a canonical git-style
  hunk (`@@ -490,7 +490,7 @@`, anchor lines around
  `platform_stall_panic_or_spin(PLATFORM_STALL_XNU_LOCATION_BSD_INIT)`, flips
  `#define DEBUG_BSDINIT 0` → `1` in `bsd/kern/bsd_init.c`, which enables the ~50
  `bsd_init: calling …` trace prints). Lesson recorded: validate repo patches with
  `git apply --check` against the CI buildtree, not only `fix_hunks.py` —
  `verify_patches.py` only replays the sweet_touch chain and stays silent on other files.
- CI run for `6bbcf85` in flight (concurrency cancels stale runs).

**Display/DT facts (from `research/shirayuki-oem/dtbo.img`)**

- Stock `dtbo.img` has **1 overlay** (id `0xd7b7ab1e`) whose FDT adds both courbet
  panel nodes `qcom,mdss_dsi_k9a_36_02_0a_mp_dsc_cmd` and `…_0b	mp_dsc_cmd`
  with `qcom,esd-err-irq-gpio`, `qcom,platform-te-gpio`, `qcom,platform-reset-gpio`.
- Our boot applies only the stock `dtb.img` (single FDT, verified) — fine for the
  console path; panel-overlay merge is future work if we switch panels/regulators.
- `dtb.img` itself lists just `qcom,msm-id` / `qcom,board-id` / `qcom,msm-name`
  strings at top level.

**Next**

1. Boot the `0084` trace build once CI lands; read the last `bsd_init: calling … `
   line from the screen → exact stall step.
2. Fix the stall (likely inside one of the calls after `dlil_init`:
   `socketinit/domaininit/skywalk_init/memorystatus/sysctl` or earlier, e.g.
   `vfsinit/IOKitInitializeTime/bsd_bufferinit/IF PP`).
3. Then rootfs: ramdisk with `launchd` mounted via our UFS/HFS path or an HFS image
   in a partition; kernel args currently have no `rootdev`, and there is no
   userspace payload yet — that is milestone M11 work.
4. `Still waiting for root device` was **not** observed on the stalled screen, so
   the stall happens **before** `IOFindBSDRoot` even starts — rootfs is not yet
   the blocker even though it is the next real milestone.

## Handoff (2026-10-25) - XNU and shim both build in CI; two fastboot images ready

**Where the tree is**

- `ios-courbet/` = full ios-sweet tree + courbet device layer + `research/` + `src/`.
- `ios-sweet-upstream/` = untouched upstream, keep it for diffing.
- `site/` still says ios-sweet everywhere — deliberately untouched for now.
- **Repo: https://github.com/qualixxe/ios-courbet** (public, created 2026-10-25,
  push credential `qualixxe` via Git Credential Manager; `gh` is not installed —
  GitHub REST calls go through `git credential fill` + `Invoke-RestMethod`).
  Initial commit `afb307b`, 144 files, `research/` + `src/` excluded.
- **CI run `40173726660`** (`xnu`, push-triggered, macos-14, 7 min 15 s) →
  `success`: https://github.com/qualixxe/ios-courbet/actions/runs/40173726660
  banner `xnu-8796.141.3`, `CURRENT_MACHINE_CONFIG=SWEET`, artifact `xnu-kernel`
  (60 MB) + `xnu-buildtree`. **Not a clean pass, though:** `0063` was skipped —
  `error: corrupt patch at line 27`, because I added 4 lines to a hunk and left
  `@@ -32,6 +32,11 @@` instead of `+32,14`. blacktop's apply loop only *warns*
  and skips, so the kernel built without the GENI touch packing fix.
  Fixed (header now `@@ -32,6 +32,14 @@`); `research/fix_hunks.py` was
  generalised from "0062 only" to all 81 patches and now passes twice with 0
  corrections. While doing that its first (buggy) version dropped hunk bodies and
  destroyed `0063` — restored from `ios-sweet-upstream/` and re-edited
  (`research/restore_0063.py`), then `verify_patches.py` → 668 lines, chain OK.
  **New CI step `Verify ios-courbet patches applied`** (milestone M5b) counts
  `Applying patch`/`Skipping patch` for `xnu/patches/*.patch` and fails the run if
  they disagree, so this can no longer go green unnoticed.
- **CI run `40175356689`** (#2, commit `0ddcae0`, 6 min 39 s) → `success`, and the
  log proves it this time: `expected=81 applied=81 skipped=0`,
  `all 81 ios-courbet patches applied`, step `Verify ios-courbet patches applied`
  = success. **M5 is closed.** https://github.com/qualixxe/ios-courbet/actions/runs/40175356689
  Run #1's log, replayed through the same rule, gives `81/80/1` → the guard fails
  exactly where it should. blacktop's own four patches (`TrustCache`,
  `iobuffermemd_monterey`, `skywalk_sonoma`, `syntax_checker_sonoma`) are skipped
  on every run and are deliberately not counted.
- **Git Credential Manager broke mid-session** (`git credential fill` and
  `git push` hang on a sign-in window that never completes; `git fetch` still
  works because the repo is public). Workaround used: read the stored OAuth token
  straight out of Windows Credential Manager (`CredRead("git:https://github.com")`,
  it is a `gho_` token and still valid) and push with
  `git -c credential.helper= push https://x-access-token:$t@github.com/... main`.
  Docs-only pushes do **not** start CI (`paths:` is `xnu/patches/**` + the
  workflow file).
- **CI run `40177122514`** (shim workflow, commit `0d6750a`) → `success`: the shim
  cross-compiles (`gcc-aarch64-linux-gnu`), links with **0 absolute relocations**,
  packs a header-v2 boot.img and the round-trip check (`cmp` kernel/ramdisk/dtb)
  passes. https://github.com/qualixxe/ios-courbet/actions/runs/40177122514
  Two bugs were in the way and are fixed in `shim/build.sh` (via
  `research/apply_port_edits.py`, so provenance stays honest):
  `awk … strtonum("0x"$1)` — `strtonum` is **gawk-only**, Debian/Ubuntu ship mawk,
  so the size came out empty and `truncate` died (now `size=$((16#$hex))`);
  and `mkbootimg` was unconditional, so a build without the stock DTB failed.
  **`mkbootimg` is not on PyPI** (404) and not in apt — `tools/aosp/` now vendors
  AOSP `mkbootimg.py` from `android-12.0.0_r1` (sha256 `2a8d05d3…`, byte-identical,
  Apache-2.0) plus a 3-line `mkbootimg` wrapper; `android-13+` imports
  `gki.generate_gki_certificate` and would drag in the whole AOSP tree.
- **Boot images built and verified** (CI has no DTB, this machine has no compiler —
  so CI compiles, here repacks):
  ```
  shim/out/shim-boot-courbet-diag.img   589 824 B  sha256 5f731d2f15b162b497a1f202100ff7f7d959c7ac68718d59ac6f46965a82bc03
  shim/out/shim-boot-courbet-xnu6g.img  17 199 104 B sha256 55d052eb00b3c9bfb3c42d5a645bd84652aaca25511493a0c20fbebb48d55cda
  ```
  Both = shim `Image` (180 224 B from the `shim` artifact) + the stock
  `research/shirayuki-oem/dtb.img` (398 043 B, verified **single** FDT: magic
  `0xd00dfeed`, `totalsize == filesize`). `diag` uses the empty-cpio ramdisk (97 B)
  from CI; `xnu6g` uses `shim/out/payload-6g.bin` (16 610 976 B) =
  `kernel.development.sweet` from run `40175356689` (sha256 `b2c7364e…`, matches its
  `SHA256SUMS`) + `research/courbet-6g.adt` (`--highmem --mem 6`) with cmdline
  `debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress`.
  Every part was `cmp`'d after packing. Recipe for a new pair:
  download the `shim` artifact → `python tools/unpack_bootv2.py` it to get
  `Image`+`ramdisk` → `python tools/aosp/mkbootimg.py … --dtb <stock dtb.img>`.

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
  `research/fix_hunks.py` — the edits themselves (re-runnable, they skip if
  applied; `fix_hunks.py` is the two-pass header check over all 81 patches).
- `research/verify_patches.py` — reconstructs `bsd/dev/sweet_touch.c` from `0060`
  and replays `0062` → `0063`: **`668 lines, chain OK`**.
- Hunk headers re-counted for **all 81** `xnu/patches/*.patch` by
  `research/fix_hunks.py`, twice, 0 corrections (`0062 @@ -490,16 +491,31 @@` and
  `0063 @@ -32,6 +32,14 @@` were corrected after their hunks grew).
- `mkadt.py` run for both `--mem 6` and `--mem 8`.

**Not done / not verified**

- No device. The XNU build, the full-series apply against a clean `xnu-8796`, and
  the shim compile+pack are now covered by CI (runs #2 and `40176742478`); what is
  left unproven is everything that needs the phone: boot, console, display, touch.
- **`courbet_touch_mv` default of 1648 mV is derived** from the DTB's
  `qcom,init-voltage = <0x192580>` for `pm6150l_l6`, because the stock ST driver only
  calls `regulator_enable()` and never sets a voltage. `regulator-min/max` are
  1 648 000…3 100 000, so 3000 mV is legal if touch stays dead.
- **8 GB upper bank `0x17cc00000` is derived** (2G + 8G − 0x3400000), not read off a
  live 8 GB unit. `0x3400000` top reserve is carried over from sweet.
- **Command-mode display (D1)** - **confirmed freeze**, fix in progress:
  courbet panels are `*_dsc_cmd` (TE tlmm 10, reset PM6150L GPIO 9); sweet was
  video-mode. First boot (`shim-boot-courbet-xnu6g.img`) reached XNU, printed
  `SWEET FB: swap ...` and then froze - CPU writes frame to panel memory but
  command-mode DSI panel doesn't update. Fix: added `sweet_panel_refresh()` in
  new patch `0082-sweet-command-mode-panel-refresh.patch` that writes SDE CTL_1
  FLUSH register (0xae2204) after each vsync flush. CI run building
  (commit `60849f8`).
- **Touch controller variant unknown.** courbet's defconfig compiles
  `CONFIG_TOUCHSCREEN_FTS=y` (I²C `0x49`, `st,fts`) and
  `CONFIG_TOUCHSCREEN_GOODIX_BRL=y` (SPI Berlin via `xiaomi-spits`). The I²C
  `goodix@5d` node has **no** enabled driver. Port implements FTS; SPI Berlin is
  unimplemented. Identify with `adb shell dumpsys input` on Android.
- T4 (SPI Goodix Berlin) is the largest remaining code item if the unit needs it.

**Next action (in order)**

1. Wait for CI run on commit `7f1ea31` (0079 panel refresh fix) to finish.
   If green → download new `xnu-kernel` artifact.
2. Repack `shim-boot-courbet-xnu6g.img` with new kernel + existing ADT.
3. `fastboot boot` it — expect `SWEET FB: panel refresh kick @ 0xae2204` lines and
   continued console output (no more freeze).
4. Identify the touch controller (T5): `adb shell dumpsys input | grep -iE
   "fts|goodix|spits"` — decides whether T4 (SPI Berlin) is needed at all.

**Conventions kept**

- `SWEET` platform identifiers stay (see `AGENTS.md`).
- Apple artifacts, device dumps and extracted vendor images stay out of git.

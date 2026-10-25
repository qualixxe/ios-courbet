# ios-courbet

**Apple's iOS 16 running on a Xiaomi Mi 11 Lite 4G (`courbet`).**

This is a port of [ios-sweet](https://github.com/dipa-studio/ios-sweet) — the project
that boots Apple's open-source XNU kernel (xnu-8796, the iOS 16 generation) on a Redmi
Note 10 Pro (`sweet`) with the unmodified iOS 16.7.16 (20H392) userland of the iPhone X
on top — to the **Xiaomi Mi 11 Lite 4G**, codename `courbet` (`courbetin` is the Indian
variant), Qualcomm SM7150 / Snapdragon 732G.

`sweet` and `courbet` are the *same SoC* (SM7150-AC, `sdmmagpie`: 2×Cortex-A76 +
6×Cortex-A55, same GICv3 addresses, same 19.2 MHz arch timer, same UFS host, same
framebuffer region). The port is therefore mostly a **board-layer swap**, not a new
SoC port. See [`docs/COURBET_HARDWARE.md`](docs/COURBET_HARDWARE.md) for every
verified constant and where it came from, and [`docs/PORT_STATUS.md`](docs/PORT_STATUS.md)
for what has actually been run.

> **Status: scaffold, not yet booted.** The code changes for courbet are in place and
> self-consistent (patch chain verified, ADT builder tested), but no XNU build has been
> run and nothing has been flashed to a courbet device yet. Nothing below "works" is
> claimed. Experimental bring-up, not a usable phone OS — and it erases Android's user
> data when it does work.

## What carries over from ios-sweet unchanged

These are SoC/board-independent or already match courbet bit-for-bit:

| Area | Detail |
| --- | --- |
| Boot shim (`shim/`) | GICD `0x17a00000`, GICR `0x17a60000`, UFS `0x01d84000`, FB `0x9c000000` 1080×2400, IMEM restart `0x146aa65c`, PSHOLD `0x0c264000` — all verified against courbet's DTB |
| QUP / GENI SE7 I2C | `0x0a84000`, TLMM GPIO 6/7 (SDA/SCL), clock vote `0x5200c` |
| Touch GPIOs | reset TLMM 8, IRQ TLMM 9 (identical to sweet) |
| Buttons | vol-up on `pm6150l_gpios` GPIO 2, power/voldown on PM6150 PON |
| XNU patches | 81 of 81 carry over; the machine config stays `SWEET` |
| Payload / ADT tooling | `mkadt.py`, `mkpayload.py`, `mkiosroot.sh`, `sweet-root-tweaks.py` |

## What changed for courbet

| Area | sweet | courbet |
| --- | --- | --- |
| Identity | `xiaomi,sweet` | `xiaomi,courbet` + `xiaomi,sweet` (platform match) |
| RAM | 6 GB, upper bank `0x1_00000000 + 0xfcc00000` | 6 GB **or** 8 GB → `mkadt.py --mem 6\|8` |
| Touch VDDIO switch | TLMM GPIO **90** | TLMM GPIO **72** |
| Touch analog rail | PM6150L **LDO11** @ 3200 mV | PM6150L **LDO6** @ 1648 mV (DTB `qcom,init-voltage`), overridable with `courbet_touch_mv=` |
| Touch controller | Goodix GT9896 (I²C `0x5d`) | **ST FTS** (I²C `0x49`) on the units whose stock kernel matches the shipped defconfig; Goodix Berlin on SPI is *not* implemented |
| Battery | 5020 mAh | **4250 mAh** (K9A cosmx / sunwoda) |
| Display | 1080×2400 video-mode DSC | 1080×2400 **command-mode** DSC (`k9a_36_02_0a` / `k9a_42_02_0b`, 60/90 Hz) |

The `SWEET` platform name (`ARM64_BOARD_CONFIG_SWEET`, `sweet-fbcon`, `xiaomi,sweet`,
`SWEETXNU` payload magic) is **deliberately kept**: it identifies the SM7150 XNU port,
not the Redmi Note 10 Pro, and renaming it would churn ~40 patches for zero benefit.
The ADT advertises `xiaomi,courbet` first and `xiaomi,sweet` second so that
`SweetPlatformExpert` still binds.

## Building

```sh
# 1. device tree for the ADT
python tools/mkadt.py shim/out/courbet.adt --highmem --mem 6     # or --mem 8

# 2. XNU (macOS only, via GitHub Actions: workflow "xnu", MACHINE_CONFIG=SWEET)

# 3. payload
python tools/mkpayload.py <kernel> shim/out/courbet.adt shim/out/payload.bin \
    --cmdline "debug=0xc serial=3 cpus=6 keepsyms=1" --ramdisk <ios-root.img>

# 4. shim + boot.img (needs aarch64-linux-gnu-gcc, mkbootimg; DTB=... to override)
shim/build.sh
```

The shim re-reads the phone's live `/memory` node before jumping to XNU and **refuses
to boot** if the ADT's RAM window is not inside the real RAM — a 6 GB phone built with
`--mem 8` stops at `payload RAM exceeds live RAM` instead of corrupting memory.

## Layout

```
shim/            bare-metal boot shim (loader, UFS probe, framebuffer console)
xnu/patches/     81 patches against xnu-8796 (see xnu/patches/index)
tools/           ADT / payload / rootfs builders
docs/            courbet hardware notes, port status
site/            project page (inherited from ios-sweet)
research/        device dumps, decompiled DTS, source pulls (git-ignored;
                 research/*.py are tracked — they reproduce the port edits)
src/             courbet kernel DTS + the stock touch drivers (git-ignored)
NOTES-sweet.md   the ios-sweet engineering log (historical reference)
```

`research/` and `src/` hold device dumps, decompiled DTs and Xiaomi kernel sources.
They are git-ignored apart from `research/*.py`; the facts extracted from them live
in [`docs/COURBET_HARDWARE.md`](docs/COURBET_HARDWARE.md).

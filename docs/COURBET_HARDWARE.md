# courbet hardware facts

Everything below was read out of **courbet's own device tree** and **Xiaomi's
`courbet-r-oss` kernel source**, not from third-party specs sheets.

Sources:

| Source | Path | Note |
| --- | --- | --- |
| Stock base DTB | `research/courbet.dts` (decompiled) | byte-identical to the `dtb.img` inside the supplied `shirayuki-oem.zip` AnyKernel3 package, SHA256 `1A9A51C616494D9D…` |
| Stock DTBO | `research/courbet_dtbo.dts` (decompiled) | SHA256 `752742EC71647681…` |
| Board DTSI | `src/courbet-sdmmagpie.dtsi` | MiCode `courbet-r-oss` branch, authoritative for touch/keys/regulators/battery |
| Pinctrl DTSI | `src/courbet-sdmmagpie-pinctrl.dtsi` | QUP SE7 pin mux |
| Display DTSI | `src/sdmmagpie-sde-display.dtsi` | panel definitions |
| Stock touch drivers | `src/fts.c`, `src/goodix.c` | what the shipping kernel actually binds |
| Stock defconfig | `arch/arm64/configs/vendor/courbet_user_defconfig` | which touch driver is compiled in |

`research/` and `src/` are git-ignored (device dumps and third-party sources).

---

## 1. SoC — identical to sweet

`courbet` and `sweet` are both SM7150-AC (`sdmmagpie`). Every address the shim and the
ADT depend on was re-verified against the courbet DTB:

| Item | courbet | sweet | Match |
| --- | --- | --- | --- |
| GICv3 distributor | `0x17a00000`, size `0x10000` | same | yes |
| GICv3 redistributor | `0x17a60000`, stride `0x20000` | same | yes |
| Arch timer | `clock-frequency = 0x124f800` (19.2 MHz), virtual timer PPI 3 / `VTIMER_INTID 19` | same | yes |
| UFS host | `ufshc@1d84000`, `reg = <0x1d84000 0x3000 0x1d90000 0x8000>` | same | yes |
| QUP SE7 I²C | `i2c@0xa84000`, `qcom,i2c-geni`, IRQ `0x162` | same | yes |
| PSHOLD | `0x0c264000` | same | yes |
| IMEM restart reason | `0x146aa65c` | same | yes |
| `cont_splash_region` | `0x9c000000`, size `0x1700000` | same | yes |
| `dfps_data_region` | `0x9d700000`, size `0x100000` | same | yes |

**Conclusion:** `shim/` needs no SoC changes. Verified, not assumed.

## 2. QUP SE7 I²C — identical to sweet

From `research/courbet.dts`:

```
qupv3_se7_i2c_active {
    mux { pins = "gpio6", "gpio7"; function = ...; };
}
i2c@0xa84000 { compatible = "qcom,i2c-geni"; reg = <0xa84000 0x4000>; }
```

sweet's touch driver already uses `TOUCH_SE_PA 0x00a84000`, `TOUCH_GCC_PA 0x00100000`,
`TOUCH_GCC_VOTE 0x5200c` and TLMM GPIO 6/7 — unchanged. (sweet's own comment said
"qup11"; it was always SE7. The patches now say `SE7`.)

## 3. Touch — the one real functional difference

### Pins (both units, verified)

| Signal | courbet | sweet |
| --- | --- | --- |
| I²C SDA/SCL | TLMM **6/7** | TLMM 6/7 |
| Reset | TLMM **8** (`fts,reset-gpio = <&tlmm 8>`, `goodix,reset-gpio = <&tlmm 8>`) | TLMM 8 |
| IRQ | TLMM **9** (`interrupts = <9 …>`) | TLMM 9 |
| VDDIO enable (fixed reg `touch_vddio_vreg`, name `disp_vddio_vreg`) | TLMM **72** | TLMM **90** ← changed |
| Analog rail | `pm6150l_l6` → `avdd` (FTS) / `vtouch` (Goodix) | `pm6150l_l11` ← changed |
| SPI variant rail (unused here) | `pm6150l_l11` (`pmavdd` of `xiaomi-spits`) | — |

### Regulator values (from the DTB, `qcom,pm6150l-regulators`)

| Rail | min | max | `qcom,init-voltage` | mode |
| --- | --- | --- | --- | --- |
| `pm6150l_l6` | 1 648 000 µV | 3 100 000 µV | **1 648 000 µV** | LPM (2) |
| `pm6150l_l11` (sweet's) | 2 950 000 µV | 3 400 000 µV | 2 950 000 µV | LPM (2) |

The stock ST FTS driver only calls `regulator_enable()`; it never
`regulator_set_voltage()`. So the rail runs at the DTB's initial value **1648 mV**.
`sweet_rpmh_vreg_enable()` therefore votes `ldoc6` at **1648 mV**, overridable at boot
with `courbet_touch_mv=` (window 1600…3400) in case the hardware turns out to need
2.9–3.0 V.

> ⚠ **Unverified on hardware.** If the touch panel stays dead but the kernel logs
> `SWEET TOUCH: LDO6 RPMh enable complete`, try
> `courbet_touch_mv=3000` first.

### Which controller does courbet use?

courbet's DT enables **three** touch nodes at once (Xiaomi ships all of them and lets
the kernel probe):

1. `fts@49`, `compatible = "st,fts"`, I²C `0x49` on SE7 — **`CONFIG_TOUCHSCREEN_FTS=y`**
2. `goodix@5d`, `compatible = "goodix,gt9886"`, I²C `0x5d` — **no enabled driver**
   (`CONFIG_TOUCHSCREEN_GOODIX_GTX8` is commented out, mainline `goodix.c` does not
   list `gt9886` in its `of_device_id` table)
3. `xiaomi-spits@0`, SPI on QUP SE4 — **`CONFIG_TOUCHSCREEN_GOODIX_BRL=y`** (Berlin,
   `depends on SPI_MASTER`) and `CONFIG_TOUCHSCREEN_FTS=y` (`focaltech_spi`)

So on a stock courbet the touch is either **ST FTS over I²C SE7** or **Goodix Berlin
over SPI**. The port implements the FTS path (it is the one whose driver the defconfig
actually compiles, and its protocol already matches sweet's `TOUCH_FTS` branch:
chip-id registers `0xa3`/`0x9f` → `0x54:0x52`).

**To identify your unit**, boot Android and run:

```
adb shell dumpsys input | grep -iE "fts|goodix|focaltech|touchscreen"
adb shell 'zcat /proc/config.gz 2>/dev/null | grep -E "GOODIX|FTS"'
```

- `st,fts` / `fts` in the device list → supported now.
- `goodix` + `spits` → SPI Berlin part; **needs a new SPI GENI driver**, tracked in
  `docs/PORT_STATUS.md` as milestone T3.

The patched `0063` probe still accepts a Goodix PID at `0x4022` (`9896`) but that path
will not match on a stock courbet; it is kept for modified units.

## 4. Display — command mode, the main bring-up risk

From `src/sdmmagpie-sde-display.dtsi` and the DTBO:

| | courbet | sweet |
| --- | --- | --- |
| Panel | `dsi_k9a_36_02_0a_mp_dsc_cmd` / `dsi_k9a_42_02_0b_mp_dsc_cmd` | video-mode DSC |
| Mode | **command mode** (TE-driven) | video mode |
| Resolution | 1080 × 2400 (`0x438` × `0x960`) | same |
| Refresh | 60 Hz (`0x3c`) / 90 Hz (`0x5a`) | up to 120 Hz |
| TE GPIO | tlmm **10** | — |
| Panel reset | PM6150L GPIO **9** | — |

The boot shim does not touch the display: it reuses whatever ABL/UEFI left on the
`cont_splash_region` (`0x9c000000`), and XNU keeps doing the same (`0010`, `0012`).
The framebuffer address, stride and size are already correct for courbet.

> ⚠ **Risk:** on a *command-mode* panel the panel does not refresh on its own; it
> refreshes when the DSI controller is asked to. Whether ABL leaves the panel in a
> self-refreshing state (or whether XNU's framebuffer writes get picked up) has **not**
> been observed on courbet. Sweet's video-mode panel always worked. If courbet shows a
> frozen splash while the kernel runs, the fix is a DSI kick — see
> `docs/PORT_STATUS.md` milestone D1.

Panel/refresh rate is selected at runtime by panel-ID detection; the stock boot.img
cmdline carries no `msm_drm.dsi_display0`, so no boot-arg is required for the panel.

## 5. Buttons

The DTBO's `fragment@47/48`:

```
key_vol_up { pins = "gpio2"; function = "normal"; input-enable; bias-pull-up; }
gpio_keys { vol_up { gpios = <0xffffffff 0x02 0x01>; linux,code = <0x73>; } }
```

`0xffffffff` is the `pm6150l_gpios` fixup → **vol-up = PM6150L GPIO 2**, exactly like
sweet (`KEYS_GPIO_RT 0xc110`, "PM6150L SID 4, not PM6150 SID 0"). Power and vol-down
stay on PM6150 PON (`0xc110` lane). **No change needed.**

## 6. Battery and charging

From `src/courbet-sdmmagpie.dtsi`:

- `qcom,battery-data` includes `qg-batterydata-K9A-cosmx-4250mah.dtsi` and
  `qg-batterydata-K9A-sunwoda-4250mah.dtsi` → **4250 mAh**, two cell vendors
  (sweet: 5020 mAh — the patches now say 4250).
- Charge pump `bq25970-standalone@66`, `compatible = "ti,bq2597x-standalone"`.
- `qcom,fv-max-uv = <4480000>`, `qcom,usb-icl-ua = <3000000>`,
  `qcom,fcc-max-ua = <6000000>`, `qcom,auto-recharge-soc = <99>`.
- Fuel gauge: PM6150 QG (same PMIC lane sweet reads read-only through
  `sweet_spmi.c` / `SweetBattery.cpp`).

## 7. Memory map — the reason `--mem` exists

courbet ships in 6 GB and 8 GB. ABL's live FDT memory node is
`<0x80000000 2G>, <0x100000000 <bank>>`, with the top `0x3400000` reserved on both
variants (same as sweet), so:

| Variant | Upper bank size | `mkadt.py` |
| --- | --- | --- |
| 6 GB | `0xfcc00000` | `--mem 6` (default) |
| 8 GB | `0x17cc00000` | `--mem 8` |

Low bank carve-outs end at `0x8ab00000` (`removed_region@86200000` size
`0x4900000`, `smcinvoke@86d00000` size `0x3e00000`), which is why the kernel runs in
the upper bank only.

> ⚠ The `0x3400000` top reserve and the 8 GB upper-bank size are **derived**, not read
> off a live 8 GB phone. The shim's live-FDT check (`payload RAM exceeds live RAM`)
> converts a wrong guess into a clean refusal instead of memory corruption. Re-derive
> both from `fastboot`/`dmesg` on an 8 GB unit before shipping a `--mem 8` payload.

## 8. What was deliberately *not* changed

- The `SWEET` machine config, `xiaomi,sweet` platform match, `sweet-fbcon`,
  `sweet-io`, `SWEETXNU` payload magic, `sweet_*` tool names — platform identifiers
  for the SM7150 XNU port, not the Redmi. Renaming them touches ~40 patches.
- `xnu/patches/0004` machine config, `0016` platform expert, `0059` identity,
  `0061` display size (iPhone X 1125×2436 presentation) — device-independent.
- The framebuffer/console `1080 × 2400` and FB base — already correct.

#!/usr/bin/env python3
"""courbet: move the touch VDDIO switch and rail from sweet's values to courbet's.

sweet: TLMM GPIO90 VDDIO switch, PM6150L LDO11 @3.2 V.
courbet: TLMM GPIO72 VDDIO switch, PM6150L LDO6 (DTB init 1.648 V).
Both use SE7 I2C (0xa84000), TLMM GPIO6/7 SDA/SCL, reset GPIO8, IRQ GPIO9.
"""
import sys


def edit(path, pairs):
    raw = open(path, 'r', encoding='utf-8', newline='').read()
    crlf = '\r\n' in raw
    text = raw.replace('\r\n', '\n')
    for old, new in pairs:
        if old not in text:
            if new in text:
                print(f'  skip (already): {path}: {old[:50]!r}')
                continue
            raise SystemExit(f'{path}: anchor not found:\n{old[:160]!r}')
        text = text.replace(old, new, 1)
    if crlf:
        text = text.replace('\n', '\r\n')
    open(path, 'w', encoding='utf-8', newline='').write(text)
    print(f'patched {path}')


# --- 0060: the driver file created here must already use courbet's GPIO72.
edit('xnu/patches/0060-sweet-keys-touch-drivers.patch', [
    ('+	printf("SWEET TOUCH: TLMM reset=%#x irq=%#x vdd90=%#x; L11C must be powered by firmware\\n",',
     '+	printf("SWEET TOUCH: TLMM reset=%#x irq=%#x vdd72=%#x; LDO6 must be powered by firmware\\n",'),
    ('+	    touch_rd(st.gpio, TOUCH_GPIO_IO(90)));',
     '+	    touch_rd(st.gpio, TOUCH_GPIO_IO(72)));'),
    ('+	touch_gpio(90, 0, 0, 0, true); /* board digital power enable, high */',
     '+	touch_gpio(72, 0, 0, 0, true); /* board VDDIO enable, high */'),
])

# --- 0062: pre-image lines must match 0060's output, post-image uses courbet.
edit('xnu/patches/0062-sweet-touch-power-battery.patch', [
    ('-\tprintf("SWEET TOUCH: TLMM reset=%#x irq=%#x vdd90=%#x; L11C must be powered by firmware\\n",',
     '-\tprintf("SWEET TOUCH: TLMM reset=%#x irq=%#x vdd72=%#x; LDO6 must be powered by firmware\\n",'),
    (' \t    touch_rd(st.gpio, TOUCH_GPIO_IO(90)));',
     ' \t    touch_rd(st.gpio, TOUCH_GPIO_IO(72)));'),
    ('-\ttouch_gpio(90, 0, 0, 0, true); /* board digital power enable, high */',
     '-\ttouch_gpio(72, 0, 0, 0, true); /* board VDDIO enable, high */'),
    ('+\tint power_error = sweet_rpmh_vreg_enable("ldoc11", 3200);\n'
     '+\tif (power_error) {\n'
     '+\t\tprintf("SWEET TOUCH: L11C RPMh enable failed %d; probes skipped\\n", power_error);',
     '+\t/* courbet: the I2C touch analog rail is PM6150L LDO6; the 1.8 V VDDIO\n'
     '+\t * switch is TLMM GPIO72.  The DTB initialises LDO6 to 1648 mV and the\n'
     '+\t * stock ST driver only enables it, so match that unless overridden. */\n'
     '+\tint touch_mv = 1648;\n'
     '+\t(void)PE_parse_boot_argn("courbet_touch_mv", &touch_mv, sizeof(touch_mv));\n'
     '+\tint power_error = sweet_rpmh_vreg_enable("ldoc6", (unsigned)touch_mv);\n'
     '+\tif (power_error) {\n'
     '+\t\tprintf("SWEET TOUCH: LDO6 RPMh enable failed %d; probes skipped\\n", power_error);'),
    ('+\ttouch_gpio(90, 0, 0, 0, true, true); /* board digital power enable */',
     '+\ttouch_gpio(72, 0, 0, 0, true, true); /* board VDDIO enable (courbet tlmm 72) */'),
    ('+ * SWEET PM6150L L11C bring-up; see report.md for DT and source evidence.',
     '+ * SWEET PM6150L LDO6 touch-rail bring-up; see report.md for DT/source evidence.'),
    ('+\t\t\t\tprintf("SWEET RPMH: conflicting inherited L11C request in TCS%u\\n", t);',
     '+\t\t\t\tprintf("SWEET RPMH: conflicting inherited LDO6 request in TCS%u\\n", t);'),
    ('+\tprintf("SWEET RPMH: L11C ACTIVE vote complete (rail voltage requires hardware verification)\\n");',
     '+\tprintf("SWEET RPMH: LDO6 ACTIVE vote complete (mv=%u, verify on hardware)\\n", mv);'),
    ('+\tif (!res || strcmp(res, "ldoc11") || mv < 2950 || mv > 3400) {\n'
     '+\t\tprintf("SWEET RPMH: expected ldoc11 and 2950..3400 mV\\n");',
     '+\tif (!res || strcmp(res, "ldoc6") || mv < 1600 || mv > 3400) {\n'
     '+\t\tprintf("SWEET RPMH: expected ldoc6 and 1600..3400 mV\\n");'),
])

# Battery: courbet uses 4250 mAh K9A packs (cosmx/sunwoda), not sweet's 5020.
p = 'xnu/patches/0062-sweet-touch-power-battery.patch'
raw = open(p, 'r', encoding='utf-8', newline='').read()
n = raw.count('5020')
open(p, 'w', encoding='utf-8', newline='').write(raw.replace('5020', '4250'))
print(f'battery: {n} x 5020 -> 4250')

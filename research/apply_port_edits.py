#!/usr/bin/env python3
"""Apply the courbet device-layer edits to the ios-sweet-derived tree.

Kept in research/ for provenance: it records every textual change that is not
a whole-file rewrite (README, docs, NOTES) and is idempotent-safe in the sense
that it refuses to run twice (the anchors disappear after the first run).
"""
import sys

ROOT = '.'


def edit(path, pairs):
    full = f'{ROOT}/{path}'
    raw = open(full, 'r', encoding='utf-8', newline='').read()
    crlf = '\r\n' in raw
    text = raw.replace('\r\n', '\n')
    for old, new in pairs:
        if new in text:
            continue
        if old not in text:
            raise SystemExit(f'{path}: anchor not found:\n{old[:160]!r}')
        text = text.replace(old, new, 1)
    if crlf:
        text = text.replace('\n', '\r\n')
    open(full, 'w', encoding='utf-8', newline='').write(text)
    print(f'patched {path}')


# ---------------------------------------------------------------- shim/fdt.h
edit('shim/fdt.h', [(
    "/* Read a u32/u64 (cell-size agnostic) property of /chosen. Returns 0 if absent. */\n"
    "int fdt_chosen_u64(uintptr_t fdt, const char *prop, uint64_t *out);\n",
    "/* Read a u32/u64 (cell-size agnostic) property of /chosen. Returns 0 if absent. */\n"
    "int fdt_chosen_u64(uintptr_t fdt, const char *prop, uint64_t *out);\n"
    "\n"
    "/* Highest address covered by the live /memory nodes. Returns 0 if absent. */\n"
    "int fdt_memory_top(uintptr_t fdt, uint64_t *top);\n",
)])

# ---------------------------------------------------------------- shim/fdt.c
MEMORY_TOP = r'''
/*
 * Highest address covered by the live /memory nodes, for the RAM-window guard
 * in loader.c.  ABL writes the real banks here (the base DTB's /memory is a
 * placeholder): 2G at 0x80000000 plus one bank at 0x1_00000000 whose size is
 * 0xfcc00000 on a 6 GB courbet and 0x17cc00000 on an 8 GB one.  SM7150 uses
 * #address-cells = #size-cells = 2, so every entry is four big-endian cells.
 */
int fdt_memory_top(uintptr_t fdt, uint64_t *top)
{
	if (!fdt || be32(fdt) != FDT_MAGIC)
		return 0;
	uintptr_t p = fdt + be32(fdt + 8);		/* off_dt_struct */
	uintptr_t strings = fdt + be32(fdt + 12);	/* off_dt_strings */
	int depth = 0, mem_depth = 0;
	uint64_t best = 0;

	for (;;) {
		uint32_t tok = be32(p);
		p += 4;
		switch (tok) {
		case FDT_BEGIN_NODE: {
			const char *name = (const char *)p;
			depth++;
			if (depth == 2 && name[0] == 'm' && name[1] == 'e' &&
			    name[2] == 'm' && name[3] == 'o' && name[4] == 'r' &&
			    name[5] == 'y' && (name[6] == '\0' || name[6] == '@'))
				mem_depth = depth;
			p = align4(skip_str(p));
			break;
		}
		case FDT_END_NODE:
			if (depth == mem_depth)
				mem_depth = 0;
			depth--;
			break;
		case FDT_PROP: {
			uint32_t len = be32(p), nameoff = be32(p + 4);
			uintptr_t val = p + 8;
			if (mem_depth && len >= 16 && (len & 15u) == 0 &&
			    streq((const char *)(strings + nameoff), "reg")) {
				for (uint32_t o = 0; o < len; o += 16) {
					uint64_t base = (uint64_t)be32(val + o) << 32 |
					    be32(val + o + 4);
					uint64_t size = (uint64_t)be32(val + o + 8) << 32 |
					    be32(val + o + 12);
					if (base + size > best)
						best = base + size;
				}
			}
			p = align4(val + len);
			break;
		}
		case FDT_NOP:
			break;
		default:	/* FDT_END or garbage */
			if (!best)
				return 0;
			*top = best;
			return 1;
		}
	}
}
'''
raw = open('shim/fdt.c', 'r', encoding='utf-8', newline='').read()
crlf = '\r\n' in raw
text = raw.replace('\r\n', '\n')
if 'fdt_memory_top' not in text:
    text = text.rstrip('\n') + '\n' + MEMORY_TOP
    if crlf:
        text = text.replace('\n', '\r\n')
    open('shim/fdt.c', 'w', encoding='utf-8', newline='').write(text)
    print('patched shim/fdt.c')

# ---------------------------------------------------------------- shim/loader.c
# The live RAM top is read and printed *before* the payload is parsed: the
# diagnostic image (no payload) must still report it, because that line is what
# settles `mkadt --mem 6|8` on a new unit.
edit('shim/loader.c', [
    (' * Milestone 4: act as iBoot for xnu.\n',
     ' * Milestone 4: act as iBoot for xnu on courbet.\n'),
    ("\tcon_hex2(\"INITRD\", \"lo=\", rd_start, \"hi=\", rd_end);\n",
     "\tcon_hex2(\"INITRD\", \"lo=\", rd_start, \"hi=\", rd_end);\n"
     "\n"
     "\t/* Live RAM top from the FDT ABL handed us. */\n"
     "\tuint64_t ram_top = 0;\n"
     "\tint have_top = fdt_memory_top(dtb, &ram_top);\n"
     "\tif (have_top)\n"
     "\t\tcon_hex(\"RAMTOP\", ram_top);\n"
     "\telse\n"
     "\t\tcon_str(\"RAMTOP\", \"no /memory node in the live FDT\");\n"),
    ("\tcon_hex(\"ENTRY\", p->entry_va);\n",
     "\tcon_hex(\"ENTRY\", p->entry_va);\n"
     "\n"
     "\t/* The ADT's RAM window must exist in the live FDT: a 6 GB phone booted\n"
     "\t * with an 8 GB ADT (or vice versa) would corrupt memory silently. */\n"
     "\tif (have_top && p->phys_base + p->mem_size + 0x100000ULL > ram_top)\n"
     "\t\treturn \"payload RAM exceeds live RAM (mkadt --mem 6|8)\";\n"),
])

# ---------------------------------------------------------------- shim/shim.c
edit('shim/shim.c', [
    ('con_str("SHIM", "sweet milestone 4: xnu loader");',
     'con_str("SHIM", "courbet milestone 4: xnu loader");'),
    ('con_str("SHIM", "sweet milestone 3");',
     'con_str("SHIM", "courbet milestone 3");'),
])

# ---------------------------------------------------------------- shim/build.sh
edit('shim/build.sh', [
    ('# Build the shim and wrap it in a boot.img v2 that mirrors the stock PixelOS header.',
     '# Build the shim and wrap it in a boot.img v2 that mirrors the stock PixelOS header.\n'
     '# DTB=/path/to/dtb overrides the stock courbet DTB (default below).'),
    # mawk (Debian/Ubuntu default) has no strtonum(); bash understands 16#hex.
    ('size=$(aarch64-linux-gnu-nm out/shim.elf | awk \'$3=="_end"{print strtonum("0x"$1)}\')\n'
     'truncate -s "$size" out/Image',
     'size_hex=$(aarch64-linux-gnu-nm out/shim.elf | awk \'$3=="_end"{print $1}\')\n'
     'size=$((16#$size_hex))\n'
     'truncate -s "$size" out/Image'),
    # The stock DTB is a device dump and is not in git: a compile-only run (CI)
    # has nothing to pack, and that must not be an error.
    ('mkbootimg --header_version 2 --kernel out/Image --ramdisk out/ramdisk.bin \\\n'
     '\t--dtb ../dtb/boot_unpacked/dtb --base 0 --kernel_offset 0x8000 --ramdisk_offset 0x1000000 \\\n'
     '\t--tags_offset 0x100 --dtb_offset 0x1f00000 --pagesize 4096 \\\n'
     '\t--os_version 17.0.0 --os_patch_level 2035-06 \\\n'
     '\t--cmdline "console=null" -o out/shim-boot.img\n'
     '# Host render of the console layout.\n'
     'gcc -O1 -Wall -o out/host_test console.c host_test.c && ./out/host_test\n'
     'ls -l out/Image out/shim-boot.img\n',
     'DTB=${DTB:-../dtb/boot_unpacked/dtb}\n'
     'if [ -f "$DTB" ] && command -v mkbootimg >/dev/null 2>&1; then\n'
     '\tmkbootimg --header_version 2 --kernel out/Image --ramdisk out/ramdisk.bin \\\n'
     '\t\t--dtb "$DTB" --base 0 --kernel_offset 0x8000 --ramdisk_offset 0x1000000 \\\n'
     '\t\t--tags_offset 0x100 --dtb_offset 0x1f00000 --pagesize 4096 \\\n'
     '\t\t--os_version 17.0.0 --os_patch_level 2035-06 \\\n'
     '\t\t--cmdline "console=null" -o out/shim-boot.img\n'
     'else\n'
     '\techo "note: no boot.img (DTB=$DTB missing or mkbootimg not installed)" >&2\n'
     'fi\n'
     '# Host render of the console layout.\n'
     'gcc -O1 -Wall -o out/host_test console.c host_test.c && ./out/host_test\n'
     'ls -l out/Image out/shim-boot.img 2>/dev/null || ls -l out/Image\n'),
])

# ---------------------------------------------------------------- tools/mkpayload.py
edit('tools/mkpayload.py', [(
    '"""Pack an xnu kernel Mach-O + ADT into the payload the sweet shim boots.',
    '"""Pack an xnu kernel Mach-O + ADT into the payload the courbet shim boots.',
)])

# ---------------------------------------------------------------- mkadt comments
edit('tools/mkadt.py', [
    ('    # SWEET SMP: all eight cores in physical-core order (0-5 Cortex-A55,',
     '    # courbet/SM7150 SMP: all eight cores in physical-core order (0-5 Cortex-A55,'),
    ('    # and uses cpus=N to select an initial prefix (N <= 8).',
     '    # and uses cpus=N to select an initial prefix (N <= 8).'),
])

# ---------------------------------------------------------------- 0062 touch rail + battery
edit('xnu/patches/0062-sweet-touch-power-battery.patch', [
    ('+ * Requires ABL-loaded GENI I2C firmware; votes L11C through sweet_rpmh.c.',
     '+ * Requires ABL-loaded GENI I2C firmware; votes PM6150L LDO6 through sweet_rpmh.c.'),
    ('+	printf("SWEET TOUCH: TLMM reset=%#x irq=%#x vdd90=%#x; voting L11C through RPMh\\n",',
     '+	printf("SWEET TOUCH: TLMM reset=%#x irq=%#x vdd72=%#x; voting LDO6 through RPMh\\n",'),
    # The printf's third argument (TOUCH_GPIO_IO(n)) is a *context* line in this
    # hunk, shared with the pre-image: it is edited in fix_touch_rails.py together
    # with 0060, or 0062 stops applying.
    ('+	int power_error = sweet_rpmh_vreg_enable("ldoc11", 3200);\n'
     '+	if (power_error) {\n'
     '+		printf("SWEET TOUCH: L11C RPMh enable failed %d; probes skipped\\n", power_error);',
     '+	/* courbet: the I2C touch analog rail is PM6150L LDO6; the 1.8 V VDDIO\n'
     '+	 * switch is TLMM GPIO72.  The DTB initialises LDO6 to 1648 mV and the\n'
     '+	 * stock ST driver only enables it, so match that unless overridden. */\n'
     '+	int touch_mv = 1648;\n'
     '+	(void)PE_parse_boot_argn("courbet_touch_mv", &touch_mv, sizeof(touch_mv));\n'
     '+	int power_error = sweet_rpmh_vreg_enable("ldoc6", (unsigned)touch_mv);\n'
     '+	if (power_error) {\n'
     '+		printf("SWEET TOUCH: LDO6 RPMh enable failed %d; probes skipped\\n", power_error);'),
    ('+	touch_gpio(90, 0, 0, 0, true, true); /* board digital power enable */',
     '+	touch_gpio(72, 0, 0, 0, true, true); /* board VDDIO enable (courbet tlmm 72) */'),
    ('+ * SWEET PM6150L L11C bring-up; see report.md for DT and source evidence.',
     '+ * SWEET PM6150L LDO6 touch-rail bring-up; see report.md for DT/source evidence.'),
    ('+				printf("SWEET RPMH: conflicting inherited L11C request in TCS%u\\n", t);',
     '+				printf("SWEET RPMH: conflicting inherited LDO6 request in TCS%u\\n", t);'),
    ('+	printf("SWEET RPMH: L11C ACTIVE vote complete (rail voltage requires hardware verification)\\n");',
     '+	printf("SWEET RPMH: LDO6 ACTIVE vote complete (mv=%u, verify on hardware)\\n", mv);'),
    ('+	if (!res || strcmp(res, "ldoc11") || mv < 2950 || mv > 3400) {\n'
     '+		printf("SWEET RPMH: expected ldoc11 and 2950..3400 mV\\n");',
     '+	if (!res || strcmp(res, "ldoc6") || mv < 1600 || mv > 3400) {\n'
     '+		printf("SWEET RPMH: expected ldoc6 and 1600..3400 mV\\n");'),
])

# Battery: courbet is 4250 mAh (K9A cosmx/sunwoda packs), not sweet's 5020.
raw = open('xnu/patches/0062-sweet-touch-power-battery.patch', 'r',
           encoding='utf-8', newline='').read()
n = raw.count('5020')
raw = raw.replace('5020', '4250')
open('xnu/patches/0062-sweet-touch-power-battery.patch', 'w',
     encoding='utf-8', newline='').write(raw)
print(f'patched 0062 battery: {n} x 5020 -> 4250')

# ------------------------------------------------------- 0063 context + note
# 0062 rewrites this comment in 0063's context, otherwise the hunk misses.
edit('xnu/patches/0063-sweet-goodix-geni-packing.patch', [(
    ' * Requires ABL-loaded GENI I2C firmware; votes L11C through sweet_rpmh.c.',
    ' * Requires ABL-loaded GENI I2C firmware; votes PM6150L LDO6 through sweet_rpmh.c.',
)])

edit('xnu/patches/0063-sweet-goodix-geni-packing.patch', [(
    '+/* GT9896 is Yellowstone in Xiaomi sweet-r-oss, not the Berlin protocol. */',
    '+/* GT9896 is Yellowstone in Xiaomi sweet-r-oss, not the Berlin protocol.\n'
    '+ * courbet ships either ST FTS (I2C 0x49, the path used here) or a Goodix\n'
    '+ * Berlin part on SPI; the stock courbet kernel enables no I2C Goodix\n'
    '+ * driver, so the 0x5d probe below only ever matches on modified units. */',
)])

print('done')

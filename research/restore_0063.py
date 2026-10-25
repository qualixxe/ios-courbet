#!/usr/bin/env python3
"""0063 was destroyed by the first (buggy) fix_hunks.py pass: restore it from the
read-only upstream clone and re-apply the two courbet edits + the header fix."""
import shutil
import sys

UP = '../ios-sweet-upstream/xnu/patches/0063-sweet-goodix-geni-packing.patch'
DST = 'xnu/patches/0063-sweet-goodix-geni-packing.patch'

shutil.copyfile(UP, DST)
print(f'restored {DST} from upstream')

raw = open(DST, 'r', encoding='utf-8', newline='').read()
crlf = '\r\n' in raw
t = raw.replace('\r\n', '\n')

pairs = [
    # 0062 changed this line, so 0063's context must follow it
    (' * Requires ABL-loaded GENI I2C firmware; votes L11C through sweet_rpmh.c.',
     ' * Requires ABL-loaded GENI I2C firmware; votes PM6150L LDO6 through sweet_rpmh.c.'),
    # courbet note on the Goodix PID probe
    ('+/* GT9896 is Yellowstone in Xiaomi sweet-r-oss, not the Berlin protocol. */',
     '+/* GT9896 is Yellowstone in Xiaomi sweet-r-oss, not the Berlin protocol.\n'
     '+ * courbet ships either ST FTS (I2C 0x49, the path used here) or a Goodix\n'
     '+ * Berlin part on SPI; the stock courbet kernel enables no I2C Goodix\n'
     '+ * driver, so the 0x5d probe below only ever matches on modified units. */'),
    # the added comment grew the hunk by 3 lines (4 added over 1 replaced)
    ('@@ -32,6 +32,11 @@', '@@ -32,6 +32,14 @@'),
]

for old, new in pairs:
    if new in t and old not in t:
        print(f'  already applied: {old[:60]!r}')
        continue
    if old not in t:
        raise SystemExit(f'anchor not found: {old[:80]!r}')
    t = t.replace(old, new, 1)
    print(f'  applied: {old[:60]!r}')

if crlf:
    t = t.replace('\n', '\r\n')
open(DST, 'w', encoding='utf-8', newline='').write(t)
print('written')

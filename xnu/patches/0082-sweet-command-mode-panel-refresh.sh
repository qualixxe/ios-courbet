#!/bin/bash
# Add command-mode panel refresh kick to SweetFramebuffer.cpp
# The courbet panel is command-mode (DSC_CMD) and needs an explicit DSI refresh
# after each CPU flush to panel memory. We write to the SDE CTL_1 FLUSH register
# (MDSS base 0xae00000 + CTL_1 offset 0x2200 + FLUSH 0x4 = 0xae2204).
set -euo pipefail

# The build script runs us from ${WORK_DIR}/xnu, so the source is relative.
FILE="iokit/Kernel/arm/SweetFramebuffer.cpp"

python3 - "$FILE" <<'PY'
import sys
path = sys.argv[1]
s = open(path, 'r').read()
old = '\t\tfb->present(rec);\n\t\tIOFreeData(rec, SWEET_FB_SWAP_REC_SIZE);'
new = '\t\tfb->present(rec);\n\t\t/* command-mode panel needs a kick after the CPU flush to panel memory */\n\t\t*(volatile uint32_t *)0xae2204 = 1;\n\t\tIOFreeData(rec, SWEET_FB_SWAP_REC_SIZE);'
if old not in s:
    print('ERROR: anchor not found', file=sys.stderr)
    sys.exit(1)
s = s.replace(old, new, 1)
open(path, 'w').write(s)
print('patched SweetFramebuffer.cpp (panel refresh kick)')
PY
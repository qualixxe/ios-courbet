#!/usr/bin/env python3
"""Dedup the blocks research/apply_port_edits.py inserted (it ran twice) and make
that script idempotent: a pair whose *new* text is already present must be skipped
before the old (prefix) anchor is looked up.
"""
BLOCK = '''\t/* The ADT's RAM window must exist in the live FDT: a 6 GB phone booted
\t * with an 8 GB ADT (or vice versa) would corrupt memory silently. */
\tuint64_t ram_top = 0;
\tif (fdt_memory_top(dtb, &ram_top)) {
\t\tcon_hex("RAMTOP", ram_top);
\t\tif (p->phys_base + p->mem_size + 0x100000ULL > ram_top)
\t\t\treturn "payload RAM exceeds live RAM (mkadt --mem 6|8)";
\t}
'''

DECL = '''/* Highest address covered by the live /memory nodes. Returns 0 if absent. */
int fdt_memory_top(uintptr_t fdt, uint64_t *top);
'''


def dedup(path, block, keep=1, crlf=True):
    raw = open(path, 'r', encoding='utf-8', newline='').read()
    is_crlf = '\r\n' in raw
    text = raw.replace('\r\n', '\n')
    n = text.count(block)
    if n <= keep:
        print(f'{path}: {n} occurrence(s), nothing to do')
        return
    first = text.find(block)
    # drop every occurrence after the first `keep`
    parts = text.split(block)
    out = parts[0]
    for i, p in enumerate(parts[1:], start=1):
        out += block if i <= keep else ''
        out += p
    print(f'{path}: {n} -> {out.count(block)} occurrence(s)')
    if is_crlf:
        out = out.replace('\n', '\r\n')
    open(path, 'w', encoding='utf-8', newline='').write(out)


dedup('shim/fdt.h', DECL)
dedup('shim/loader.c', BLOCK)

# --- apply_port_edits.py: check `new` before the (prefix) `old` anchor
p = 'research/apply_port_edits.py'
raw = open(p, 'r', encoding='utf-8', newline='').read()
old = '''    for old, new in pairs:
        if old not in text:
            if new in text:
                continue
            raise SystemExit(f'{path}: anchor not found:\\n{old[:160]!r}')'''
new = '''    for old, new in pairs:
        if new in text:
            continue
        if old not in text:
            raise SystemExit(f'{path}: anchor not found:\\n{old[:160]!r}')'''
if old in raw:
    open(p, 'w', encoding='utf-8', newline='').write(raw.replace(old, new, 1))
    print('apply_port_edits.py: made idempotent')
elif new in raw:
    print('apply_port_edits.py: already idempotent')
else:
    raise SystemExit('apply_port_edits.py: helper block not found')

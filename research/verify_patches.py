#!/usr/bin/env python3
"""Reconstruct bsd/dev/sweet_touch.c from 0060 and replay 0062/0063 on it.

The full xnu tree is huge and not present here, so this checks the part that
the courbet port actually edited: the patch chain must still apply cleanly.
"""
import re
import sys

PATCHES = [
    'xnu/patches/0060-sweet-keys-touch-drivers.patch',
    'xnu/patches/0062-sweet-touch-power-battery.patch',
    'xnu/patches/0063-sweet-goodix-geni-packing.patch',
]
TARGET = 'bsd/dev/sweet_touch.c'
HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def sections(path):
    """Yield (old_name, new_name, hunks) where hunks = [(start, [(tag,line)])]."""
    raw = open(path, 'r', encoding='utf-8', newline='').read().replace('\r\n', '\n')
    lines = raw.split('\n')
    i = 0
    while i < len(lines):
        if lines[i].startswith('--- a/') or lines[i].startswith('--- /dev/null'):
            old = lines[i][6:] if lines[i].startswith('--- a/') else '/dev/null'
            new = lines[i + 1][6:] if i + 1 < len(lines) and lines[i + 1].startswith('+++ b/') else old
            i += 2
            hunks = []
            while i < len(lines) and lines[i].startswith('@@'):
                m = HUNK.match(lines[i])
                if not m:
                    raise SystemExit(f'{path}:{i + 1}: bad hunk header {lines[i]!r}')
                start = int(m.group(1))
                body = []
                i += 1
                while i < len(lines):
                    l = lines[i]
                    if l.startswith('@@ ') or l.startswith('--- a/') or l.startswith('diff --git'):
                        break
                    if l[:1] in (' ', '+', '-') and not l.startswith('+++') and not l.startswith('---'):
                        body.append((l[0], l[1:]))
                    elif l.startswith('\\'):
                        pass
                    elif l == '':
                        # trailing blank line of the file
                        break
                    else:
                        break
                    i += 1
                hunks.append((start, body))
            yield old, new, hunks
        else:
            i += 1


files = {}
for p in PATCHES:
    for old, new, hunks in sections(p):
        if new != TARGET and old != TARGET:
            continue
        if new == TARGET and old == TARGET and new not in files:
            raise SystemExit(f'{p}: {TARGET} modified before it exists')
        if new not in files:
            if old != '/dev/null' and old != TARGET:
                raise SystemExit(f'{p}: cannot create {new} from {old}')
            files[new] = []
            print(f'{p}: create {new}')
        src = files[new]
        pos = 0
        for start, body in hunks:
            old_block = [l for tag, l in body if tag in (' ', '-')]
            new_block = [l for tag, l in body if tag in (' ', '+')]
            # locate the old block at/after pos (unified diff context is exact)
            found = -1
            for k in range(pos, len(src) - len(old_block) + 1):
                if src[k:k + len(old_block)] == old_block:
                    found = k
                    break
            if found < 0:
                print(f'  FAIL: hunk at old line {start} not found')
                print('  old block:', old_block[:6])
                sys.exit(1)
            src[found:found + len(old_block)] = new_block
            pos = found + len(new_block)
        print(f'{p}: applied {len(hunks)} hunk(s) to {new}')
        files[new] = src

print(f'\n{TARGET}: {len(files[TARGET])} lines, chain OK')

#!/usr/bin/env python3
"""Re-count every unified-diff hunk header in xnu/patches/*.patch and fix any
whose header no longer matches its body.

This exists because the touch-drivers edits grew a hunk in 0063 without updating
`@@ -32,6 +32,11 @@`; git then reports "corrupt patch at line N" and blacktop's
apply loop *skips* the file with only a warning, so the kernel silently builds
without it.
"""
import glob
import re
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def fix(path):
    # surrogateescape so patches that embed non-UTF-8 bytes round-trip unchanged
    raw = open(path, 'r', encoding='utf-8', errors='surrogateescape', newline='').read()
    crlf = '\r\n' in raw
    text = raw.replace('\r\n', '\n')
    lines = text.split('\n')
    out = []
    i = 0
    fixed = 0
    while i < len(lines):
        line = lines[i]
        m = HUNK.match(line)
        if not m:
            out.append(line)
            i += 1
            continue
        old_start, old_n, new_start, new_n = m.groups()
        old_n = int(old_n) if old_n is not None else 1
        new_n = int(new_n) if new_n is not None else 1
        j = i + 1
        old_c = new_c = 0
        while j < len(lines):
            l = lines[j]
            if l.startswith('@@ ') or l.startswith('--- ') or l.startswith('diff --git') \
                    or l.startswith('index ') or l.startswith('new file') \
                    or l.startswith('deleted file'):
                break
            if l.startswith('+') and not l.startswith('+++'):
                new_c += 1
            elif l.startswith('-') and not l.startswith('---'):
                old_c += 1
            elif l.startswith(' '):
                old_c += 1
                new_c += 1
            elif l.startswith('\\'):
                pass          # "\ No newline at end of file"
            else:
                break
            j += 1
        if (old_c, new_c) != (old_n, new_n):
            print(f'{path}: line {i + 1}: header says old={old_n} new={new_n}, '
                  f'body has old={old_c} new={new_c} -> corrected')
            rest = line.split('@@', 2)
            suffix = '@@' + rest[2] if len(rest) > 2 else '@@'
            line = f'@@ -{old_start},{old_c} +{new_start},{new_c} {suffix}'
            fixed += 1
        out.append(line)
        out.extend(lines[i + 1:j])      # the body, unchanged
        i = j
    if not fixed:
        return 0
    text = '\n'.join(out)
    if crlf:
        text = text.replace('\n', '\r\n')
    open(path, 'w', encoding='utf-8', errors='surrogateescape', newline='').write(text)
    return fixed


total = 0
files = sorted(glob.glob('xnu/patches/*.patch'))
for p in files:
    total += fix(p)
print(f'{len(files)} patch file(s) checked, {total} hunk header(s) corrected')
if total:
    sys.exit(1)     # something changed: re-run before trusting the tree

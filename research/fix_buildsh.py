p = 'shim/build.sh'
raw = open(p, 'r', encoding='utf-8', newline='').read()
crlf = '\r\n' in raw
t = raw.replace('\r\n', '\n').split('\n')
out = []
for l in t:
    if out and l == out[-1] and l.strip() and (l.startswith('# DTB=') or l.startswith('DTB=')):
        continue
    out.append(l)
t = '\n'.join(out)
if crlf:
    t = t.replace('\n', '\r\n')
open(p, 'w', encoding='utf-8', newline='').write(t)
print('build.sh deduped')

d = open(p, 'r', encoding='utf-8', newline='').read()
print('  header comment x', d.count('# DTB=/path/to/dtb'))
print('  DTB default line x', d.count('DTB=${DTB:-'))

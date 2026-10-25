p = 'shim/loader.c'
raw = open(p, 'r', encoding='utf-8', newline='').read()
crlf = '\r\n' in raw
t = raw.replace('\r\n', '\n')
import re
t = re.sub(r'\n{3,}', '\n\n', t)
if crlf:
    t = t.replace('\n', '\r\n')
open(p, 'w', encoding='utf-8', newline='').write(t)
print('loader.c blank runs collapsed')

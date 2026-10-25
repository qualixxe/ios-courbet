import re
import sys

for f in ['shim/fdt.c', 'shim/fdt.h', 'shim/loader.c', 'shim/shim.c']:
    d = open(f, 'r', encoding='utf-8', newline='').read()
    d = re.sub(r'/\*.*?\*/', '', d, flags=re.S)
    d = re.sub(r'//[^\n]*', '', d)
    d = re.sub(r'"(\\.|[^"\\])*"', '""', d)
    d = re.sub(r"'(\\.|[^'\\])*'", "''", d)
    b = d.count('{') - d.count('}')
    p = d.count('(') - d.count(')')
    print(f'{f:16} braces {b:+d}  parens {p:+d}' + ('' if b == 0 and p == 0 else '   <-- CHECK'))

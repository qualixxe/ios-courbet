import struct, os, sys

def info(p):
    try:
        d = open(p, 'rb').read(4096)
    except Exception as e:
        print(p, 'ERR', e)
        return
    magic = d[:8]
    print('==', p, 'size', os.path.getsize(p))
    if magic == b'ANDROID!':
        ver = struct.unpack_from('<I', d, 40)[0]
        print('  boot header v%d' % ver)
        if ver < 3:
            print('  cmdline:', d[64:64 + 512].split(b'\0')[0].decode('utf-8', 'replace'))
        else:
            print('  cmdline:', d[44:44 + 1536].split(b'\0')[0].decode('utf-8', 'replace'))
    else:
        print('  magic:', magic)

for p in sys.argv[1:]:
    info(p)

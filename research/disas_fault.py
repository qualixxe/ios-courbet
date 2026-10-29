import struct, os

kp = os.environ["TEMP"] + "\\kernel.development.sweet"
k = open(kp, "rb").read()
ncmds = struct.unpack_from("<I", k, 16)[0]
off = 32
segs = []
for _ in range(ncmds):
    cmd, csize = struct.unpack_from("<II", k, off)
    if cmd == 0x19:
        name = k[off + 8:off + 24].split(b"\0")[0].decode()
        vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<4Q", k, off + 24)
        segs.append((name, vmaddr, vmsize, fileoff, filesize))
    off += csize
for s in segs:
    print(s)

# _current_percpu_base at 0xfffffe0007480040 (+0xc = 0x4c fault)
target = 0xfffffe000748004c
for name, vmaddr, vmsize, fileoff, filesize in segs:
    if vmaddr <= target < vmaddr + vmsize:
        foff = fileoff + (target - vmaddr)
        print("FAULT ADDR %#x is in %s at file offset %#x" % (target, name, foff))
        print("Bytes around fault:")
        for i in range(-16, 16, 4):
            off2 = foff + i
            val = struct.unpack_from("<I", k, off2)[0]
            print("  %#x: %08x" % (target + i, val))

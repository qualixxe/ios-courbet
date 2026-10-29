import struct, os

kp = os.environ["TEMP"] + "\\kernel.development.sweet"
k = open(kp, "rb").read()

# Find _memmove symbol using symsweet-like logic
import bisect
ncmds = struct.unpack_from("<I", k, 16)[0]
off = 32
symoff = nsyms = stroff = None
for _ in range(ncmds):
    cmd, csize = struct.unpack_from("<II", k, off)
    if cmd == 0x2:
        symoff, nsyms, stroff, strsize = struct.unpack_from("<4I", k, off + 8)
    off += csize

syms = []
for i in range(nsyms):
    strx, typ, sect, desc, value = struct.unpack_from("<IBBHQ", k, symoff + i * 16)
    if value == 0 or strx == 0 or not typ & 0x0e:
        continue
    end = k.index(b"\0", stroff + strx)
    syms.append((value, k[stroff + strx:end].decode("utf-8", "replace")))
syms.sort()
addrs = [s[0] for s in syms]

# Find _memmove
for i, (addr, name) in enumerate(syms):
    if name == "_memmove":
        memmove_addr = addr
        # Find end (next symbol)
        end_addr = syms[i + 1][0] if i + 1 < len(syms) else addr + 0x1000
        print(f"_memmove at {addr:#x}, size ~{end_addr - addr:#x}")
        # Disassemble bytes from addr to addr+64
        foff = None
        # Find segment containing addr
        ncmds2 = struct.unpack_from("<I", k, 16)[0]
        off2 = 32
        for _ in range(ncmds2):
            cmd2, csize2 = struct.unpack_from("<II", k, off2)
            if cmd2 == 0x19:
                name2 = k[off2 + 8:off2 + 24].split(b"\0")[0].decode()
                vmaddr2, vmsize2, fileoff2, filesize2 = struct.unpack_from("<4Q", k, off2 + 24)
                if vmaddr2 <= addr < vmaddr2 + vmsize2:
                    foff = fileoff2 + (addr - vmaddr2)
                    break
            off2 += csize2
        
        if foff:
            code = k[foff:foff + 64]
            for j in range(0, len(code), 4):
                if j + 4 <= len(code):
                    val = struct.unpack_from("<I", code, j)[0]
                    print(f"  {addr + j:#x}: {val:08x}")
        break

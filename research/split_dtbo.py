#!/usr/bin/env python3
"""Split an Android DTBO (dt_table) image into individual .dtb overlays."""
import struct
import sys
import os

DT_TABLE_MAGIC = 0xD7B7AB1E


def main():
    src = sys.argv[1]
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    data = open(src, "rb").read()
    magic, total, hdr_size, entry_size, entry_count, ver = struct.unpack_from(">6I", data, 0)
    print(f"file={src} size={len(data)}")
    print(f"magic=0x{magic:08x} total={total} hdr_size={hdr_size} "
          f"entry_size={entry_size} count={entry_count} version={ver}")
    if magic != DT_TABLE_MAGIC:
        print("NOT a dtbo image")
        return 1
    for i in range(entry_count):
        off = hdr_size + i * entry_size
        size, offset, id_, rev, custom = struct.unpack_from(">5I", data, off)
        blob = data[offset:offset + size]
        fdt_magic = struct.unpack_from(">I", blob, 0)[0] if len(blob) >= 4 else 0
        name = os.path.join(outdir, f"overlay_{i:02d}_id{id_:08x}_rev{rev}.dtb")
        open(name, "wb").write(blob)
        print(f"  [{i}] size={size} offset={offset} id=0x{id_:08x} rev={rev} "
              f"custom={custom} fdt_magic=0x{fdt_magic:08x} -> {os.path.basename(name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

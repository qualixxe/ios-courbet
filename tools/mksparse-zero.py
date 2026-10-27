#!/usr/bin/env python3
"""Wrap a raw image into an Android sparse image minus its zero blocks.

  mksparse-zero.py IN.img OUT.simg [--raw-mib 64]

Zero 4096-byte blocks become DONT_CARE chunks (the bootloader leaves whatever
was on the partition there; HFS+ never reads unallocated blocks), real data
becomes RAW chunks of at most --raw-mib each. Typical images shrink by the size
of their free space, which also shrinks the single host-side buffer fastboot
builds before sending (16G raw/sparse images can exceed the commit limit and
die with std::bad_alloc).

Chunks stream straight to disk in one pass; memory stays bounded.
"""
import argparse, os, struct

MAGIC = 0xed26ff3a
RAW, DONT_CARE = 0xcac1, 0xcac3
BS = 4096
ZB = b'\x00' * BS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--raw-mib', type=int, default=64)
    a = ap.parse_args()

    size = os.path.getsize(a.src)
    if size % BS:
        raise SystemExit('source size must be a multiple of %d' % BS)
    nblocks = size // BS
    raw_max = (a.raw_mib << 20) // BS
    if raw_max < 1:
        raise SystemExit('--raw-mib too small')

    chunks = 0
    blob = bytearray()          # pending bytes of the current data run
    zrun = 0                    # pending length of the current zero run (blocks)
    emitted = 0                 # blocks already written out
    pos = 0                     # source bytes processed

    with open(a.src, 'rb') as s, open(a.dst, 'wb') as d:
        d.write(struct.pack('<IHHHHIIII', MAGIC, 1, 0, 28, 12, BS, nblocks, 0, 0))

        def emit_raw(nblocks_now):
            nonlocal chunks, blob, emitted
            d.write(struct.pack('<III', RAW, 0, 12 + nblocks_now * BS))
            d.write(bytes(blob[:nblocks_now * BS]))
            del blob[:nblocks_now * BS]
            emitted += nblocks_now
            chunks += 1

        while True:
            buf = s.read(8 << 20)
            if not buf:
                break
            i = 0
            while i < len(buf):
                if buf[i:i + BS] == ZB:
                    if blob:
                        while len(blob) >= raw_max * BS:
                            emit_raw(raw_max)
                        if blob:
                            n = len(blob) // BS
                            emit_raw(n)
                        blob = bytearray()
                    zrun += 1
                else:
                    if zrun:
                        d.write(struct.pack('<III', DONT_CARE, 0, 12))
                        emitted += zrun
                        chunks += 1
                        zrun = 0
                    blob += buf[i:i + BS]
                    if len(blob) >= raw_max * BS:
                        emit_raw(raw_max)
                i += BS
            pos += len(buf)
            if (pos >> 30) != ((pos - len(buf)) >> 30):
                print('  %5.2f / %5.2f GiB' % (pos / (1 << 30), size / (1 << 30)), flush=True)

        if blob:
            while len(blob) >= raw_max * BS:
                emit_raw(raw_max)
            if blob:
                n = len(blob) // BS
                emit_raw(n)
        if zrun:
            d.write(struct.pack('<III', DONT_CARE, 0, 12))
            emitted += zrun
            chunks += 1

    if emitted != nblocks:
        raise SystemExit('accounted %d of %d blocks' % (emitted, nblocks))

    with open(a.dst, 'r+b') as d:
        d.seek(20)
        d.write(struct.pack('<I', chunks))
    print('done: %s  %d bytes  %d chunks' % (a.dst, os.path.getsize(a.dst), chunks))


if __name__ == '__main__':
    main()

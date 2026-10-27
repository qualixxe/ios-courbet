#!/usr/bin/env python3
"""Wrap a raw filesystem image into an Android sparse image made of RAW chunks.

  mksparse-full.py IN.img OUT.simg [--chunk-mib 128]

Unlike `fastboot flash` on a raw file (which can buffer the whole image and
die with std::bad_alloc on 16G), a sparse file is streamed chunk by chunk,
each chunk below the bootloader's max-download-size. Every byte of the input
is still transmitted (no delta scanning); the on-device result is identical.
"""
import argparse, os, struct

MAGIC = 0xed26ff3a
RAW = 0xcac1
BS = 4096


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--chunk-mib', type=int, default=128)
    a = ap.parse_args()

    size = os.path.getsize(a.src)
    if size % BS:
        raise SystemExit('source size must be a multiple of %d' % BS)
    nblocks = size // BS
    bpc = (a.chunk_mib << 20) // BS
    nchunks = -(-nblocks // bpc)

    with open(a.src, 'rb') as s, open(a.dst, 'wb') as d:
        d.write(struct.pack('<IHHHHIIII', MAGIC, 1, 0, 28, 12, BS, nblocks, nchunks, 0))
        left = nblocks
        sent = 0
        sent_chunks = 0
        while left:
            n = min(bpc, left)
            data = s.read(n * BS)
            if len(data) != n * BS:
                raise SystemExit('short read at offset %d' % (sent * BS))
            d.write(struct.pack('<III', RAW, 0, 12 + n * BS))
            d.write(data)
            left -= n
            sent += n
            sent_chunks += 1
            if sent_chunks % 16 == 0 or not left:
                print('  %6.2f / %6.2f GiB (%d chunks)'
                      % (sent * BS / (1 << 30), size / (1 << 30), sent_chunks),
                      flush=True)
    # patch the real chunk count into the header
    with open(a.dst, 'r+b') as d:
        d.seek(struct.calcsize('<IHHHHIIII') - 8)
        d.write(struct.pack('<II', sent_chunks, 0))
    print('done:', a.dst, '%d bytes' % os.path.getsize(a.dst))


if __name__ == '__main__':
    main()

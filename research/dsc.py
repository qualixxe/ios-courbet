"""Map a runtime PC inside the dyld shared cache of an iOS root image to its dylib.

The qemu-fullroot image keeps the caches as HFS+ hardlinks: the catalog record in
/System/Library/Caches/com.apple.dyld has a zero-size data fork and an inode
number in HFSPlusBSDInfo.special; the bytes live in /.HFS+ Private Data/iNode<N>.
With a split cache (iOS 16) the main file carries the whole dyld_cache_image_info
array, while each .NN subcache has its own dyld_cache_header mappings -- so a VM
address resolves to (subcache file, file offset) through those mappings.

    python research/dsc.py research/qemu-fullroot.img 0x198a7a6cc 0x198a66624
    python research/dsc.py IMG --dump 0x198a7a6cc research/qfull/crash.bin
    python research/dsc.py IMG --dump-image /System/Library/Frameworks/UIKitCore.framework/UIKitCore research/qfull/UIKitCore.bin

Cache structures are little-endian (they are plain memory images); the HFS layer
in hfs-check.py is big-endian.
"""
import argparse, importlib.util, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('hc', os.path.join(HERE, 'hfs-check.py'))
hc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hc)

CACHE_DIR = '/System/Library/Caches/com.apple.dyld'
MAIN = 'dyld_shared_cache_arm64'


def u32(b, o): return struct.unpack_from('<I', b, o)[0]
def u64(b, o): return struct.unpack_from('<Q', b, o)[0]


class DSC:
    def __init__(self, image):
        self.v = hc.Volume(image)
        self.t, self.dirs, self.files, self.threads = self.v.scan_catalog()
        self._id = {cn: (p, n) for (p, n), cn in self.files.items()}
        self._id.update({cn: (p, n) for (p, n), cn in self.dirs.items()})
        self._paths = {}
        self._files = {}          # cache file name -> (logicalSize, extents)
        self._headers = {}        # ditto -> parsed header dict
        self._subcache_names = None
        self.cache_files = {}     # cache-dir file name -> (parent cnid, cnid)
        for (p, n), cn in self.files.items():
            if self.path(p) == CACHE_DIR:
                self.cache_files[n] = (p, cn)
        self.hdr = self.header(MAIN)
        self._load_images()

    # -- HFS plumbing --------------------------------------------------------
    def path(self, cnid):
        if cnid in self._paths:
            return self._paths[cnid]
        chain = []
        cn = cnid
        while cn != 2 and cn not in self._paths and cn in self._id:
            p, n = self._id[cn]
            chain.append((cn, n))
            cn = p
        base = self._paths.get(cn, '')
        for c, n in reversed(chain):
            base = base + '/' + n
            self._paths[c] = base
        self._paths.setdefault(cnid, base)
        return self._paths[cnid]

    def _catalog_record(self, parent, name):
        hit, err = self.v.descend(self.v.btree('catalogBtree'), hc.cat_key(parent, name))
        if err:
            raise SystemExit(err)
        num, idx, exact = hit
        if not exact:
            raise SystemExit(f'{name}: not in catalog')
        return self.v.node_data(self.v.node(self.t, num), idx)

    def file(self, name):
        if name in self._files:
            return self._files[name]
        got = self.cache_files.get(name)
        if got is None:
            raise SystemExit(f'{CACHE_DIR}/{name}: not in image')
        parent, cnid = got
        rec = self._catalog_record(parent, name)
        special = struct.unpack_from('>I', rec, 44)[0]      # HFSPlusBSDInfo.special
        size, exts = self.v.ext_of(cnid)
        if not size:                                        # hardlink: inode file
            inode = 'iNode%d' % special
            for (p, n), c2 in self.files.items():
                if n == inode:
                    size, exts = self.v.ext_of(c2)
                    break
            else:
                raise SystemExit(f'{name}: hardlink inode {inode} not found')
        self._files[name] = (size, exts)
        return size, exts

    def read(self, name, off, n):
        size, exts = self.file(name)
        if off >= size:
            return b''
        return self.v.read(exts, off, min(n, size - off))

    def header(self, name):
        if name in self._headers:
            return self._headers[name]
        h = self.read(name, 0, 0x400)
        if h[:7] != b'dyld_v1':
            raise SystemExit(f'{name}: bad magic {h[:16]!r}')
        d = dict(
            name=name, size=self.file(name)[0],
            mappingOffset=u32(h, 16), mappingCount=u32(h, 20),
            uuid=h[88:104].hex(), cacheType=u64(h, 104),
            platform=u32(h, 216),
            sharedRegionStart=u64(h, 224), sharedRegionSize=u64(h, 232),
            osVersion=u32(h, 364),
            imagesOffset=u32(h, 448), imagesCount=u32(h, 452),
        )
        mo, mc = d['mappingOffset'], d['mappingCount']
        maps = []
        raw = self.read(name, mo, 32 * mc)
        for i in range(mc):
            addr, size, foff, mprot, iprot = struct.unpack_from('<QQQII', raw, 32 * i)
            maps.append(dict(addr=addr, size=size, fileOffset=foff,
                             maxprot=mprot, initprot=iprot))
        d['mappings'] = maps
        self._headers[name] = d
        return d

    def subcaches(self):
        """Every cache file in the directory, main first, then .01/.02/... .dylddata."""
        if self._subcache_names is not None:
            return self._subcache_names
        names = [n for n in self.cache_files if n.startswith(MAIN)]
        def key(n):
            tail = n[len(MAIN):]
            if tail == '': return (0, 0)
            if tail.startswith('.'):
                num = tail[1:].split('.')[0]
                if num.isdigit(): return (1, int(num))
            return (2, 0)
        self._subcache_names = sorted(names, key=key)
        return self._subcache_names

    def _load_images(self):
        h = self.hdr
        raw = self.read(MAIN, h['imagesOffset'], 32 * h['imagesCount'])
        imgs = []
        for i in range(len(raw) // 32):
            addr, mtime, inode, pathoff, pad = struct.unpack_from('<QQQII', raw, 32 * i)
            imgs.append(dict(address=addr, modTime=mtime, inode=inode, pathOffset=pathoff))
        for im in imgs:
            p = self.read(MAIN, im['pathOffset'], 512)
            im['path'] = p.split(b'\0')[0].decode('utf-8', 'replace')
        imgs.sort(key=lambda x: x['address'])
        self.images = imgs
        self._by_addr = [im['address'] for im in imgs]

    # -- address translation -------------------------------------------------
    def image_for(self, pc):
        import bisect
        i = bisect.bisect_right(self._by_addr, pc) - 1
        if i < 0:
            return None
        im = self.images[i]
        return im, pc - im['address']

    def vm_to_file(self, addr):
        """(cache file name, file offset) for a VM address, scanning subcache maps."""
        for name in self.subcaches():
            try:
                hdr = self.header(name)
            except SystemExit:
                continue
            for m in hdr['mappings']:
                if m['addr'] <= addr < m['addr'] + m['size']:
                    return name, m['fileOffset'] + (addr - m['addr'])
        return None

    def read_vm(self, addr, n):
        got = self.vm_to_file(addr)
        if not got:
            return None
        name, off = got
        return self.read(name, off, n)

    def image_bytes(self, path):
        im = next((x for x in self.images if x['path'] == path), None)
        if im is None:
            raise SystemExit(f'{path}: not in cache image table')
        nxt = next((x['address'] for x in self.images
                    if x['address'] > im['address']), None)
        size = (nxt - im['address']) if nxt else 1 << 20
        out = bytearray()
        addr = im['address']
        while len(out) < size:
            blob = self.read_vm(addr + len(out), min(1 << 20, size - len(out)))
            if not blob:
                break
            out += blob
        return im, bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('pcs', nargs='*', help='runtime PC, e.g. 0x198a7a6cc')
    ap.add_argument('--subcaches', action='store_true')
    ap.add_argument('--dump', nargs=2, metavar=('PC', 'OUT'), action='append', default=[],
                    help='write 256 bytes around PC')
    ap.add_argument('--dump-image', nargs=2, metavar=('PATH', 'OUT'), action='append', default=[])
    args = ap.parse_args()
    d = DSC(args.image)
    h = d.hdr
    print('main: size=%d sharedRegion=%#x+%#x images=%d os=%#x' % (
        h['size'], h['sharedRegionStart'], h['sharedRegionSize'],
        h['imagesCount'], h['osVersion']))
    if args.subcaches:
        for n in d.subcaches():
            hh = d.header(n)
            spans = ', '.join('%#x+%#x@%#x' % (m['addr'], m['size'], m['fileOffset'])
                              for m in hh['mappings'][:3])
            print('  %-36s size=%-10d maps=%d %s' % (n, hh['size'], hh['mappingCount'], spans))
    for s in args.pcs:
        pc = int(s, 0)
        got = d.image_for(pc)
        if got is None:
            print('%#x: below shared region' % pc)
            continue
        im, off = got
        vf = d.vm_to_file(pc)
        print('%#x -> %s + %#x (%d)  [%s]' % (pc, im['path'], off, off,
                                              '%s@%#x' % vf if vf else 'unmapped'))
    for pc_s, out in args.dump:
        pc = int(pc_s, 0)
        blob = d.read_vm(pc & ~0xf, 256)
        if blob is None:
            raise SystemExit('%#x: unmapped' % pc)
        open(out, 'wb').write(blob)
        print('wrote %d bytes at %#x -> %s' % (len(blob), pc & ~0xf, out))
    for path, out in args.dump_image:
        im, blob = d.image_bytes(path)
        open(out, 'wb').write(blob)
        print('%s: %d bytes at %#x -> %s' % (path, len(blob), im['address'], out))


if __name__ == '__main__':
    main()

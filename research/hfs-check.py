"""Read an HFS+/HFSX volume straight out of a raw image: no kernel, no FUSE.

The 2026-10-29 A/B is that the same instrumented kernel boots a 64 MB root with
namei()==0 for /sbin/launchd, while on the 6.4 GB root every namei() is EINVAL.
Before blaming XNU, prove what the image holds: is the catalog B-tree intact,
does /sbin/launchd exist, do the extents stay inside the volume, and is the file
data really there?

Records are enumerated by scanning every leaf node instead of walking the tree,
because the catalog tree's index keys are thread keys (a CNID spelled as two
UTF-16 units) -- comparing those correctly is precisely the code under
suspicion, so it must not be trusted to read its own volume.

    python research/hfs-check.py research/qemu-fullroot.img
    python research/hfs-check.py IMG --paths /sbin/launchd /usr/sbin/cydst
"""
import argparse, os, struct

VH = 1024
HDR_SIZE = 1024
# HFSPlusVolumeHeader: 5 80-byte HFSPlusForkData records starting after finderInfo
FORK_OFF = dict(VBM=112, extentsBtree=192, catalogBtree=272,
                attributesFile=352, startupFile=432)
# Reserved CNIDs of those files (hfs_format.h:294) -- the keys of the overflow tree.
META_ID = dict(VBM=6, extentsBtree=3, catalogBtree=4, attributesFile=8, startupFile=7)
DESC = 14                     # fLink bLink kind height numRecords reserved
NODE = dict(header=1, index=0, leaf=-1, map=2)
CAT = {1: 'folder', 2: 'file', 3: 'folderThread', 4: 'fileThread'}


def u8(b, o): return b[o]
def u16(b, o): return struct.unpack('>H', b[o:o + 2])[0]
def u32(b, o): return struct.unpack('>I', b[o:o + 4])[0]
def u64(b, o): return struct.unpack('>Q', b[o:o + 8])[0]


class Volume:
    def __init__(self, path):
        self.path = path
        self.f = open(path, 'rb')
        self.filesize = os.path.getsize(path)
        self.f.seek(VH)
        self.hdr = self.f.read(HDR_SIZE)
        if u16(self.hdr, 0) not in (0x482b, 0x4858):
            raise SystemExit(f'{path}: not HFS+/HFSX at {VH} (sig 0x{u16(self.hdr,0):04x})')
        self.block = u32(self.hdr, 40)
        self.blocks = u32(self.hdr, 44)
        self._ovfl = None
        self._fileExt = {}
        self._fileFork = {}

    # -- forks ---------------------------------------------------------------
    def fork(self, what):
        """(logicalSize, extents) for one of the volume header's reserved files."""
        o = FORK_OFF[what]
        exts = [struct.unpack('>II', self.hdr[o + 16 + 8 * i:o + 24 + 8 * i])
                for i in range(8)]
        return u64(self.hdr, o), [e for e in exts if e[1]]

    def read(self, exts, off, n):
        pos = 0
        out = bytearray()
        for start, cnt in exts:
            size = cnt * self.block
            if pos + size > off:
                lo, hi = max(off, pos), min(off + n, pos + size)
                self.f.seek(start * self.block + (lo - pos))
                out += self.f.read(hi - lo)
            pos += size
            if pos >= off + n:
                break
        return bytes(out)

    # -- btree ---------------------------------------------------------------
    def btree(self, what, deep=True):
        """BTHeaderRec sits at a fixed offset 14 -- BTree.c:250 and hfs_btreeio.c:142.

        deep=False reads the header through the volume header's own 8 extents, which
        is what the overflow tree itself needs (it is small, and indexing it must not
        recurse).
        """
        logical, exts = self.fork(what)
        if deep:
            exts = self.full_extents(META_ID[what], exts)
        head = self.read(exts, 0, DESC + 80)[DESC:]
        return dict(logical=logical, exts=exts, nodeSize=u16(head, 18), depth=u16(head, 0),
                    root=u32(head, 2), leafRecords=u32(head, 6), firstLeaf=u32(head, 10),
                    lastLeaf=u32(head, 14), maxKey=u16(head, 20), totalNodes=u32(head, 22),
                    freeNodes=u32(head, 26), clump=u32(head, 32), btreeType=head[36],
                    keyCompareType=head[37], attributes=u32(head, 38))

    def nodes(self, t, kinds=('leaf',)):
        want = {NODE[k] for k in kinds}
        for n in range(t['totalNodes']):
            off = n * t['nodeSize']
            if off + t['nodeSize'] > t['logical']:
                return
            node = self.read(t['exts'], off, t['nodeSize'])
            if len(node) != t['nodeSize']:
                raise SystemExit(f'node {n}: short read ({len(node)}/{t["nodeSize"]}) '
                                 f'-> extents do not cover the btree')
            if struct.unpack('>b', node[8:9])[0] in want:
                yield n, node

    def records(self, node, trim=True):
        """BTreeNodeOps.c:165 -- GetRecordOffset(i) = node + nodeSize - 2*i - 2.

        A record is [u16 keyLength][key][data]: these volumes have no data-length
        field (verified against thread records, whose parentID + name fill the slot
        exactly), so data starts right after the key.
        """
        for i in range(u16(node, 10)):
            yield from self.records_at(node, i, i + 1, trim)

    def ext_of(self, fileID):
        """Data-fork extents of any file: its catalog record plus the overflow tree."""
        got = self._fileExt.get(fileID)
        return None if got is None else (got[0], self.full_extents(fileID, got[1]))

    # -- tree walk, the way the kernel does it --------------------------------
    def node(self, t, n):
        return self.read(t['exts'], n * t['nodeSize'], t['nodeSize'])

    @staticmethod
    def cat_cmp(search, trial):
        """cat_binarykeycompare (hfs_catalog.c:3446) on raw key bytes: parentID first,
        then the name by UnicodeBinaryCompare, which compares min(len) units and calls
        the shorter key the smaller one -- index keys are truncated, so that matters."""
        p1, p2 = u32(search, 0), u32(trial, 0)
        if p1 != p2:
            return 1 if p1 > p2 else -1
        n1, n2 = u16(search, 4), u16(trial, 4)
        for i in range(min(n1, n2)):
            a, b = u16(search, 6 + 2 * i), u16(trial, 6 + 2 * i)
            if a != b:
                return 1 if a > b else -1
        return (n1 > n2) - (n1 < n2)

    def descend(self, t, search, trace=None, resident=None):
        """SearchTree (BTreeTreeOps.c:196): from the root, index record i covers the
        keys from key(i) up to key(i+1), so on a miss the kernel descends to
        child[insertionPoint-1] (BTreeTreeOps.c:293)."""
        num, level, node = t['root'], t['depth'], None
        while True:
            if num == 0:
                return None, 'btBadNode (child pointer 0)'
            node = self.node(t, num)
            if len(node) != t['nodeSize']:
                return None, f'node {num}: short read'
            kind, height = struct.unpack('>b', node[8:9])[0], u8(node, 9)
            off = num * t['nodeSize']
            if trace is not None:
                trace.append((num, off, kind, off < resident))
            if height != level:
                return None, f'node {num}: height {height} != expected {level}'
            cnt = u16(node, 10)
            keys = []
            for i in range(cnt):
                k, _ = next(self.records_at(node, i, i + 1))
                keys.append(k)
            lo, hi, idx, exact = 0, cnt - 1, 0, False
            while lo <= hi:
                idx = (lo + hi) >> 1
                r = self.cat_cmp(search, keys[idx])
                if r == 0:
                    exact = True
                    break
                if r < 0:
                    hi = idx - 1
                else:
                    lo = idx + 1
            if not exact:
                idx = lo
                if idx != 0:
                    idx -= 1
            if kind == NODE['leaf']:
                return (num, idx, exact), None
            if kind != NODE['index']:
                return None, f'node {num}: kind {kind} at level {level}'
            num = u32(self.node_data(node, idx), 0)
            level -= 1

    @staticmethod
    def records_at(node, lo, hi, trim=False):
        cnt, n = u16(node, 10), len(node)
        for i in range(lo, hi):
            ro = u16(node, n - 2 * i - 2)
            nxt = u16(node, n - 2 * (i + 1) - 2) if i + 1 < cnt else n
            klen = u16(node, ro)
            data = node[ro + 2 + klen:nxt]
            if trim and i + 1 == cnt:
                data = data[:Volume.rec_size(data)]
            yield node[ro + 2:ro + 2 + klen], data

    @staticmethod
    def rec_size(data):
        """Catalog records are fixed-size except thread records, whose name length
        lives at +8. The last record of a node has no successor offset to bound it,
        so free space would otherwise be mistaken for payload (a fake 1e18-byte fork)."""
        rt = u16(data, 0)
        if rt == 1:
            return 88
        if rt == 2:
            return 244
        if rt in (3, 4):
            return 10 + 2 * u16(data, 8)
        return len(data)

    def node_data(self, node, i, trim=False):
        return next(self.records_at(node, i, i + 1, trim))[1]

    def overflow_index(self):
        """One pass over the extents B-tree: fileID -> [(startBlock, 8 extents)]."""
        if self._ovfl is None:
            self._ovfl = {}
            t = self.btree('extentsBtree', deep=False)
            for _, node in self.nodes(t):
                for key, data in self.records(node, trim=False):
                    if len(key) == 10 and key[0] == 0:
                        self._ovfl.setdefault(u32(key, 2), []).append(
                            (u32(key, 6), [struct.unpack('>II', data[8 * i:8 * i + 8])
                                           for i in range(8)]))
        return self._ovfl

    def full_extents(self, fileID, header_exts):
        """A fork's extents: the 8 in its record, then the overflow chain, which is
        indexed by the file's own allocation-block progress (MapFileBlockC)."""
        exts = list(header_exts)
        for sb, recs in sorted(self.overflow_index().get(fileID, [])):
            exts.extend([e for e in recs if e[1]])
        return exts

    def scan_catalog(self):
        t = self.btree('catalogBtree')
        dirs, files, threads, zero = {}, {}, {}, []
        self._fileExt = {}
        sizes = {}
        for n, node in self.nodes(t):
            for key, data in self.records(node):
                parent = u32(key, 0)
                klen = u16(key, 4)
                name = key[6:6 + klen * 2].decode('utf-16-be', 'replace')
                rt = u16(data, 0)
                sizes[CAT.get(rt, rt)] = sizes.get(CAT.get(rt, rt), 0) + 1
                if rt == 1:
                    cnid = u32(data, 8)
                    dirs[(parent, name)] = cnid
                elif rt == 2:
                    cnid = u32(data, 8)
                    files[(parent, name)] = cnid
                    if cnid == 0:
                        zero.append((parent, name))
                    o = len(data) - 160      # dataFork then resourceFork, both 80 bytes
                    self._fileExt[cnid] = (u64(data, o),
                                           [struct.unpack('>II', data[o + 16 + 8 * i:o + 24 + 8 * i])
                                            for i in range(8)
                                            if u32(data, o + 20 + 8 * i)])
                    # clumpSize/totalBlocks drive MapFileBlockC and hfs_getnewvnode, so
                    # keep the whole fork header, not just the extents.
                    self._fileFork[cnid] = (u32(data, o + 8), u32(data, o + 12),
                                            u64(data, o + 80), u32(data, o + 88),
                                            u32(data, o + 92))
                elif rt in (3, 4):
                    # A thread record's key carries the child CNID in parentID; this
                    # mkfs leaves the key name empty and puts the parent dir plus the
                    # real name in the data record.
                    threads[u32(key, 0)] = (u32(data, 4),
                                            data[10:10 + 2 * u16(data, 8)].decode('utf-16-be', 'replace'))
        self._zero = zero
        print('   record sizes:', sizes)
        if zero:
            print(f'   !!! {len(zero):,} records with CNID 0 -- cat_lookupbykey '
                  f'(hfs_catalog.c:809) returns EINVAL for exactly those: {zero[:8]}')
        return t, dirs, files, threads


def path_of(_v, cnid, dirs, files, threads):
    """Rebuild a path from a CNID through the thread records."""
    out = []
    while cnid != 2 and cnid in threads:
        pparent, pname = threads[cnid]
        out.append(pname)
        cnid = pparent
    return '/' + '/'.join(reversed(out)) or '/'


def cat_key(parent, name):
    units = name.encode('utf-16-be')
    return struct.pack('>IH', parent, len(units) // 2) + units


def walk(v, t, paths, dirs, files):
    """Descend the catalog tree exactly like SearchTree and say which nodes the
    kernel would have to read -- and whether they live in the volume header's eight
    resident extents or only in the extents-overflow tree."""
    _, resident_exts = v.fork('catalogBtree')
    resident = sum(c for _, c in resident_exts) * v.block
    print(f'catalog resident extents cover {resident:,} B = nodes 0..{resident // t["nodeSize"] - 1}')
    for p in paths:
        cnid, bad = 2, None
        for part in [x for x in p.split('/') if x]:
            trace = []
            key = cat_key(cnid, part)
            hit, err = v.descend(t, key, trace, resident)
            nodes = ' '.join(f'{n}{"*" if not res else ""}[{off // t["nodeSize"] // 2048}]'
                             for n, off, _, res in trace)
            if err:
                print(f'   {p:44} /{part:22} descend FAILED: {err}   nodes {nodes}')
                bad = part
                break
            num, idx, exact = hit
            if not exact:
                print(f'   {p:44} /{part:22} not in tree (leaf {num} idx {idx})   nodes {nodes}')
                bad = part
                break
            rec = v.node_data(v.node(t, num), idx)
            rt, cn = u16(rec, 0), u32(rec, 8)
            print(f'   {p:44} /{part:22} ok type={CAT.get(rt, rt)} cnid={cn}   nodes {nodes}')
            cnid = cn
        if bad is None:
            print(f'   {p:44} => cnid={cnid}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--paths', nargs='*', default=['/sbin/launchd', '/sbin', '/usr',
                                                   '/usr/appleinternal/sbin/launchd.development'])
    ap.add_argument('--walk', action='store_true',
                    help='descend the catalog tree like SearchTree and show which nodes are touched')
    ap.add_argument('--forks', action='store_true',
                    help='audit every file record: totalBlocks vs ceil(logicalSize/blockSize)')
    a = ap.parse_args()
    v = Volume(a.image)
    sig = u16(v.hdr, 0)
    print(f'{a.image}  file={v.filesize:,} B  sig={"HFSX" if sig == 0x4858 else "HFS+"}  '
          f'ver={u16(v.hdr,2)} attrs=0x{u32(v.hdr,4):08x} lastMnt={v.hdr[8:12]!r} '
          f'journalBlk={u32(v.hdr,12)}')
    print(f'   blockSize={v.block} blocks={v.blocks:,} ({v.block*v.blocks:,} B) free={u32(v.hdr,48):,} '
          f'files={u32(v.hdr,32):,} folders={u32(v.hdr,36):,} nextCNID={u32(v.hdr,64):,}')
    for what in FORK_OFF:
        o = FORK_OFF[what]
        logical, exts = v.fork(what)
        tb, clump = u32(v.hdr, o + 12), u32(v.hdr, o + 8)
        last = max((s + c for s, c in exts), default=0)
        need = -(-logical // v.block)
        flag = ' OUTSIDE VOLUME' if last > v.blocks else ''
        if need > tb:
            flag += f'  totalBlocks {tb:,} < size/block {need:,} -> MapFileBlockC EINVAL'
        print(f'   {what:17} logical={logical:>13,} clump={clump:>10,} totalBlocks={tb:>7,} '
              f'resident={sum(c for _, c in exts):>6,} lastBlock={last:,}{flag}')

    t, dirs, files, threads = v.scan_catalog()
    print(f"catalog: nodeSize={t['nodeSize']} depth={t['depth']} root={t['root']} "
          f"nodes={t['totalNodes']:,} leafRecords={t['leafRecords']:,} firstLeaf={t['firstLeaf']} "
          f"lastLeaf={t['lastLeaf']} keyCompare=0x{t['keyCompareType']:02x} attrs=0x{t['attributes']:x}")
    print(f'   parsed: {len(dirs):,} folders {len(files):,} files {len(threads):,} threads')
    if a.forks:
        bad = 0
        for cnid, (clump, tb, rlogical, rclump, rtb) in sorted(v._fileFork.items()):
            logical, _ = v._fileExt[cnid]
            need = -(-logical // v.block)
            if need != tb:
                bad += 1
                if bad <= 10:
                    print(f'   MISMATCH cnid={cnid:>7} {path_of(v, cnid, dirs, files, threads):52} '
                          f'size={logical:>12,} need={need:>7,} totalBlocks={tb:>7,} rsrc={rtb}')
        print(f'   {bad:,} of {len(v._fileFork):,} file records carry totalBlocks != ceil(size/block); '
              f'hfs_getnewvnode returns EINVAL when size/block > totalBlocks')
        for cnid in (3, 4, 6, 7, 8):
            rec = v._fileFork.get(cnid)
            print(f'   system cnid={cnid}: ' +
                  (f'clump={rec[0]:,} totalBlocks={rec[1]:,} rsrc={rec[4]:,} '
                   f'exts={v._fileExt[cnid][1]}' if rec else 'NO CATALOG RECORD'))
    if a.walk:
        walk(v, t, a.paths, dirs, files)
    kids = {}
    for (parent, name), cnid in list(dirs.items()) + list(files.items()):
        kids.setdefault(parent, []).append(name)

    for p in a.paths:
        cnid = 2
        miss = None
        for part in [x for x in p.split('/') if x]:
            nxt = dirs.get((cnid, part), files.get((cnid, part)))
            if nxt is None:
                miss = (cnid, part)
                break
            cnid = nxt
        if miss:
            print(f'   {p:46} MISSING under {path_of(v, miss[0], dirs, files, threads)}: '
                  f'{sorted(kids.get(miss[0], []))[:12]}')
            continue
        line = f'   {p:46} cnid={cnid} dir={path_of(v, cnid, dirs, files, threads)}'
        ext = v.ext_of(cnid)
        if ext:
            logical, exts = ext
            last = max((s + c for s, c in exts), default=0)
            head = v.read(exts, 0, 16) if exts else b''
            line += (f' size={logical:,} ext0={exts[0] if exts else None} last={last:,}'
                     f'{" OUTSIDE" if last > v.blocks else ""} magic={head[:4].hex()}')
            fork = v._fileFork.get(cnid)
            if fork:
                need = -(-logical // v.block)
                line += (f' totalBlocks={fork[1]:,} need={need:,}'
                         f'{" !!! hfs_getnewvnode EINVAL" if need > fork[1] else ""}')
        print(line)


if __name__ == '__main__':
    main()

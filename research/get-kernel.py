"""Install the CI-built kernel from the xnu-kernel-artifact branch and prove
what is actually in it.

The Actions artifact API needs a token we do not have (401), so xnu.yml pushes
each build to the single-commit branch `xnu-kernel-artifact` instead -- a plain
git fetch reaches it.  Booting %TEMP%\\kernel.development.sweet without checking
it is what cost a day: every 2026-10-29 run used the Oct-27 build, so the
"patched kernel" conclusions were observations about an unpatched kernel.

So: fetch, then verify.  Hard requirement is the 0047 console-ring symbols,
because tools/qemu-sweet.py reads them out of guest RAM to produce
console.txt.  Everything else is reported, not required: each printf literal
our patches add is looked for in the binary, which is what shows whether the
diagnostics you are about to boot are actually in it.

    python research/get-kernel.py            # fetch + verify + install
    python research/get-kernel.py --check    # verify the installed file only
"""
import argparse, importlib.util, os, re, subprocess, sys, pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
DEST = pathlib.Path(os.environ['LOCALAPPDATA']) / 'Temp' / 'kernel.development.sweet'
BRANCH = 'xnu-kernel-artifact'
NEEDED = ('_sweet_log_ring', '_sweet_log_total')   # tools/qemu-sweet.py console.txt
STR = re.compile(r'(?:printf|kprintf|IOLog)\(\s*"([^"]{8,}?)(?:%|\\n)')


def patch_log_lines():
    """Log literals our xnu/patches/*.patch files add, with their patch."""
    out = []
    for p in sorted((REPO / 'xnu' / 'patches').glob('*.patch')):
        for line in p.read_text(encoding='utf-8', errors='surrogateescape').splitlines():
            if line.startswith('+') and not line.startswith('+++'):
                for m in STR.finditer(line[1:]):
                    text = m.group(1).rstrip()
                    if len(text) >= 8:
                        out.append((p.name, text))
    return out


def macho_syms(kernel):
    spec = importlib.util.spec_from_file_location('qemu_sweet', REPO / 'tools' / 'qemu-sweet.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {n: v for v, n in mod.macho_defined_syms(str(kernel))}


def report(kernel):
    blob = kernel.read_bytes()
    at = blob.find(b'Darwin Kernel Version ')
    banner = blob[at:].split(b'\0', 1)[0].decode(errors='replace') if at >= 0 else '? (no banner)'
    print(f'kernel : {kernel}')
    print(f'         {len(blob):,} bytes   {banner}')

    try:
        syms = macho_syms(kernel)
    except Exception as exc:
        print(f'symbols: unreadable ({exc})')
        return False
    ok = True
    for name in NEEDED:
        if name in syms:
            print(f'symbol : {name} = 0x{syms[name]:x}')
        else:
            print(f'symbol : {name} MISSING -> no console.txt from this kernel')
            ok = False

    want = patch_log_lines()
    missing = [(p, s) for p, s in want if s.encode() not in blob]
    print(f'patched log lines: {len(want) - len(missing)}/{len(want)} present in the binary')
    for p, s in missing:
        print(f'   absent  {p[:34]:34} {s[:60]!r}')
    return ok


def fetch():
    r = subprocess.run(['git', '-C', str(REPO), 'fetch', '-q', '--depth', '1',
        'origin', f'refs/heads/{BRANCH}'], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f'fetch of {BRANCH} failed -- is the xnu CI run finished?\n{r.stderr.strip()}')
    listing = subprocess.run(['git', '-C', str(REPO), 'ls-tree', '-r', '--name-only', 'FETCH_HEAD'],
        capture_output=True, text=True, check=True).stdout.splitlines()
    kernels = [p for p in listing if os.path.basename(p).startswith('kernel.')]
    if not kernels:
        sys.exit(f'no kernel.* on {BRANCH}: {listing[:5]}')
    sha = subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'FETCH_HEAD'],
        capture_output=True, text=True, check=True).stdout.strip()
    print(f'{BRANCH} @ {sha[:10]} -> {kernels[0]}')
    with open(DEST, 'wb') as out:
        subprocess.run(['git', '-C', str(REPO), 'cat-file', 'blob', f'FETCH_HEAD:{kernels[0]}'],
            stdout=out, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='verify the installed kernel only')
    args = ap.parse_args()
    if not args.check:
        fetch()
    if not DEST.exists():
        sys.exit(f'{DEST} missing')
    if not report(DEST):
        sys.exit('\nrefusing: this kernel cannot support the harness -- do not trust a run with it')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Boot a SWEETXNU payload (tools/mkpayload.py) in QEMU's virt board.

  qemu-sweet.py PAYLOAD OUTDIR [--secs N] [--gdb] [--live-serial]

Does what shim/loader.c does on the phone, but on the host: places the
kernel segments, ADT and boot_args at their physical addresses and starts
the CPU at a 6-instruction stub that jumps to the entry with x0 = boot_args.
virt RAM starts at 0x40000000; with 4G it covers the phone's framebuffer
(0x9c000000) and the kernel's phys_base (0xb0000000) as plain memory.

After N seconds (or when the guest stops) it writes into OUTDIR:
  fb.png     the 1080x2400 framebuffer (what the phone screen would show)
  regs.txt   QEMU's view of CPU state
  qemu.log   exceptions with ESR/FAR/ELR (-d int,guest_errors)

With --kernel KERNEL (the matching unstripped Mach-O), also decode the
framebuffer using its iso_font into fb.txt and write result.json. This is a
snapshot of the circular screen, not a complete boot log. --fail-on-panic
returns 2 when a panic is visible; absence of a panic does not prove boot.
An undecodable or blank screen returns 3 with --fail-on-panic.
"""
import argparse, json, os, shutil, socket, struct, subprocess, sys, time, zlib

FB_BASE, FB_W, FB_H = 0x9c000000, 1080, 2400
FB_STRIDE = FB_W * 4
PAGE = 0x4000
STUB_PA = 0x40200000	# above the dtb QEMU places at RAM base
BOOT_LINE_LENGTH = 608


def check_qemu_dependency(cpu='cortex-a76'):
    """Verify qemu-system-aarch64 binary and CPU model support."""
    qemu_bin = shutil.which('qemu-system-aarch64')
    if not qemu_bin:
        print('[!] Error: qemu-system-aarch64 not found in PATH.', file=sys.stderr)
        print('    Install instructions:', file=sys.stderr)
        print('      Arch Linux:    sudo pacman -S qemu-system-aarch64', file=sys.stderr)
        print('      Ubuntu/Debian: sudo apt install qemu-system-arm', file=sys.stderr)
        print('      Fedora:         sudo dnf install qemu-system-aarch64', file=sys.stderr)
        print('      macOS:          brew install qemu', file=sys.stderr)
        return False
    try:
        ver = subprocess.check_output([qemu_bin, '--version'], text=True).splitlines()[0]
        print(f'[*] Found QEMU: {ver}', file=sys.stderr)
    except Exception as e:
        print(f'[!] Warning: Failed to query QEMU version: {e}', file=sys.stderr)
        return False

    try:
        cpu_list = subprocess.check_output([qemu_bin, '-M', 'virt', '-cpu', 'help'], text=True)
        if cpu in cpu_list:
            print(f'[*] CPU model {cpu} supported', file=sys.stderr)
        else:
            print(f'[!] Warning: CPU model {cpu} not explicitly listed in qemu-system-aarch64 -cpu help', file=sys.stderr)
    except Exception:
        pass
    return True


def macho_defined_syms(path):
    """(address, name) for every N_SECT symbol in a Mach-O64 — replaces llvm-nm."""
    import bisect  # noqa: F401  (kept local to this feature)
    data = open(path, 'rb').read()
    magic, = struct.unpack_from('<I', data, 0)
    if magic != 0xfeedfacf:
        raise ValueError(f'not Mach-O64: {magic:#010x}')
    ncmds, = struct.unpack_from('<I', data, 16)
    symtab = None
    off = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', data, off)
        if cmd == 0x2:  # LC_SYMTAB
            symoff, nsyms, stroff, strsize = struct.unpack_from('<4I', data, off + 8)
            symtab = (symoff, nsyms, stroff)
        off += cmdsize
    if not symtab:
        raise ValueError('no LC_SYMTAB (stripped)')
    symoff, nsyms, stroff = symtab
    syms = []
    for i in range(nsyms):
        strx, typ, sect, desc, value = struct.unpack_from('<IBBHQ', data, symoff + i * 16)
        if value == 0 or strx == 0 or not typ & 0x0e:  # N_SECT = defined in section
            continue
        end = data.index(b'\0', stroff + strx)
        syms.append((value, data[stroff + strx:end].decode('utf-8', 'replace')))
    return syms


def check_kernel_tools(kernel_path):
    """Verify the kernel file exists; symbol lookup is built in (no llvm-nm needed)."""
    if not os.path.isfile(kernel_path):
        print(f'[!] Error: kernel file does not exist: {kernel_path}', file=sys.stderr)
        return False
    try:
        fonts = [v for v, n in macho_defined_syms(kernel_path) if n == '_iso_font']
    except ValueError as e:
        print(f'[!] Error: {kernel_path}: {e}', file=sys.stderr)
        return False
    if len(fonts) != 1:
        print(f'[!] Error: kernel must contain exactly one _iso_font symbol (found {len(fonts)})',
              file=sys.stderr)
        return False
    return True


class Payload:
    """A SWEETXNU payload on disk; segments are copied out by file offset, so
    a multi-gigabyte ramdisk never has to be read into memory."""

    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f:
            head = f.read(0x2a8 + 32 * 64)	# header + segment table
        magic, ver, nsegs = struct.unpack_from('<8sII', head, 0)
        assert magic == b'SWEETXNU' and ver == 1, 'not a SWEETXNU v1 payload'
        self.nsegs = nsegs
        (self.virt_base, self.entry_va, self.adt_off, self.adt_size,
         self.kernel_end, self.phys_base, self.mem_size) = struct.unpack_from('<7Q', head, 0x10)
        self.cmdline = head[0x48:0x48 + BOOT_LINE_LENGTH]
        self.segs = [struct.unpack_from('<4Q', head, 0x2a8 + 32 * i) for i in range(nsegs)]

    def read_at(self, off, size):
        with open(self.path, 'rb') as f:
            f.seek(off)
            data = f.read(size)
        if len(data) != size:
            raise ValueError('payload truncated')
        return data

    def data_by_va(self, va, size):
        """Read initialized segment bytes by VA (the payload has no slide)."""
        for vmaddr, vmsize, foff, fsize in self.segs:
            if vmaddr <= va and va + size <= vmaddr + fsize:
                return self.read_at(foff + va - vmaddr, size)
        raise ValueError(f'VA {va:#x}+{size:#x} not in initialized payload segments')

    def copy_to(self, dst, off, size, chunk=8 << 20):
        with open(self.path, 'rb') as f:
            f.seek(off)
            while size:
                data = f.read(min(chunk, size))
                if not data:
                    raise ValueError('payload truncated')
                dst.write(data)
                size -= len(data)


def build_image(p, rambin):
    """Stream the payload into rambin; returns (phys_base, boot_args_pa, entry_pa, top)."""
    delta = p.phys_base - p.virt_base
    adt_pa = p.kernel_end + delta
    ba_pa = (adt_pa + p.adt_size + PAGE - 1) & ~(PAGE - 1)
    top = ba_pa + PAGE
    with open(rambin, 'wb') as out:
        out.truncate(top - p.phys_base)
        for vmaddr, vmsize, foff, fsize in p.segs:
            out.seek(vmaddr + delta - p.phys_base)
            p.copy_to(out, foff, fsize)
        out.seek(adt_pa - p.phys_base)
        p.copy_to(out, p.adt_off, p.adt_size)
        ba = struct.pack('<HH4x4Q6QI4xQI', 2, 2, p.virt_base, p.phys_base, p.mem_size, top,
                         FB_BASE, 1, FB_STRIDE, FB_W, FB_H, 32, 0, adt_pa - delta, p.adt_size)
        ba += p.cmdline + b'\0' * 4 + struct.pack('<QQ', 0, p.mem_size)
        assert len(ba) == 736
        out.seek(ba_pa - p.phys_base)
        out.write(ba)
    return p.phys_base, ba_pa, p.entry_va + delta, top


def stub(ba_pa, entry_pa):
    # ldr x0, =ba ; ldr x1, =entry ; br x1 ; nop ; .quad ba ; .quad entry
    return struct.pack('<4I2Q', 0x58000080, 0x580000a1, 0xd61f0020, 0xd503201f, ba_pa, entry_pa)


def write_png(path, raw):
    rows = []
    for y in range(FB_H):
        line = raw[y * FB_STRIDE:(y + 1) * FB_STRIDE]
        rgb = bytearray(FB_W * 3)	# a8r8g8b8 little endian = B G R A in memory
        rgb[0::3], rgb[1::3], rgb[2::3] = line[2::4], line[1::4], line[0::4]
        rows.append(b'\0' + bytes(rgb))
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', FB_W, FB_H, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(b''.join(rows), 6)) + chunk(b'IEND', b'')
    open(path, 'wb').write(png)


def decode_screen(raw, font):
    """Exact glyph matching for pe_serial.c's 2x, white-on-black fbcon."""
    glyphs = {font[c * 16:(c + 1) * 16]: chr(c) for c in range(32, 127)}
    rows, unknown = [], 0
    for row in range(FB_H // 32):
        chars = []
        for col in range(FB_W // 16):
            glyph = bytearray(16)
            for y in range(16):
                offset = (row * 32 + y * 2) * FB_STRIDE + col * 16 * 4
                for x in range(8):
                    if raw[offset + x * 8:offset + x * 8 + 4] == b'\xff' * 4:
                        glyph[y] |= 1 << x
            key = bytes(glyph)
            char = glyphs.get(key, '?')
            unknown += key not in glyphs
            chars.append(char)
        rows.append(''.join(chars).rstrip())
    return '\n'.join(rows).rstrip() + '\n', unknown


def screen_result(screen, unknown):
    if 'panic(cpu ' in screen or 'SWEET EARLY PANIC:' in screen:
        status = 'panic'
    elif unknown:
        status = 'incomplete_decode'
    elif screen.strip():
        status = 'no_panic_observed'
    else:
        status = 'blank_screen'
    return {'status': status, 'unknown_glyphs': unknown, 'snapshot_only': True}


def qmp(target, *cmds, pmemsave=None):
    """Run QEMU human-monitor commands over QMP (synchronous, unlike the echoing HMP socket)."""
    if isinstance(target, tuple):	# Windows: this Python build has no AF_UNIX, QEMU gets a TCP port
        s = socket.create_connection(target, timeout=30)
    else:
        s = socket.socket(socket.AF_UNIX)
        s.connect(target)
    f = s.makefile('rw')
    f.readline()

    def call(execute, **args):
        f.write(json.dumps({'execute': execute, 'arguments': args}) + '\n')
        f.flush()
        while True:
            r = json.loads(f.readline())
            if 'return' in r or 'error' in r:
                return r

    call('qmp_capabilities')
    out = []
    for c in cmds:
        r = call('human-monitor-command', **{'command-line': c})
        if 'error' in r:
            print(f'qmp {c!r}: {r["error"]}', file=sys.stderr)
        out.append(r.get('return', ''))
    if pmemsave:	# native QMP: HMP's argument parser chokes on '-' in paths
        r = call('pmemsave', val=pmemsave[0], size=pmemsave[1], filename=pmemsave[2])
        if 'error' in r:
            print(f'qmp pmemsave: {r["error"]}', file=sys.stderr)
    s.close()
    return out


def stream_serial_file(serial_path, file_pos, out_stream=sys.stdout):
    """Read newly appended content from serial.txt and write directly to stream."""
    if not os.path.exists(serial_path):
        return file_pos
    try:
        with open(serial_path, 'r', errors='replace') as f:
            f.seek(file_pos)
            data = f.read()
            if data:
                out_stream.write(data)
                out_stream.flush()
                return f.tell()
    except Exception:
        pass
    return file_pos


def main():
    ap = argparse.ArgumentParser(
        description="Boot a SWEETXNU payload in QEMU's virt board.",
        epilog="Examples:\n"
               "  qemu-sweet.py payload.bin out/\n"
               "  qemu-sweet.py payload.bin out/ --live-serial\n"
               "  qemu-sweet.py payload.bin out/ --kernel kernel.macho --fail-on-panic\n"
               "  qemu-sweet.py --check-env\n",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument('payload', nargs='?', help='SWEETXNU payload binary (from mkpayload.py)')
    ap.add_argument('outdir', nargs='?', help='Output directory for fb.png, regs.txt, and logs')
    ap.add_argument('--secs', type=float, default=20, help='Duration to run QEMU in seconds (default: 20)')
    ap.add_argument('--gdb', action='store_true', help='start halted, gdb stub on :1234, no timeout')
    ap.add_argument('--hmp', action='append', default=[], help='extra monitor command run after stop (repeatable), e.g. "x /8gx 0xfffffe..."')
    ap.add_argument('--cpu', default='cortex-a76', help='QEMU CPU model (default: cortex-a76)')
    ap.add_argument('--kernel', help='matching unstripped kernel, for exact framebuffer text decoding (built-in Mach-O nm)')
    ap.add_argument('--fail-on-panic', action='store_true', help='exit 2 for a visible panic, 3 for incomplete/blank decoding; requires --kernel')
    ap.add_argument('--live-serial', action='store_true', help='stream serial console output to stdout in real time')
    ap.add_argument('--check-env', action='store_true', help='check QEMU installation and dependencies without running a payload')
    a = ap.parse_args()

    if a.check_env:
        ok = check_qemu_dependency(a.cpu)
        print('[*] Mach-O symbol lookup is built into qemu-sweet.py (no llvm-nm needed)', file=sys.stderr)
        return 0 if ok else 1

    if not a.payload or not a.outdir:
        ap.error('payload and outdir are required unless --check-env is specified')

    if a.fail_on_panic and not a.kernel:
        ap.error('--fail-on-panic requires --kernel')

    if not check_qemu_dependency(a.cpu):
        return 1

    if a.kernel and not check_kernel_tools(a.kernel):
        return 1

    p = Payload(a.payload)
    font = None
    if a.kernel:
        fonts = [v for v, n in macho_defined_syms(a.kernel) if n == '_iso_font']
        if len(fonts) != 1:
            ap.error('kernel must contain exactly one _iso_font symbol')
        font = p.data_by_va(fonts[0], 256 * 16)
    os.makedirs(a.outdir, exist_ok=True)
    out = os.path.abspath(a.outdir)

    phys_base, ba_pa, entry_pa, top = build_image(p, f'{out}/ram.bin')
    open(f'{out}/stub.bin', 'wb').write(stub(ba_pa, entry_pa))
    print(f'phys_base={phys_base:#x} boot_args={ba_pa:#x} entry={entry_pa:#x} top={top:#x}',
          file=sys.stderr)

    if os.name == 'nt':
        with socket.socket() as probe:	# free TCP port for QMP (no AF_UNIX on Windows builds)
            probe.bind(('127.0.0.1', 0))
            mon = ('127.0.0.1', probe.getsockname()[1])
        qmp_arg = f'tcp:{mon[0]}:{mon[1]},server,nowait'
    else:
        mon = f'{out}/mon.sock'
        if os.path.exists(mon):
            os.unlink(mon)
        qmp_arg = f'unix:{mon},server,nowait'
    # virt RAM starts at 0x40000000. It must cover both the kernel's declared
    # RAM (phys_base + mem_size) and everything loaded into it — a multi-GB
    # ramdisk pushes `top` (ADT + boot_args end) past the declared RAM end.
    mem_size = p.mem_size
    ram_gib = max(4, -(-(max(phys_base + mem_size, top) - 0x40000000) // (1 << 30)))
    cmd = ['qemu-system-aarch64', '-M', 'virt,gic-version=3', '-cpu', a.cpu, '-smp', '1', '-m', f'{ram_gib}G',
           '-nographic', '-serial', f'file:{out}/serial.txt', '-qmp', qmp_arg,
           '-d', 'int,guest_errors,unimp', '-D', f'{out}/qemu.log', '-no-reboot',
           '-device', f'loader,file={out}/ram.bin,addr={phys_base:#x},force-raw=on',
           '-device', f'loader,file={out}/stub.bin,addr={STUB_PA:#x},force-raw=on',
           '-device', f'loader,addr={STUB_PA:#x},cpu-num=0']
    if a.gdb:
        cmd += ['-S', '-gdb', 'tcp::1234']

    p = None
    serial_file = f'{out}/serial.txt'
    serial_pos = 0

    try:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL)
        if a.gdb:
            print('gdb stub on :1234; QMP socket:', mon, file=sys.stderr)
            p.wait()
            return 0

        t0 = time.time()
        while p.poll() is None and time.time() - t0 < a.secs:
            if a.live_serial:
                serial_pos = stream_serial_file(serial_file, serial_pos)
            time.sleep(0.2)

        if a.live_serial:
            stream_serial_file(serial_file, serial_pos)

        result = {'status': 'qemu_exited', 'qemu_returncode': p.returncode}
        if p.poll() is None:
            _, regs, *extra = qmp(mon, 'stop', 'info registers', *a.hmp, pmemsave=(FB_BASE, FB_STRIDE * FB_H, f'{out}/fb.raw'))
            open(f'{out}/regs.txt', 'w').write(regs + ''.join(f'\n(qemu) {c}\n{r}' for c, r in zip(a.hmp, extra)))
            p.kill()
            p.wait()
            raw = open(f'{out}/fb.raw', 'rb').read()
            write_png(f'{out}/fb.png', raw)
            result = {'status': 'not_decoded'}
            if font is not None:
                screen, unknown = decode_screen(raw, font)
                open(f'{out}/fb.txt', 'w').write(screen)
                result = screen_result(screen, unknown)
            os.unlink(f'{out}/fb.raw')
        else:
            print(f'qemu exited early: {p.returncode}', file=sys.stderr)

        open(f'{out}/result.json', 'w').write(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), file=sys.stderr)
        print(f'{out}/fb.png  {out}/regs.txt  {out}/qemu.log', file=sys.stderr)
        if a.fail_on_panic and result['status'] == 'panic':
            return 2
        if a.fail_on_panic and result['status'] in ('incomplete_decode', 'blank_screen'):
            return 3
        if result['status'] == 'qemu_exited':
            return 1
        return 0

    except KeyboardInterrupt:
        print('\n[!] Interrupted by user, stopping QEMU...', file=sys.stderr)
        if p and p.poll() is None:
            p.kill()
            p.wait()
        return 130
    finally:
        ram_file = f'{out}/ram.bin'
        if os.path.exists(ram_file):
            try:
                os.unlink(ram_file)
            except Exception:
                pass


if __name__ == '__main__':
    sys.exit(main())

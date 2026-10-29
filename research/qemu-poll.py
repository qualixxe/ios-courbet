"""Poll the XNU framebuffer console during a QEMU run and decode it.

The panic screen only shows the last ~75 lines: earlier console output
(e.g. "load_init_program: failed loading ... errno 22") is scrolled away
by the panic dump. This script freezes the CPU with -S, releases it with
`cont` and snapshots the fbcon rapidly so the whole boot console history
can be reconstructed.

Usage:
  python research/qemu-poll.py PAYLOAD OUTDIR SECS KERNEL
"""
import importlib.util
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
QS = os.path.join(HERE, '..', 'tools', 'qemu-sweet.py')
spec = importlib.util.spec_from_file_location('qs', QS)
qs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qs)

# QEMU answers QMP only after the 6 GB ramdisk finishes loading into guest RAM
# (~30 s); qemu-sweet.py's default 30 s socket timeout is too tight for that.
_orig_create_connection = socket.create_connection


def _slow_create_connection(target, timeout=30, *a, **kw):
    return _orig_create_connection(target, 180, *a, **kw)


socket.create_connection = _slow_create_connection


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        return 1
    payload, outdir, secs, kernel = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    fast_until = float(os.environ.get('POLL_FAST_SECS', '120'))
    fast_iv = float(os.environ.get('POLL_FAST_INTERVAL', '0.06'))
    slow_iv = float(os.environ.get('POLL_SLOW_INTERVAL', '0.5'))
    os.makedirs(outdir, exist_ok=True)
    out = os.path.abspath(outdir)

    p = qs.Payload(payload)
    fonts = [v for v, n in qs.macho_defined_syms(kernel) if n == '_iso_font']
    if len(fonts) != 1:
        print(f'kernel must contain exactly one _iso_font (found {len(fonts)})', file=sys.stderr)
        return 1
    font = p.data_by_va(fonts[0], 256 * 16)

    phys_base, ba_pa, entry_pa, top = qs.build_image(p, f'{out}/ram.bin')
    open(f'{out}/stub.bin', 'wb').write(qs.stub(ba_pa, entry_pa))
    print(f'phys_base={phys_base:#x} boot_args={ba_pa:#x} entry={entry_pa:#x} top={top:#x}',
          file=sys.stderr)

    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        mon = ('127.0.0.1', probe.getsockname()[1])
    qmp_arg = f'tcp:{mon[0]}:{mon[1]},server,nowait'

    mem_size = p.mem_size
    ram_gib = max(4, -(-(max(phys_base + mem_size, top) - 0x40000000) // (1 << 30)))
    cmd = ['qemu-system-aarch64', '-M', 'virt,gic-version=3', '-cpu', 'cortex-a76',
           '-smp', '1', '-m', f'{ram_gib}G', '-S',
           '-nographic', '-serial', f'file:{out}/serial.txt', '-qmp', qmp_arg,
           '-d', 'int,guest_errors,unimp', '-D', f'{out}/qemu.log', '-no-reboot',
           '-device', f'loader,file={out}/ram.bin,addr={phys_base:#x},force-raw=on',
           '-device', f'loader,file={out}/stub.bin,addr={qs.STUB_PA:#x},force-raw=on',
           '-device', f'loader,addr={qs.STUB_PA:#x},cpu-num=0']

    poll_dir = os.path.join(out, 'poll')
    os.makedirs(poll_dir, exist_ok=True)

    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL)
    t_start = time.time()
    frame = 0
    saved = 0
    last_text = None
    try:
        # Wait for QMP to come up (blocking), then release the CPU.
        qs.qmp(mon)
        qs.qmp(mon, 'cont')
        t0 = time.time()
        print(f'qmp ready after {t0-t_start:.1f}s; CPU released', file=sys.stderr)
        while proc.poll() is None and time.time() - t0 < secs:
            elapsed = time.time() - t0
            time.sleep(fast_iv if elapsed < fast_until else slow_iv)
            raw_path = os.path.join(poll_dir, 'fb_tmp.raw')
            try:
                qs.qmp(mon, pmemsave=(qs.FB_BASE, qs.FB_STRIDE * qs.FB_H, raw_path))
                raw = open(raw_path, 'rb').read()
                if len(raw) == qs.FB_STRIDE * qs.FB_H:
                    screen, unknown = qs.decode_screen(raw, font)
                    if screen != last_text:
                        with open(os.path.join(poll_dir, f'fb_{saved:03d}.txt'), 'w',
                                  encoding='utf-8') as f:
                            f.write(screen)
                        print(f'saved {saved:03d} t={elapsed:6.2f}s unknown={unknown} '
                              f'lines={screen.count(chr(10))}', file=sys.stderr)
                        last_text = screen
                        saved += 1
                if os.path.exists(raw_path):
                    os.unlink(raw_path)
            except Exception as e:  # noqa: BLE001 - keep polling
                print(f'poll {frame}: {e}', file=sys.stderr)
            frame += 1
            if frame > 5000:
                break
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        try:
            os.unlink(f'{out}/ram.bin')
        except OSError:
            pass

    print(f'polls={frame} saved={saved}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())

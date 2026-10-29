import struct, sys

img_path = sys.argv[1] if len(sys.argv) > 1 else 'research/qemu-fullroot.img'
f = open(img_path, 'rb')

# Volume header at offset 1024
f.seek(1024)
vh = f.read(1024)
sig = vh[0:2]
print(f'Signature: {sig} ({sig.hex()})')
if sig not in (b'H+', b'HX'):
    print('Not an HFS+/HFSX volume at offset 1024')
    sys.exit(1)

block_size = struct.unpack_from('>I', vh, 36)[0]
total_blocks = struct.unpack_from('>I', vh, 40)[0]
print(f'Block size: {block_size}, Total blocks: {total_blocks}')
print(f'Volume size: {block_size * total_blocks / 1024 / 1024 / 1024:.2f} GB')

# Catalog file CNID = 5, find its extents
# Volume header doesn't directly store catalog extents; they're in the extent records
# Let's find catalog file by scanning catalog node records
# Actually, let's just search for common filenames in the volume

f.close()

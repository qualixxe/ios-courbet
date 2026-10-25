# tools/aosp — vendored AOSP `mkbootimg`

`mkbootimg.py` is **unmodified** AOSP source, taken from

```
https://android.googlesource.com/platform/system/tools/mkbootimg
refs/tags/android-12.0.0_r1
```

SHA256 of the file as committed:

```
2a8d05d34110f66c463668f43fc812ce2e46e66459c347eaadb080271df69aa8
```

License: Apache-2.0 (the header is part of the file).

## Why it is vendored

`shim/build.sh` packs the shim into an Android boot image (header v2). On a
normal Linux box that comes from `android-tools`; on the CI runner there is no
such package and **`mkbootimg` does not exist on PyPI** (`pip install mkbootimg`
fails with "No matching distribution found"). Rather than fetch from the network
on every run, the single-file script lives here.

It is `android-12.0.0_r1` on purpose: `android-13.0.0_r1` and newer import
`gki.generate_gki_certificate`, which needs the rest of the AOSP tree. The v2
header format is unchanged between them.

`mkbootimg` (no extension) is a three-line wrapper that runs the script with
`python3`, so `command -v mkbootimg` succeeds after adding this directory to
`PATH`. CI does that in `.github/workflows/shim.yml`; a local build should use
the system `mkbootimg` from `android-tools` instead.

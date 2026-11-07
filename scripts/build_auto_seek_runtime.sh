#!/usr/bin/env bash
# Build Auto Seek's ONNX Runtime bundles for musl (Stash's Docker image is
# Alpine): Alpine's own onnxruntime package and every library it needs except
# musl itself, flattened into one tarball per architecture. Nothing is
# executed for the foreign architecture; dependencies are read with scanelf.
#
#   scripts/build_auto_seek_runtime.sh [out-dir]
#
# Upload the tarballs to the auto-seek-runtime-v1 release and copy the printed
# sha256 and size into RUNTIMES in auto-seek/auto_seek.py.
set -euo pipefail
ALPINE=3.23
OUT=$(realpath "${1:-dist/auto-seek-runtime}")
mkdir -p "$OUT"
for ARCH in x86_64 aarch64 armv7; do
  docker run --rm -v "$OUT:/out" -e ARCH="$ARCH" -e ALPINE="$ALPINE" "alpine:$ALPINE" sh -euc '
    apk add -q pax-utils tar >/dev/null
    R=/target
    apk add -q --root $R --arch $ARCH --initdb --allow-untrusted --no-scripts \
      -X https://dl-cdn.alpinelinux.org/alpine/v$ALPINE/main \
      -X https://dl-cdn.alpinelinux.org/alpine/v$ALPINE/community onnxruntime >/dev/null
    find_lib() { for d in $R/usr/lib $R/lib; do [ -e "$d/$1" ] && { echo "$d/$1"; return; }; done; }
    todo=$(find_lib libonnxruntime.so.1); seen=""
    while [ -n "$todo" ]; do
      set -- $todo; lib=$1; shift; todo="$*"
      case " $seen " in *" $lib "*) continue;; esac
      seen="$seen $lib"
      for n in $(scanelf -qnF "%n" "$lib" | cut -d" " -f1 | tr "," " "); do
        case $n in libc.musl*|ld-musl*) continue;; esac
        p=$(find_lib "$n"); [ -n "$p" ] || { echo "missing $n" >&2; exit 1; }
        todo="$todo $p"
      done
    done
    B=/bundle; mkdir $B
    for lib in $seen; do cp -L "$lib" "$B/$(basename "$lib")"; done
    mv $B/libonnxruntime.so.1 $B/libonnxruntime.so
    apk --root $R info -v 2>/dev/null | sort > $B/PACKAGES.txt
    cat > $B/NOTICE.txt <<NOTE
ONNX Runtime and its libraries as packaged by Alpine Linux $ALPINE ($ARCH),
unchanged. Each package keeps its own licence; see PACKAGES.txt and
https://pkgs.alpinelinux.org/packages?branch=v$ALPINE&arch=$ARCH
NOTE
    tar -C $B --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -cf - . | gzip -n9 > /out/onnxruntime-alpine-$ALPINE-$ARCH.tar.gz
    echo "$ARCH: $(ls $B | wc -l) files"
  '
done
cd "$OUT" && for f in onnxruntime-alpine-*.tar.gz; do echo "$f $(sha256sum "$f" | cut -d" " -f1) $(stat -c %s "$f")"; done

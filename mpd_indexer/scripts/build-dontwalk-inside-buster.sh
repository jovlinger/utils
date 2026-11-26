#!/bin/bash
# Runs INSIDE debian:buster. Cross-builds dont-walk MPD for SHD Neo3
# (armhf userland, glibc 2.28). Expects /src (MPD tree) and /out mounted.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

cat >/etc/apt/sources.list <<'SRC'
deb http://archive.debian.org/debian buster main
deb http://archive.debian.org/debian-security buster/updates main
SRC
echo 'Acquire::Check-Valid-Until "false";' >/etc/apt/apt.conf.d/99archive

dpkg --add-architecture armhf
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  ca-certificates python3 python3-pip python3-setuptools python3-wheel \
  g++ gcc g++-arm-linux-gnueabihf gcc-arm-linux-gnueabihf pkg-config \
  ninja-build git \
  libflac-dev:armhf libasound2-dev:armhf libsoxr-dev:armhf \
  libcurl4-gnutls-dev:armhf zlib1g-dev:armhf libpcre3-dev:armhf \
  libicu-dev:armhf libboost-dev:armhf libogg-dev:armhf \
  libsystemd-dev:armhf libsqlite3-dev:armhf \
  libavcodec-dev:armhf libavformat-dev:armhf libavutil-dev:armhf \
  libavfilter-dev:armhf libswresample-dev:armhf \
  libmad0-dev:armhf libmpg123-dev:armhf \
  libvorbis-dev:armhf libopus-dev:armhf \
  libid3tag0-dev:armhf

pip3 install -q "meson==0.61.2"

cat >/tmp/armhf.ini <<'EOF'
[binaries]
c = 'arm-linux-gnueabihf-gcc'
cpp = 'arm-linux-gnueabihf-g++'
ar = 'arm-linux-gnueabihf-ar'
strip = 'arm-linux-gnueabihf-strip'
pkgconfig = 'arm-linux-gnueabihf-pkg-config'

[host_machine]
system = 'linux'
cpu_family = 'arm'
cpu = 'armv7l'
endian = 'little'
EOF

cp -a /src /tmp/mpd-src
cd /tmp/mpd-src
rm -rf build
export PKG_CONFIG_LIBDIR=/usr/lib/arm-linux-gnueabihf/pkgconfig

# Volumio-shaped feature set (not "slim"): notify + playback plugins.
meson setup build --cross-file /tmp/armhf.ini \
  --buildtype=release \
  -Dauto_features=disabled \
  -Dalsa=enabled \
  -Dflac=enabled \
  -Dsoxr=enabled \
  -Dcurl=enabled \
  -Dzlib=enabled \
  -Dicu=enabled \
  -Dsystemd=enabled \
  -Dffmpeg=enabled \
  -Dmad=enabled \
  -Dmpg123=enabled \
  -Dvorbis=enabled \
  -Dopus=enabled \
  -Did3tag=enabled \
  -Dsqlite=enabled \
  -Ddatabase=true \
  -Dcue=true \
  -Ddaemon=true \
  -Dtcp=true \
  -Dfifo=true \
  -Dinotify=true \
  -Ddocumentation=disabled \
  -Dhtml_manual=false \
  -Dmanpages=false \
  --force-fallback-for=fmt

ninja -C build
arm-linux-gnueabihf-strip -s build/mpd
cp -a build/mpd /out/mpd
ls -la /out/mpd
arm-linux-gnueabihf-readelf -d /out/mpd | grep NEEDED | head -40

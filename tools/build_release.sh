#!/usr/bin/env bash
# Build everything for a release into dist/:
#   kolibri_games-<v>-py3-none-any.whl      the plugin
#   kolibri_games-<v>.tar.gz                source
#   games/*.zim                              the sample games, ready for Kolibri Studio
#   kolibri-games-<v>-offline.tar.gz         plugin + libzim wheels for Raspberry Pi and PCs + install.sh
#   SHA256SUMS
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="$(python -c 'import kolibri_games; print(kolibri_games.__version__)')"
rm -rf dist build
python -m build

kolibri-games-pack games/* --out-dir dist/games

BUNDLE="dist/kolibri-games-$VERSION-offline"
mkdir -p "$BUNDLE/wheels" "$BUNDLE/games"
cp dist/kolibri_games-"$VERSION"-py3-none-any.whl "$BUNDLE/wheels/"
cp dist/games/*.zim "$BUNDLE/games/"
cp install.sh "$BUNDLE/"
for py in 3.8 3.9 3.10 3.11 3.12 3.13; do
  abi="cp${py/./}"
  for arch in x86_64 aarch64; do
    pip download "libzim>=3.1" --only-binary=:all: --no-deps -d "$BUNDLE/wheels" \
      --python-version "$py" --implementation cp --abi "$abi" \
      --platform "manylinux_2_28_$arch" --platform "manylinux_2_17_$arch" --platform "manylinux2014_$arch" \
      >/dev/null 2>&1 && echo "libzim for Python $py $arch: ok" || echo "libzim for Python $py $arch: not available"
  done
done
cat > "$BUNDLE/README.txt" <<EOF
Kolibri Games $VERSION - offline installer

1. Copy this folder to the Kolibri server (for example on a USB stick).
2. In a terminal on the server, go into this folder and run:

     sudo ./install.sh

   It finds Kolibri, installs or updates the plugin from the wheels/ folder,
   updates the database, and restarts Kolibri.

3. The games/ folder has sample games. Copy .zim files into Kolibri's games
   folder (shown at the end of the install), or upload them to a channel in
   Kolibri Studio.

https://github.com/togetherings/kolibri-games
EOF
tar -czf "dist/kolibri-games-$VERSION-offline.tar.gz" -C dist "kolibri-games-$VERSION-offline"
rm -rf "$BUNDLE"

(cd dist && sha256sum ./*.whl ./*.tar.gz games/*.zim > SHA256SUMS)
echo "Release files:"
ls -l dist dist/games

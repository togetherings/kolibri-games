#!/usr/bin/env bash
# Kolibri Games installer and updater.
#
# Installs (or updates) the Kolibri Games plugin into the Kolibri already on
# this machine, e.g. on Internet-in-a-Box. Safe to run again: it updates to the
# newest release and leaves your games and results alone.
#
#   Online:   curl -fsSL https://raw.githubusercontent.com/togetherings/kolibri-games/main/install.sh | sudo bash
#   Version:  ... | sudo bash -s -- --version 0.1.0
#   Offline:  unpack the offline bundle, then:  sudo ./install.sh
#   Remove:   sudo ./install.sh --uninstall
#
# Options:
#   --version X     install release X instead of the newest one
#   --wheel FILE    install this wheel file
#   --bundle DIR    install from an offline bundle folder (contains wheels/)
#   --home DIR      Kolibri's home folder (default: detected; IIAB uses /library/kolibri)
#   --user NAME     user Kolibri runs as (default: detected; usually kolibri)
#   --no-restart    don't restart the Kolibri service
#   --uninstall     disable and remove the plugin (results stay in Kolibri's database)
set -euo pipefail

REPO="togetherings/kolibri-games"
PACKAGE="kolibri-games"
PLUGIN="kolibri_games"
VERSION=""
WHEEL=""
BUNDLE=""
KHOME=""
KUSER=""
RESTART=1
UNINSTALL=0

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf 'Warning: %s\n' "$*" >&2; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="${2#v}"; shift 2 ;;
    --wheel) WHEEL="$2"; shift 2 ;;
    --bundle) BUNDLE="$2"; shift 2 ;;
    --home) KHOME="$2"; shift 2 ;;
    --user) KUSER="$2"; shift 2 ;;
    --no-restart) RESTART=0; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) sed -n '2,24p' "$0" 2>/dev/null || echo "See https://github.com/$REPO"; exit 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

[ "$(id -u)" -eq 0 ] || die "Please run as root, e.g. with sudo."

# An offline bundle has a wheels/ folder next to this script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd || pwd)"
if [ -z "$BUNDLE" ] && [ -z "$WHEEL" ] && [ -d "$SCRIPT_DIR/wheels" ]; then
  BUNDLE="$SCRIPT_DIR"
fi

# ------------------------------------------------------------------ Kolibri

KBIN="$(command -v kolibri || true)"
[ -n "$KBIN" ] || die "Kolibri isn't installed (no 'kolibri' command found)."

# Use the same Python that runs Kolibri.
PY=""
SHEBANG="$(head -1 "$KBIN" 2>/dev/null || true)"
case "$SHEBANG" in
  "#!"*env\ *) PY="$(command -v "$(echo "$SHEBANG" | awk '{print $2}')" || true)" ;;
  "#!"*) PY="$(echo "${SHEBANG#\#!}" | awk '{print $1}')" ;;
esac
[ -n "$PY" ] && [ -x "$PY" ] || PY="$(command -v python3)"
KVER="$("$PY" -c 'import kolibri; print(kolibri.__version__)' 2>/dev/null)" \
  || die "Couldn't load Kolibri with $PY."

# Where Kolibri keeps its data, and which user runs it.
if command -v systemctl >/dev/null 2>&1 && systemctl cat kolibri >/dev/null 2>&1; then
  for kv in $(systemctl show kolibri -p Environment --value 2>/dev/null); do
    case "$kv" in
      KOLIBRI_HOME=*) [ -n "$KHOME" ] || KHOME="${kv#*=}" ;;
      KOLIBRI_USER=*) [ -n "$KUSER" ] || KUSER="${kv#*=}" ;;
    esac
  done
  [ -n "$KUSER" ] || KUSER="$(systemctl show kolibri -p User --value 2>/dev/null || true)"
fi
if [ -z "$KHOME" ] && [ -f /etc/kolibri/daemon.conf ]; then
  KHOME="$(sed -n 's/^ *\(export \)\{0,1\}KOLIBRI_HOME="\{0,1\}\([^"]*\)"\{0,1\} *$/\2/p' /etc/kolibri/daemon.conf | tail -1)"
fi
if [ -z "$KUSER" ] && [ -f /etc/kolibri/username ]; then
  KUSER="$(tr -d '[:space:]' < /etc/kolibri/username)"
fi
[ -n "$KUSER" ] || KUSER="kolibri"
id "$KUSER" >/dev/null 2>&1 || die "User '$KUSER' doesn't exist. Use --user to say which user runs Kolibri."
if [ -z "$KHOME" ]; then
  KHOME="$(getent passwd "$KUSER" | cut -d: -f6)/.kolibri"
fi
[ -d "$KHOME" ] || die "Kolibri's home folder $KHOME doesn't exist. Use --home to point to it."

run_kolibri() {
  if [ "$KUSER" = "root" ]; then
    env KOLIBRI_HOME="$KHOME" "$KBIN" "$@"
  elif command -v runuser >/dev/null 2>&1; then
    runuser -u "$KUSER" -- env KOLIBRI_HOME="$KHOME" "$KBIN" "$@"
  else
    sudo -u "$KUSER" env KOLIBRI_HOME="$KHOME" "$KBIN" "$@"
  fi
}

say "Kolibri $KVER (Python: $PY, home: $KHOME, user: $KUSER)"

# ---------------------------------------------------------------------- pip

if ! "$PY" -m pip --version >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    say "Installing pip"
    apt-get install -y python3-pip >/dev/null
  fi
  "$PY" -m pip --version >/dev/null 2>&1 || die "pip isn't available for $PY."
fi
PIP_FLAGS=(--disable-pip-version-check)
if "$PY" -m pip install --help 2>/dev/null | grep -q -- '--break-system-packages'; then
  # Kolibri on IIAB runs on the system Python, so the plugin has to go there too.
  PIP_FLAGS+=(--break-system-packages)
fi
if "$PY" -m pip install --help 2>/dev/null | grep -q -- '--root-user-action'; then
  PIP_FLAGS+=(--root-user-action=ignore)
fi

PREVIOUS="$("$PY" -m pip show "$PACKAGE" 2>/dev/null | sed -n 's/^Version: //p' || true)"

restart_kolibri() {
  if [ "$RESTART" -eq 1 ] && command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet kolibri; then
    say "Restarting Kolibri (this can take a minute)"
    systemctl restart kolibri
  elif [ "$RESTART" -eq 1 ]; then
    warn "Kolibri isn't running as a service here, so restart it yourself."
  fi
}

# ---------------------------------------------------------------- uninstall

if [ "$UNINSTALL" -eq 1 ]; then
  [ -n "$PREVIOUS" ] || die "Kolibri Games isn't installed."
  say "Disabling and removing Kolibri Games $PREVIOUS"
  run_kolibri plugin disable "$PLUGIN" || true
  "$PY" -m pip uninstall -y "${PIP_FLAGS[@]}" "$PACKAGE"
  restart_kolibri
  say "Removed. Game results are still in Kolibri's database if you reinstall later."
  exit 0
fi

# ------------------------------------------------------------- what to get

if [ -n "$WHEEL" ]; then
  [ -f "$WHEEL" ] || die "No such file: $WHEEL"
  SPEC=("$WHEEL")
  SOURCE="file $WHEEL"
elif [ -n "$BUNDLE" ]; then
  ls "$BUNDLE"/wheels/kolibri_games-*.whl >/dev/null 2>&1 || die "No kolibri_games wheel in $BUNDLE/wheels."
  SPEC=(--no-index --find-links "$BUNDLE/wheels" "$PACKAGE")
  SOURCE="offline bundle $BUNDLE"
else
  command -v curl >/dev/null 2>&1 || die "curl is needed to download the plugin."
  if [ -z "$VERSION" ]; then
    LATEST="$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/$REPO/releases/latest")" \
      || die "Couldn't reach GitHub. Check the internet connection, or use the offline bundle."
    VERSION="${LATEST##*/}"
    VERSION="${VERSION#v}"
    case "$VERSION" in
      [0-9]*) ;;
      *) die "No releases of Kolibri Games found yet." ;;
    esac
  fi
  SPEC=("https://github.com/$REPO/releases/download/v$VERSION/kolibri_games-$VERSION-py3-none-any.whl")
  SOURCE="release $VERSION"
fi

# ------------------------------------------------------------------ install

if [ -n "$PREVIOUS" ]; then
  say "Updating Kolibri Games $PREVIOUS from $SOURCE"
  say "Backing up Kolibri's database first"
  run_kolibri manage dbbackup || warn "The database backup didn't work; continuing anyway."
else
  say "Installing Kolibri Games from $SOURCE"
fi

rollback() {
  warn "Something went wrong."
  if [ -n "$PREVIOUS" ]; then
    warn "Putting back Kolibri Games $PREVIOUS."
    "$PY" -m pip install "${PIP_FLAGS[@]}" "$PACKAGE==$PREVIOUS" >/dev/null 2>&1 \
      || warn "Couldn't reinstall $PREVIOUS automatically. Run this script with --version $PREVIOUS."
    warn "If the database needs restoring, use: kolibri manage dbrestore --latest"
  fi
  exit 1
}
trap rollback ERR

"$PY" -m pip install --upgrade "${PIP_FLAGS[@]}" "${SPEC[@]}"
NEW="$("$PY" -m pip show "$PACKAGE" | sed -n 's/^Version: //p')"

# libzim lets Wiki BLAZE read Wikipedia .zim files. The other games work
# without it, so a failure here only gives a warning.
if [ -n "$BUNDLE" ]; then
  LIBZIM_SPEC=(--no-index --find-links "$BUNDLE/wheels" "libzim>=3.1")
else
  LIBZIM_SPEC=("libzim>=3.1")
fi
"$PY" -m pip install "${PIP_FLAGS[@]}" "${LIBZIM_SPEC[@]}" >/dev/null 2>&1 \
  || warn "Couldn't install libzim, which Wiki BLAZE needs to read Wikipedia. The other games work without it."

say "Enabling the plugin and updating the database"
run_kolibri plugin enable "$PLUGIN"
run_kolibri manage migrate --noinput

mkdir -p "$KHOME/kolibri_games/games"
chown "$KUSER" "$KHOME/kolibri_games" "$KHOME/kolibri_games/games" 2>/dev/null || true

say "Checking the setup"
run_kolibri manage kolibri_games_check
trap - ERR

restart_kolibri
say "Kolibri Games $NEW is installed."
echo "Install Free-play Games on the games page: open Games in Kolibri's menu, then Setup."
echo "(Game .zip files are attached to each release. You can also copy them into"
echo "  $KHOME/kolibri_games/games )"
echo "Classroom Games come in Kolibri channels, like any other resource."

#!/bin/bash
# Build dist/MiniDict.app. The bundle wraps this checkout's venv, so rebuild
# after moving the project; for a self-contained bundle use py2app/PyInstaller.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
VENV_PYTHON="$ROOT/.venv/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "venv python not found: $VENV_PYTHON" >&2
    exit 1
fi

APP="dist/MiniDict.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

"$VENV_PYTHON" scripts/make_icon.py "$APP/Contents/Resources/MiniDict.icns" ||
    echo "warning: icon generation failed, the app uses the default icon" >&2

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>MiniDict</string>
    <key>CFBundleDisplayName</key><string>MiniDict</string>
    <key>CFBundleIdentifier</key><string>com.qdcchh.minidict</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>CFBundleShortVersionString</key><string>1.0.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>MiniDict</string>
    <key>CFBundleIconFile</key><string>MiniDict</string>
    <key>LSUIElement</key><true/>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/MiniDict" <<LAUNCHER
#!/bin/bash
# Paths are baked at build time; run scripts/build_app.sh again after moving.
exec "$VENV_PYTHON" "$ROOT/gui.py" >>/tmp/minidict.log 2>&1
LAUNCHER
chmod +x "$APP/Contents/MacOS/MiniDict"

echo "built: $ROOT/$APP"

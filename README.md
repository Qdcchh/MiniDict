# MiniDict

A lightweight macOS Dictionary applacation written in python,please download the ECDICT database to data/

## Goal

- Global hotkey
- Fast local dictionary look up
- Chinese → English reverse lookup (paste a Chinese word to see English candidates)
- Minimal UI
- Offline support

## Build the macOS app

```bash
./scripts/build_app.sh
```

Produces `dist/MiniDict.app`: no Dock icon (LSUIElement), resident in the
menu bar (「译」), ⌥D or the menu bar icon summons the window, and the red
close button only hides it. The bundle wraps this checkout's venv — rebuild
after moving the project or switching machines; logs go to /tmp/minidict.log.

# somni desktop

Electron wrapper around the somni web UI. Produces:

- `somni.exe` — opens somni in a native Windows window. Spawns `server.py` in the background.
- `installer.exe` — wizard that copies `somni.exe` + resources to a user-chosen install dir.

The desktop app **still requires Python 3.x** at runtime (it shells out to `server.py`). The web version's setup also requires Python — same story.

---

## Layout

```
desktop/
├── somni-app/                  ← Electron project: somni.exe
│   ├── main.js                 spawns server.py, opens window
│   └── package.json
├── installer-app/              ← Electron project: installer.exe
│   ├── main.js                 wizard backend (IPC handlers)
│   ├── preload.js              window.somni.* bridge
│   ├── installer.html          wizard UI
│   └── package.json
├── build-all.bat               builds both apps + assembles setup folder
└── dist/                       (output, gitignored)
    ├── somni-app/win-unpacked/
    ├── installer-app/win-unpacked/
    └── setup/                  ← contents of this folder become the release zip
        ├── installer.exe       installer + its Electron runtime
        └── somni-app/          somni.exe + its Electron runtime (copied to install dir)
```

## What ships to users

The `dist/setup/` folder becomes your **somni-desktop-setup-vX.Y.Z.zip**. Inside:

```
installer.exe                    ← user double-clicks this
chrome_100_percent.pak           (electron runtime files)
...
resources/                       installer.exe's own resources
somni-app/
  somni.exe                      (copied to install dir during install)
  chrome_100_percent.pak         (somni.exe's electron runtime)
  ...
  resources/
    app.asar
    server.py
    index.html
    icon.png / icon.ico
    version.txt
    README.md / LICENSE
```

After install, the user's install dir contains everything from `somni-app/` plus a generated `resources/somni_config.json` and (optionally) `launch_comfyui_and_somni.bat`.

---

## Build prerequisites

- **Node.js 18+** (https://nodejs.org)
- **Windows 10/11** (electron-builder produces Windows binaries; cross-compilation from Linux/macOS works but is fiddly)

## Build

From this folder:

```cmd
build-all.bat
```

That runs `npm install` and `npm run dist` for both sub-projects, then assembles `dist/setup/`. First run downloads ~150 MB of Electron — subsequent builds are fast.

To zip:

```cmd
cd dist\setup
tar -a -c -f ..\somni-desktop-setup-v1.0.1.zip *
```

Or just right-click → Send to → Compressed (zipped) folder on the **contents** of `setup/` (not the folder itself).

## Dev

To run somni-app without packaging:

```cmd
cd somni-app
npm install
npm start
```

Note: it'll try to find `server.py` at `process.resourcesPath`, which won't exist in dev mode — you'll see an error. For full dev testing, build and run the packaged `somni.exe` from `dist/somni-app/win-unpacked/`.

To run installer-app without packaging:

```cmd
cd installer-app
npm install
npm start
```

The installer's "Install" button will fail in dev mode because it expects to find `somni-app/` next to `installer.exe`. To test installs end-to-end, run `build-all.bat` and use the packaged `installer.exe` from `dist/setup/`.

---

## Per-release checklist

1. Bump `version.txt` in the repo root.
2. Update `version` in both `somni-app/package.json` and `installer-app/package.json` to match.
3. Run `build-all.bat`.
4. Zip the contents of `dist/setup/`.
5. Upload as a release asset alongside (or instead of) the web setup zip.

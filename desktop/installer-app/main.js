// somni desktop installer — Electron main process.
// Walks user through path config, then copies the bundled "somni-app/" payload
// into the chosen install dir and writes somni_config.json.
const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path  = require('path');
const fs    = require('fs');
const { spawn } = require('child_process');

// In a packaged build, this is the folder containing installer.exe/appimage.
const APP_ROOT  = path.dirname(process.execPath);
// The somni payload — the somni-app build, copied alongside the installer
// at zip-time. See build-win.bat / build-linux.sh.
const PAYLOAD   = path.join(APP_ROOT, 'somni-app');

// Detect platform and set executable name
const IS_LINUX = process.platform === 'linux';
const SOMNI_EXE = IS_LINUX ? 'somni.AppImage' : 'somni.exe';

let mainWindow = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 880,
    height: 760,
    minWidth: 640,
    minHeight: 600,
    title: 'somni installer',
    backgroundColor: '#161618',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadFile(path.join(__dirname, 'installer.html'));
}

// ── IPC: detect ──────────────────────────────────────────────────────
ipcMain.handle('detect', () => {
  const guesses = IS_LINUX ? [
    '/home/' + (process.env.USER || 'user') + '/ComfyUI',
    '/opt/ComfyUI',
  ] : [
    'C:\\ComfyUI',
    'D:\\ComfyUI',
    path.join(process.env.USERPROFILE || '', 'ComfyUI'),
    path.join(process.env.USERPROFILE || '', 'Documents', 'ComfyUI'),
  ];
  let guessedComfy = '';
  for (const c of guesses) {
    if (c && fs.existsSync(path.join(c, 'main.py'))) { guessedComfy = c; break; }
  }
  return {
    payloadOk:   fs.existsSync(PAYLOAD) && fs.existsSync(path.join(PAYLOAD, SOMNI_EXE)),
    payloadDir:  PAYLOAD,
    guessedComfy,
    defaultInstall: guessedComfy ? path.join(guessedComfy, 'somni') : '',
  };
});

// ── IPC: verify-comfy ────────────────────────────────────────────────
ipcMain.handle('verify-comfy', (_e, p) => {
  const norm = (p || '').trim().replace(/^["']|["']$/g, '');
  if (!norm) return { ok: false, reason: 'Please enter a path.' };
  if (!fs.existsSync(norm)) return { ok: false, reason: 'Folder does not exist.' };
  if (!fs.existsSync(path.join(norm, 'main.py')))
    return { ok: false, reason: "main.py not found — doesn't look like ComfyUI." };
  const portable = fs.existsSync(path.join(norm, 'python_embeded', 'python.exe'));
  return { ok: true, path: norm, portable };
});

// ── IPC: verify-venv ─────────────────────────────────────────────────
ipcMain.handle('verify-venv', (_e, p) => {
  const norm = (p || '').trim().replace(/^["']|["']$/g, '');
  if (!norm) return { ok: false, reason: 'Provide a venv folder path.' };
  if (!fs.existsSync(norm)) return { ok: false, reason: 'Folder does not exist.' };
  
  if (IS_LINUX) {
    const activate = path.join(norm, 'bin', 'activate');
    const pyexe    = path.join(norm, 'bin', 'python');
    if (fs.existsSync(activate) && fs.existsSync(pyexe))
      return { ok: true, path: norm, activate, python: pyexe };
    return { ok: false, reason: 'No bin/activate / bin/python inside.' };
  } else {
    const activate = path.join(norm, 'Scripts', 'activate.bat');
    const pyexe    = path.join(norm, 'Scripts', 'python.exe');
    if (fs.existsSync(activate) && fs.existsSync(pyexe))
      return { ok: true, path: norm, activate, python: pyexe };
    return { ok: false, reason: 'No Scripts\\activate.bat / python.exe inside.' };
  }
});

// ── IPC: verify-install ──────────────────────────────────────────────
ipcMain.handle('verify-install', (_e, p) => {
  const norm = (p || '').trim().replace(/^["']|["']$/g, '');
  if (!norm) return { ok: false, reason: 'Provide an install path.' };
  if (fs.existsSync(norm))
    return { ok: true, path: norm, note: 'Folder exists. Files will be overwritten as needed.' };
  return { ok: true, path: norm, note: 'Folder will be created.' };
});

// ── IPC: pick-dir (native folder picker) ─────────────────────────────
ipcMain.handle('pick-dir', async (_e, def) => {
  const r = await dialog.showOpenDialog(mainWindow, {
    title: 'Choose folder',
    defaultPath: def || undefined,
    properties: ['openDirectory', 'createDirectory'],
  });
  if (r.canceled || !r.filePaths.length) return '';
  return r.filePaths[0];
});

// ── Helpers: recursive copy ──────────────────────────────────────────
function copyRecursive(src, dst) {
  const st = fs.statSync(src);
  if (st.isDirectory()) {
    if (!fs.existsSync(dst)) fs.mkdirSync(dst, { recursive: true });
    for (const item of fs.readdirSync(src)) {
      copyRecursive(path.join(src, item), path.join(dst, item));
    }
  } else {
    fs.copyFileSync(src, dst);
  }
}

// ── IPC: install ─────────────────────────────────────────────────────
ipcMain.handle('install', async (_e, cfg) => {
  try {
    if (!fs.existsSync(PAYLOAD) || !fs.existsSync(path.join(PAYLOAD, SOMNI_EXE)))
      throw new Error(`somni-app payload not found at:\n${PAYLOAD}\nThis installer was packaged incorrectly.`);

    const comfyDir   = (cfg.comfyDir || '').trim();
    const pythonMode = cfg.pythonMode || 'system';
    const venvDir    = (cfg.venvDir || '').trim();
    const installDir = (cfg.installDir || '').trim();
    const openOnLaunch = !!cfg.openBrowser;
    const bootDelay  = parseInt(cfg.bootDelay, 10) || 8;

    if (!fs.existsSync(path.join(comfyDir, 'main.py')))
      throw new Error('ComfyUI path is not valid.');
    if (!installDir) throw new Error('Install path is missing.');
    
    if (IS_LINUX) {
      if (pythonMode === 'venv' && !fs.existsSync(path.join(venvDir, 'bin', 'python')))
        throw new Error('Virtual env is not valid.');
    } else {
      if (pythonMode === 'venv' && !fs.existsSync(path.join(venvDir, 'Scripts', 'python.exe')))
        throw new Error('Virtual env is not valid.');
      if (pythonMode === 'portable' && !fs.existsSync(path.join(comfyDir, 'python_embeded', 'python.exe')))
        throw new Error('Portable Python not found inside the ComfyUI folder.');
    }

    // 1. Copy the somni-app payload into the install dir.
    fs.mkdirSync(installDir, { recursive: true });
    for (const item of fs.readdirSync(PAYLOAD)) {
      copyRecursive(path.join(PAYLOAD, item), path.join(installDir, item));
    }

    // 2. Choose the Python the server.py will run under.
    let somniPython;
    if (IS_LINUX) {
      if (pythonMode === 'portable')
        somniPython = path.join(comfyDir, 'python_embeded', 'python');
      else if (pythonMode === 'venv')
        somniPython = path.join(venvDir, 'bin', 'python');
      else
        somniPython = 'python3';
    } else {
      if (pythonMode === 'portable')
        somniPython = path.join(comfyDir, 'python_embeded', 'python.exe');
      else if (pythonMode === 'venv')
        somniPython = path.join(venvDir, 'Scripts', 'python.exe');
      else
        somniPython = 'python';
    }

    // 3. Write somni_config.json into <installDir>/resources/
    const resourcesDir = path.join(installDir, 'resources');
    fs.mkdirSync(resourcesDir, { recursive: true });
    const config = {
      comfyDir, pythonMode,
      venvDir: pythonMode === 'venv' ? venvDir : '',
      installDir,
      openBrowser: openOnLaunch,
      bootDelay,
      somniPython,
    };
    fs.writeFileSync(path.join(resourcesDir, 'somni_config.json'),
                     JSON.stringify(config, null, 2));

    return {
      ok: true,
      installDir,
      files: [SOMNI_EXE, 'resources/'],
    };
  } catch (e) {
    return { ok: false, error: e.message };
  }
});

// ── IPC: launch somni after install ──────────────────────────────────
ipcMain.handle('launch-somni', (_e, installDir) => {
  const exe = path.join(installDir, SOMNI_EXE);
  if (!fs.existsSync(exe)) return { ok: false, error: `${SOMNI_EXE} not found.` };
  try {
    // On Linux, make AppImage executable before launching
    if (IS_LINUX) {
      fs.chmodSync(exe, 0o755);
    }
    spawn(exe, [], { cwd: installDir, detached: true, stdio: 'ignore' }).unref();
    return { ok: true };
  } catch (e) { return { ok: false, error: e.message }; }
});

// ── IPC: close ───────────────────────────────────────────────────────
ipcMain.handle('close-window', () => { app.quit(); });

app.whenReady().then(createWindow);
app.on('window-all-closed', () => app.quit());

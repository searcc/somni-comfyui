// somni desktop — Electron wrapper around the existing somni web UI.
// Spawns server.py as a child process, then loads http://localhost:8080.
const { app, BrowserWindow, shell, dialog } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs   = require('fs');
const net  = require('net');

const SOMNI_PORT = 8080;
const RES_DIR    = process.resourcesPath;    // <install-dir>/resources/  (next to somni.exe)
const CONFIG     = path.join(RES_DIR, 'somni_config.json');
const SERVER_PY  = path.join(RES_DIR, 'server.py');
const ICON_PATH  = path.join(RES_DIR, process.platform === 'win32' ? 'icon.ico' : 'icon.png');

let mainWindow = null;
let pyProcess  = null;
let pyExited   = false;

function readConfig() {
  try { return JSON.parse(fs.readFileSync(CONFIG, 'utf-8')); }
  catch { return {}; }
}

function writeConfig(cfg) {
  try { fs.writeFileSync(CONFIG, JSON.stringify(cfg, null, 2)); }
  catch (e) { console.error('Failed to write config:', e); }
}

// Check if config is complete (first run detection)
function needsConfiguration(cfg) {
  return !cfg.comfyDir || !cfg.pythonMode;
}

// Show first-run configuration dialog
async function showConfigurationDialog() {
  const result = await dialog.showMessageBox(null, {
    type: 'question',
    buttons: ['Cancel', 'Configure'],
    defaultId: 1,
    title: 'somni Configuration',
    message: 'Welcome to somni!',
    detail: 'Before using somni, you need to configure it to connect to your ComfyUI installation.\n\nClick "Configure" to set up your ComfyUI directory and Python settings.',
  });

  if (result.response === 0) {
    app.quit();
    return false;
  }

  // Simple folder picker for ComfyUI directory
  const comfyDirResult = await dialog.showOpenDialog(null, {
    title: 'Select ComfyUI Directory',
    properties: ['openDirectory'],
  });

  if (comfyDirResult.canceled || !comfyDirResult.filePaths[0]) {
    app.quit();
    return false;
  }

  const comfyDir = comfyDirResult.filePaths[0];
  const mainPyPath = path.join(comfyDir, 'main.py');

  if (!fs.existsSync(mainPyPath)) {
    await dialog.showErrorBox('Configuration Error', `main.py not found in:\n${comfyDir}\n\nPlease select the correct ComfyUI directory.`);
    app.quit();
    return false;
  }

  // Ask for Python mode
  const pythonModeResult = await dialog.showMessageBox(null, {
    type: 'question',
    buttons: ['ComfyUI Portable', 'Virtual Environment', 'System Python'],
    defaultId: 0,
    title: 'Python Configuration',
    message: 'How do you run ComfyUI?',
    detail: 'Select the Python installation method you use for ComfyUI.',
  });

  let pythonMode = 'portable';
  let venvDir = '';

  if (pythonModeResult.response === 1) {
    pythonMode = 'venv';
    const venvResult = await dialog.showOpenDialog(null, {
      title: 'Select Virtual Environment Directory',
      properties: ['openDirectory'],
    });

    if (venvResult.canceled || !venvResult.filePaths[0]) {
      app.quit();
      return false;
    }

    venvDir = venvResult.filePaths[0];
    const activateBat = path.join(venvDir, 'Scripts', 'activate.bat');

    if (!fs.existsSync(activateBat)) {
      await dialog.showErrorBox('Configuration Error', `Virtual environment not found in:\n${venvDir}\n\nPlease select the correct venv directory.`);
      app.quit();
      return false;
    }
  } else if (pythonModeResult.response === 2) {
    pythonMode = 'system';
  }

  // Save configuration
  const cfg = {
    comfyDir,
    pythonMode,
    venvDir,
    bootDelay: 8,
  };

  writeConfig(cfg);

  // Ask about launch script
  const launchScriptResult = await dialog.showMessageBox(null, {
    type: 'question',
    buttons: ['No', 'Yes'],
    defaultId: 1,
    title: 'Launch Script',
    message: 'Create a launch script?',
    detail: 'Would you like to create a batch file that launches both ComfyUI and somni?',
  });

  if (launchScriptResult.response === 1) {
    const launchScriptPath = path.join(comfyDir, 'launch_comfyui_and_somni.bat');
    let scriptContent = '@echo off\n';
    scriptContent += `cd /d "${comfyDir}"\n`;

    if (pythonMode === 'portable') {
      scriptContent += 'start "" python_embeded\\python.exe main.py\n';
    } else if (pythonMode === 'venv') {
      scriptContent += `call "${venvDir}\\Scripts\\activate.bat"\n`;
      scriptContent += 'python main.py\n';
    } else {
      scriptContent += 'python main.py\n';
    }

    scriptContent += `timeout /t ${cfg.bootDelay} /nobreak >nul\n`;
    scriptContent += `start "" "${path.join(RES_DIR, 'somni.exe')}"\n`;

    try {
      fs.writeFileSync(launchScriptPath, scriptContent);
      await dialog.showMessageBox(null, {
        type: 'info',
        buttons: ['OK'],
        title: 'Launch Script Created',
        message: 'Launch script created successfully!',
        detail: `You can find it at:\n${launchScriptPath}`,
      });
    } catch (e) {
      console.error('Failed to create launch script:', e);
    }
  }

  return true;
}

// Try the saved python from the installer first, fall back to PATH.
function pickPython(cfg) {
  if (cfg.somniPython && fs.existsSync(cfg.somniPython)) return cfg.somniPython;
  return process.platform === 'win32' ? 'python' : 'python3';
}

function isPortOpen(port) {
  return new Promise(resolve => {
    const s = net.createConnection({ port, host: '127.0.0.1' });
    s.once('connect', () => { s.destroy(); resolve(true); });
    s.once('error',   () => resolve(false));
  });
}

async function waitForServer(timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await isPortOpen(SOMNI_PORT)) return true;
    if (pyExited) return false;
    await new Promise(r => setTimeout(r, 150));
  }
  return false;
}

function startServer() {
  const cfg = readConfig();
  const py  = pickPython(cfg);
  if (!fs.existsSync(SERVER_PY)) {
    dialog.showErrorBox('somni', `server.py not found at:\n${SERVER_PY}\n\nReinstall using the installer.`);
    app.quit();
    return;
  }
  pyProcess = spawn(py, [SERVER_PY], {
    cwd: RES_DIR,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  pyProcess.stdout.on('data', d => process.stdout.write(`[server] ${d}`));
  pyProcess.stderr.on('data', d => process.stderr.write(`[server] ${d}`));
  pyProcess.on('exit',  code => { pyExited = true; console.log(`server.py exited with ${code}`); });
  pyProcess.on('error', err  => {
    pyExited = true;
    dialog.showErrorBox('somni', `Failed to start Python: ${err.message}\n\nMake sure Python 3 is installed and on your PATH.`);
    app.quit();
  });
}

function stopServer() {
  if (pyProcess && !pyExited) {
    try {
      if (process.platform === 'win32') {
        spawn('taskkill', ['/pid', pyProcess.pid, '/f', '/t']);
      } else {
        pyProcess.kill('SIGTERM');
      }
    } catch {}
  }
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 720,
    minHeight: 480,
    icon: ICON_PATH,
    title: 'somni',
    backgroundColor: '#161618',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // Show a tiny loading splash while waiting for the Python server.
  mainWindow.loadURL('data:text/html,' + encodeURIComponent(`
    <html><head><style>
      html,body { margin:0; height:100%; background:#161618; color:#80808a;
        font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif;
        display:flex; align-items:center; justify-content:center; flex-direction:column; gap:14px; }
      .icn { font-size: 42px; opacity:0.7; }
      .t   { font-size: 15px; color:#b4b4ba; }
      .s   { font-size: 12.5px; opacity:0.8; }
      @keyframes spin { to { transform: rotate(360deg); } }
      .sp  { width:16px; height:16px; border:2px solid #2e2e33; border-top-color:#fff; border-radius:50%; animation:spin .8s linear infinite; }
    </style></head><body>
      <div class="icn">✦</div>
      <div class="t">Starting somni…</div>
      <div class="sp"></div>
      <div class="s">Booting the local server</div>
    </body></html>
  `));

  const ok = await waitForServer();
  if (!ok) {
    dialog.showErrorBox('somni', 'The local server did not start in time.\nCheck the console for errors.');
    return;
  }
  mainWindow.loadURL(`http://localhost:${SOMNI_PORT}/`);

  // External links open in the user's default browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(`http://localhost:${SOMNI_PORT}`)) {
      shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });
}

app.whenReady().then(async () => {
  const cfg = readConfig();
  
  // Show configuration dialog on first run
  if (needsConfiguration(cfg)) {
    const configured = await showConfigurationDialog();
    if (!configured) return;
  }

  startServer();
  createWindow();
});

app.on('window-all-closed', () => { stopServer(); app.quit(); });
app.on('before-quit',       () => { stopServer(); });

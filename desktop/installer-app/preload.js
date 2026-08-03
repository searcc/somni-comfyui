const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('somni', {
  detect:         ()    => ipcRenderer.invoke('detect'),
  verifyComfy:    (p)   => ipcRenderer.invoke('verify-comfy', p),
  verifyVenv:     (p)   => ipcRenderer.invoke('verify-venv', p),
  verifyInstall:  (p)   => ipcRenderer.invoke('verify-install', p),
  pickDir:        (def) => ipcRenderer.invoke('pick-dir', def),
  install:        (cfg) => ipcRenderer.invoke('install', cfg),
  closeWindow:    ()    => ipcRenderer.invoke('close-window'),
  launchSomni:    (dir) => ipcRenderer.invoke('launch-somni', dir),
});

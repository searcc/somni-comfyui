<div align="center">
  <img src="icon.png" width="80" alt="somni">

  # somni

  **A modern frontend for ComfyUI. Gemini-style easy mode, IP-Adapter support, and built for both desktop and mobile.**

  <sub>Open `index.html` and you'll forget you're using ComfyUI.</sub>
  
  <img src="somni-ui.png" alt="somni UI">
</div>

---

## ✦ What is it

somni is a polished, opinionated frontend that runs alongside your existing ComfyUI install. It talks to ComfyUI over HTTP: your workflows, models, and outputs stay exactly where they are.

- **Easy mode**: a chat-style interface (think Gemini / ChatGPT) for one-prompt-and-go generation
<div align="center">
  <img src="somni-ui-easy.png" width="550" alt="somni UI Easy Mode">
</div>

- **Pro mode**: full sidebar with sampler, scheduler, seed, LoRAs, CFG, advanced options
- **Reference image (IP-Adapter)**: General · Face · FaceID modes with a denoising slider
- **Batch generation**: generate N images, displayed in a scrollable preview
- **Gallery** with full-screen viewer, swipe-to-navigate on mobile, arrow buttons on desktop
- **Favorites**: star any option and its value persists across reloads
- **Mobile-first design**: phone-friendly bottom bar, swipe gestures, tap targets sized properly
- **Smooth animations** everywhere: toggles spring, popovers pop, gallery items stagger in
- **No background services**: runs as a single Python script when you want it, closes when you don't

---

## ✦ Installation

### Requirements

- **ComfyUI** already installed and working ([download here](https://github.com/comfyanonymous/ComfyUI))
- **Python 3.x** in your PATH (same one you'd use to run ComfyUI is fine)
- **Windows** (the launch scripts are `.bat` files; Linux/macOS support is on the roadmap)

### Steps (Web UI)

1. **Download** the latest [release zip](../../releases) and extract it anywhere (e.g. `C:\somni`)
2. **Run `installer.bat`**. Your browser opens to `http://localhost:8081`
3. **Walk through the 4 steps:**
   - Point to your ComfyUI folder
   - Pick how you launch its Python (portable / venv / system)
   - Choose where to install somni (defaults to `<ComfyUI>\somni`)
   - Tick the "open browser on launch" option
4. **Click Install** — somni copies its files and writes two launch scripts
5. **Done.** Run `launch_comfyui_and_somni.bat` (or `launch_somni.bat` if ComfyUI is already running)

That's it. somni opens in your browser at `http://localhost:8080`.

### Steps (Desktop Application)

1. **Download** the latest [Windows release zip](../../releases) and extract it anywhere (e.g. `C:\somni`)
2. **Run `installer.exe`**. An installer window should open
3. **Walk through the 3 steps:**
   - Point to your ComfyUI folder
   - Pick how you launch its Python (portable / venv / system)
   - Choose where to install somni (defaults to `<ComfyUI>\somni`)
4. **Click Install** — somni copies its files and writes a `somni.exe` file
5. **Done.** Launch `somni.exe`

---

## ✦ Using somni from your phone

The launch script binds to `0.0.0.0`, so any device on your Wi-Fi can reach it.

1. Find your PC's local IP (`ipconfig` → look for `IPv4 Address`, usually `192.168.x.x`)
2. On your phone, open `http://<that-ip>:8080`
3. Generate images from the couch

---

## ✦ Reference image (IP-Adapter)

Three modes, three workflows. Each needs specific model files in your ComfyUI install. somni's UI tells you which one is active, but **the models are on you to download**:

| Mode | Needs |
|---|---|
| **General** | `ip-adapter-plus_sdxl_vit-h.safetensors` in `ComfyUI/models/ipadapter/` |
| **Face** | `ip-adapter-plus-face_sdxl_vit-h.safetensors` in `ComfyUI/models/ipadapter/` |
| **FaceID** | `ip-adapter-faceid-plusv2_sdxl.bin` in `ipadapter/`, matching LoRA in `loras/`, plus `pip install insightface onnxruntime` |

All three modes also need:
- `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` in `ComfyUI/models/clip_vision/`
- The [ComfyUI_IPAdapter_plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus) custom node (install via ComfyUI Manager)

Easiest path: open **ComfyUI Manager → Install Models**, search for "ipadapter". Pick what you want.

---

## ✦ Something went wrong?

If somni won't launch:

- **Re-run `installer.bat`** — this won't touch your images or settings, it just regenerates the launch scripts
- **Check the terminal output** when running `launch_somni.bat`. Python errors get printed there
- **Port conflict?** Something else on `:8080` (full ComfyUI desktop app?) close it first
- **MS Store Python stub** intercepting `python`: the installer handles this, but if it slipped through: `Settings → Apps → Advanced app settings → App execution aliases` → turn off the `python.exe` toggles

If you find a bug or want a feature, [open an issue](../../issues).

---

## ✦ How it works (in a nutshell)

```
┌──────────────┐    HTTP/WS     ┌──────────────────┐
│  Your browser│  ───────────▶  │  somni server.py │
└──────────────┘                │  (port 8080)     │
                                └────────┬─────────┘
                                         │  proxies + serves index.html
                                         ▼
                                ┌──────────────────┐
                                │     ComfyUI      │
                                │  (port 8188)     │
                                └──────────────────┘
```

`server.py` is a tiny Python proxy (~200 lines, stdlib only). It serves `index.html` and forwards everything else to ComfyUI, stripping `Origin`/`Referer` headers so ComfyUI's loopback host-check passes. It also adds two endpoints: `/__list` for gallery thumbnails and `/__delete` for delete buttons because vanilla ComfyUI doesn't expose them.

The entire UI is one HTML file. No build step. No npm. No bundler. Open the source and you can change anything.

---

## ✦ Roadmap

- Linux & macOS launch scripts (`.sh`)
- Multi-image reference (IP-Adapter combine mode)
- Workflow presets (save/load custom configurations)
- Inpainting

---

## ✦ License

MIT (see [LICENSE](LICENSE)). Do whatever you want, just don't blame me.

---

<div align="center">
  <sub>Built on top of <a href="https://github.com/comfyanonymous/ComfyUI">ComfyUI</a></sub>
</div>

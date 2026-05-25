module.exports = {
  version: "3.6",
  title: "Voice Studio KH",
  description: "Apple Silicon text-to-speech — VoxCPM, Kokoro, F5-TTS, Chatterbox, Bark, Spark-TTS, XTTS-v2.",
  icon: "icon.png",
  menu: async (kernel, info) => {
    const installed = info.exists("conda_env")
    const generationInstalled = info.exists("conda_env/lib/python3.12/site-packages/transformers") &&
                                info.exists("conda_env/lib/python3.12/site-packages/diffusers")
    const running = {
      install: info.running("install.js"),
      install_generation: info.running("install_generation.js"),
      start: info.running("start.js"),
      update: info.running("update.js"),
      reset: info.running("reset.js")
    }

    if (running.install) {
      return [{ default: true, icon: "fa-solid fa-plug", text: "Installing", href: "install.js" }]
    }
    if (running.install_generation) {
      return [{ default: true, icon: "fa-solid fa-wand-magic-sparkles", text: "Installing Generation", href: "install_generation.js" }]
    }
    if (running.update) {
      return [{ default: true, icon: "fa-solid fa-rotate", text: "Updating", href: "update.js" }]
    }
    if (running.reset) {
      return [{ default: true, icon: "fa-solid fa-broom", text: "Resetting", href: "reset.js" }]
    }

    if (!installed) {
      return [{ default: true, icon: "fa-solid fa-plug", text: "Install", href: "install.js" }]
    }

    if (running.start) {
      const local = info.local("start.js")
      if (local && local.url) {
        // Cache-bust so Pinokio's embedded webview can't keep serving a stale
        // index.html / app.js from a previous launch. menu() is re-run every
        // time Pinokio refreshes the sidebar, so this gives a fresh URL each
        // refresh — clicking "Open UI" always loads a unique URL.
        const cb = Date.now()
        const bust = `?_cb=${cb}`
        // Browser-friendly URL: 0.0.0.0 is server-bind, not client-reachable —
        // the external browser needs localhost. Also pluck the port for compact
        // display in the sidebar so the user can always SEE which port is live.
        const browserUrl = local.url.replace("0.0.0.0", "localhost")
        const portMatch = local.url.match(/:(\d+)/)
        const port = portMatch ? portMatch[1] : "?"
        return [
          { default: true, icon: "fa-solid fa-rocket", text: "Open UI", href: `${local.url}/${bust}` },
          { icon: "fa-solid fa-cube", text: "Models", href: `${local.url}/${bust}#/models` },
          { icon: "fa-solid fa-download", text: "Downloads", href: `${local.url}/${bust}#/downloads` },
          // ── Escape hatch (v1.1.1) ──
          // Always-visible port + one-click open in system default browser.
          // Pinokio's embedded webview occasionally caches a black/blank
          // screen — this lets the user keep working in Chrome/Safari.
          { icon: "fa-solid fa-arrow-up-right-from-square",
            text: `Port ${port} · Open in Browser`,
            href: "open_external.js",
            params: { url: browserUrl } },
          { icon: "fa-solid fa-terminal", text: "Terminal", href: "start.js" },
          { icon: "fa-solid fa-folder-tree", text: "HF Cache", href: "cache/HF_HOME/hub?fs=true" },
          { icon: "fa-solid fa-microphone-lines", text: "Outputs", href: "app/output?fs=true" },
          { icon: "fa-solid fa-wand-magic-sparkles",
            text: generationInstalled ? "Reinstall Generation" : "Install Generation",
            href: "install_generation.js" }
        ]
      }
      return [{ default: true, icon: "fa-solid fa-terminal", text: "Terminal", href: "start.js" }]
    }

    return [
      { default: true, icon: "fa-solid fa-power-off", text: "Start", href: "start.js" },
      { icon: "fa-solid fa-folder-tree", text: "HF Cache", href: "cache/HF_HOME/hub?fs=true" },
      { icon: "fa-solid fa-microphone-lines", text: "Outputs", href: "app/output?fs=true" },
      { icon: "fa-solid fa-wand-magic-sparkles",
        text: generationInstalled ? "Reinstall Generation" : "Install Generation",
        href: "install_generation.js" },
      { icon: "fa-solid fa-rotate", text: "Update", href: "update.js" },
      { icon: "fa-solid fa-plug", text: "Reinstall", href: "install.js" },
      { icon: "fa-regular fa-circle-xmark", text: "Reset", href: "reset.js" }
    ]
  }
}

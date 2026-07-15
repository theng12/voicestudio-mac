// One-click Update — correct in EVERY run mode (launchd service, start.js, or
// stopped). Replaces the old split of "Update" vs "Update & Restart": one button
// pulls the latest code, refreshes deps, and restarts whichever server this
// machine actually runs.
//
// Why this exists: the old flow made users hunt several buttons and often left
// production broken. "Update & Restart" was hardwired to stop/start start.js,
// but in service mode the server IS the launchd service — so it stopped nothing
// and then started a SECOND server that fought the service for the fixed port.
// The restart here is service-aware and mutually exclusive: kickstart the
// service, OR start start.js — never both. Deps install from source
// (requirements*.txt, not the .lock) because a drifted lock can silently omit
// packages.
module.exports = {
  run: [
    {
      // start.js mode: stop it so its Python exits and re-imports after install.
      // Service mode: start.js isn't running (skips) — the service keeps serving
      // through pull+install and only blips at the final kickstart. Stopped: no-op.
      when: "{{running('start.js')}}",
      method: "script.stop",
      params: { uri: "start.js" }
    },
    {
      method: "shell.run",
      params: { message: "git pull" }
    },
    {
      // Base deps (always).
      when: "{{exists('conda_env')}}",
      method: "shell.run",
      params: {
        path: "app",
        conda: { "path": "{{path.resolve(cwd, 'conda_env')}}" },
        message: [
          "python -m pip install --upgrade pip",
          "uv pip install -r requirements.txt"
        ]
      }
    },
    {
      // Generation deps — ONLY if generation is installed here. This is what
      // makes an ML-dep bump land on the SAME Update click (no separate
      // "Reinstall Generation").
      when: "{{exists('conda_env/lib/python3.12/site-packages/diffusers')}}",
      method: "shell.run",
      params: {
        path: "app",
        conda: { "path": "{{path.resolve(cwd, 'conda_env')}}" },
        message: [
          "uv pip install -r requirements-generation.txt"
        ]
      }
    },
    {
      // Restart the REAL server for this machine's mode — mutually exclusive so a
      // second server never fights the service for the fixed port. Use
      // install_service.sh (NOT restart_service.sh): it REWRITES the launchd plist
      // to match the current on-disk scripts before relaunching, so a git pull that
      // renamed the serve script (serve.sh -> <app>-serve.sh) can't leave the plist
      // kickstarting a deleted path. Idempotent + safe to run every update.
      when: "{{exists('service/.installed')}}",
      method: "shell.run",
      params: { message: [ "bash install_service.sh" ] }
    },
    {
      when: "{{!exists('service/.installed')}}",
      method: "script.start",
      params: { uri: "start.js" }
    },
    {
      // Verify generation still imports (if installed). A failure breaks the run
      // here → the success notify is withheld and the terminal shows the error.
      when: "{{exists('conda_env/lib/python3.12/site-packages/diffusers')}}",
      method: "shell.run",
      params: {
        path: "app",
        conda: { "path": "{{path.resolve(cwd, 'conda_env')}}" },
        message: [
          "python -c \"import torch, transformers, diffusers, mlx, mlx_lm, mlx_audio, mistral_common, f5_tts; from importlib.metadata import version; assert version('mistral-common') == '1.11.5'; print('GEN_VERIFY_OK')\" 2>&1"
        ],
        on: [{ event: "/(ModuleNotFoundError|ImportError|Traceback)/", break: true }]
      }
    },
    {
      method: "notify",
      params: { html: "Updated &amp; restarted — you're on the latest version." }
    }
  ]
}

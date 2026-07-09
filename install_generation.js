// Heavy install: adds the TTS generation stack (torch, torchaudio,
// transformers, diffusers, accelerate, plus a few TTS-specific deps) on
// top of the Phase 1 deps. Required before any actual speech can be
// generated. Safe to re-run.
//
// Note: we DELIBERATELY don't install Coqui TTS, audiocraft, or any other
// library that hard-pins torch versions. Each TTS model in our catalog
// either runs on stock transformers/diffusers, or has its own dedicated
// runner that we vendor in `app/backend/voice_engines/<engine>.py`.
//
// Restart flow: if start.js is running when this script fires, we stop
// it first so its Python process exits, then run the install, then start
// it back up. Without the stop+start the long-lived uvicorn worker keeps
// the old sys.modules cache and never sees the freshly installed torch —
// the UI then surfaces "ModuleNotFoundError: No module named 'torch'"
// even though pip succeeded. Auto-restarting removes the manual
// "Stop → Start" step users used to have to remember.
module.exports = {
  requires: {
    bundle: "ai"
  },
  run: [
    {
      when: "{{running('start.js')}}",
      method: "script.stop",
      params: { uri: "start.js" }
    },
    {
      method: "shell.run",
      params: {
        path: "app",
        conda: {
          "path": "{{path.resolve(cwd, 'conda_env')}}"
        },
        message: [
          // Fully-pinned lock of the ENTIRE verified env (phase 1 + generation) —
          // converges everything to known-good versions.
          "uv pip install -r requirements-generation.lock.txt"
        ]
      }
    },
    {
      method: "script.start",
      params: { uri: "start.js" }
    },
    {
      method: "notify",
      params: {
        html: "TTS generation engine installed. Server restarted — Generate is ready."
      }
    }
  ]
}

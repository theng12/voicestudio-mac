// Heavy install: adds the TTS generation stack (torch, torchaudio,
// transformers, diffusers, accelerate, plus a few TTS-specific deps) on
// top of the Phase 1 deps. Required before any actual speech can be
// generated. Safe to re-run.
//
// Note: we DELIBERATELY don't install Coqui TTS, audiocraft, or any other
// library that hard-pins torch versions. Each TTS model in our catalog
// either runs on stock transformers/diffusers, or has its own dedicated
// runner that we vendor in `app/backend/voice_engines/<engine>.py`.
module.exports = {
  requires: {
    bundle: "ai"
  },
  run: [
    {
      method: "shell.run",
      params: {
        path: "app",
        conda: {
          "path": "{{path.resolve(cwd, 'conda_env')}}"
        },
        message: [
          "uv pip install -r requirements-generation.txt"
        ]
      }
    },
    {
      method: "notify",
      params: {
        html: "TTS generation engine installed. Restart the server (Stop → Start) to enable the Generate tab."
      }
    }
  ]
}

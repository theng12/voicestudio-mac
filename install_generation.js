// Heavy install: adds the generation stack to the existing conda_env. Required
// for any generation endpoint to work. Safe to run more than once.
//
// SOURCE-FIRST (not the lock): install from `requirements-generation.txt`, the
// authoritative range file that actually lists the heavy deps. We deliberately
// do NOT install `requirements-generation.lock.txt` — a drifted lock once
// shipped containing ONLY base web-server packages, so "Install Generation"
// installed nothing, generation silently never worked, and the UI still
// reported success. Installing from source can't have that failure mode.
//
// VERIFY-THEN-NOTIFY: after installing we import the key modules. A failure
// prints a traceback, the matcher breaks the run, and the success notify never
// fires. The old script fired it unconditionally — telling users it worked even
// on total failure.
//
// Restart flow: stop the server first so its Python re-imports the freshly
// installed packages, then restart whichever server this machine runs (launchd
// service if installed, otherwise start.js).
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
        conda: { "path": "{{path.resolve(cwd, 'conda_env')}}" },
        message: [
          "uv pip install -r requirements-generation.txt"
        ]
      }
    },
    {
      method: "shell.run",
      params: {
        path: "app",
        conda: { "path": "{{path.resolve(cwd, 'conda_env')}}" },
        message: [
          "python -c \"import torch, transformers, diffusers, mlx, mlx_lm, mlx_audio, mistral_common, f5_tts, fugashi, jieba; from importlib.metadata import version; from misaki.ja import JAG2P; from misaki.zh import ZHG2P; assert version('mistral-common') == '1.11.5'; JAG2P(); ZHG2P(); print('GEN_VERIFY_OK')\" 2>&1"
        ],
        on: [{ event: "/(ModuleNotFoundError|ImportError|Traceback)/", break: true }]
      }
    },
    {
      // install_service.sh (not restart_service.sh) rewrites the launchd plist to
      // the current on-disk serve script before relaunching — robust to the
      // serve.sh -> <app>-serve.sh rename. Idempotent.
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
      method: "notify",
      params: {
        html: "Generation engine installed &amp; verified. Server restarted — ready."
      }
    }
  ]
}

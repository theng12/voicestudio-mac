// Heavy install: adds the generation stack to the existing conda_env. Required
// for any generation endpoint to work. Safe to run more than once.
//
// SOURCE-FIRST (not the lock): the fixed convergence command installs from
// `requirements-generation.txt`, the authoritative range file that actually
// lists the heavy deps. We deliberately do NOT use
// `requirements-generation.lock.txt` — a drifted lock once shipped containing
// ONLY base web-server packages, so "Install Generation" installed nothing.
//
// VERIFY-THEN-NOTIFY: the fixed command imports the key modules after
// installation. A failure ends this run before the success notification.
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
      params: { uri: "{{path.resolve(cwd, 'start.js')}}" }
    },
    {
      method: "shell.run",
      params: {
        path: "app",
        conda: { "path": "{{path.resolve(cwd, 'conda_env')}}" },
        message: [
          "python -m backend.dependency_convergence generation"
        ]
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

module.exports = {
  daemon: true,
  run: [
    {
      method: "shell.run",
      params: {
        path: "app",
        conda: {
          "path": "{{path.resolve(cwd, 'conda_env')}}"
        },
        env: {
          "PYTHONUNBUFFERED": "1",
          "HF_XET_HIGH_PERFORMANCE": "1"
        },
        message: [
          "if [ -f ../service/.installed ]; then echo \"Startup service mode is installed. Use 'Open UI (service)' or uninstall the startup service before using Start.\"; exit 1; fi",
          // Bind on every interface (LAN, Tailscale, loopback) at a fixed
          // port so other devices can hit the API directly. We picked 47870
          // so it doesn't clash with ImageStudio (47868) or MusicStudio (47869).
          "python -m uvicorn backend.main:app --host 0.0.0.0 --port 47870"
        ],
        on: [{
          event: "/Uvicorn running on (http:\\/\\/[0-9.:]+)/",
          done: true
        }, {
          event: "/error:/i",
          break: false
        }]
      }
    },
    {
      method: "local.set",
      params: {
        url: "{{input.event[1]}}"
      }
    }
  ]
}

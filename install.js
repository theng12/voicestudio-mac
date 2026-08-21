module.exports = {
  requires: {
    bundle: "ai"
  },
  run: [
    {
      when: "{{!exists('ENVIRONMENT')}}",
      method: "fs.copy",
      params: {
        src: "ENVIRONMENT.example",
        dest: "ENVIRONMENT"
      }
    },
    {
      method: "shell.run",
      params: {
        path: "app",
        conda: {
          "path": "{{path.resolve(cwd, 'conda_env')}}",
          "python": "python=3.12"
        },
        message: [
          "python -m backend.dependency_convergence base"
        ]
      }
    }
  ]
}

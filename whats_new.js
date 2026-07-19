// Always-available, offline release notes for the installed checkout.
// `fs.cat` is Pinokio's documented file-display API, so this stays current
// automatically whenever Update pulls a new CHANGELOG.md.
module.exports = {
  run: [
    {
      method: "fs.cat",
      params: {
        path: "CHANGELOG.md"
      }
    }
  ]
}

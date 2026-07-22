from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[2]


def _launcher_menus() -> dict[str, list[dict]]:
    script = r"""
const launcher = require('./pinokio.js');
const generationFiles = [
  'conda_env/lib/python3.12/site-packages/transformers',
  'conda_env/lib/python3.12/site-packages/diffusers',
  'conda_env/lib/python3.12/site-packages/mlx_audio',
  'conda_env/lib/python3.12/site-packages/fugashi',
  'conda_env/lib/python3.12/site-packages/jieba',
];
function info({ installed = true, generation = true, service = false,
                running = [], local = {} }) {
  return {
    exists(path) {
      if (path === 'conda_env') return installed;
      if (path === 'service/.installed') return service;
      if (generationFiles.includes(path)) return generation;
      return false;
    },
    running(path) { return running.includes(path); },
    local(path) { return path === 'start.js' ? local : {}; },
  };
}
(async () => {
  const scenarios = {
    installing: { running: ['install.js'] },
    installing_generation: { running: ['install_generation.js'] },
    service: { service: true },
    running_ready: { running: ['start.js'], local: { url: 'http://0.0.0.0:47870' } },
    running_starting: { running: ['start.js'] },
    stopped_missing_generation: { generation: false },
    updating: { running: ['update.js'] },
    updating_restart: { running: ['update_and_restart.js'] },
    resetting: { running: ['reset.js'] },
    uninstalled: { installed: false, generation: false },
  };
  const result = {};
  for (const [name, state] of Object.entries(scenarios)) {
    result[name] = await launcher.menu({}, info(state));
  }
  console.log(JSON.stringify(result));
})().catch(error => { console.error(error); process.exit(1); });
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_generation_action_is_persistent_in_regular_and_service_modes() -> None:
    menus = _launcher_menus()

    for state in ("service", "running_ready", "running_starting"):
        actions = {item.get("href"): item.get("text") for item in menus[state]}
        assert actions["install_generation.js"] == "Reinstall Generation"

    missing_actions = {
        item.get("href"): item.get("text")
        for item in menus["stopped_missing_generation"]
    }
    assert missing_actions["install_generation.js"] == "Install Generation"


def test_whats_new_is_visible_in_every_launcher_state() -> None:
    menus = _launcher_menus()

    for state, menu in menus.items():
        assert any(
            item.get("href") == "whats_new.js" and item.get("text") == "What's New"
            for item in menu
        ), state


def test_whats_new_displays_the_local_changelog() -> None:
    source = (ROOT / "whats_new.js").read_text(encoding="utf-8")

    assert 'method: "fs.cat"' in source
    assert 'path: "CHANGELOG.md"' in source


def test_common_actions_use_consistent_names_and_safe_order() -> None:
    menus = _launcher_menus()

    service = [item["text"] for item in menus["service"]]
    assert "Repair Startup Service" in service
    assert service.index("Outputs") < service.index("HF Cache")
    assert service.index("Update") < service.index("What's New")
    assert service.index("What's New") < service.index("Uninstall Startup Service")

    running = [item["text"] for item in menus["running_ready"]]
    assert running.index("Terminal") < running.index("Outputs")
    assert running.index("Outputs") < running.index("HF Cache")
    assert running.index("Install as Startup Service") < running.index("Update")
    assert running.index("Update") < running.index("What's New")

    stopped = [item["text"] for item in menus["stopped_missing_generation"]]
    assert stopped.index("Outputs") < stopped.index("HF Cache")
    assert stopped.index("Update") < stopped.index("What's New")
    assert stopped.index("What's New") < stopped.index("Reinstall") < stopped.index("Reset")

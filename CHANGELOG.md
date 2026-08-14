# Changelog — Voice Studio KH

All notable changes to Voice Studio KH are documented here.

Versioning follows [Semantic Versioning](https://semver.org/) with this project-specific interpretation:

- **MAJOR** (1.x.x → 2.x.x) — breaking change. Re-install required.
- **MINOR** (1.1.x → 1.2.x) — new engine / new feature / new model family. **Re-run "Install Generation"** to pick up new Python deps.
- **PATCH** (1.2.0 → 1.2.1) — bugfix / UI tweak / catalog entry within an existing family. **Just run Update** from the Pinokio sidebar.

---

## [2.1.0] — 2026-08-14

### Added — LongCat AudioDiT as a qualified-hardware internal candidate

- Added the MIT-licensed `mlx-community/LongCat-AudioDiT-1B-4bit` voice-cloning
  checkpoint to the local catalog, reusing the pinned `mlx-audio` worker with
  no new runtime dependency. It requires a reference voice with its exact
  transcript and automatically stages the small `google/umt5-base` tokenizer
  companion.
- Set a measured 16 GB minimum and 24 GB preferred tier. Real pinned-runtime
  evidence on an M4 16 GB Mac produced 4:01 of audio in 7:04 with a 4.94 GB MLX
  peak; the checkpoint stays internal and is not a GenStudio production route
  until multi-voice long-form listening qualification passes.
- Added sentence-safe 280-character private sections, 180 ms joins, exact job
  seed propagation into LongCat's own sampler, saved-voice UI support, and
  immutable model/reference revision evidence.

## [2.0.7] — 2026-08-14

### Fixed — startup-service generation can find Pinokio's bundled media tools

- The macOS startup service inherited launchd's minimal executable search path,
  unlike a foreground Pinokio run. F5-TTS could load its local checkpoint but
  then failed before inference because its reference-audio preprocessor could
  not find Pinokio's bundled `ffprobe`.
- The self-locating service entrypoint now prepends the current Pinokio home's
  Miniforge tools directory to `PATH`. It is derived from the installed app
  location and contains no username-specific path.
- Added an executable service regression that starts the real entrypoint under
  a launchd-like minimal environment and proves a bundled media tool remains
  discoverable. No model, generation control, or API contract changed.

## [2.0.6] — 2026-08-13

### Fixed — OmniVoice section cleanup can no longer delete quiet words

- Removed adapter 1.3's destructive energy-based edge trimming after the
  owner's 4m42s Rowan production check proved it removed the sentence-opening
  word “The.” Fleet-internal Whisper Large independently transcribed the same
  omission and identified the retained tail artifact as an extra “D.”
- Signal energy cannot distinguish a quiet intended word from a voiced
  conditioning fragment. Adapter 1.4 therefore preserves every generated frame
  and applies only the existing speed-compensated 10 ms micro-fades. The
  approved 300 ms sentence, 600 ms paragraph, and 180 ms soft-split pacing is
  unchanged, with no speech crossfade.
- This deliberately prefers an occasional section-edge crumb over irreversible
  narration word loss. A future artifact remover must be transcript-aligned and
  separately qualified; Voice Studio does not add fleet-wide Whisper latency or
  memory pressure to the 8 GB production path in this safety release.
- Published the replacement hash-bound OmniVoice adapter 1.4 contract and added
  regressions proving quiet 180 ms opening words, measured 17–260 ms edge
  activity, mono/stereo audio, WAV format, and total frame counts are preserved.

## [2.0.5] — 2026-08-13

### Fixed — OmniVoice section edges reject conditioning noise without clipping uncertain speech

- Added conservative join-time cleanup for the occasional 17–270 ms
  conditioning blobs observed at independently rendered OmniVoice section
  edges. It searches only the first and last 300 ms for a clear transition to
  sustained speech and keeps a 20 ms speech-protection pad.
- Ambiguous speech-like activity and sections too short to establish a safe
  boundary keep their original frame bounds. Cleanup is streamed and atomic,
  preserving the WAV sample rate, channel count, and subtype without loading a
  long section into memory beside the active model.
- Added speed-compensated 10 ms fades to each section edge without mixing or
  crossfading speech. The owner-approved 300 ms sentence, 600 ms paragraph,
  and 180 ms soft-split gaps remain unchanged.
- Advanced the OmniVoice adapter contract to 1.3 with hash-bound cleanup
  limits and regression coverage for the measured artifact range, immediate
  mono/stereo speech, ambiguous openings, short sections, non-finite audio,
  atomic joins, and unchanged pacing.

## [2.0.4] — 2026-08-13

### Fixed — OmniVoice sections leave natural breathing room

- Replaced OmniVoice's abrupt fixed 120 ms section join with boundary-aware
  pacing: 300 ms after ordinary sentences, 600 ms between paragraphs, and
  180 ms when an oversized sentence needs a softer internal split.
- Join silence is pre-scaled before OmniVoice's final pitch-preserving tempo
  pass, so the audible gaps remain stable when generation speed changes.
- The production script that exposed the problem resolves to nine sentence
  joins and eight paragraph joins: 7.50 seconds of deliberate breathing space
  instead of 2.04 seconds across its 18 sections. No Hub or GenStudio request
  contract changed.
- Advanced the OmniVoice adapter contract to 1.2 and recorded the owner-approved
  pacing policy. The existing model, 288-character section budget, voice-clone
  inputs, local routing, and generation controls remain unchanged.

## [2.0.3] — 2026-08-09

### Changed — new installs favor cross-Studio switching

- Fresh installs now default to **Immediate** model-memory release. Existing
  saved operator choices remain authoritative.
- A controlled M1/M2/M4 fleet pressure run completed every Image and Voice job
  with valid artifacts. On an M4 16 GB Mac, Immediate release left Image time
  unchanged at about 72 seconds and reduced the following Voice job from 52.7
  seconds to 4.0 seconds.

## [2.0.2] — 2026-08-09

### Fixed — the documented download transport matches production

- The README and both launch modes still claimed to enable Hugging Face Xet's
  high-performance transfer mode, even though Voice Studio has deliberately
  disabled Xet by default since 1.27.15 after repeat fleet stalls and held
  cache locks. Removed the inert `HF_XET_HIGH_PERFORMANCE` launch flags and now
  document resumable classic HTTP as the safe default, with the existing
  `VOICESTUDIO_ENABLE_XET=1` diagnostic opt-in.
- Declared Pydantic and Starlette as direct base dependencies because Voice
  Studio imports both at runtime. The existing base and generation lock
  versions already satisfy the compatible floors, so no model runtime changed.

The 17 local TTS families, model download/resume implementation, fleet voice
sync, generation, transcription, memory admission and idle release, safe
updates, and local-only API remain unchanged. Verification: 358 tests,
dependency integrity, Python compilation, JavaScript and launcher syntax,
catalog truth, and contract-to-runtime audits pass.

## [2.0.1] — 2026-08-09

### Fixed — legacy voice files are scrubbed, not only ignored

- v2.0.0 removed provider metadata from the voice schema and API, but its
  tolerant loader only ignored an old `providers` key on disk. Loading a voice
  now rewrites that metadata file through the local-only schema, so the retired
  IDs are actually removed. All ten disposable test voice records in this
  checkout were migrated; no audio, transcript, fleet ownership, or local voice
  metadata was removed.
- The regression now verifies both the returned voice contract and the
  rewritten file. No dependency reinstall is required. Run **Update**, then
  restart Voice Studio.

## [2.0.0] — 2026-08-09

### Removed — the remaining cloud compatibility and inherited studio UI

- Removed the legacy provider fields from voice metadata, generation jobs,
  public job responses, and persisted history. Old hosted-provider history is
  discarded on load; local history is rewritten without provider keys. This is
  the deliberate breaking boundary that makes Voice Studio's data contract
  local-only instead of merely leaving the old fields inert.
- Settings now accepts and persists only the Hugging Face download token.
  Unknown legacy keys — including the removed provider credential object — are
  scrubbed atomically the next time settings load.
- Removed the empty `/api/loras` compatibility route, its startup request and
  state, and inherited image-generation helpers for aspect ratios, prompts,
  image drop/paste, LoRAs, and output-image actions. Removed their unused CSS
  and other unreachable frontend helpers.
- Removed obsolete cloud-row filters from the cache organization, family-view,
  and fleet-test tools. The catalog has one kind of model now: local.

### Fixed — streaming families use the normal local model layout

- The streaming capability still selected a CSS class named `tone-cloud`,
  which also applied the retired cloud table's four-column geometry to local
  streaming models. It is now a color-only `tone-streaming` accent; every local
  family uses the same five-column desktop table and responsive layouts.
- Capability labels now describe Voice Studio features instead of carrying
  dead text-to-image mappings.

### Kept deliberately

- All 17 catalog families and their workers, local model download/storage,
  voice cloning and fleet voice sync, transcription, job idempotency, resource
  telemetry, memory admission, idle release, manual release, and Studio Hub
  authentication/contracts are unchanged.
- The small `provider:` request guard remains as a refusal boundary: stale
  callers receive a truthful `400` before engine checks, and no hosted call can
  be made.

Application, tooling, documentation, and regression changes remove **416 net
lines** before these release notes. The local data in this checkout is treated
as disposable test data, so no cloud-history or provider-ID compatibility is
preserved. No generation dependency changed. Run **Update**, then restart Voice
Studio; a generation-stack reinstall is not required.

## [1.33.0] — 2026-08-08

### Removed — Voice Studio is a local TTS studio again

- The cloud audio gateway is gone: ElevenLabs, GenAIPro, Fish Audio, fal.ai and
  Kie.ai, the ElevenLabs named-account pool with its quota-aware failover, and
  the restart-safe paid-task recall machinery. `providers.py` (1,537 lines),
  `PROVIDERS_PLAN.md`, and three provider test modules are deleted.
- Gone with it: `GET /api/providers` and every `/api/providers/*` endpoint
  (keys, paid consent, enable/pause, connection test, the account-pool CRUD,
  `models/live`, `voices/live`), plus `PUT /api/voices/{id}/providers`. The
  Settings panel, the cloud entries in the Generate model picker, the cloud
  voice selector, and the per-voice provider mapping editor are removed from the
  UI.
- This removes a capability nothing used. Voice Studio's cloud path had been
  unreachable through Studio Hub for some time — the Hub's broker requires a
  cached local model and rejects this app's `cache.state="cloud"` — and paid
  cloud generation belongs to GenStudio, which holds its own vendor adapters and
  its own credential vault and calls the vendors directly. Exactly one cloud job
  exists in this checkout's entire history. Hub consumers already treat a 404
  from `/api/providers` as "not supported", so nothing on the Hub side changes.
- `/api/catalog` still publishes `kind: "local"` on every model, which is what
  Studio Hub reads.

### Changed

- A generate request whose `repo` still starts with `provider:` — a stale
  bookmark, a saved preset, a replayed Hub batch item — now gets a `400`
  reading "Cloud providers are no longer supported; choose a local model."
  before any engine or catalog check, rather than falling through to an
  "Unknown repo" error or a 503 that would send someone off to reinstall the
  generation stack for no reason.
- `httpx` is no longer a direct dependency of the base server; the only code
  that imported it was the gateway. It stays pinned in `requirements.lock.txt`
  because `huggingface_hub` 1.x requires it outright and Starlette's TestClient
  needs it — the lockfile records transitive pins too.

### Kept deliberately

- **Recorded provider voice IDs.** The `providers` array stays on `Voice`, stays
  in every `app/voices/*/metadata.json`, and is still returned by
  `GET /api/voices`. Three voices — the owner's own clones — carry Fish and
  ElevenLabs IDs, and this metadata may be the only local record of the
  ElevenLabs half. Only the editing UI and the write endpoint were removed.
- **Archived cloud history.** `GenerationJob.provider*` remains in the schema
  and `_from_disk` stays tolerant, so pre-1.33 history rows load and play
  exactly as before. `.history.json` was not migrated or rewritten.
- Saved provider API keys are left untouched in the gitignored local settings
  file. Revoking them at the vendor is the owner's call, not this release's.

## [1.32.11] — 2026-08-08

### Added — a check that compares an audit record to the code it describes

- Every existing check in the model-audit pipeline is a **self-consistency**
  check. `contract_hash` matches because it is computed over the contract. The
  `genstudio_candidate` block mirrors the contract because it was copied from
  it. GenStudio's `normalise_controls` derives the supported modes from the
  controls the record declares. All of them pass for a record copied wholesale
  from a different model — the pipeline was best at passing exactly the
  forgeries worth catching. Nothing in the chain had ever compared the document
  to the adapter it claims to describe.
- That is not hypothetical: the superseded OmniVoice record validated perfectly
  and shipped in v1.32.8 with four contract fields contradicted by this
  repository's own code, three of them Qwen3-TTS Base's values.
- `audit_contract_runtime.py` (sibling to `audit_truth.py`) now checks every
  installed audit record against the adapter, deriving each expectation from
  source rather than retyping it: `record.subject.model_id` → the catalog's
  `ModelEntry` → `MLX_AUDIO_FAMILIES[family]["mode"]` → the dispatcher branch →
  the body of the `_mlx_kwargs_*` builder.
  - **section budget** (highest value — `catalog.py` feeds the audited number
    straight into `long_form_policy`, so a wrong one silently changes how every
    machine splits a script), **reference window** vs the duration the adapter
    truncates to, **join pause** vs the family runtime default, whether
    **`controls.language`** may exist at all, **`voice_clone.required`** vs the
    guard that actually raises, the declared **engine mode**, and that the
    declared text ceiling is reachable through the API's own cap.
  - Long-form expectations call `policy_for()` with **no** audit override, so
    the expectation is the family default rather than the value under test.
- **The result names its own blind spots.** `audit_status`, hardware
  qualification, quality comparisons, licence and clone-permission
  attestations, and the *chosen* value of `text_max_characters` are human
  judgements the validator does not verify — and it says so in the returned
  result and the printed report, not only in a comment. A model whose adapter
  cannot be introspected reports "not checkable", never "passed".
- Wired into the test suite (`app/tests/test_audit_contract_runtime.py`), with
  mutation tests that fail if a record is set back to any of the four known-bad
  values. `--strict` exits non-zero for CI.

### Changed — the OmniVoice text ceiling reads as the decision it is

- `input_limits.text_max_characters = 25000` was filed under
  `declared_not_measured`, which implied a pending measurement and a
  deficiency. It is neither: it is a deliberate commercial ceiling. The owner
  knows it forecloses a 40K tier and does not want one.
- It now sits under `commercial_decisions` as a settled owner decision, noting
  the API's own 40,000-character cap only as context for the headroom being
  intentional. The `contract` object is untouched and `contract_hash` is
  unchanged at `sha256:d9710ace…52f36a`, so Studio Hub's existing approval
  still binds.

## [1.32.10] — 2026-08-08

### Security — the fleet's machine table was being published in a public repo

- `tools/fleet_test.py` carried all 19 fleet machines as a literal table: id,
  Tailscale address and RAM, with a comment explaining that the leading digits
  of a machine id select which site's fleet token authenticates the request.
  This repository is public, so that table — and the shape of the auth scheme
  next to it — was readable by anyone.
- The table now loads from `fleet_machines.json`, an untracked file at the
  launcher root (gitignored, alongside the existing per-machine files), or from
  whatever `FLEET_MACHINES_FILE` points at so one copy can serve several
  checkouts. Each entry carries its own `token_key`, so the repo no longer
  encodes which machines share a token, or the machine-id prefix the old lookup
  sliced to find one.
- **There is deliberately no built-in fallback list.** If the config is missing
  the tool exits naming the expected path and format. A baked-in default is how
  a table survives a re-address and then quietly dispatches jobs at whichever
  host now answers.
- Removed the remaining machine names from `FLEET-SETUP.md`, the `catalog.py`
  measurement comments and the `bench_tts.py` help text; all of them already
  stated the chip and memory tier, which is the part that carried the meaning.
- This stops future publication only. The addresses remain in this repository's
  git history and in any clone or fork already taken; rotating the fleet tokens
  and re-addressing are the owner's call.

---

## [1.32.9] — 2026-08-08

### Fixed — the OmniVoice audit record published four fields the code contradicts

- Two sessions were asked to author this record and both did, minutes apart, at
  the same path. The one that landed in 1.32.8 validates structurally — correct
  schema, correct hash, correct mirror — and is wrong in four places that
  matter, because an audit record is not documentation: it is the routing
  contract Studio Hub and GenStudio read.
- **`controls.language` claimed a 10-value enum.** The OmniVoice adapter sets no
  language parameter at all (`_mlx_kwargs_omnivoice`), and the catalogue entry
  declares `languages=()` with `claimed_count: 646`. The model claims 646
  languages and enumerates none; a 10-language roster is neither the claim nor
  the runtime. The control is removed and `language_selection: "none"` is
  declared instead.
- **`voice_clone.required` was `true`.** The adapter raises only when *both* a
  reference and voice-design traits are absent. Voice design alone is a valid
  OmniVoice request, so a required reference would have refused half the
  model's supported modes at the routing boundary.
- **The reference window said 8 / 12 / 15 seconds.** The adapter clamps to
  `ref_audio_max_duration_s = 10.0`, and the family guidance and UI both say a
  3–10 second clip. Those figures were Qwen3-TTS Base's.
- **`private_join_pause_milliseconds` was 180.** The OmniVoice policy uses
  `DEFAULT_JOIN_PAUSE_SECONDS`, which is `0.12` — 120 ms. 180 is also Qwen's.
- Three of the four wrong values are Qwen3-TTS Base's, which is the same failure
  mode the 288-character constant already had: a value copied from a neighbouring
  model that carries no derivation of its own.
- Added what was missing: OmniVoice's actual engine controls (`num_steps` 4–64,
  `guidance_scale` 0.0–8.0, `duration_s` 0.5–120 s), the non-verbal tag set
  pinned to the engine's own pattern, the measured peak memory and the
  three-tier frame ceiling, the exact mlx-audio release and commit, and the
  120-second single-pass clamp at 25 latent frames per second.
- **Neither session's evidence was discarded.** The owner's quality verdicts and
  the fleet cache observations are carried over verbatim and attributed; the
  contract fields now come from the code. `evidence.corrections` records each
  change with the file and line that grounds it, and `evidence.supersedes_audit_id`
  points back at the record this replaces.
- Still declared rather than measured, and still said so in the record itself:
  the 25,000-character commercial text ceiling and the adapter version.

## [1.32.8] — 2026-08-08

### Added — OmniVoice has a passed audit record, so it can be a GenStudio candidate

- OmniVoice has been the small-machine workhorse in the catalogue since 1.29.4
  and has accumulated more grounded measurement than most models here — the
  transcribe-back section-budget curve, the three-tier fleet memory ceiling, the
  peak-memory and real-time-factor bands — but none of it was ever written as an
  audit record. Without one, `model_audits.audit_record()` returns `None`, the
  catalogue's `execution_contract` reports `qualification_source: "unverified"`,
  and Studio Hub has nothing to expose. The evidence existed; the record did not.
- `model-audits/2026-08-08-omnivoice/mlx-community--OmniVoice-bfloat16.audit.json`
  records the audit as **passed** and **candidate for GenStudio**, bound to
  checkpoint `6119f707…` — the exact revision cached in this tree — for the
  single operation `voice.tts`.
- Every mirrored block is grounded in this repository rather than restated from
  a model card: the 288-character private section budget and its quality curve
  (`long_form_policy.py`), the 25 frames/second and 2250-frame 8 GB ceiling
  (`generation.py`), the 4–64 / 0.0–8.0 / 0.5–120 s control ranges and the
  3–10 s reference window (`_mlx_kwargs_omnivoice`), the pitch-preserving speed
  pass, the 24 kHz mono output, the exact non-verbal tag set, and Apache-2.0
  from the checkpoint's own card.
- **A candidate is not an approval.** Studio Hub remains the authority that
  decides whether this revision and contract hash are actually exposed, and
  nothing here publishes anything.
- Two values are declared rather than measured, and the record says so in its
  own `evidence.declared_not_measured`: the 25,000-character commercial text
  ceiling (narrower than the API's own 40,000 cap, but not fixed by a
  measurement here), and the `1.0` adapter version, which has no registry in
  code.

## [1.32.7] — 2026-08-08

### Added — process uptime, so `release_count: 0` finally means something

- `/api/health` gains a `process` block (`pid`, `started_at`,
  `started_at_iso`, `uptime_seconds`) and `/api/memory-policy` now returns the
  same block plus `counters_since` — the process start that `release_count`,
  `last_release_at`, `last_release_reason` and `last_error` are all measured
  from. Those counters are in-process globals that reset to zero on every
  start, so a read-only fleet probe could not tell "the idle-release thread
  never fired" from "a restart zeroed the counter" — and the v1.32.5 rollout
  required a restart, while job history persisted to disk. All 13 8 GB
  machines reported `release_count: 0` and the reading was unusable.
- `restart_health` did not close this: it only parses the watchdog log, so a
  deliberate upgrade or a `launchctl` bounce leaves `last_restart_at: null`,
  which reads like a long uptime and is not. The two are now published side by
  side in `/api/health` as separate readings — "what restarted us" and "when
  did we start" — and only the second is always populated.
- The absolute epoch timestamp is the primary value, since it is directly
  comparable with the other absolute timestamps the API already publishes
  (`last_release_at`, `next_release_at`, job `started_at`) and does not drift
  between being served and being read. `uptime_seconds` is derived from it for
  readability. The start is resolved once from the kernel via
  `psutil.Process().create_time()`, falling back to import time.
- The settings UI now renders the release count as "N since <time>" and adds a
  Service uptime tile, so the same ambiguity is not reproduced on screen.
- No release or eviction behavior changed — this is observability only.

### Fixed — `model_retained` was always false on the MLX path

- Per-job telemetry reported `outcome.model_retained: false` on all 19 fleet
  machines, including one whose own release log recorded
  `cleared mlx_audio_model` — proof that OmniVoice was resident and later
  evicted. The check probed a private `_loaded_model` attribute that no engine
  has ever set; the MLX engine parks its model on `_mlx_audio_model` and
  F5-TTS on `_f5_tts_model`.
- Both telemetry sites now answer through a shared
  `has_loaded_model()` accessor on `GenerationManager` and
  `TranscriptionManager`, derived from the same `loaded_model_keys()` /
  `loaded_model_key()` that `memory_policy` releases against — one definition
  of "loaded" for the release path and the telemetry, instead of two. The
  transcription site previously used a bare `self._model is not None`, which
  disagreed with the policy whenever the repo was unset.
- The regression survived because the test that covered it set the same
  invented `_loaded_model` attribute the production code read, so the pair
  agreed with each other and with nothing on the fleet. The fixture now holds
  a real MLX cache slot.

### Fixed — the README still called Performance the memory default

- Same stale claim v1.32.5 removed from the mode picker, still shipped in the
  README: "**Performance** is the default". Since v1.32.3 the default follows
  the host's memory (Memory Saver below 12 GB, Balanced above), so on most of
  the fleet the README pointed the owner at the one mode that never releases.
  The `/api/health` and `/api/memory-policy` sections are updated for the new
  process/uptime fields at the same time.

## [1.32.6] — 2026-08-08

### Fixed — dirty-worktree update refusals were undiagnosable remotely

- A genuine dirty-worktree refusal in the auto-updater now lists the exact
  blocking paths (from `git status --porcelain`) in the error surfaced through
  `/api/auto-update/status`, capped at the first 5 with an "and N more" suffix
  for pathological worktrees. Paths are repo-relative filenames only — no file
  content or diffs — so nothing sensitive leaks through the API. Mirrors
  Studio Hub v1.45.0's fix for the same blind spot; without it, a stuck
  machine like `terranash-0103` (wedged on v1.32.1) could not be diagnosed
  through the fleet API at all, since there is no SSH or remote-exec channel.
- The refusal behavior itself is unchanged — dirty trees are still refused.
  This only adds diagnostic detail to the message.

### Fixed — the OmniVoice section-budget comment pointed at the wrong constraint

- The comment above `OMNIVOICE_SECTION_MAX_CHARACTERS = 288` documented the
  memory ceiling (~1286 chars at 8 GB) and said the value was "deliberately
  NOT raised yet" pending a quality gate that hadn't run. That gate has since
  run: transcribe-back coverage measurements show 288 chars gives 99.4%
  coverage (1 word lost); 350 is the measured ceiling for equal coverage, but
  raising past 288 up to 1200 chars steadily loses words (down to 60%
  coverage / 66 words lost at 1200), because OmniVoice commits its frame
  budget up front from a duration estimate that drifts long over longer
  spans. The comment now records quality as the binding constraint and the
  memory figures as a retained note, not a reason to raise the value. No
  behavior change: `OMNIVOICE_SECTION_MAX_CHARACTERS` stays 288.

### Fixed — psutil was missing from the base install

- `memory_policy.default_mode()` imports `psutil` unconditionally to pick the
  machine-aware idle-release default, but `psutil` was declared only in
  `requirements-generation.txt` (the optional generation stack), not in the
  base `requirements.txt` / `requirements.lock.txt` that `install.js` always
  installs. A base-only install silently swallowed the resulting `ImportError`
  and always fell back to the roomy-machine default — defeating the v1.32.3
  memory-aware default on precisely the 8 GB machines it was written for.
  Mirrors Chat Studio v1.24.7 (commit `ad01773`).

## [1.32.5] — 2026-08-08

### Fixed — the mode picker still called Performance the default

- v1.32.3 made the default depend on the host's memory, but the settings UI
  still hardcoded "Performance · default". On every 8 GB machine — which is most
  of the fleet — that label was simply false, and it pointed the owner at the
  exact mode that caused the thrash.
- The badge is now bound to the `default_mode` the backend actually reports, so
  it follows the machine instead of a constant. Test asserts the hardcoded label
  is gone and that all four modes are bound.

## [1.32.4] — 2026-08-07

### Added — numbers are expanded to words before OmniVoice speaks them

- Caught by ear in a 1-minute sample: "1,200" was read as "one two hundred".
  Characterised on the real model — digits are a lottery, not a consistent bug:

  | sent | heard | |
  |---|---|---|
  | `1,200` | "when 200" | wrong |
  | `1200` | 1,200 | ok |
  | `12,500` | 1,200,500 | wrong |
  | `12500` | "twelve five hundred" | wrong |
  | `3,000` / `3000` | 3,000 | ok |
  | `$1,450.75` | "50, 70 feet fence" | wrong |
  | `1450 dollars and 75 cents` | "$14.50 and 75 cents" | wrong |
  | every fully spelled-out form | correct | ok |

  5 of 8 digit forms wrong, 4 of 4 spelled-out forms right. It is not the comma:
  `3,000` is fine and `12500` is broken. There is no rule an author could follow.
- Root cause: mlx-audio does no number normalisation for OmniVoice. `_combine_text()`
  handles whitespace and CJK spacing only, and raw digits reach the tokenizer.
  **KittenTTS and Voxtral, in the same package, do expand digits** — OmniVoice
  never used those helpers.
- New stdlib-only `backend/text_normalization.py` expands cardinals, thousands
  separators, currency with cents, years (1900-2099 read naturally, and a
  thousands separator always disqualifies year-reading), clock times, ordinals,
  decimals and negatives. Non-verbal tags and digit-bearing words like `MP3`,
  `B2B`, `4K` are left untouched.
- Applied automatically for OmniVoice via a narrow allow-list — families that
  already normalise upstream are not normalised twice. Normalisation failures are
  logged and skipped, never fatal.
- **`normalize_text` now means what it says.** It was accepted by the API,
  serialised by the frontend, and read by no backend worker at all. It can now
  force normalisation for any family.

### Fixed — the catalog advertised a non-verbal tag OmniVoice does not have

- Owner listening flagged `[cough]` as rendering badly. It is not a tag to this
  model: mlx-audio's `_NONVERBAL_PATTERN` recognises exactly `laughter`, `sigh`,
  `confirmation-en`, four `question-*`, four `surprise-*` and `dissatisfaction-hnn`.
  Anything outside that list falls through to ordinary tokenization and is
  rendered as noise — which is precisely what was heard.
- The summary no longer advertises `[cough]`. The guidance now lists the exact
  recognised set and explicitly warns that `[cough]`, `[breath]` and `[gasp]` are
  not tags. A regression test pins the advertised list to the engine's own
  pattern, so documentation cannot drift from the model again.

## [1.32.3] — 2026-08-07

### Fixed — "mlx-audio didn't produce a wav file" told the owner nothing

- On a small machine an oversized request dies *inside* mlx-audio: it returns
  having written no WAV and raises nothing of its own. Voice Studio then
  reported `mlx-audio didn't produce a wav file. Temp dir: /var/folders/...`,
  which is technically true, names no cause, and hands the owner a temp path
  they cannot act on. Measured case: OmniVoice at 3000 frames on an 8 GB box
  fails this way after ~236 s, reproducibly (3/3 reps).
- The error now names what was attempted (requested duration and the latent
  frames committed in one pass, or the section length), what the host actually
  had (unified memory and free memory), and for OmniVoice on a small machine
  what is measured to fit — ~2250 frames, about 90 s per pass — plus what to do
  about it.
- A machine with headroom is never told it is too small; the size-specific
  advice is gated on the host's actual unified memory.
- Applies to both raise sites, including per-section long-form rendering, so a
  section that dies mid-script explains itself instead of surfacing a temp dir.
- Regression test pins all four parts of the message and the no-false-blame case.

### Fixed — every Studio shipped a memory policy that could never fire

- The idle-release mechanism is fully implemented and its background thread has
  been running on every machine the whole time, waking every 5 s. It just had
  nothing to do: the shipped default is `performance`, whose `idle_seconds` is
  `None`, so `run_due_release()` returned immediately every single time.
- This is not a Voice Studio bug so much as a shared-assumption bug. Image,
  Chat, Video, Music and Voice Studio all ship the *same* skeleton with the
  *same* `DEFAULT_MODE = "performance"`. That default is reasonable for an app
  that owns its machine. The actual deployment puts 3-5 of them on one 8 GB Mac,
  where each independently concludes that pinning its model forever is free.
- Measured fleet-wide 2026-08-07: 16 of 19 machines sat below the memory guard's
  3.2 GB floor with 1.5-4.4 GB of swap burned and could not start a job at all.
  After setting a real policy: swap ~4 GB -> ~0.4 GB, 8 GB boxes 1.7-2.8 GB free
  -> 4.3-5.2 GB, 16 GB boxes 3.1 GB -> 12.3-13.3 GB.
- The default is now chosen from the host's own memory — `memory_saver` (120 s)
  below 12 GB, `balanced` (600 s) above — instead of assuming a machine alone.
  An operator's explicit choice, persisted in `memory_policy.json`, still wins;
  `performance` remains available and still pins when asked for.
- Note this only fixes *fresh installs*. `memory_policy.json` is gitignored, so
  an in-place Update or Reset never resets an operator-chosen mode — which also
  means the 19 machines already corrected over the API stay corrected.
- **The same one-line default is still shipped by Image, Chat, Video and Music
  Studio, and Render Studio has no idle-release mechanism at all.** Those are
  separate products with their own release flows and are not changed here.
- No cross-studio coordination exists: no Studio knows the others are resident.
  Studio Hub can read and set all five policies over HTTP, but only when
  explicitly invoked — there is no scheduler behind it.

## [1.32.2] — 2026-08-07

### Fixed — OmniVoice's speed control did nothing, and said nothing

- `mlx_audio`'s `OmniVoice.Model.generate()` takes **no `speed` argument**. It
  declares `**kwargs` and never reads it, so anything passed there is discarded
  in silence.
- OmniVoice was missing from *both* places that make speed work: it was absent
  from the pass-through exclusion set, so `speed` was handed to the engine and
  swallowed, and absent from `_POSTPROCESSED_SPEED_FAMILIES`, so no FFmpeg
  pitch-preserving tempo pass ran either. A speed request was a no-op that
  raised no error.
- The UI hid the slider for OmniVoice, which concealed the gap from the app but
  not from GenStudio or Studio Hub, which call the API directly.
- Audio8 (`arktts`) and Echo-TTS have the identical "no native speed" situation
  and were correctly handled in both places. OmniVoice had simply been missed.
- Fixed in both places and the slider is visible again. Two regression tests
  added: one pins the truthful hint text and that OmniVoice is no longer hidden,
  the other asserts the family appears in the post-process map *and* in the
  exclusion set, so re-introducing either half of the bug fails the suite.

### Changed — OmniVoice's 288-character section budget now states its evidence

- The constant was copied verbatim from `QWEN_CLONE_SECTION_MAX_CHARACTERS` — a
  *disqualified* model with entirely different failure physics — and carried no
  derivation, where every other family's constant cites a measurement.
- OmniVoice is flow-matching, not autoregressive: no internal splitting, no
  length cap, and the whole latent block committed up front from
  `target_len = ceil(duration_s * 25)`. There is no EOS to bail out early, so
  the outer section budget matters more here, not less.
- Fleet measurement (3 reps/tier, 2026-08-07) puts the real memory ceiling far
  higher: 8 GB passed 2250 frames and failed 3000 (reproduced); 16 and 24 GB
  both cleared 3000, which is the API's clamp rather than their limit. At the
  measured 1.749 frames/char that is ~1286 characters even on 8 GB — roughly
  4.5× the shipped budget.
- **The value is deliberately unchanged.** Memory is only half the question and
  the long-section quality gate has not run. Raising it on memory evidence alone
  would repeat the original mistake in the opposite direction. What changed is
  that the number now carries its evidence and its open question.

### Added — `section_max_characters` on the generate API

- Optional, clamped to 40–20,000, omitted in normal use where the family policy
  owns chunking. The internal Qwen retry override still wins over it.
- Exists so the outstanding long-section quality gate can actually be measured;
  until now section size was settable only from inside a Qwen retry, which is
  why the OmniVoice budget could never be tested above 288 in the first place.

## [1.32.1] — 2026-08-07

### Fixed — three tests that asserted a catalogue which no longer exists

- The suite had been red since this morning's model work, which is the worst
  state for it to be in: a red suite is one nobody reads, so a real regression
  would have hidden among the noise.
- `test_priority_catalog_is_focused_and_clone_capable` asserted Fish Audio's
  floor `is None`. Fish has since been measured and set to 24 GB, so the test
  was actively asserting the opposite of the shipped policy. It now asserts the
  qualified state.
- `test_diagnostics_cover_every_wired_engine` hardcoded 14 engines and went
  stale the moment Audio8, MOSS-TTS-Nano and Echo-TTS were wired. The count is
  now derived from `_WIRED_FAMILIES`, with a floor so wholesale deletion still
  trips, and the three newest engines named so a silent removal is caught.
- `test_catalog_reports_runtime_cache_load_and_memory_truth` had two separate
  stale assertions, one of which predated today's changes. VoxCPM2 is now
  asserted ineligible on the simulated 8 GB machine — it has enough free memory
  but not enough total, which is precisely the case proving both halves of
  `memory_eligible` are applied — and Kokoro was added as the eligible case, so
  the test cannot pass with the flag hardwired off. Fish's `is None` assertion
  became unreachable once every model gained a measured floor.

## [1.32.0] — 2026-08-07

### Fixed — Fish Audio S2 Pro raised to 24 GB

- 16 GB cleared the guard but not comfortably. Measured at 13.234 GB peak on a
  17.2 GB machine, leaving under 4 GB for macOS and anything else the worker is
  doing, and it ran at 3.75x realtime — the slowest of every model measured on
  the fleet. Raised to 24 GB on the owner's judgement after listening on real
  hardware.
- Consequence worth stating plainly: exactly one machine in the fleet has 24 GB,
  so Fish is now a single-worker model. The pruning pass will reclaim its 6.73 GB
  from every other machine holding it.

## [1.31.0] — 2026-08-07

### Fixed — VoxCPM2's memory floor was measured and raised to 16 GB

- Both VoxCPM2 checkpoints declared floors they cannot meet. Measured on the
  fleet with the same text on both tiers: the 4-bit ran in 61.9 s on a 17.2 GB
  M2 (3.95x realtime) but took 738.4 s on an 8.6 GB M2 (47.09x realtime) —
  twelve times slower for identical work, with a 7.963 GB peak against 8.6 GB
  of total memory. The small machine spends the whole run swapping.
- The output is correct on both (93% transcribe-back coverage), which is
  precisely why an 8 GB floor looked defensible on paper. Only wall-clock on
  real hardware exposed it.
- 4-bit goes 8 to 16 GB. bf16 goes 12 to 16 GB: it was never measured, but it
  carries 2.2x the weights of the sibling now known to need 16, so it cannot
  plausibly need less. 16 is the floor it is known not to run below; the true
  figure may be higher.

### Added

- `tools/fleet_test.py` covers the remaining clone-capable models (VoxCPM2,
  Chatterbox, Chatterbox Turbo, MOSS-TTS-Nano) and takes `--models` so a single
  model can be re-tested without repeating a fifteen-minute sweep. Chatterbox
  entries now pass the language code the engine requires — without it the job
  fails outright, which had made the model look broken when the harness was.

## [1.30.0] — 2026-08-07

### Added — Fish Audio S2 Pro finally has a qualified memory floor

- Fish S2 Pro shipped with `min_unified_memory_gb=None` — it had never been
  qualified, so it made no hardware claim at all. Measured on the fleet with an
  Aiden clone at one production section:
  - **16 GB Mac**: 13.27 GB MLX active, host peaked 88.4%, 1.99 GB free,
    `warning` pressure, +0.33 GB swap — runs, but with no margin.
  - **24 GB Mac**: 13.51 GB, host peaked 81.2%, 4.85 GB free, `normal`
    pressure, no swap — comfortable.
  - **8.6 GB Mac**: refused by the guard.
- Floor set to **16 GB**, with 24 GB documented as the comfortable tier.

### Changed — OmniVoice documented as the small-machine pick, with measurements

- Fleet testing makes OmniVoice the clear choice for constrained machines: it is
  the **only clone-capable model that completes on an 8 GB Mac**, at **3.3–3.5 GB
  peak** (about a third of Audio8) and **faster** than Audio8 everywhere —
  1.4–1.7x real time on 16/24 GB, 1.7–2.1x on 8 GB, verified on Apple M1 and two
  other 8 GB machines.
- The catalogue now also records the caveat: on 8 GB it finishes without
  swapping but leaves **under 1 GB free and reaches `warning` pressure**, so it
  suits a dedicated fleet worker rather than a machine in general use.

## [1.29.4] — 2026-08-07

### Fixed — Audio8 floor restored to 16 GB, now confirmed on the fleet

- The temporary 8 GB test setting from 1.29.3 is reverted. Fleet measurements
  put Audio8's peak at **8.22 / 8.39 GB on a 24 GB Mac** and **8.61 GB on a
  16 GB Mac**, matching the 9.44 GB measured locally. The 16 GB run left only
  **1.44 GB free**, reached `warning` memory pressure and added 0.21 GB of
  swap — so 16 GB is the genuine floor, not a comfortable target.
- An 8.6 GB machine has less total headroom than that run consumed, so the
  8 GB tier was ruled out on the numbers rather than by running it there.

### Added — OmniVoice is the small-machine option, with evidence

- Measured on the fleet for comparison: OmniVoice peaks at **2.75 GB** (16 GB
  Mac) at **1.73x** real time, against Audio8's 8.61 GB at 1.79x — comparable
  speed for roughly a third of the memory.
- Wave-2 qualification (2026-08-03) had already completed an OmniVoice clone on
  an **8 GB** machine (`terranash-0206`, 3.68 GB peak, RTF 3.26) — but it
  reached `urgent` pressure with 0.71 GB free and added 0.76 GB swap, and that
  review concluded the production floor should stay at 16 GB. That conclusion
  is unchanged; the catalogue's 8 GB floor for OmniVoice reflects that it
  *completes* there, not that it is comfortable.

## [1.29.3] — 2026-08-07

### Changed — Audio8 memory floor temporarily lowered to 8 GB (TEST SETTING)

- `min_unified_memory_gb` for Audio8 is temporarily **8** instead of the
  measured 16, so the fleet's 8 GB Macs will accept a dispatched job. The
  memory guard is exactly what refuses an under-spec job, so it has to be
  relaxed for the experiment to run at all.
- **This is not a fit claim.** The measurement behind 16 stands: 5.39 GB on a
  short line, **9.44 GB at 246 characters**, and ~10 GB at the 280-character
  production section size. While the floor sits at 8, nothing prevents an
  ordinary Audio8 job from swapping hard on an 8 GB Mac.
- To be reverted to 16 once the 8 GB results are in — or, if it genuinely
  fits, replaced with the new measurement rather than silently left at 8.

## [1.29.2] — 2026-08-06

### Added — the model picker is grouped by family, and dependencies are visible

- The Generate tab's model dropdown was a flat list of 19 local models under a
  single "Local" heading. It now uses **one `<optgroup>` per family**, matching
  how the Models tab already reads, and groups cloud models **per provider**
  instead of one combined "Cloud" bucket. (HTML cannot nest `<optgroup>`, so
  families become the groups rather than sitting under a "Local" parent.)
- **Companion models are no longer invisible.** Six families load a second repo
  at generation time — a codec or tokenizer — and that cost was tracked in the
  backend but never shown. Each family panel now lists what it "Also downloads"
  with the repo id, on-disk size, and ready / not-downloaded state, and each
  variant's Download cell shows a "with deps" total. Sizes come from the cache
  snapshot, so a companion that isn't present reports no size rather than a
  guessed one.
- `/api/catalog` gained `cache.companions` (the full list, not just the pending
  ones) and `cache.bytes_with_companions`.

### Fixed — `size_gb` now means the same thing on every row

- Echo-TTS and MOSS-TTS-Nano shipped with `size_gb` that already folded in their
  companion codec (7.5 GB and 0.36 GB), while every older family lists weights
  only. With the new "with deps" total this read as nonsense — Echo showed
  "7.5 GB … 7.47 GB with deps". Both are now weights-only (5.6 GB / 0.29 GB) and
  the UI derives the true total, so the column is consistent catalogue-wide.

## [1.29.1] — 2026-08-05

### Fixed — Audio8's memory floor was an estimate, and it was too low

- Audio8 shipped in 1.28.0 with `min_unified_memory_gb=8`, inferred from its
  2.55 GB download rather than measured — the `verbose=False` workaround added
  for its crash bug also suppressed the line that reports peak memory, so the
  number was never observed.
- Measured now: peak scales with **output length**, because activations
  dominate rather than weights — 2.55 GB after load, **5.39 GB** on a short
  line, **9.44 GB at 246 characters**. Voice Studio renders 280-character
  sections, so the production peak is ~10 GB and an 8 GB Mac would swap or
  fail. Floor corrected to **16 GB**, with the measurement recorded inline.
- Runtime measured at the same time (model cached, warm): 2.2 s load;
  1.65x slower than real time on a full section (27.7 s of compute for 16.76 s
  of audio), versus 3-4x on short lines — Audio8 is markedly more efficient
  per second of audio when a section is filled.

## [1.29.0] — 2026-08-05

### Added — Echo-TTS

- **Echo-TTS** (`mlx-community/echo-tts-base`, family `echo-tts`) — a diffusion
  (DiT) TTS built on Fish Audio's S1 codec, via mlx-audio's `echo_tts` engine.
  44.1 kHz, CC-BY-NC-SA-4.0 (non-commercial **and** ShareAlike — the most
  restrictive license in the catalog).
- **Clones from a reference clip alone — no transcript required.** Verified
  against the installed engine source: `generate()` has no `ref_text` parameter
  at all, so a library voice without a saved transcript works. That makes it
  the only clone-capable family with no transcript dependency.
- Pulls the Fish S1 DAC codec (`jordand/fish-s1-dac-min`, ~1.87 GB) as a
  companion download, so the honest first-run cost is ~7.5 GB, not the model
  repo's 5.6 GB. Registered in `FAMILY_COMPANIONS` so the cached badge stays
  truthful.
- Voice Studio's seed is threaded into Echo's own `rng_seed` sampler argument —
  it does not draw from `mlx.core.random`, so seeding that alone would not have
  made a history reuse repeatable.

### Hardware floor is measured, not estimated

- Declared `min_unified_memory_gb=24`, derived from a real local run rather
  than the file size: **zero-shot peaked at 8.93 GB, cloning at 18.35 GB.**
  Cloning therefore does **not** fit a 16 GB Mac — the 16 GB machine used for
  the measurement only finished by swapping, which is also why its observed
  speed is not representative. The existing memory guard was confirmed to
  enforce this end-to-end: submitting an Echo job on a 17.2 GB Mac is refused
  with an actionable message instead of swapping or failing mid-generation.
- Quality verified by transcribing output back and measuring word coverage:
  100% on short zero-shot and clone samples, and semantically complete on a
  287-character section (the only diffs were Whisper's own spelling variants).
  Long-form sections are capped at 300 characters, inside Echo's ~30-second
  acoustic window.

### Evaluated and rejected — Ming-omni-tts 0.5B

- `mlx-community/Ming-omni-tts-0.5B-4bit` was evaluated and **not added**. It
  looked strong on every shallow metric (loads in 9 s, runs faster than real
  time, ~1.4 GB peak, clean non-silent audio) but transcribe-back showed it
  silently drops text: 93% word coverage at 91 characters, 86% at 140,
  **63% at 174**, and **0% at 191** — where it emitted 1.6 s of gibberish
  instead of the sentence. Not a token cap: raising `max_tokens` 200→600 and
  varying temperature changed nothing; the model's learned stop head fires
  early. Silently dropping words is the worst TTS failure mode, and Voice
  Studio's long-form joiner would have stitched quietly-incomplete sections
  together, so no per-section cap could make it safe.
- Note for anyone revisiting: mlx-audio's `dense` README names
  `mlx-community/Ming-omni-tts-0.5B-bf16` as its supported model, but that repo
  **was never published** — the 4-bit build tested here is the only 0.5B
  variant on the Hub. The properly-supported model is the 16.8B flagship
  (`mlx-community/Ming-omni-tts-16.8B-A3B-4bit`, 10.1 GB), which was not
  evaluated. `onnx`/`onnxruntime` were installed locally for the evaluation but
  deliberately **not** added to `requirements-generation.txt`, since no shipped
  family needs them.

## [1.28.0] — 2026-08-05

### Added — Audio8 TTS Preview + MOSS-TTS-Nano

- Two new MLX-native families, both verified with real local generations
  (Aiden's reference clip) before shipping:
  - **Audio8 TTS Preview** (`mlx-community/Audio8-TTS-Preview-0.6b-bf16`,
    family `arktts`) — DualAR preview model in the style of Fish Audio S2 Pro.
    Zero-shot with the model's single built-in default voice, or clone a
    reference clip (no named preset roster). 44.1 kHz, 11-language preview
    scope, Apache-2.0.
  - **MOSS-TTS-Nano** (`mlx-community/MOSS-TTS-Nano-100M`, family
    `moss-tts-nano`) — OpenMOSS's 100M-parameter voice-cloning TTS. No
    zero-shot mode — a reference clip is always required, but no saved
    transcript is needed. 48 kHz **stereo** output, the only stereo family in
    the catalog; pulls a companion codec repo
    (`OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano`, ~84 MB) at first generation.
    Apache-2.0.
- Both engines landed in mlx-audio v0.4.7 (bumped from the v0.4.6 pin).
  Bumping also required `transformers` 5.9.0 → 5.14.1 (the floor mlx-audio
  v0.4.7 declares); `tokenizers==0.22.2` and `mlx`/`mlx-lm` were already
  within range. Re-verified the whole generation stack before shipping: the
  full import-verify chain, a real Kokoro generation, a real Fish Audio S2
  Pro generation, and a real Whisper transcription through the app's actual
  tokenizer-fallback path (the exact spot that broke once before over a
  similar version mismatch) — all still pass.
- Neither new model ships named preset voices — checked the actual
  maintainer-authored mlx-audio source/READMEs rather than guessing.

### Fixed — Audio8 generation crashed before saving audio

- `mlx-audio`'s `arktts` engine builds `GenerationResult.prompt` with a
  different shape (`{"text", "ref_text"}`) than every other engine
  (`{"tokens", "tokens-per-sec"}`). `generate_audio()`'s verbose logging
  (on by default) reads the `tokens-per-sec` key unconditionally and raised
  `KeyError` before the WAV was written — silently discarding every Audio8
  generation. Caught only because generation was verified for real, not just
  imported. Voice Studio now passes `verbose=False` for this family
  specifically; every other family is unaffected.

### Added — Hugging Face link on every model

- Every catalog model (local and, where applicable, in the Generate
  workspace) now links out to its Hugging Face page — in the Models tab's
  expanded model details, and next to the selected model in the Generate
  workspace header. Derived generically from each model's `repo` field, so
  it applies to the full catalog, not just the two new families. Hidden for
  cloud/gateway models, which use a synthetic `provider:key:model_id` id with
  no Hugging Face page to link to.

### Verification

- Real local generations for both new families (zero-shot + Aiden voice
  clone for Audio8; Aiden voice clone for MOSS-TTS-Nano, which has no
  zero-shot mode), confirmed via `ffprobe` (sample rate, channels, duration
  match the engine's reported output).
- Confirmed via direct DOM inspection that the new Hugging Face links resolve
  correctly for local models (including non-`mlx-community` repos like
  `SWivid/F5-TTS`) and correctly disappear for a selected cloud model.

## [1.27.19] — 2026-08-04

### Fixed — Qwen clone retry failures retain complete redacted evidence

- Qwen3-TTS Base jobs now retain redacted quality evidence for every output
  validation attempt. The latest result remains in `quality_validation` for
  compatibility, while `quality_retry_history` records both the initial
  rejection and the one permitted retry.
- A second `QWEN_OUTPUT_TEXT_MISMATCH` remains a controlled terminal failure:
  Voice Studio never publishes an artifact whose transcript does not pass the
  existing Whisper Large validation gate, and it does not fall back to
  x-vector-only cloning or another model.

### Verification

- Added a deterministic forced-retry regression covering seeds 41 → 42,
  unchanged Qwen Base/reference/text inputs, the retry-only 230-character
  section cap, two recorded mismatch attempts, and no final artifact.
- The audited production contract is unchanged: 288-character sections,
  180 ms joins, exact revision pin, 16 GB minimum, one local retry, and
  contract hash `sha256:818d607b274f4f9b9dc224d3f97e9ff5e423bbeb242bef8df7112c6f143d0ef7`.

## [1.27.18] — 2026-08-04

### Changed — Fish qualification wording is evidence-neutral

- The Fish Audio S2 Pro 8-bit memory note now directs operators to controlled
  16 GB and 24 GB qualification evidence without claiming that those tests are
  currently running.

## [1.27.17] — 2026-08-04

### Fixed — Fish Audio S2 Pro no longer claims an unqualified 24 GB floor

- Removed the invented 24 GB unified-memory floor, the matching 32 GB
  long-form recommendation, and the matching warning from the Fish Audio S2
  Pro 8-bit MLX catalog row. The Models UI and API now state that its memory
  tier is unqualified and avoid presenting it as a hardware fit or recommendation.
- Controlled 16 GB and 24 GB Apple Silicon qualification remains the source of
  truth. Until it produces evidence, Fish stays internal-only and the public
  research/non-commercial license warning is unchanged.

### Verification

- Focused catalog coverage confirms the API emits no memory floor and an
  `unqualified` fit state; the client renders “Not yet qualified” and excludes
  the model from automatic RAM-fit recommendations.
- No inference, model download, cache repair, worker restart, approval,
  routing, or publication was performed by this correction.

## [1.27.16] — 2026-08-04

### Removed — Whisper Tiny transcription offering

- Whisper Tiny is no longer advertised, downloadable, or accepted as a Voice
  Studio transcription model. Fleet qualification against the same 42-minute
  control found only 68.10–73.02% source-word coverage, compared with
  99.32–99.35% for Whisper Large v3 Turbo.
- Whisper Large v3 Turbo is the sole GenStudio-qualified transcription model
  and remains qualified on 8, 16, and 24 GB Apple Silicon workers. Voice
  Studio does not silently fall back to Tiny.
- Existing Tiny model and tokenizer cache folders are preserved and shown as
  retired, safely removable packages in Models → Storage & dependencies. This
  release does not delete cached data or alter historical jobs.

No dependency reinstall is required. Run **Update**, then restart Voice Studio.

## [1.27.15] — 2026-08-04

### Fixed — large model downloads no longer stall forever

- Hugging Face's Xet transport is now disabled for model downloads. Xet could
  wedge mid-transfer while holding the repo file lock, so bytes stopped growing
  on disk and `snapshot_download` never returned. The 15-minute stall watchdog
  could then only cancel and restart the attempt.
- Because each attempt writes its own `<blob>.<suffix>.incomplete`, a cancelled
  attempt's bytes were not reused by the next one. Progress fragmented across
  temp files and a large repo could loop indefinitely without completing:
  `mlx-community/fish-audio-s2-pro-8bit` accumulated six partials of a single
  blob (4351/629/201/201/52/31 MB) across repeated attempts and never finished.
  With the classic HTTP transport the same repo completed in one 103-minute
  pass, verified file-by-file against its published manifest.
- The flag is applied before `huggingface_hub` is imported, because its
  constants module reads it at import time and the download child process is
  spawned rather than forked. Set `VOICESTUDIO_ENABLE_XET=1` to opt back in.

## [1.27.14] — 2026-08-03

### Fixed — Qwen3-TTS Base clone hallucination containment

- Qwen Base references are now checked by Whisper Large with word timestamps
  inside the durable generation job. A mismatched or unaligned transcript is
  rejected before Qwen inference, and immutable successful checks are reused.
- Every private Qwen section now receives an automatic model-owned acoustic
  token and duration ceiling. Callers no longer need to supply a safety limit
  to prevent the known 96-second no-EOS exhaustion failure.
- Finished Qwen clone audio is transcribed and compared with the requested
  text before it can become a successful artifact. Repetition, unrelated
  speech, missing text, and implausible duration return stable error codes.
- A certainly rejected local result is retried once with a different seed and
  a shorter 230-character sentence-safe section budget. A second rejection is
  a controlled failure; Voice Studio never silently changes the chosen model.
- Job history now retains redacted validation evidence, retry count, and the
  stable error code without storing customer transcript text in that evidence.

No dependency reinstall is required. Run **Update**, then restart Voice Studio.

## [1.27.13] — 2026-08-03

### Added — visible per-model long-form delivery policies

- Every model using Voice Studio-managed long-form delivery now shows its
  effective sentence-safe section ceiling, join pause, and model-specific note
  directly in the Models library.
- Generation and catalog display now consume one shared policy, including exact
  model-audit overrides, so the visible values cannot drift from runtime
  behavior.
- The catalog API publishes whether the customer submits one complete script,
  the split method, and whether the effective ceiling came from the runtime
  default or an exact model audit.

No dependency reinstall is required. Run **Update**, then restart Voice Studio.

## [1.27.12] — 2026-08-03

### Added — transcription qualification resource evidence

- Successful local Whisper transcription responses now include the same
  worker-owned resource telemetry schema used by TTS qualification: observed
  peak memory, minimum available RAM, macOS memory pressure, swap activity,
  MLX allocator evidence, completion state, and model-retention state.
- Failed transcription attempts still finish their private telemetry sampler
  and classify memory-allocation failures before the loaded model is evicted.
  No credentials, filesystem paths, or customer audio/text are added to the
  evidence payload.
- Focused tests cover successful evidence publication and failure cleanup so
  Whisper Tiny and Large v3 Turbo can be compared consistently across real
  8, 16, and 24 GB fleet workers.

No dependency reinstall is required. Run **Update**, then restart Voice Studio.

## [1.27.11] — 2026-08-03

### Changed — owner-approved Qwen cloning continuity

- Qwen3-TTS Base voice cloning now uses a verified 288-character private
  sentence-safe section ceiling after owner listening found it free of the
  tonation change heard with the previous 360-character ceiling.
- Qwen Base clone joins now use a slightly more relaxed 180 ms narration pause
  instead of 120 ms. Other model families and Qwen CustomVoice retain their
  existing section budgets and pauses.
- The public customer request remains one complete script and returns one
  validated WAV; these pacing controls remain private adapter details.

No dependency reinstall is required. Run **Update**, then restart Voice Studio.

## [1.27.10] — 2026-08-03

### Fixed — cancellable OmniVoice long-form cloning

- OmniVoice cloning now privately divides long scripts into conservative,
  sentence-safe sections while reusing the same reference voice for every
  section, then returns one validated, joined WAV.
- Multi-minute OmniVoice jobs now report section progress and honor
  cancellation between sections instead of entering one opaque, hours-long
  diffusion call.
- Customer requests remain whole: the internal 288-character section budget
  is an implementation detail and is not exposed as a customer text limit.

No dependency reinstall is required. Run **Update**, then restart Voice Studio.

## [1.27.9] — 2026-08-03

### Changed — grounded VibeVoice preset inventory

- VibeVoice Realtime now exposes the exact 25 preset files shipped by the
  supported MLX checkpoint instead of accepting an unrestricted voice name.
- Its seven English and Indian-English presets are distinguished from the 18
  upstream-labelled experimental presets across nine additional languages.
  Experimental presets remain available for owner research but are not
  presented as commercially qualified language support.
- The backend rejects nonexistent VibeVoice presets before model execution,
  and the UI shows the verified roster as selectable buttons.

No dependency reinstall is required. Run **Update**, then restart Voice Studio.

## [1.27.8] — 2026-08-03

### Changed — closed Group B rejections

- Qwen3-TTS 0.6B CustomVoice and Chatterbox 4-bit now carry durable,
  hash-bound failed qualification records. Both remain usable for local
  internal testing, but neither is a GenStudio candidate and neither can be
  promoted by Studio Hub from these records.
- The CustomVoice record preserves its exact nine-speaker roster, completed
  tier evidence, unresolved long-form text-integrity result, and the owner's
  inconsistent-quality rejection.
- The Chatterbox record preserves all 23 tested language cases, unsafe 8 GB
  long-form pressure, substantially slower-than-real-time 16 GB endurance,
  and the owner's production-latency rejection.

### Verification

- Audit-contract tests prove both exact immutable revisions are closed as
  `failed`, `candidate_for_genstudio` is false, contract hashes are valid, and
  no sibling record claims final exposure authority.

No dependency reinstall is required. Run **Update**, then restart Voice Studio.

## [1.27.7] — 2026-08-03

### Added — qualified Qwen3-TTS voice cloning

- Qwen3-TTS 0.6B Base now publishes an exact, hash-bound GenStudio candidate
  for transcript-assisted voice cloning at its immutable MLX 8-bit revision.
- The audited contract records 3–15 second technical reference limits, an
  8-second default and 8–12 second preferred reference window, 40,000-character
  adapter-managed long form, 24 kHz WAV output, and one physical execution slot.
- Qualification evidence preserves the successful 8, 16, and 24 GB runs while
  setting the safe commercial floor to 16 GB and the preferred tier to 24 GB.

### Changed — truthful cloning and hardware requirements

- The catalog uses the official **Qwen3-TTS 0.6B Base** name, advertises only
  the ten upstream-supported languages, and no longer describes the model as
  suitable for 8 GB production machines.
- Qwen Base cloning now requires the exact reference transcript. Voice Studio
  no longer substitutes a meaningless placeholder that silently selects a
  lower-fidelity or unverifiable cloning path.

### Verification

- Focused audit, catalog, reference-audio, generation, release-metadata, and
  Studio Hub contract tests cover the exact candidate, 16 GB eligibility,
  transcript enforcement, 8–12 second guidance, and 40,000-character flow.

No dependency reinstall is required. Run **Update**, then restart Voice Studio.

## [1.27.6] — 2026-08-03

### Fixed — truthful repair-download progress

- Repair downloads now count completed bytes only when they belong to the
  requested immutable snapshot. Existing unversioned or other-revision cache
  inventory remains untouched and visible as pending verification, but can no
  longer force a running transfer to display 100% prematurely.
- Live speed and ETA use only verified snapshot bytes plus resumable partials.
  A running transfer stops at 99.9% while Hugging Face finalizes its snapshot;
  100% remains the explicit signal that the download completed successfully.
- Successful cleanup and retry behavior are unchanged: verified terminal jobs
  still show 100%, stale partials are pruned only by their successful owner,
  and failed or cancelled attempts keep resumable bytes.

### Verification

- Focused cache and download regressions cover unversioned standalone bytes,
  exact immutable-snapshot accounting, growing resumable repairs, companion
  progress, terminal success, and finalization without a misleading ETA.
- The full Voice Studio test suite passes, along with release metadata and
  frontend syntax checks.

No dependency reinstall is required. Run **Update**, then restart Voice Studio.

## [1.27.5] — 2026-08-03

### Fixed — immutable model-cache readiness

- Model and dependency cache entries now become runnable only when the
  selected snapshot has an immutable revision. Historical `snapshots/main`
  layouts remain visible as partial and retain all existing complete and
  resumable bytes for normal Hugging Face reconciliation.
- Model availability also verifies that model weights belong to the selected
  immutable snapshot, rather than accepting weights found only in a separate
  mutable folder.
- Manual stale-partial cleanup no longer treats an unversioned layout as a
  verified complete snapshot, preventing repairable bytes from being removed
  before reconciliation.

### Verification

- Focused cache, download, fleet API, and storage tests cover unversioned model
  and dependency layouts, immutable-snapshot weight fencing, repair download
  scheduling, and preservation of resumable partials.

No dependency reinstall is required. Run **Update**, then restart Voice Studio.

## [1.27.4] — 2026-08-03

### Fixed — dependency-aware model download completion

- Download progress, byte-rate observation, and stall detection now aggregate
  the selected model with every required companion repository. A Chatterbox
  transfer therefore continues to advance while S3TokenizerV2 is downloading
  and a successful terminal job always displays 100%.
- After a successful, still-owning `snapshot_download` job, Voice Studio now
  safely prunes stale unresolved partials for both the main model and its
  companions. Failed, cancelled, stalled, and replaced attempts retain their
  resumable partial files; manual cleanup remains manifest-conservative.

### Verification

- Focused download tests cover companion-phase progress, companion growth
  avoiding a false stall, terminal 100%, successful paired cleanup, failed and
  cancelled preservation, and active-replacement protection.

---

## [1.27.3] — 2026-08-03

### Fixed — local TTS pathological silent tails

- Voice Studio now detects and atomically removes a multi-second terminal
  silent tail from Qwen3 CustomVoice and Chatterbox output before publishing
  it. A tiny late blip can no longer preserve a preceding pathological silence
  span; normal interior pauses and short natural ending pads are preserved.
- The correction is deliberately restricted to those two local TTS adapter
  modes. Qwen clone mode, other TTS models, transcription, and
  source/reference recordings are untouched.

### Verification

- Artifact tests cover preserved normal pauses, the reported Qwen and Spanish
  Chatterbox short-speech / long-silence shapes, late-blip rejection, short
  valid audio unchanged byte-for-byte, Qwen clone exclusion, and corrected
  duration/size/checksum evidence.

---

## [1.27.2] — 2026-08-03

### Fixed — resilient Hugging Face download transport

- Disabled the Hugging Face Xet transport before the Hub library is imported.
  This avoids the observed stalled-transfer and held-cache-lock failure mode;
  normal HTTP downloads continue to resume the same partial cache files.
- Added the explicit `VOICESTUDIO_ENABLE_XET=1` opt-in for a diagnosed machine
  that needs to use Xet.

### Verification

- Focused subprocess tests prove that the default, an inherited conflicting
  Hub flag, and the explicit opt-in are all resolved before
  `huggingface_hub` imports.

---

## [1.27.1] — 2026-08-03

### Added — offline Wave 1 qualification draft foundation

- Added a standard-library-only planner and validator for the exact Wave 1
  Qwen CustomVoice, Qwen Base clone, and Chatterbox clone qualification matrix.
  It records only draft/pending evidence and explicitly rejects passed audit
  material, provider activity, live execution state, and non-8/16/24 GB tiers.

### Verification

- Focused contract tests cover the exact nine Qwen speakers, 23 Chatterbox
  languages, required short/long/cancellation cases, deterministic manifests,
  and audit-promotion rejection.

---

## [1.27.0] — 2026-08-03

### Added — truthful structured language support in the model catalog

- Catalog models now expose a backward-compatible `language_support` object.
  Exact language codes are separated from count-only and lower-bound coverage
  claims, so API and Studio Hub clients never receive display placeholders as
  machine-readable languages.
- VoxCPM2 now exposes its complete 30-code language enumeration, while
  OmniVoice (646 claimed) and Fish S2 Pro (80+ claimed) expose non-actionable
  coverage claims until their exact runtime contracts are audited.
- Chatterbox now exposes and validates its 23 exact language codes, and the
  Generate view requires an explicit language selection that is forwarded to
  MLX Audio as `lang_code`. Chatterbox Turbo truthfully exposes its
  English-only exact selector under the same adapter contract.

### Changed

- Model cards now show compact exact or claimed language coverage instead of
  rendering pseudo-language entries such as `+70 more`.

### Verification

- Focused catalog/API and Chatterbox adapter tests verify exact enumerations,
  no placeholders, non-selectable claimed coverage, and language validation.

No dependency reinstall is required. Run **Update**, then restart Voice Studio.

---

## [1.26.4] — 2026-08-03

### Fixed — Kokoro catalog contract matches audited capabilities

- Removed the unsupported streaming-request capability from Kokoro's catalog
  entry. The model remains fast for local narration, but it does not expose a
  streaming request API.
- Made Kokoro's catalog hardware guidance explicit: Apple Silicon with at
  least 8 GB unified memory.

### Verification

- Focused catalog/audit regression coverage verifies the public catalog's
  streaming and hardware claims against the hash-bound GenStudio candidate.

---

## [1.26.3] — 2026-08-03

### Fixed — accurate model-cache storage accounting

- The Storage & dependencies view and whole-package cleanup now include real
  files stored directly in Hugging Face snapshot folders, not only blob-store
  entries. Shared snapshot symlinks and hardlinks remain counted once, and
  unfinished files remain excluded.

### Verification

- Focused cache and model-storage tests cover snapshot-only and blob-only
  caches, link de-duplication, unfinished-file exclusion, and reported cleanup
  space.

---

## [1.26.2] — 2026-08-03

### Fixed — automatic updates support linked Git worktrees

- The production auto-updater now accepts Git's standard linked-worktree
  `gitdir:` file when it points to an existing Git metadata directory. Unsafe,
  malformed, missing, and symlinked checkout roots continue to be refused.

### Verification

- Focused updater tests cover accepted linked-worktree metadata plus malformed,
  missing-target, and symlinked-root refusals.

---

## [1.26.1] — 2026-08-02

### Added — managed model storage and dependency families

- Models now includes a **Storage & dependencies** view that indexes every
  existing Hugging Face cache folder in place. Nothing is moved or downloaded
  again: executable models, shared tokenizers/codecs, missing companions,
  legacy alternatives, partial transfers, and unrecognised packages are
  labelled and grouped under their real model family.
- Shared dependencies show every installed parent that needs them and are
  protected from deletion. Missing companions remain visible beneath their
  parent and offer a guided **Complete model** action.
- Whole-package removal now uses a guarded API and an in-app confirmation. It
  refuses active downloads, active generation/transcription, loaded models,
  paths outside the managed cache, and dependencies still in use.
- Voice Studio writes `README-VOICE-STUDIO-CACHE.md` beside the raw Hugging
  Face folders so Finder users know not to rename or delete individual cache
  internals.

### Verification

- Focused inventory tests cover in-place discovery, dependency protection,
  tokenizer-only companions, missing companions, legacy cleanup, unknown
  packages, and whole-package removal.
- The full Voice Studio suite passes, and the family tree, protected-removal
  confirmation, missing-companion state, desktop layout, and 390 px mobile
  layout were verified through the real web interface without horizontal
  overflow.

## [1.26.0] — 2026-08-02

### Added — per-job local resource evidence

- Every local TTS job now samples host unified memory, Darwin memory pressure,
  swap activity, Voice Studio process-tree RSS, and MLX allocator use while the
  exact model attempt is running.
- Active and terminal job responses expose a versioned
  `voicestudio.resource-telemetry` summary with observed peaks, the lowest free
  memory, before/after values, sample timing, and the terminal memory outcome.
- Terminal telemetry is persisted with job history across Voice Studio
  restarts. It reports measurements only; it does not invent or automatically
  change a model's minimum-RAM qualification.

### Verification

- Focused tests cover peak/delta aggregation, unavailable platform probes,
  local-generation publication, and restart-safe job serialization.
- The probes are best-effort on non-macOS test runners and never prevent a
  generation job from running.

## [1.25.2] — 2026-08-02

### Changed — Kokoro supplemental commercial evidence

- Reissued Kokoro's exact audit candidate for adapter 1.1 after a live
  snapshot-symlink generation, all 54 stock voices, and the requested real
  40,000-character Lewis endurance run passed.
- The 54 native-language preview WAVs use distinct scripts and all measure
  between 20.175 and 29.900 seconds. The 40,000-character output contains 55
  private sections, lasts 2,567.705 seconds, and has no clipped samples.
- Bounded Whisper verification matched 6,540 of 6,583 source words (99.3468%
  coverage). The audit records that one unbounded 42-minute Whisper request
  restarts the 16 GB worker; this is a transcription-adapter limitation and
  does not alter Kokoro's passed adapter-managed long-form result.

### Verification

- The updated audit contract hash is recomputed and validated by the focused
  model-audit suite. Generated evidence is stored outside the release tree in
  the dated fleet-audit sample folder.

## [1.25.1] — 2026-08-02

### Fixed — cached Kokoro voicepacks generate through the live API

- Preserve each snapshot voicepack's `.safetensors` filename when passing it
  to Kokoro. Resolving Hugging Face's symlink to its extensionless blob name
  made the runtime treat that path as a voice ID, append another extension,
  and finish without producing a WAV.
- Added a regression test using the same snapshot-symlink layout as the real
  Hugging Face cache. The live failure is now represented in the test suite,
  rather than covered only by ordinary-file fixtures.

### Verification

- The focused Kokoro, audited-contract, and priority-model suites pass. A live
  Lewis generation is required after the active model download finishes and
  Voice Studio restarts onto this patch.

## [1.25.0] — 2026-08-02

### Added — private customer references and adapter-managed long form

- Added a checksum-bound private reference-audio endpoint for assigned
  GenStudio work. Voice Studio derives a model-compatible PCM reference using
  the exact audited duration, sample-rate, transcript, and alignment contract
  while keeping local paths and private request fields out of job responses.
- Model catalogues now publish audit-derived reference-audio requirements and
  long-form execution capabilities, including the public 40,000-character
  request ceiling and each adapter's private sentence-safe chunk budget.
- Generation results now report reference-source and prepared-audio checksums,
  preprocessing revision, prepared duration, long-form strategy, and chunk
  totals so Studio Hub can verify the exact execution evidence.

### Changed — model adapters own model-specific audio work

- Clone-capable local adapters can consume a temporary prepared customer
  reference without creating a permanent Voice Studio library voice. The
  original upload remains owned by GenStudio; Voice Studio caches only a
  deterministic derived execution reference until its supplied expiry.
- Long requests are split inside Voice Studio at audited sentence-safe limits,
  then generated, validated, stitched, and speed-adjusted through the existing
  adapter path. A model can therefore qualify as adapter-managed long form
  without claiming one-pass 40,000-character support.
- Job logging now redacts source text; job serialization redacts private paths
  and internal preparation parameters while preserving safe progress and
  terminal evidence.

### Verification

- Focused tests cover duration selection, timestamp-aligned transcript slicing,
  deterministic cache reuse, private-field redaction, exact adapter injection,
  audited chunk sizing, catalog capabilities, and terminal evidence.
- The complete Voice Studio suite passes without loading a model, downloading a
  dependency, or calling a paid provider.

## [1.24.0] — 2026-08-02

### Added — revision-bound Group A model audits

- Added durable, machine-readable audit records for the exact cached Kokoro
  82M bf16, Whisper Large v3 Turbo, and Whisper Tiny checkpoints.
- `/api/catalog` and `/api/transcribe/availability` now attach a versioned
  `genstudio_candidate` summary with the immutable runtime revision, exact
  operations, adapter, controls, limits, hardware evidence, capacity ceiling,
  and contract hash. This is candidate evidence only; Studio Hub still owns
  deliberate exposure and no `approved_for_genstudio` authority is emitted.
- Kokoro's record enumerates all 54 stock voices and the nine language
  pipelines. Whisper records enumerate the accepted audio formats, 100
  language codes, timestamp controls, and stable response fields.

### Fixed — audited local execution remains bounded to real assets

- Kokoro now loads its verified preset voicepacks from the exact cached model
  revision instead of performing a surprise first-use download from another
  repository. The catalog's stale MIT wording was corrected to the model
  cards' Apache-2.0 license.
- Whisper transcription now probes the source-media duration, removes tokens
  emitted in a padded-silence window, and clamps segment and word timestamps
  to the real file. This prevents Whisper Tiny from appending junk text and
  impossible 30-second timestamps to a short clip.

### Verification

- All 54 Kokoro voicepacks were present, loadable, and shape-consistent; one
  preset from each of the nine language pipelines generated non-silent 24 kHz
  audio offline. Speeds 0.5x, 1.0x, and 2.0x produced the expected duration
  ordering.
- Both Whisper checkpoints transcribed the same deterministic 3.278-second
  local speech fixture with one bounded segment, eight word timestamps, and
  valid SRT/VTT. WAV, MP3, FLAC, M4A, AAC, OGG, Opus, and WebM decoding passed;
  unsupported AIFF is deliberately not advertised.
- Focused contract, catalog, generation, artifact, and transcription tests and
  the full Voice Studio suite pass. Other cached models remain unaudited and
  unmodified; no Hub exposure, GenStudio product, paid provider call, service
  restart, or dependency reinstall was performed.

## [1.23.4] — 2026-08-01

### Fixed — cancelled placeholders no longer block completed models

- Zero-byte Hugging Face `.incomplete` placeholders left by an interrupted
  worker are now recognized as non-resumable metadata and safely removed on
  the next reconciliation.
- Non-empty partial blobs remain untouched and resumable; a real model
  snapshot is never deleted to clean up download history.

### Verification

- Cache and download tests cover both resumable non-empty partials and empty
  cancellation placeholders.

## [1.23.3] — 2026-08-01

### Fixed — stalled model retries release their transfer process

- Hugging Face model transfers now run in an interruptible worker process.
- A stalled retry terminates the blocked transfer before starting the next
  attempt, so it cannot hold a file lock and leave the replacement queued
  forever.
- The retry continues using the existing Hugging Face cache and `.incomplete`
  blobs; it does not create a fresh duplicate download.

### Verification

- Focused download, cache, and fleet-auth tests pass. Existing generation and
  cache files are left untouched during recovery.

## [1.23.2] — 2026-07-30

### Fixed — self-healing resumable model transfers

- Successful model downloads now automatically remove only stale Hugging Face
  partial blobs that are proven unnecessary by the exact current manifest,
  completed snapshot, and real model weights. Normal incomplete files remain
  intact and resumable.
- A running download with no observed byte progress for 15 minutes is safely
  marked for cancellation on the next download or Hub reconciliation request,
  then replaced with one fresh resumable attempt. It never deletes the partial
  files or interrupts Voice Studio generation.

### Verification

- Added completed-download cleanup and stalled-transfer recovery coverage.
  **Just run Update.**

## [1.23.1] — 2026-07-30

### Fixed — completed model downloads are idempotent

- `POST /api/downloads` now returns an explicit `already_cached` result instead
  of creating another terminal download job when the requested immutable model
  snapshot is already complete. The Downloads page therefore stays a truthful
  history instead of accumulating duplicate “done” rows during fleet checks.
- A safely provable stale Hugging Face `.incomplete` blob is pruned before this
  decision only when Voice Studio verifies the current official manifest byte
  total, a complete snapshot, and real model weights. Active and resumable
  downloads are never removed or interrupted.
- A request pinned to a different immutable revision still downloads that
  revision; an existing cache is never falsely reused.

### Fleet compatibility

- Studio Hub can now treat a worker that safely repaired its cache during a
  baseline reconcile as ready immediately, without recording a fake queued
  download. This is a patch-level protocol addition; existing workers remain
  compatible.

### Verification

- Added API coverage for completed-cache deduplication and immutable-revision
  protection, alongside the existing cache and fleet-auth tests. **Just run
  Update.**

## [1.23.0] — 2026-07-30

### Added — MLX-Audio v0.4.6 and Fish Audio S2 Pro

- Pinned `mlx-audio` to the immutable v0.4.6 release commit
  `d28d68c6ac4e28f7d2d66007f640b06cf3fd8ceb`, bringing the current upstream
  Chatterbox fixes, OmniVoice engine, and Fish S2 Pro support to every future
  Generation install.
- Added functional Fish Audio S2 Pro MLX rows for the published 8-bit and bf16
  checkpoints. Fish uses the existing MLX-Audio stack and its bundled codec—no
  separate Fish Python package or companion model is required.
- Fish S2 Pro supports optional Voices-library cloning, natural-language style
  prompts, private sentence-safe long-form sections, final WAV joining, and one
  pitch-preserving speed pass after the join. Sampling controls are recorded in
  the normal job parameters.
- The catalog records the observed 44.1 kHz output, approximately 6.73 GB / 11.01
  GB download sizes, and conservative 24 GB / 32 GB unified-memory floors. It
  clearly marks Fish Audio's public research/non-commercial license boundary.

### Audited — OmniVoice dependencies and quantized artifacts

- OmniVoice remains wired through the pinned MLX-Audio loader; there is no
  separate `omnivoice` package in the tracked Generation requirements. The
  stale package in an existing environment was deliberately not removed while
  the live service was left untouched.
- The published OmniVoice 4-bit and 8-bit rows remain excluded because their
  custom `omnivoice-rowwise` manifests are not loadable by MLX-Audio v0.4.6's
  generic quantization loader. The compatible bfloat16 row remains available.

### Verification

- Truth audit, focused model/generation/release tests, JavaScript/Python syntax
  checks, and the full test suite pass. The live process was not restarted or
  reinstalled; run **Reinstall Generation** and restart the worker to activate
  the new MLX-Audio pin.

## [1.22.1] — 2026-07-27

### Fixed — fleet model downloads use the available connection

- Enabled Hugging Face Xet high-performance downloads in both regular Pinokio
  mode and the always-on startup service. Large fleet model rollouts no longer
  let Xet's adaptive controller collapse an otherwise healthy connection to a
  single slow range transfer.
- Existing partial downloads remain resumable. Updating and restarting a Voice
  Studio continues from its cached bytes with the faster transfer policy.

### Verification

- Added launcher regression coverage for both launch modes and retained the
  existing URL capture, service lifecycle, model cache, and generation
  behavior. **Just run Update.**

## [1.22.0] — 2026-07-27

### Added — 40,000-character Kokoro and VibeVoice long-form execution

- Kokoro and VibeVoice now accept one logical long-form request while Voice
  Studio privately splits it into sentence-safe sections of at most 3,000
  characters, validates every section, and returns one joined final WAV.
- VibeVoice sections receive a 4,096-token acoustic budget—about nine minutes
  at its 7.5 Hz frame rate—rather than inheriting MLX Audio's short default.
- VibeVoice speed now uses the established pitch-preserving final-file
  processor exactly once after all sections are joined.

### Fixed — hour-scale joining stays safe on 8 GB Macs

- Long-form WAV joining now streams verified section files from disk instead
  of concatenating the entire decoded project in memory.
- The joined candidate is published atomically only after every section and
  the complete output succeed. Missing, empty, incompatible, or unreadable
  sections cannot leave an apparently successful partial result.
- Kokoro's catalog no longer advertises a 1,200-character caller-side soft
  limit; callers send one request and receive one final file.

### Verification

- Added 40,000+ character conservation tests for Kokoro and VibeVoice,
  model-specific section ceilings, VibeVoice acoustic-budget and one-time speed
  assertions, atomic failure coverage, and disk-streaming join regression
  coverage. **Just run Update.**

## [1.21.12] — 2026-07-24

### Fixed — Pinokio 8 maintenance crash

- One-click Update and Install Generation now resolve this app's `start.js` to
  its canonical absolute path before calling Pinokio's `script.stop` API.
  Pinokio 8.0.40 no longer receives the rejected bare relative URI that could
  crash its interface with an unhandled rejection.
- Startup-service behavior, dependency locks, model installation, generation
  queues, and active jobs are otherwise unchanged.

### Verification

- Added launcher contract coverage requiring canonical stop URIs in every
  Voice Studio maintenance path. Node syntax, release metadata, backend
  compilation, and the complete test suite pass. **Just run Update.**

## [1.21.11] — 2026-07-23

### Changed — 30-day fleet backup retention

- Raised completed voice-output backup retention from 3 days to 30 days while
  retaining the 80 GB hard cap and protected shared voices, cloning references,
  uploads, models, credentials, and active jobs.
- Existing saved 3-day policies migrate automatically once during update.
  Later explicit operator choices remain respected, so fleet workers require no
  individual configuration.

### Verification

- Added regression coverage for automatic legacy migration and explicit
  post-migration policy choices. **Just run Update.**

## [1.21.10] — 2026-07-23

### Fixed — watchdog confirms failures before restarting

- The always-on Voice Studio watchdog now requires three consecutive failed
  health probes before restarting the service, matching the proven Image Studio
  policy and preventing one transient miss from interrupting active work.
- A successful probe immediately clears the repo-local failure streak. The
  threshold accepts a validated numeric environment override and safely falls
  back to three for invalid or unsafe values; its state remains under the
  git-ignored per-machine `service/` directory.
- Restart-rate evidence recognizes both historical one-miss restart records and
  the new confirmed-failure records without counting the first two probe misses
  as restarts.

### Verification

- Added isolated watchdog process tests for the three-failure threshold,
  immediate success reset, numeric override validation, ignored local state,
  and restart-log compatibility. No live service or job restart is required.
  **Just run Update.**

## [1.21.9] — 2026-07-23

### Security — fleet credentials stay out of URLs

- Remote Voice Studio requests now accept the existing `X-Studio-Token`,
  Bearer, and protected-cookie credentials but reject `?token=...`, preventing
  fleet secrets from leaking through browser history, logs, or copied links.
- Studio Hub's current direct and proxied Voice Studio callers were verified to
  use authenticated headers, so the established fleet path remains compatible.

### Fixed — long-form wording and readable operator controls

- Corrected the retired 30-second GenStudio wording. Generated TTS has no
  default duration ceiling; Voice Studio still owns long-form internal
  chunking, joining, and the one final speed adjustment. The optional
  `max_output_duration_s` compatibility guard remains opt-in for explicit
  callers, and stable `client_request_id` replay remains unchanged.
- Added a 12 px text floor plus shared 15 px/40 px control sizing, with a 32 px
  compact allowance for dense tabs and small actions. A regression guard now
  rejects future sub-12 px CSS declarations.
- Aligned the common Pinokio action order, renamed the service repair action to
  **Repair Startup Service**, kept destructive actions last, and expanded the
  launcher test to prove **What's New** appears in every dynamic state.

### Added — read-only restart-rate evidence

- `/api/health` and `/api/generate/diagnostics` now report bounded watchdog
  restart counts for the last 24 hours and seven days, a severity, most recent
  restart, and operator message. The probe reads only a small log tail and does
  not restart services, change health status, or alter active jobs.

### Verification

- Added authentication, long-form request, launcher-state, typography, and
  restart-rate regression coverage. **Just run Update.**

## [1.21.8] — 2026-07-21

### Fixed — Kokoro and Chatterbox completion evidence

- Completed Kokoro jobs now report the exact immutable cached model revision
  and a preset voice revision derived from that snapshot and the selected
  Kokoro voice key.
- Completed Chatterbox jobs now report the exact immutable cached model
  revision and the digest of the account-private reference audio actually used.
- GenStudio can therefore reject stale or mismatched Kokoro and Chatterbox
  results before publishing a customer asset or qualifying an 8 GB worker.

### Verification

- Added regression coverage for Kokoro preset evidence and Chatterbox cloned
  voice evidence. **Just run Update.**

## [1.21.7] — 2026-07-20

### Fixed — pinned downloads repair mutable imported caches

- Cache revision detection now rejects mutable snapshot folder names such as
  `main` and falls back only to an immutable 40–64 character commit snapshot.
- The authenticated download API accepts an optional immutable revision hash
  and passes it through to Hugging Face, allowing a drained worker to repair an
  imported cache to the exact GenStudio-approved model revision.

### Verification

- Added mutable-cache and pinned-download regression coverage and ran the full
  Voice Studio suite plus the release guard. **Just run Update.**

## [1.21.6] — 2026-07-20

### Fixed — immutable model revision is advertised before dispatch

- Voice Studio's authenticated model catalog now includes the exact immutable
  Hugging Face snapshot revision for every locally cached model. Mutable refs
  such as `main` are never substituted.
- Studio Hub can therefore prove that a worker has the exact model revision
  requested by GenStudio before assigning customer work, instead of discovering
  a mismatch only after generation completes.

### Verification

- Added cache-catalog regression coverage and ran the full Voice Studio suite
  plus the release guard. **Just run Update.**

## [1.21.5] — 2026-07-20

### Fixed — release guard now requires a real version increase

- Tightened `release_metadata_check.py`: touching `VERSION` is no longer
  enough. Any shipped change must move the semantic version numerically forward
  from its Git baseline as well as provide the matching **What's New** entry.

### Verification

- Added version-increase regression coverage and ran the release checker and
  full Voice Studio suite. **Just run Update.**

## [1.21.4] — 2026-07-20

### Added — enforced release notes for every shipped change

- Added `release_metadata_check.py` and regression coverage. It requires a
  semantic version, a matching top changelog release, and a clear release-note
  category and bullet; when product files change it also requires both
  `VERSION` and `CHANGELOG.md` to change.
- Documented the same rule for contributors, so the in-app **What's New** view
  always describes the installed release rather than relying on memory.

### Verification

- Ran the release-metadata checker and the full Voice Studio test suite.
  **Just run Update.**

## [1.21.3] — 2026-07-20

### Added — maintained VoiceStudio ↔ GenStudio integration boundary

- Added `app/backend/voicestudio_genstudio_integration.py` as the single,
  versioned owner of VoiceStudio's final TTS evidence envelope for GenStudio.
  Future worker-owned integration fields now have one explicit extension point.
- `GenerationJob.serialize()` now uses that module directly. Studio Hub remains
  authoritative for worker assignment and routing; GenStudio remains
  authoritative for customers, billing, job ownership, and publication.

### Verification

- Added integration-envelope regression coverage and ran the focused VoiceStudio
  generation suite plus backend compilation. **Just run Update.**

## [1.21.2] — 2026-07-20

### Fixed — GenStudio long-form and immutable audio evidence

- Extended Voice Studio's sentence-safe Qwen chunking to preset regular voices
  and VoiceDesign as well as cloned voices. Qwen and VoxCPM2 still join every
  private section into one WAV and apply pitch-preserving speed exactly once
  after the join.
- Added atomic final publication: local generation writes to a hidden staging
  WAV, validates every section, joins, adjusts speed, derives final media facts,
  and only then exposes the final job artifact. A failed or cancelled section
  cannot leave a successful-looking partial file.
- Added immutable model snapshot evidence for VoxCPM2 and immutable reference
  audio evidence for VoxCPM2 library clones, matching the existing Qwen fences.
- Added final WAV duration, sample rate, channels, byte size, SHA-256, media
  type, and format to the worker result, plus explicit internal model,
  runtime-revision, and voice-library identities.
- Made health and catalog inventory report busy/load state, runtime readiness,
  current availability, and exact cold/loaded free-memory admission floors.
  Qwen 1.7B tiers now truthfully require 16 GB total unified memory; 0.6B
  remains the supported 8 GB tier.

### Verification

- Added independent Qwen regular, Qwen clone, and VoxCPM2 chunking, joining,
  speed-order, revision, atomic-failure, media-evidence, and inventory tests.
- Confirmed Studio Hub only adopts the final worker artifact and validates its
  bytes before terminal publication. GenStudio independently validates those
  bytes and now preserves the exact clone-library identity with its immutable
  voice revision.
- No dependency or launcher change is required. **Just run Update.**

## [1.21.1] — 2026-07-20

### Added — exact VoxCPM2 speed control

- Added the existing `0.50x`–`2.00x` speed control to VoxCPM2 generation.
- VoxCPM2 still renders each sentence-safe section at its native pace, preserving
  reference voice and delivery instructions, then Voice Studio applies one
  pitch-preserving FFmpeg tempo adjustment after the final WAV is stitched.
- Short and long-form VoxCPM2 jobs now share the same atomic, format-validated
  post-processing path as Qwen without passing an ignored speed argument into
  the model.

### Verification

- Added duration, post-processing-order, and WebUI visibility regression tests.
- No dependency or launcher change is required. **Just run Update.**

---

## [1.21.0] — 2026-07-20

### Added — opt-in voice model memory controls

- Added Performance (default), Balanced (10 minutes), Memory Saver (2 minutes),
  and Immediate modes for local TTS and Whisper transcription models.
- Added **Release Memory / Unload Model**, which releases both TTS and STT
  caches together under their shared GPU lock, clears Python, PyTorch, MLX,
  and Metal allocator caches, and never deletes weights, shared voices,
  cloning references, or generated audio.
- Added the friendly **Voice Studio Mac** process title for Activity Monitor.
  Active generation or transcription is never interrupted.

### Verification

- Added default-mode, idle timing, dual-cache release, active-work protection,
  API, UI, and process-title coverage. The full suite, backend compilation,
  frontend syntax, dependency, and responsive WebUI checks pass.

---

## [1.20.16] — 2026-07-19

### Fixed — release notes are available inside the WebUI

- Added a **What's New** action beside the running version in the Voice Studio
  header. It opens a responsive in-app modal and closes by button, backdrop, or
  Escape without navigating away from active work.
- Release entries are read from the installed `CHANGELOG.md` through a public,
  read-only API, so every future release appears automatically and always
  matches the version actually installed on that Mac.

### Verification

- Added API and frontend-contract regression coverage, ran the full Python test
  suite, compiled the backend, and syntax-checked the frontend JavaScript.
  Generation, downloads, dependencies, and launcher behavior were checked and
  deliberately left unchanged because the omission was isolated to the WebUI.

## [1.20.15] — 2026-07-19

### Added — automatic local output protection

- Added enabled-by-default three-day retention and an 80 GB hard cap for
  completed generated audio. Cleanup runs hourly and evicts oldest-first when
  the cap is reached.
- Added a modern Generate-page policy card with usage, retention, capacity,
  Save policy, and Clean now controls, backed by the authenticated fleet API.
- Restricted cleanup to audio files in `app/output`. Shared voice masters,
  cloning references and transcripts, uploads, models, credentials, settings,
  and active generations are never eligible.

### Verification

- Added tests covering age expiry, hard-cap eviction, fleet API persistence,
  active-job safety, and shared-voice preservation. The full test suite,
  Python compilation, and JavaScript syntax checks pass. Launchers and model
  dependencies were left unchanged.

---

## [1.20.14] — 2026-07-19

### Improved — persistent generation maintenance and release notes

- Kept **Install Generation / Reinstall Generation** visible while the regular
  Pinokio server is running, while it is still starting, and in startup-service
  mode. The existing installer continues to stop and restart the appropriate
  server automatically, so no manual shutdown is required.
- Added an always-visible **What's New** launcher action in every menu state.
  It displays the installed checkout's complete `CHANGELOG.md` locally, so
  release details remain available even without opening GitHub.
- Added dynamic-menu regression coverage for regular, startup-service,
  starting, stopped, updating, and first-install states.

## [1.20.13] — 2026-07-19

### Added — immutable Qwen worker revision evidence

- Successful Qwen jobs now report the exact locally cached Hugging Face model
  snapshot revision.
- CustomVoice jobs report a deterministic preset revision; Base cloning jobs
  report the synchronized reference audio SHA-256 as the voice revision.
- Revision evidence is persisted in job history so Studio Hub can safely
  reconcile an already-completed generation after a network interruption.

## [1.20.12] — 2026-07-19

### Fixed — caller-enforced audio duration ceiling

- Added an optional `max_output_duration_s` generation guard without changing
  standalone VoiceStudio's default support for longer audio.
- Qwen jobs now translate that ceiling into the model's 12.5-Hz audio-token
  budget, preventing a missing stop token from producing a 96-second artifact
  for a caller that requested a 30-second maximum.
- Every generated WAV is decoded and checked against the requested ceiling
  before VoiceStudio publishes the job as successful.

## [1.20.11] — 2026-07-19

### Added — Qwen3-TTS 0.6B CustomVoice for 8 GB M1 workers

- Added the official Apache-2.0 MLX 8-bit conversion of Qwen3-TTS 0.6B
  CustomVoice as the memory-conscious preset-speaker tier.
- The model uses the existing verified nine-speaker roster, including Ryan and
  Aiden, and the existing CustomVoice generation path and style controls.
- Kept 1.7B CustomVoice as the higher-quality tier for workers with more memory;
  Qwen Base models remain the separate voice-cloning path.

## [1.20.10] — 2026-07-19

### Fixed — abandoned partials from older repository revisions

- Cache maintenance now compares completed blob bytes with Hugging Face's
  current official repository manifest before removing an incomplete blob
  that has no exact completed sibling.
- Resumable partials remain untouched when the manifest is unavailable, the
  completed snapshot is missing files, or another download is active.

## [1.20.9] — 2026-07-19

### Fixed — completed downloads blocked by stale partial duplicates

- Hugging Face transfers can leave a `<blob>.incomplete` file behind after a
  resumed attempt has already completed the exact `<blob>`. Voice Studio now
  ignores only those stale duplicates while unresolved partial files still
  keep the model in the `partial` state.
- Added a narrow cache-maintenance endpoint that removes only stale partial
  files with an exact completed sibling. It never removes unresolved partials
  or completed model blobs.
- Added regression coverage for both the safe cleanup and the unresolved
  download behavior.

## [1.20.8] — 2026-07-19

### Added — stable long-form Chatterbox and VoxCPM narration

- Generalized Qwen Base's sentence-safe long-form renderer so Chatterbox and
  VoxCPM can also accept chapter-scale requests without synthesizing one
  unstable model context.
- Chatterbox now renders independent 500-character sections (400 for Turbo),
  while VoxCPM uses conservative 400-character sections and reinjects the
  original voice reference for every pass.
- Every internal WAV is required, non-empty, and format-compatible before
  Voice Studio joins the sections. Missing or invalid audio fails the job
  explicitly instead of returning a partial chapter.
- Updated model guidance to show that these engines auto-split internally and
  no longer require callers to submit manually shortened text.

### Verification

- Added regression coverage for sentence-safe text preservation, all internal
  thresholds, catalog guidance, verified joins, and missing-section failures.

---

## [1.20.7] — 2026-07-18

### Added — proactive memory protection and recovery

- Added a live unified-memory preflight before direct local generation. Jobs are
  refused with an actionable message when the current free-memory headroom is
  too small for the selected model and its inference buffers.
- A confirmed MLX/MPS allocation failure now evicts cached engines and retries
  the job once. Two consecutive allocation failures evict both engine caches
  and restart the installed launchd service; launchd's existing `KeepAlive`
  policy brings Voice Studio back automatically.
- Foreground Pinokio runs remain alive after repeated memory failures, while
  the new `/api/generate/memory` endpoint and generation diagnostics expose the
  live memory snapshot and recovery state.
- Added explicit `psutil` generation dependency for the live memory probe.

### Verification

- Python compilation, memory guard/recovery regression tests, and the existing
  priority MLX/generation startup tests pass (41 tests).
- Checked the existing launchd service logs and retained its watchdog behavior;
  no launcher, model catalog, or cloud-provider behavior was changed.

---

## [1.20.6] — 2026-07-18

### Fixed — automatic update settings no longer snap back

- Kept unsaved automatic-update choices in a separate form draft so the
  five-second status refresh cannot replace a newly selected mode, schedule,
  maintenance time, or idle-only preference with the last saved values.
- Saving now submits that draft and synchronizes the controls only after the
  server validates and persists the schedule.
- Reworked the Settings panel with clear mode cards, grouped schedule controls,
  an unsaved-changes indicator, and update actions that appear only when useful.

### Verification

- Verified that unsaved mode and maintenance-time changes survive multiple
  status polls at desktop and compact widths.
- JavaScript syntax, Python compilation, updater tests, dependency checks, and
  the full Voice Studio test suite pass. No launcher or engine changes.

## [1.20.5] — 2026-07-18

### Fixed — reliable Kokoro generation and English API aliases

- Backported mlx-audio's focused SineGen length-alignment fix from upstream
  commit `cc30ce27f6`. Kokoro now trims or pads the generated sine tensor to
  the F0 tensor before multiplication, preventing intermittent
  `broadcast_shapes` failures that surfaced as "didn't produce a wav file."
- Kept the fleet's verified mlx-audio pin instead of advancing 52 unrelated
  upstream commits.
- Kokoro requests now accept public language values such as `en`, `English`,
  `en-US`, and `en-GB`, while still passing the engine's required `a` or `b`
  code and preserving the selected voice's accent.

### Verified

- Regression coverage checks overlong and short sine tensors, repeated patch
  installation, compatibility with a future upstream fix, English aliases,
  and the existing cross-language voice safeguards without loading a model.
- The complete 88-test VoiceStudio suite passes in the isolated worktree.
- Three guarded Kokoro BF16 samples generated valid mono 24 kHz WAV files after
  Studio Hub drained the local M4 from live scheduling. The 158-character cold
  sample produced 11.075 seconds of audio; two warm samples produced 3.375 and
  6.075 seconds. M1 and human listening qualification remain required before
  GenStudio catalog approval.

## [1.20.4] — 2026-07-16

### Added — truthful Qwen3-TTS speed control

- Qwen3-TTS now applies its requested speed to the finished WAV with FFmpeg's
  pitch-preserving tempo filter. This cleanly supports values such as `0.95×`
  and `0.90×` even though the current MLX Qwen engine accepts but ignores its
  native `speed` argument.
- The Speed control is available for Qwen Base voice cloning again and clearly
  explains that Qwen adjusts the finished audio while preserving pitch. Direct
  API, Story Studio, and Studio Hub requests use the same backend behavior.
- Speed is applied after long narration sections are joined, so every sentence
  keeps the same cloned voice and the short inter-section pauses remain smooth.

### Kept safe

- Sentence-aware splitting remains unchanged: complete sentences are preferred;
  an unusually long sentence falls back to punctuation or whitespace; only an
  unbroken token longer than the safety limit can require a character split.
- Other engines retain their existing native speed controls. VoxCPM2 and Bark
  remain unchanged because they do not advertise this numeric control.

### Verified

- Regression coverage verifies the `0.90×` output is about 11% longer while a
  440 Hz test tone remains 440 Hz, proving pitch is preserved. It also covers
  the `1.0×` lossless no-op, Qwen clone UI visibility, sentence-safe chunking,
  and joined-WAV integrity.

---

## [1.20.3] — 2026-07-16

### Fixed — Qwen3-TTS long-form voice cloning

- Qwen3 Base voice cloning now breaks long narration into sentence-aware
  sections (about 360 characters each), renders every section with the same
  reference voice and transcript, then joins them with short clean pauses into
  one WAV. This prevents the progressive speed-up and loss of intelligibility
  caused by a chapter being treated as one in-context clone sequence.
- Generation progress now identifies the active narration part, for example
  **part 4/18**, while retaining one input job and one finished audio file.
- The Qwen Base-clone speed control is now hidden: the current MLX Qwen engine
  accepts but does not apply that value, so the UI no longer implies native pace
  control that is not present.

### Kept compatible

- Story Studio and Studio Hub still submit one full chapter as one voice job.
  The new splitting, rendering, joining, and progress reporting happen wholly
  inside Voice Studio; its public generation contract is unchanged.

### Verified

- Regression coverage verifies sentence and fallback word splitting, lossless
  text preservation, joined WAV pause placement, per-section rendering, and
  progress metadata without loading a Qwen model.

---

## [1.20.2] — 2026-07-16

### Fixed

- fal.ai key testing now uses fal's authenticated model-list API instead of
  sending an unsupported `GET` request to a generation endpoint. Testing a
  valid fal API key no longer fails with **HTTP 405: Method Not Allowed**.
- Provider cards now say **Key saved** as soon as a key is stored, rather than
  the ambiguous **Setup** label. The selected provider explains exactly which
  action remains.
- Settings now shows how many curated TTS models will become available after
  paid-use consent, while keeping the actual generation catalog gated until
  that explicit consent is enabled.

### Verified

- The fal adapter contract covers the documented non-billable validation
  endpoint, and provider serialization verifies that no cloud models leak into
  Story Studio before paid-use consent.

---

## [1.20.1] — 2026-07-16

### Fixed

- All cloud-provider key fields, including the ElevenLabs account-pool fields,
  now use explicit new-key field names and password-manager-safe autocomplete
  hints. Browser credential autofill could visually populate fields without
  firing the input events Alpine uses for `x-model`, leaving **Save key** or
  **Add account** disabled and creating no saved provider configuration.

### Verified

- The account API and existing account-pool behavior remain unchanged; the
  focused provider tests and frontend markup regression check pass.
- Existing saved voices, provider mappings, local generation, and the current
  account-pool storage format were deliberately left untouched.

---

## [1.20.0] — 2026-07-16

### Added — centralized ElevenLabs account pool

- ElevenLabs Settings now accepts multiple named accounts on the main Voice
  Studio Mac. Each account shows a masked key, plan, usage, remaining credits,
  reset/check state, and clear Ready, paused, exhausted, invalid, cooldown, or
  unavailable status. Accounts can be added, tested, paused, resumed, removed,
  or refreshed together without exposing credentials in API responses or Git.
- Account selection prefers the enabled mapping with the most known remaining
  credits and automatically skips exhausted, invalid, cooling-down, and failed
  accounts. Definite quota, permission, voice, rate-limit, or server failures
  fail over to another mapped account; successful usage updates the local
  balance estimate immediately.
- Voice library entries can now store a different ElevenLabs voice ID for every
  account. The voice editor fetches each account's native voice catalog and the
  generation request carries the stable library voice ID, allowing account and
  voice selection to stay atomic.

### Automatic recovery and safety

- Connection setup failures retry with bounded backoff. If an ElevenLabs paid
  request loses its response, Voice Studio searches ElevenLabs History for one
  exact recent text/model/voice result and downloads that audio instead of
  submitting again. Ambiguous results stop safely and are never double-billed.
- Studio Hub supplies a stable request ID per voice item. A lost Hub-to-Voice
  submit response returns the original job, while a Voice Studio restart during
  a bound paid call performs History-only recovery and never blind resubmission.
- Existing single-key installations migrate transparently to a Primary account
  on the first pool edit. Environment keys remain read-only, and keys from the
  same ElevenLabs workspace are clearly noted as sharing one workspace quota.
- Added isolated tests for legacy migration, secret masking, quota ordering,
  per-account mappings, exhausted-account failover, exact history recovery,
  ambiguous-drop protection, and unknown-account validation. No new generation
  dependency or model installation is required.

## [1.19.0] — 2026-07-16

### Added — authenticated shared voice synchronization

- Added a stable-ID fleet import endpoint for Studio Hub. A shared reference
  now arrives with the same ID, audio SHA-256, metadata, and reviewed transcript
  on every Voice Studio, so Hub-dispatched cloning jobs resolve consistently.
- Repeating a synchronization is idempotent. Hub may refresh metadata and the
  transcript without recopying audio, while machine-local provider mappings and
  generated embedding caches remain local to each Voice Studio.
- Added a matching managed-delete endpoint that can remove only the exact
  Hub-owned audio hash. Existing local voices can never be overwritten or
  deleted by fleet synchronization.

### Safety and recovery

- Fleet writes remain protected by the existing Studio token middleware and
  reject malformed IDs, unsupported audio, oversized files, hash mismatches,
  symbolic-link targets, and stable-ID collisions.
- New focused tests cover first install, repeat sync, transcript correction,
  local voice collision protection, changed-audio refusal, safe deletion, and
  input validation. No new dependency or generation-engine install is needed.

---

## [1.18.1] — 2026-07-15

### Fixed

- Generation diagnostics and the Install/Update verification commands now import
  and report `torchaudio`, which is required by the F5-TTS and VoCoS stack.
  The existing installed environment passed this check; the gap could otherwise
  have reported F5-TTS as ready while omitting a broken audio dependency.

### Verified

- Existing model catalog, worker dispatch, MLX controls, automatic-update
  behavior, and UI formatting were checked and deliberately left unchanged.
- Full test suite, Python compilation, JavaScript parsing, dependency checks,
  and the live health/diagnostics endpoints passed.

---

## [1.18.0] — 2026-07-15

### Added — safe optional automatic updates

- Added an **Automatic updates** Settings panel with Off, Notify only, and
  automatic-install modes. It is disabled by default, supports daily or weekly
  checks, uses a staggered 02:00 maintenance hour, and verifies its launchd
  schedule separately from saving preferences.
- Added live installed/latest versions, last and next check times, updater state,
  defer reasons, results, retry and check actions, release notes, and collapsible
  technical details. **Update after current work** retries automatically once
  generation, transcription, model loading, and downloads are idle.
- Added a short-lived per-app LaunchAgent and detached update helper. It works
  without an open browser or a continuously running Python polling process.

### Safety and recovery

- Updates now verify the fixed GitHub origin, `main`, clean worktree,
  fast-forward history, free disk space, dependencies, imports, health endpoint,
  and exact running version. Dirty, detached, divergent, rewritten, or unexpected
  repositories are refused without changing files.
- The helper detects startup-service versus Pinokio Start mode and restarts only
  the active owner. A per-app lock prevents concurrent manual and scheduled runs.
- Failed installs or health checks make one bounded rollback attempt to the clean
  pre-update commit, reinstall matching requirements, restart the previous mode,
  and report whether recovery succeeded. Secrets are redacted from bounded logs.
- Reset now unloads and removes the updater before deleting the environment.

### Verified

- Added 19 focused updater tests covering default-off, notify and automatic
  modes, scheduler transitions, settings validation, active-work deferral,
  remote/branch/worktree/history checks, disk failure, dependency and health
  failures, rollback outcomes, service and Pinokio restarts, locking, scheduling,
  and secret redaction.
- A real launchd enable, validation, disable, and removal cycle passed; the
  released default remains Off.

## [1.17.2] — 2026-07-15

### Fixed — final MLX runtime audit

- Voxtral generation now pins `mistral-common[audio]` 1.11.5. Its speech-request
  encoder is required by the current MLX tokenizer; the previous 1.9.1 install
  imported successfully but failed only when speech generation began.
- Removed the published OmniVoice 4-bit and 8-bit conversions from the catalog.
  Their custom row-wise scale tensors do not match the parameter layout accepted
  by the current or latest upstream `mlx-audio` loader. The compatible bf16 MLX
  checkpoint remains as the recommended OmniVoice option.
- MLX memory cleanup now prefers the current `mlx.clear_cache()` API, avoiding a
  deprecation warning while preserving compatibility with older installations.
- Voice-reference upload sizes and the 25 MB limit now use the same decimal units
  as the rest of the app.

### Improved — diagnostics and interface

- Dependency diagnostics now cover all 13 wired engine families, including
  Voxtral and Marvis, show package versions even when modules omit `__version__`,
  and distinguish an installed-but-incompatible package from a missing one.
- Long engine tracebacks in Recent generations are now collapsed behind a short,
  readable explanation. Technical details remain available on demand without
  stretching the page by thousands of lines.
- Diagnostic tables scroll inside their panel on compact screens and use the
  shared success, warning, and error colors consistently.
- Update and Reinstall Generation now verify the full MLX stack and the exact
  Voxtral tokenizer version before displaying a success notification.

### Verified

- Real local MLX generations passed for Kokoro, VoxCPM2, Qwen3-TTS cloning and
  VoiceDesign, Chatterbox, Orpheus, Marvis, and Voxtral. Voxtral was re-run
  successfully with the new dependency before it was pinned.
- The dependency resolver changes only `mistral-common` 1.9.1 to 1.11.5; the
  pinned MLX, MLX-LM, MLX-Audio, Transformers, and Torch stack remains unchanged.
- Catalog, worker dispatch, and diagnostics all agree on the same 13 families.
  Automated tests, Python compilation, JavaScript parsing, and dependency checks
  pass. Run **Update** once; it applies the dependency and restarts the active
  Voice Studio mode automatically.

## [1.17.1] — 2026-07-15

### Fixed

- F5-TTS now visibly shows the transcript saved with the selected library voice,
  matching the Qwen3-TTS cloning flow. The saved transcript is automatically sent
  with the reference clip when the one-time override is blank.
- Added a worker-level regression test that verifies the saved library transcript
  reaches F5-TTS inference, while preserving the existing override behavior.

---

## [1.17.0] — 2026-07-15

### Refined — current Suno Bark, native MLX

- Consolidated Bark onto the current `mlx-community/bark` conversion and removed
  the older full and small PyTorch catalog rows. The model now shares Voice
  Studio's single-memory-slot MLX worker with the other Apple Silicon engines.
- Added all 130 v2 voice presets across Bark's 13 supported languages. Presets
  are grouped by language in the existing compact picker.
- Exposed the controls implemented by the MLX engine: sampling temperature,
  voice-history context, generation-window size, natural early stopping, and
  repeatable MLX seeds. The speed control is hidden because upstream currently
  accepts but does not apply it.

### Fixed

- Bark voice presets now resolve to their downloaded local `.npz` files instead
  of relying on an upstream relative-path lookup that fails outside the model
  directory. Random voice mode explicitly avoids inheriting mlx-audio's Kokoro
  default voice.
- The voice dropdown now stays synchronized with the selected preset when its
  130 asynchronously loaded options arrive, instead of visually falling back to
  Random while generation still used the saved preset.
- Bark downloads now include its Encodec and multilingual tokenizer companions
  before the model is marked ready, preventing surprise first-generation
  downloads. Duplicate preset files and unused BERT model weights are skipped.
- Temperature is now passed to Bark's semantic, coarse, and fine samplers; the
  previous PyTorch worker silently ignored the UI's generic temperature value.

No new Python package is required; the pinned `mlx-audio` build already contains
the Bark engine. Run **Update**, then download **Suno Bark (MLX)** from Models.
Existing PyTorch Bark caches are left on disk but no longer appear in the catalog.

---

## [1.16.0] — 2026-07-15

### Refined — current VoxCPM2, MLX first

- Consolidated VoxCPM onto the current 2B VoxCPM2 architecture. The catalog now
  offers two purposeful MLX tiers: 4-bit for normal generation and bf16 for
  final-quality output. Removed VoxCPM v1, duplicate PyTorch v2, and the
  indistinct 8-bit middle tier.
- Added an active-mode indicator for zero-shot speech, voice design, reference
  cloning, transcript-aware ultimate cloning, and style-controlled cloning.
- Exposed VoxCPM2's real quality controls: guidance, diffusion steps, onset
  warmup patches, maximum audio tokens, and reproducible MLX sampling seeds.
  The numeric speed control is now hidden because VoxCPM2 controls pace through
  its natural-language voice instruction instead.

### Fixed

- Saved or overridden reference transcripts now activate VoxCPM2's actual
  high-fidelity continuation path by pairing prompt text and prompt audio with
  the reference clip. Clips without transcripts continue to use valid basic
  reference cloning.
- Backported the upstream MLX sample-rate-boundary materialization fix so a
  cached VoxCPM2 model can be reused safely by later worker threads without
  advancing the shared `mlx-audio` pin across unrelated engine changes.
- Removed the unused PyTorch `voxcpm` dependency and its ModelScope / WeText
  chain, reducing the resolved generation environment from 236 to 210 packages.

Run **Update**, then **Reinstall Generation** once to converge on the lighter
dependency set. Existing cached model files are not deleted automatically.

## [1.15.0] — 2026-07-15

### Refined — one complete, MLX-first Kokoro workflow

- Consolidated Kokoro onto the latest v1.0 82M MLX bf16 model and removed the
  duplicate PyTorch and 4-bit catalog rows. Fresh downloads also skip duplicate
  PyTorch voicepack files.
- Added all 54 bundled voices across American and British English, Spanish,
  French, Hindi, Italian, Brazilian Portuguese, Japanese, and Mandarin.
- Replaced the long voice list with a compact language-first picker and added
  optional equal voice blending. Voice, language, blend, and speed persist per
  model and are restored from generation history.

### Fixed

- Added and verified the multilingual text-processing dependencies, including
  self-contained Japanese dictionaries and Mandarin phonemization. Installation
  now checks both pipelines before reporting success.
- MLX long-form generation now joins every newline-delimited segment into the
  returned WAV instead of keeping only the first segment.
- Fixed narrow-screen overflow in generation controls and long history tags.

Run **Update**, then **Reinstall Generation** once to install the new language
dependencies. Existing downloaded models are not deleted automatically.

## [1.14.1] — 2026-07-15

### Fixed — saved cloning transcripts are visible and correctly paired

- The Voices listing now includes the saved transcript text, not only a
  has-transcript flag.
- Voice creation, editing, provider-tag updates, and seed imports now return the
  same complete transcript-bearing record, so the Generate tab updates
  immediately without a reload.
- Qwen3 Base cloning shows the selected voice's saved transcript and sends it
  explicitly with the reference clip. A separate optional override remains
  available for one generation without changing the library entry.
- Switching reference voices clears any one-time transcript override, preventing
  a transcript from the previous voice being paired with the newly selected
  audio. This protection applies to every local cloning engine.
- Transcript overrides are no longer persisted per model because they belong to
  a specific reference clip.

No dependency or launcher change is required. **Just run Update.**

## [1.14.0] — 2026-07-15

### Added — priority MLX voice-cloning workflow

- Added the requested `Qwen3-TTS-12Hz-1.7B-Base-8bit` model for higher-quality
  voice cloning alongside the faster 0.6B Base tier.
- Wired voice cloning into every curated OmniVoice MLX tier through the pinned
  `mlx-audio` engine. A reference clip, voice traits, or both can now be used in
  one workflow, with optional transcript override, quality steps, guidance, and
  target duration.
- Added Chatterbox's real sampling controls: temperature, repetition penalty,
  top-p, and the standard model's voice guidance and minimum probability.
  Turbo only shows and sends the controls its engine actually supports.

### Refined

- Reduced Qwen3-TTS to four distinct jobs: fast cloning, quality cloning,
  quality preset speakers, and VoiceDesign. The redundant 0.6B CustomVoice row
  was removed.
- Reduced Chatterbox to standard 4-bit, standard 8-bit, and Turbo 4-bit. Removed
  the redundant fp16 and Turbo 8-bit downloads.
- Reduced OmniVoice to MLX 4-bit, 8-bit, and bf16. Removed the duplicate fp32
  and separate PyTorch/MPS rows, plus the obsolete second OmniVoice package.
- Updated model descriptions so Base, CustomVoice, and VoiceDesign capabilities
  are no longer conflated.
- The workspace summary now reports the active preset, reference, or designed
  voice instead of leaking Kokoro's default voice into other model families.
- New engine controls, temperature, and language now persist per model and are
  restored with job parameter reuse.

### Verification

- Added focused catalog and parameter-routing tests for Qwen3 1.7B cloning,
  Chatterbox standard/Turbo controls, and OmniVoice clone-plus-traits behavior.
- No new dependency is required; the pinned `mlx-audio` build already contains
  the OmniVoice MLX cloning implementation. **Just run Update.**

## [1.13.1] — 2026-07-14

### Fixed — reliable root-level verification

- Added the repository test configuration so `conda_env/bin/python -m pytest` works from the Voice Studio root instead of failing collection because the backend package is under `app`.

Fifteen tests pass from the repository root. No runtime, dependency, launcher, provider, or billing behavior changed; **Just run Update**.

## [1.13.0] — 2026-07-14

### Added — Five-provider cloud audio gateway

- Added GenAIPro, Fish Audio, fal.ai, and Kie.ai alongside ElevenLabs. All five use the existing focused provider cards, paid-use consent, key tests, voice mappings, cloud model picker, and shared generation history.
- GenAIPro loads its live Labs voice catalog and recalls asynchronous task IDs. Fish Audio exposes owned and public reference voices and returns speech directly. fal.ai and Kie.ai use their documented queue/task APIs with curated speech models and voices.
- Active asynchronous jobs now persist provider task metadata and automatically resume polling after an Update or restart. Existing paid tasks are never re-submitted, including fal queue jobs whose status and result URLs are opaque.

### Fixed

- Cloud generation no longer depends on the optional local TTS engine being installed.
- Generated MP3 and other supported cloud audio files now count toward output storage and cleanup, rather than only WAV files.
- Provider result downloads validate HTTPS hosts and every redirect target to prevent internal-network requests from untrusted task responses.
- fal credential testing now uses a read-only model request; invalid keys reliably report an error and the Test button cannot create a paid generation.

### Verification

- Fifteen backend tests pass, including provider request/response contracts, restart recovery without re-submission, task metadata persistence, SSRF rejection, and cloud MP3 storage cleanup.
- Invalid-key smoke checks against GenAIPro, Fish Audio, fal.ai, and Kie.ai return authentication errors without submitting paid work.
- No dependency or launcher changes. The production process on port 47870 was not restarted; run **Update** once when ready.

No new dependency is required; **Just run Update**.

## [1.12.0] — 2026-07-14

### Added — Cloud audio-provider gateway · Phase 1

- **Focused provider settings** — Settings now has compact searchable provider cards with one focused detail view. API keys, paid-use consent, provider enablement, connection tests, model refreshes, documentation links, loading states, and clear save/error feedback all live in one flow.
- **Multi-provider voice mappings** — a library voice can now store one provider-native voice ID per cloud provider. The editor can paste an ID or select from the provider's live voice catalog, and voice cards show their cloud mappings without duplicating local audio.
- **Cloud generation UI** — Generate groups ready models into Local and Cloud sections. Choosing a cloud model filters the voice picker to library voices tagged for that provider and submits the provider-native voice ID through the existing job, history, playback, reveal, and download flow.
- **Rolling-update compatibility** — the frontend detects older running backends, keeps the provider settings that they already support, and withholds voice mapping and cloud generation until one Update activates the new contract.

### Fixed

- Corrected the edit-voice license choices to use the values accepted by the backend, so permission and public-domain metadata save reliably.
- Added validation and regression coverage for provider voice mappings, including old voice metadata, duplicate mappings, unknown providers, and live voice-catalog normalization.

### Verification

- Nine backend tests pass; Python compilation, JavaScript syntax, whitespace checks, and temporary-port API smoke tests pass.
- Settings and voice mapping were browser-checked at desktop and mobile widths with no console warnings or horizontal overflow.
- The production Voice Studio process on port 47870 was not restarted. Run **Update** once to activate the v1.12 backend.

No new dependency is required; **Just run Update**.

---

## [1.11.0] — 2026-07-10

### Added — Cloud audio-provider gateway (Phase 0 + ElevenLabs) · backend

Voice Studio can now act as an **audio gateway**: alongside the local engines it exposes cloud TTS providers behind the SAME `/api/generate` contract Story Studio already calls, so Story Studio links **one** connection and sees local + cloud models in one live list. This ships the backend; the Settings/voice-tag UI is the next slice.

- **`providers.py`** — a `TTSAdapter` interface + `Provider` registry. Cloud models are addressed by a synthetic id `provider:<key>:<model_id>`; the generation router sends those to the adapter and reuses the existing async job engine, history, SSE progress, and per-job actions unchanged. (Audio APIs aren't standardized like Chat's OpenAI-compatible LLMs, so each provider gets a thin adapter rather than a shared client.)
- **ElevenLabs adapter** (first provider) — live model + voice listing, synthesize → MP3, and a key `test()`. Verified against the real API.
- **Self-healing / never double-charge** — jobs carry a persisted `provider_task_id`; async providers submit once and re-poll that id on retry instead of re-submitting (matters for fal's queue in Phase 2). ElevenLabs is synchronous/atomic. Plus a per-request character cap so a runaway caller can't rack up a bill.
- **No accidental billing** — a cloud model only appears once the provider has a saved API key AND an explicit per-provider **paid** consent toggle is on. Live model listing is TTL-cached (auto new/deprecated) with a curated fallback.
- **Endpoints** — `GET /api/providers`, `POST /api/providers/{key}/key|paid|enabled|test`, `GET /api/providers/{key}/models/live`. Cloud models merge into `/api/catalog`; MP3 outputs serve with the right media type.

### Notes
- MINOR bump (1.10.4 → 1.11.0). Backend only — activates after one **Update** (restart). Adds `httpx` (already installed) to requirements. Next slice: Settings provider panel (key/paid/test), voice-library provider tags, and cloud models in the Generate UI. Then fal / Fish Audio / kie adapters (Phase 2).

---
## [1.10.4] — 2026-07-13

### Added — one-click Whisper transcripts for new voices

- The Add Voice dialog can now transcribe the selected or recorded reference clip with the existing cached Whisper model.
- The returned transcript is placed into the editable transcript field for review before the voice is saved, including the transcript needed by F5-TTS.
- If no Whisper model is downloaded, the dialog explains where to download one; no extra dependency is required.

### Verification

- JavaScript syntax and whitespace checks pass.
- The live server was not restarted during this change.

No launcher or dependency changes; **Just run Update**.

## [1.10.3] — 2026-07-13

### Added — official OmniVoice voice cloning on Apple Silicon

- Added the official `k2-fsa/OmniVoice` checkpoint to the Models catalog. It runs through the installed PyTorch/MPS API and supports cloning from a 3–10 second reference clip in the Voices library.
- Kept the existing `mlx-community/OmniVoice-*` variants as the lightweight voice-design path. The Generate UI now makes the backend choice explicit instead of implying that every OmniVoice entry can clone.
- Reference transcripts are used when saved; otherwise OmniVoice may auto-transcribe the reference clip. A generated voice-design sample can be saved to the library and reused as a cloning reference.

### Verification

- Python compilation, JavaScript syntax checks, startup regression test, catalog smoke test, and `audit_truth.py` all pass.
- The live server was not restarted during this change. Download the new official checkpoint from Models, then use the existing Update/restart workflow before first generation.

No new package is required beyond the already-installed OmniVoice package; **Just run Update**.

## [1.10.2] — 2026-07-13

### Fixed — Voice Studio restarts no longer preload every model library

- Server startup now checks whether PyTorch, Transformers, and Kokoro are installed without importing their full model stacks. Real imports still happen when generation starts, and the diagnostics endpoint still performs deep package checks on demand.
- This removes the restart-time import chain through PyTorch, spaCy, pandas, SciPy, and scikit-learn. On the reference Mac, the full backend import fell from 16.7 seconds to about 3 seconds.
- Normal engine availability checks are lightweight too, and the UI no longer waits for the deliberate deep diagnostics scan before becoming usable.
- Added a regression test that fails if the generation module imports a heavy model library during server startup.

No launcher or dependency changes; **Just run Update**.

## [1.10.1] — 2026-07-13

### Fixed — saved fleet credentials apply without restarting Voice Studio

- Protected requests now verify against the current owner-only fleet-token file instead of a startup snapshot. Studio Hub credential saves and rotations take effect immediately, and authenticated browser cookies follow the current value.

Verified with a live-rotation middleware regression test plus the full test suite. No launcher, voice engine, or dependency changes; **Just run Update**.

## [1.10.0] — 2026-07-12

### Added — secure fleet access and capability contract

- Remote API and output access now requires the automatically shared StudioHub fleet token; loopback Pinokio use remains passwordless.
- Browser writes are same-origin protected, authenticated browser sessions use an HttpOnly cookie, and remote Studio pages prompt once per tab when a token is needed.
- Added the normalized `GET /api/capabilities` contract for Hub preflight and rolling-update orchestration, including TTS, voice cloning, and speech-to-text support.

### Verification

- Python and JavaScript syntax checks pass. Security-contract tests cover public health/capability routes, protected catalog access, accepted fleet credentials, cross-origin write rejection, and private token permissions.

## [1.9.1] — 2026-07-12

### Fixed — Voice generation failures and misleading controls

- OmniVoice now unwraps its one-item batch before writing WAV audio. The old code
  passed the outer list to SoundFile, which interpreted thousands of samples as
  channels and left an empty, unreadable output file.
- Voxtral now tolerates its `voice_num_audio_tokens` tekken metadata with current
  `mistral-common`; mlx-audio already reads that mapping, so the compatibility shim
  ignores only the unsupported constructor keyword while loading the tokenizer.
- Chatterbox's Generate button now requires a reference-library voice, and all
  disabled Generate states explain the actual missing field instead of always saying
  “Type some text.” OmniVoice guidance now lists its real fixed trait vocabulary and
  provides valid presets instead of suggesting unsupported free-form prose.
- Failed generations remove partial or empty WAV files.

### Security

- Hugging Face token storage is forced to owner-only (`0600`) permissions.
- Remote version metadata is rendered with `textContent`, closing the update-banner
  HTML injection path.
- FastAPI/Starlette were raised to patched releases identified by `pip-audit`.

### Verification

- Python/JavaScript/HTML checks pass; the Voxtral tokenizer loads under the scoped
  compatibility shim, OmniVoice output-shape handling is covered with synthetic data,
  and the generation truth audit remains clean. LAN binding/CORS remain unchanged as
  part of the documented service-mode contract.

## [1.9.0] — 2026-07-10

### Added — Audio-generator overhaul: live feedback, per-job actions, disk management

A batch of generator improvements (frontend live immediately; the backend bits below activate after one **Update** — no new Python deps, so no "Install Generation" needed):

- **Live generation feedback.** The progress readout showed "Generating… undefined/undefined" — it read fields that don't exist on the job. Now a real bar + percentage + elapsed time. The queue panel is sticky (stays visible while you scroll) and shows a live progress bar on the running job; the "Generating…" strip echoes the same. *(Backend: workers now report `progress` — per-chunk for Kokoro, phase-based otherwise.)*
- **Per-generation actions.** Each result now has **Reveal** (show the file in Finder), **Delete** (remove it and its WAV — two-click confirm), plus the existing Download and Reuse. *(Backend: new `DELETE /api/generate/history/<built-in function id>`.)*
- **Disk management.** A footer shows how many files and how much disk the outputs use, with one-click prune ("keep newest 50" / "delete > 30 days"). Fixes outputs piling up unbounded. *(Backend: `GET /api/output/stats`, `POST /api/output/prune`.)*
- **Auto-play** toggle — plays the newest result when a generation finishes.
- **Friendlier empty state** when there are no generations yet.

### Fixed — Three more native `confirm()` dialogs replaced with a webview-safe modal

Remove-token, Import-move, and Remove-voice used `window.confirm()`, which Pinokio's embedded webview silently blocks — so those buttons did nothing. All now use an in-app confirm modal (same class of bug as the Clear-history fix in 1.8.8).

### Notes
- MINOR bump (1.8.8 → 1.9.0). Frontend (app.js/index.html/style.css) is live on reload; the new endpoints + per-chunk progress need one **Update** (restart) — the UI degrades gracefully until then (disk/delete just show a "run Update" hint). Deferred: MP3/FLAC export (needs an audio-encoder dependency).

---
## [1.8.8] — 2026-07-10

### Fixed — "Clear history" now works; added an "Open outputs folder" button

- **Clear history** used the native `window.confirm()` dialog, which Pinokio's
  embedded webview can silently block (it returns false) — so the button did
  nothing. Replaced with a webview-safe two-click confirm: the first click arms
  the button ("Click again to clear"), a second click within 3s clears. It now
  also keeps any in-progress job on screen and only trims finished entries.
- **Open outputs folder** — new button in the Recent generations header that
  reveals the folder holding every generated WAV in Finder (via the existing
  `/api/reveal`). Handy because the history index and the files on disk can
  diverge (clearing history keeps the WAVs).

### Notes
- PATCH bump (1.8.7 → 1.8.8) — frontend only (app.js + index.html + style.css). Live on reload; no restart needed.

---
## [1.8.7] — 2026-07-10

### Fixed — download ETA settle-guard, real catalog sizes, memory floors, and dead-entry cleanup

**Absurd download ETA (`downloads.py`).** The speed EMA's first sample was taken while `snapshot_download()` was still resolving repo metadata, before real bytes landed — a near-zero "instant" speed (e.g. 1.57 KB over ~3 sec) that, divided into a multi-GB remaining total, produced an ETA like "99679m 03s" seconds after clicking Download. `eta_seconds` is now suppressed until the job has ≥3 s of runtime so the EMA settles to a representative rate first.

**Unreadable long durations (`app.js`).** `formatDuration()` only had `Xm YYs`, so a legitimately long ETA rendered as e.g. "734m 12s". Added hour/day rollup (`Xh YYm`, `Xd YYh`); short job-render durations are unchanged.

**Catalog sizes corrected to real Hugging Face download sizes.** 13 entries were under-counted because they bundle files the old estimate ignored — OmniVoice (4-bit 0.5→1.1 GB, 8-bit 0.9→1.5, bf16 1.3→2.0) and Spark-TTS ship an audio-tokenizer / wav2vec2 encoder; VibeVoice-fp16 1.0→2.1; Kokoro-82M-4bit 0.18→0.67; and others. Verified against the HF API `blobs=true` file listing, with each entry's `ignore_patterns` applied to match what `downloads.py` actually fetches.

**Memory floors recalibrated.** Seven small TTS models were over-classified — e.g. OmniVoice fp32 (a 3.3 GB, 0.6B model) required a 16 GB floor, so on a 16 GB Mac it read "⚠ tight". Floors now reflect the real footprint (fp32 → 8 GB, so a 16 GB Mac reads "✓ fits"). Same for Qwen3-TTS-1.7B, chatterbox-fp16, Spark-8bit/bf16, VibeVoice-fp16, and OmniVoice-bf16.

**Removed 3 entries.** `mlx-community/chatterbox-mlx-4bit` and `-8bit` return HTTP 401 (undownloadable) and were already superseded by the newer `chatterbox-4bit/8bit/fp16` in the same family; `Spark-TTS-0.5B-6bit` was a redundant middle tier between the 4-6bit (recommended) and 8bit variants.

**Checked, left unchanged:** the PyTorch VoxCPM / Kokoro / F5-TTS entries (a different runtime from their MLX ports — not duplicates). `py_compile` clean; catalog re-imports to 40 models.

## [1.8.6] — 2026-07-10

### Fixed — API examples now generate speech instead of copied FLUX images

The API tab and token help still contained Image Studio content: a FLUX repository,
`txt2img` requests, image dimensions, and PNG download routes. Every generated example
would fail against Voice Studio's actual API. Curl, JavaScript, Python, re-download, job
search, endpoint summaries, and token guidance now use `txt2speech`, voice fields, and WAV
audio routes. Import examples now name a voice model instead of FLUX, and the workspace
also hides a stale voice preset when no model is selected.

### Verification

- Cross-checked every documented route and request field against `backend/main.py`, ran
  JavaScript and HTML validation, and exercised the API tab against the live frontend.
- Byte formatting remains intentionally decimal for downloads; binary units remain only
  for the voice-upload size limit, where the code and limit use MiB-sized byte constants.

---

## [1.8.5] — 2026-07-10

### Changed — Generate opens with a focused voice workspace overview

The Generate tab previously dropped straight from a plain heading into warnings and
dependency details. It now opens with a compact workspace overview showing the active
model, voice, and compute target before the existing controls. The header icon and active
tab also use the refined Studio treatment established in Image Studio.

### Verification

- Validated Alpine expressions, JavaScript syntax, HTML parsing, and desktop/mobile
  layout against the live no-cache frontend without restarting the managed service.
- Generation controls, diagnostics, engine behavior, saved voices, and API routes were
  checked and deliberately left unchanged.

---

## [1.8.4] — 2026-07-10

### Changed — Version now shown as a badge in the top-right header (consistent across all sibling apps)

The app version was displayed inconsistently across the Studio fleet (bottom footer on
some, top-right on Chat, missing on Video). It's now a small `v1.8.4`-style badge in the
top-right of the header on every app, matching Chat Studio — visible at a glance without
scrolling to a footer.

### Notes

- PATCH bump (1.8.3 → 1.8.4) — frontend only (`index.html` + `style.css`). Served with
  no-cache headers, so it appears on the next browser reload without a restart.

---
## [1.8.3] — 2026-07-10

### Fixed — Update reinstalls the service (rewrites the launchd plist) instead of kickstarting a stale one

The service scripts were renamed from generic `serve.sh` / `watchdog.sh` to
`<app>-serve.sh` / `<app>-watchdog.sh`, and the launchd plist's `ProgramArguments`
now points at the renamed script. A machine with the service already installed has
a plist pointing at the OLD `serve.sh` — so a plain **kickstart** (`restart_service.sh`)
would relaunch a plist pointing at a now-deleted path and the service would fail to
come back up after an update.

`update.js` (and `install_generation.js`) now restart the service with
**`install_service.sh`** instead of `restart_service.sh`. `install_service.sh`
regenerates the plist to match the current on-disk scripts *before* relaunching
(bootout → bootstrap → kickstart), so the rename is folded in automatically. It's
idempotent and safe to run on every update.

### Notes

- PATCH bump (1.8.2 → 1.8.3) — launcher scripts only. Applies only where the app
  runs as a launchd service (`service/.installed`); the `start.js` path is unchanged.

---
## [1.8.2] — 2026-07-10

### Added — In-app auto-check banner: tells you when to update instead of failing silently

On load the web UI checks `GET /api/update-status` and shows a dismissible banner when this install needs attention:

- **A newer version is published** — compares this install's VERSION against the repo's published VERSION (fetched from GitHub raw, cached ~6h, in a background thread so it never blocks). Banner: "⬆ Update available (vX → vY)", pointing at the one-click **Update** button in the Pinokio sidebar.
- **The generation engine isn't installed** — detects the missing stack directly. Banner: "⚠ Generation engine not installed — the Generate tab won't work", pointing at **Install Generation** (or **Update**) in the sidebar. This is the exact silent failure that let a broken generation install look fine before.

Detect-in-app, apply-via-sidebar: a sandboxed web page (external browser, Tailscale) can't reliably drive Pinokio's script runner, so the banner points at the sidebar's one-click Update rather than trying to self-update. The banner is self-contained (no framework coupling) and degrades silently if the endpoint isn't live yet (e.g. a running service that hasn't restarted onto the new build).

### Notes

- PATCH bump (1.8.1 → 1.8.2) — backend adds `GET /api/update-status`; frontend adds the banner to `index.html`. No change to existing features.

---
## [1.8.1] — 2026-07-10

### Fixed — One-click Update that actually works, and generation installs that don't silently fail

Overhauled the update/install flow. It was tedious and, worse, quietly broken:

- **One Update button, correct in every run mode.** The old "Update & Restart" was hardwired to stop/start `start.js`, but in production this app runs as an always-on launchd **service** — so it stopped nothing and then launched a *second* server that fought the service for the fixed port. The unified `update.js` now detects the mode and restarts the **real** server (kickstart the service **or** start `start.js` — never both), so updating no longer requires manually stopping production first.
- **Generation deps refresh on the same click.** `update.js` used to install only the base deps; heavy ML deps came from a separate "Reinstall Generation" button, so a release that bumped a model dependency silently didn't apply on Update. Update now refreshes generation deps too (when generation is installed) — no second button to hunt for.
- **Install from source, not a drifted lock.** `install_generation.js` (and Update) now install from `requirements-generation.txt`, the authoritative range file. The generation `.lock.txt` had drifted — on some machines it contained only base packages, so "Install Generation" installed nothing while the UI still reported success. Source-first can't have that failure mode.
- **Verify-then-notify.** After installing, the key modules are imported; a failure breaks the run and withholds the "installed" notification. The old script fired "Generation engine installed" unconditionally — even on total failure.
- **"Update & Restart" folded into "Update"** (kept as a back-compat alias that forwards to `update.js`).

### Notes

- PATCH bump (1.8.0 → 1.8.1) — launcher scripts only (`update.js`, `install_generation.js`, `update_and_restart.js`, `pinokio.js`). No app-code change.
- Verified: all launcher scripts load; the menu renders a single mode-aware "Update"; generation deps import in the env.

---
## [1.8.0] — 2026-07-09

### Added — dependency lockfiles: fresh installs are now reproducible forever

`requirements.txt` / `requirements-generation.txt` use version **floors** (`>=`), so a fresh install months from now would resolve to whatever PyPI serves that day — one breaking release in any dependency (torch, mlx, kokoro, …) bricks the app on a new machine while existing installs keep working. Same fix Chat Studio shipped in its v1.19.0.

- **`app/requirements.lock.txt`** — the pinned phase-1 set (36 packages, compiled from the floors constrained to the verified env's installed versions).
- **`app/requirements-generation.lock.txt`** — the FULL verified env (240 packages), including the two git-sourced engines (`mlx-audio`, `omnivoice`) **pinned to exact commits** — previously these installed whatever the upstream repo's HEAD was that day, the single most drift-prone part of this app.
- `install.js`, `install_generation.js`, and `update.js` now install from the locks. Upgrade flow (edit floors → verify → regenerate both locks → commit) is documented in each lock's header.

Verified: phase-1 lock resolves all-satisfied against the live env; both launcher scripts pass `node --check`; python was already pinned (`python=3.12`).

### Notes

- MINOR bump (1.7.5 → 1.8.0) — install-pipeline change, no package versions changed (locks pin exactly what's installed and verified).

---

## [1.7.5] — 2026-07-08

### Fixed — Start now refuses to compete with startup service mode

The startup service already takes over port `47870` when installed, and the service-mode sidebar hides the normal Start button. But `start.js` itself still had no direct guard, so any stale menu, direct script launch, or automation path could still try to start a second Uvicorn server on the same fixed port and fail with "address already in use."

`start.js` now checks for `service/.installed` before launching the server. If service mode is active, it exits immediately with a clear message telling the user to use **Open UI (service)** or uninstall the startup service first. The existing Uvicorn URL capture and `local.set` behavior are unchanged.

**Verified:** `node --check start.js`, direct inspection against the required Pinokio URL-capture pattern (`input.event[1]`), and current logs showing service install already takes over the same port by stopping the previous Pinokio Start process.

### Notes

- PATCH bump (1.7.4 → 1.7.5) — launcher guard only, no app/backend change. **Just run Update**.

## [1.7.4] — 2026-07-01

### Fixed — UX/UI consistency pass: unified the download flow, chip colors, and one more GB-formatting gap

Requested as a follow-up audit alongside v1.7.2/v1.7.3: "run a ux/ui consistency test and fix and make it better." Audited chip color semantics, byte/size formatting, download interaction patterns, and terminology across the whole frontend. Applied the changes that had real, user-visible impact; explicitly skipped low-value ones (see below).

**Chip color system consolidated (`style.css`):** Three independent, hardcoded color palettes were all expressing the same "good / caution / bad" semantics with subtly different hex values — `.chip.ok/.warn/.bad` (the canonical one, backed by the `--ok`/`--warn`/`--bad` CSS variables) vs. `.chip.engine-ready/-pending/-missing` (its own greens/ambers/oranges) vs. `.chip.fit-ok/-tight/-risky` (a third palette), plus `.dep-chip` and `.diag-pending`/`.diag-row-pending` each hardcoding their own amber. All of these now reference `var(--ok)`/`var(--warn)`/`var(--bad)` via the same `color-mix(in srgb, var(--X) N%, transparent)` pattern already used elsewhere in the stylesheet. Result: every "ready/good," "caution/pending," and "missing/risky" indicator in the app — engine-readiness chips, RAM-fit chips, dependency chips, diagnostics rows — now renders the exact same green/amber/red, instead of 3 different greens and 2 different ambers that all meant the same thing.

**Two more raw byte-formatting gaps found and fixed (same bug class as v1.7.2/v1.7.3):** The Subtitle-models grid card and the Whisper-model `<select>` dropdown on the Subtitles tab both built their size text as `m.size_gb + ' GB'` directly, bypassing the shared `formatGb()` helper entirely — so a Whisper model under 1 GB (e.g. `whisper-base`, 0.15 GB) showed "0.15 GB" instead of "150 MB," while the exact same model showed the correctly-formatted size everywhere else in the app. Both now call `formatGb(m.size_gb)`, matching every other size display.

**Download confirmation flow unified across TTS and Whisper models:** Clicking "Download" behaved differently depending on which tab you were on — TTS models opened a confirmation dialog (size, RAM requirement, gated-repo token prompt) via `confirmDownload()`, while Whisper/subtitle models downloaded immediately with no confirmation via a separate `downloadWhisperModel()` path. Same button label, same icon, two different behaviors. Whisper downloads (both the Models-tab card and the Subtitles-tab inline download button) now route through the same `confirmDownload()` → `pendingDownload` → `startDownload()` flow as every other model. The confirm dialog's memory-requirement and recommended-hardware lines are now conditionally shown (`x-show`) since Whisper models don't carry those fields — they simply don't render for Whisper, rather than showing `undefined`. `startDownload()` now detects whether the confirmed model is a Whisper model and, if so, runs the same completion-polling loop `downloadWhisperModel()` used to run standalone (kept as `_pollWhisperUntilCached()`); the old duplicate method was removed.

**Terminology aligned:** the Subtitle-models grid card showed "✓ ready" for a cached model while every other tab in the app calls the same on-disk state "✓ cached" (see the Models-tab chip legend). Changed to "✓ cached" to match.

**Checked and deliberately left unchanged (real inconsistencies, but not worth the churn or not actually bugs):**
- The Download-confirm modal's Cancel button (`class="ghost"`, no `.btn`) vs. other modals' Cancel buttons (`class="btn ghost"`) — verified in `style.css` that `.btn` has no bearing here: the applicable rule is the tag+class selector `button.ghost`, which matches regardless of whether `.btn` is also present. Zero rendering difference, so not a real bug (same conclusion reached earlier this session for the API-docs Copy buttons).
- "Clear" vs. "Remove" vs. "Discard + re-record" across various destructive actions — re-checked each instance in context; "Clear" is consistently used for bulk/list-clearing actions (history, filters, finished downloads) and "Remove" for single-item deletion from a persisted collection (voice library). Consistent on inspection, not a real bug.
- Empty-state copy tone varies a little (conversational vs. neutral vs. directive) across tabs — real but low-impact stylistic drift; left alone to avoid rewriting seven unrelated strings with no functional benefit.
- The "🚀 Ready to generate" filter chip vs. the "✓ Cached" filter chip on the Models tab — these looked like a possible duplicate label at first glance, but they filter on two genuinely different conditions (cached-only vs. cached-**and**-engine-installed), each with a clarifying tooltip. Not a bug.

### Notes

- PATCH bump (1.7.3 → 1.7.4) — frontend-only (`app.js`, `index.html`, `style.css`), no backend/schema change. Already live on the running server (static assets, no-cache headers) — `Update` makes it permanent.
- Verified via `curl` against the live server (port 47870 is the user's own running Pinokio instance, not something this session restarts) plus a Node.js syntax check on `app.js`.

---

## [1.7.3] — 2026-07-01

### Fixed — Audited every byte/size display in the app for the same GB-vs-GiB bug; found and fixed two more instances

Follow-up to v1.7.2's download-progress fix — asked "does this affect other models / other places too?" Audited every byte-formatting code path in the app (frontend and backend) rather than assuming the one fix covered everything.

**Already covered by v1.7.2, confirmed universal:** `downloadCaption()` — the single shared renderer for download progress — is called from exactly two places: the Models-tab per-card "active download" caption *and* the Downloads-tab job table. Both read from the same `humanBytes()` helper, and the underlying job data comes from one shared `manager.list_jobs()` regardless of engine family. So the original fix already applies to **every** downloadable model — TTS engines and Whisper alike — not just the one that got reported.

**Found two more instances of the same bug class, now fixed:**

- **`formatGb()`** (used for the *static* size shown on every model card, the RAM-planner's "best pick" caption, and the download-confirmation dialog) rounded sub-1 GB values with `× 1024` instead of `× 1000`. Real impact: any catalog entry under 1 GB — Kokoro (0.34 GB), whisper-tiny (0.07 GB), whisper-base (0.15 GB), several MLX quant variants — displayed an advertised size ~2.4% larger than its real decimal size (e.g. Kokoro showed "348 MB" instead of "340 MB"). Same root cause as v1.7.2, just a different formatter that hadn't been touched. Now uses `× 1000`, matching `humanBytes()` and the catalog's own convention.
- **`_setSubtitleFile()`** (the file-size caption shown when you pick/drop an audio clip on the Subtitles tab) had its own inline binary (`/1024/1024`) computation instead of calling the shared `humanBytes()`. Not a cross-reference bug (there's no separate "advertised size" for a user's own file to disagree with), but a duplicate, inconsistent implementation — replaced with a call to `humanBytes()` so every byte count in the app now goes through exactly one, correct, decimal formatter.

**Confirmed correct and deliberately left unchanged:** `system_info.py`'s RAM-detection (`hw.memsize / 1024**3`) — installed memory capacity is conventionally reported in binary GiB (matches Apple's own "About This Mac"), which is a different domain from network/file-transfer byte counts. Not the same bug; changing it would make the RAM figure wrong instead of right. Also left alone: a Python code sample string on the API docs tab (`len(img)//1024`) — that's illustrative example text for a different, hypothetical app, not live app logic.

### Notes

- PATCH bump (1.7.2 → 1.7.3) — pure frontend formatting, no backend change, no schema change. Already live on the running server (static assets, no-cache headers) — `Update` makes it permanent.
- With this, every byte/size display in the app — download progress, catalog card sizes, RAM-planner picks, download-confirmation dialogs, and file-picker previews — uses one consistent decimal (SI) convention, matching what Hugging Face's own site shows and what `du`/Finder will report once a file is fully on disk.

---

## [1.7.2] — 2026-07-01

### Fixed — Download progress showed 1.5 GB for a model the catalog lists as 1.6 GB (unit mismatch, not data loss)

Reported: downloading `mlx-community/whisper-large-v3-turbo` — the Models tab lists it as **1.6 GB**, but live progress only ever showed **1.5 GB**, and the job seemed to vanish from the Downloads tab entirely.

**Root cause, verified live against a real download job:** the model's `weights.safetensors` is exactly `1,613,979,758` bytes.

- Divided the standard (decimal/SI) way — same convention HF's own site and our static catalog `size_gb` use — that's **1.614 GB**, which rounds to the "1.6 GB" shown before downloading.
- The frontend's `humanBytes()` helper (used only for *live* download byte counters) divided by **1024** at each step instead — same bytes, but that's **1.503 GiB**, mislabeled "GB" in the UI.

Same bytes, two unit systems, two different-looking numbers. Nothing was actually missing.

**Fix:** `humanBytes()` in `app.js` now divides by 1000 (decimal) like everything else in the app, so live download progress agrees with the catalog's advertised size. Verified against the real in-flight job: `1,613,979,758` bytes → **1.61 GB**, consistent with the catalog's "1.6 GB" (small residual rounding — 1 vs 2 decimal places between the two display contexts — is expected and no longer looks like data loss).

### Diagnosed — why the download appeared to disappear from the Downloads tab

Not a code bug: `GET /api/downloads` and the SSE stream both return every in-memory job unconditionally, confirmed live (a fresh whisper download showed up immediately). What actually happened: **the server was restarted while the download was mid-flight** (the timestamps on a stray 0-byte `.incomplete` blob on disk lined up exactly with the last server restart). Download jobs are tracked in-memory only, so a restart — including our own "Update & Restart" button — silently drops any job in progress and leaves a partial blob behind. Re-triggering the download today picked up cleanly and is progressing normally; no code path prevented it from showing up.

Not changed in this release (flagged for later if it becomes a recurring annoyance): persisting in-flight download jobs across a server restart, and/or auto-detecting a stale `.incomplete` blob on startup to offer a one-click resume.

### On which Whisper model to use

`whisper-tiny` mis-transcribing (including the "wrong accent" pattern) is a well-known limitation of that model, not a bug — it's the least accurate tier in the registry, meant for quick tests only. `whisper-large-v3-turbo` (1.6 GB, the app's recommended default, currently mid-download as of this fix) is a large jump in accuracy and should resolve it. The full non-turbo `whisper-large-v3` (3.1 GB) is not a better default on 8 GB Macs — it shares the same unified-memory pool as any loaded TTS engine, and turbo already carries "near-large accuracy" per its own catalog note. `whisper-large-v3-turbo-q4` (0.5 GB) is the safer pick specifically for tight-RAM 8 GB machines if turbo's 1.6 GB footprint is ever a concern.

### Notes

- PATCH bump (1.7.1 → 1.7.2) — pure frontend formatting fix in `app.js`. No backend change, no new deps, no schema change. Already live on the running server without a restart (static asset, no-cache headers) — `Update` picks it up permanently.

---

## [1.7.1] — 2026-06-26

### Changed — Models tab split into "Audio Generator" + "Audio Transcriber" sub-tabs

The Models tab previously stacked the TTS catalog and the Whisper speech-to-text models on one long page. They're now two clean sub-tabs so the two model types don't muddle together:

- **🎙️ Audio Generator (TTS)** — the RAM planner, "Best for your RAM" picks, search/sort/family/capability/RAM-fit filters, and the TTS family cards. Sorting stays here, scoped to the generator catalog.
- **🎬 Audio Transcriber (Whisper · STT)** — the Whisper subtitle/transcription models, with a "ready" count badge on the tab when any are downloaded.

Defaults to the Generator sub-tab; the toggle is purely a view switch (no reload). **Frontend-only — a plain _Update_ is enough.**

---

## [1.7.0] — 2026-06-26

### Added — RAM planner: interactive memory slider + live "Best for your RAM" picks (Models tab)

The Models tab gained a **hardware planner** so you can size models to a machine you don't own yet — set the unified-memory budget and every fit chip re-scores instantly.

- **RAM slider + numeric entry + tier presets** (8 / 16 / 24 / 32 / 48 / 64 / 128 / 256 / 512 GB). Defaults to your detected RAM; drag/type to *preview* a different Mac (e.g. plan an M3 Ultra 512 GB before buying it). A `↩ My Mac` button snaps back to detected. The chosen budget persists across reloads.
- **Live hardware fit** — per-card fit chips (✓ fits / ⚠ tight / ✗ over budget) are now scored **client-side** against the slider value via `fitFor()`/`effectiveRam`, so they update with no server round-trip.
- **✨ Best for your RAM** — a recommendation strip surfaces the highest-quality model in each lane (overall / voice cloning / multilingual / expressive / streaming) that still fits the budget. At 8 GB it favours the lighter tiers; at 512 GB it upgrades to the full-precision builds.
- **Segmented "RAM fit" filter** (All / ✓ Fits / ⚠ Tight / ✗ Over), mirroring the Chat Studio model-tab control for a consistent look across the suite. The old binary "Fits my Mac" chip is folded into this.

> Note: open TTS models are small — catalog RAM floors top out at 16 GB — so on a big machine essentially everything fits; the planner's upside there is picking the highest-precision tier and previewing headroom.

**Frontend-only — no new Python dependencies. A plain _Update_ from the Pinokio sidebar is enough (no re-install / Install Generation needed).**

---

## [1.6.3] — 2026-06-06

### Fixed — Whisper transcription `ImportError: cannot import name 'ReasoningEffort'` (dependency drift)

A Mac mini hit this transcribing with `mlx-community/whisper-tiny`:

```
Whisper model mlx-community/whisper-tiny ships no HF processor, and the fallback
processor from openai/whisper-tiny couldn't be loaded
(ImportError: cannot import name 'ReasoningEffort' from 'transformers' ...)
```

**Diagnosis — verified, not assumed.** Reproduced on the dev box: `WhisperProcessor.from_pretrained("openai/whisper-tiny")` loads **fine** there, and `from transformers import ReasoningEffort` fails everywhere (the symbol isn't in transformers 5.9.0). So the failing Mac had a **different, drifted environment** — not a code bug.

**Root cause: floating dependency pins.** `requirements-generation.txt` had `transformers>=4.55` (any version ≥ 4.55) and `mlx-audio @ git+…mlx-audio.git` (always latest **master**). Every Mac that ran *Install Generation* on a different day resolved a different transformers + a different mlx-audio commit. The mini drifted into a combo where mlx-audio's newer code path expects `transformers.ReasoningEffort` but its transformers doesn't export it. The dev box happened to land on a working combo (`transformers 5.9.0` + `mlx-audio @14add66`).

### Fix 1 — Pinned the whole transformers + MLX stack to one verified-good set

`requirements-generation.txt` now pins the exact combo that's verified working end-to-end (TTS engines + Whisper STT):

```
transformers==5.9.0
tokenizers==0.22.2
mlx==0.31.2
mlx-lm==0.31.3
mlx-audio @ git+https://github.com/Blaizzy/mlx-audio.git@14add666b5313cadff94a231ee11979f6ac1adf7
```

The `mlx-audio` git pin (an **exact commit**, not floating master) is the biggest stability win — every server now converges to one identical environment. To upgrade later: bump the commit + `transformers` together, verify TTS + STT, then commit the new pins.

### Fix 2 — Hardened the processor fallback (resilience + clear errors)

`_attach_processor()` in `transcription.py` now:
- Tries a **narrow `WhisperTokenizer` import first** (all mlx-audio's whisper `get_tokenizer()` actually reads is `processor.tokenizer`). This dodges the heavier `WhisperProcessor` import chain that can blow up on unrelated drifted symbols like `ReasoningEffort`. A tiny `_TokenizerOnlyProcessor` shim exposes just `.tokenizer`. Verified to produce identical transcription.
- Falls back to the full `WhisperProcessor` if the narrow path fails.
- If both fail, raises a **clear, actionable error** that distinguishes a *dependency mismatch* ("re-run Install Generation — it now pins a known-good set; or `uv pip install 'transformers==5.9.0' 'tokenizers==0.22.2'`") from a *network* failure — instead of surfacing a raw `ImportError`.

### Verification

End-to-end through the real `TranscriptionManager.transcribe()`: `whisper-tiny` loads, the tokenizer-only path attaches from `openai/whisper-tiny`, and it transcribes a clip into valid SRT. `whisper-large-v3-turbo`'s base tokenizer (`openai/whisper-large-v3-turbo`) confirmed to load too. `audit_truth.py`: NO DRIFT.

### How to apply across all your Mac servers

On **each** Mac running Voice Studio:

1. **Update** from the Pinokio sidebar (pulls v1.6.3 with the pinned `requirements-generation.txt`).
2. **Re-run "Install Generation"** — this is the important step; it forces the environment to the pinned `transformers==5.9.0` + `mlx-audio @14add66` set. (`uv` will downgrade/upgrade as needed to match.)
3. **Stop → Start** the server.

Manual equivalent (if not using the sidebar), from the app's conda env:

```
uv pip install 'transformers==5.9.0' 'tokenizers==0.22.2' 'mlx==0.31.2' 'mlx-lm==0.31.3' \
  'mlx-audio @ git+https://github.com/Blaizzy/mlx-audio.git@14add666b5313cadff94a231ee11979f6ac1adf7'
```

After that, every server has the identical working environment, and any Whisper model (tiny → large-v3-turbo) transcribes. **You can keep the 0.5 GB `whisper-large-v3-turbo-q4`** on the 8 GB mini — this fix unblocks it.

### Notes

- PATCH bump (1.6.2 → 1.6.3) — a dependency change, so it **requires re-running Install Generation** (same as v1.5.1's `mistral-common` addition). No new engines, no schema change.
- The earlier advice to "switch to the 1.6 GB full turbo to sidestep the broken fallback" was a *workaround*, not a fix — all models share the same processor-fallback code, so the version pin is what actually resolves it for every model.

---

## [1.6.2] — 2026-06-06

### Added — auto-restart the service after Update + a "Repair · take over port" button

Two follow-ups from the post-build audit:

- **Update now restarts the service.** A running launchd service keeps the *old* backend code in memory until restarted. `update.js` now ends with a `bash restart_service.sh` step gated on `{{exists('service/.installed')}}` — so after Update, an installed service is kicked to pick up the new code automatically. No-op if the service isn't installed.
- **"Repair · take over port" menu item** (service mode). Re-runs the installer (boot out → free the port → re-bootstrap), so any wedged/conflicting state is fixable in one click without the Terminal. Distinct from **Restart Service** (a quick `kickstart -k`).

### Fixed — take-over no longer risks killing connected clients
The port take-over in v1.6.1 used `lsof -ti tcp:PORT`, which matches **any** socket on the port — including connected clients (a browser tab, the Pinokio webview, an SSE stream). Clicking Install with the UI open could have killed your browser. Now filtered with `-sTCP:LISTEN` so **only the listening server** is targeted. Verified live: a real client connection is correctly excluded.

### Notes
- PATCH — service scripts + update.js only. `Update`, then re-run **Install as Startup Service** once so the safer take-over + repair are in place.

---

## [1.6.1] — 2026-06-06

### Fixed — "Check Service Status" is now clear + detects the double-run conflict

Two issues surfaced the first time the status button ran against a live service:

- **"Watchdog: not running" looked broken — it isn't.** The watchdog is a *periodic* agent (fires ~1s every 60s), so between checks it's idle by design. The status now says so explicitly instead of dumping a scary raw `state = not running`. The server line is also cleaner: `✓ loaded · running (pid N)`.
- **Port-conflict detection.** If you start the app via Pinokio's **Start** and *also* install the service, both fight for the same port — the service can't bind and launchd crash-loops (the err log fills with `[Errno 48] address already in use`, and the health check is unknowingly answered by the *Pinokio* instance). The status script now detects this from the service err-log and prints a clear **PORT CONFLICT** box.

### Changed — installing the service now cleanly takes over the port
The bigger fix: **Install as Startup Service** now **stops whatever is already listening on the port** (your Pinokio "Start" instance) right before it starts the service. So the common flow — *click Start, then Install Service* — now Just Works: the old instance is stopped, the service binds, no crash loop, no manual `pkill`. (Graceful TERM, then KILL any straggler.) It targets **only the LISTENING server** (`lsof -sTCP:LISTEN`) — never connected clients, so an open browser tab / the Pinokio webview / an SSE stream is left alone. Uninstalling does NOT auto-restart the Pinokio instance — click **Start** again if you want manual mode back.

### Notes
- PATCH — service scripts only; no app/deps change. `Update` to refresh, then re-run **Install as Startup Service** once so the new take-over logic is in place.

---

## [1.6.0] — 2026-06-06

### Added — one-click "Install as Startup Service" (always-on server + self-healing)

For running this on a headless/server Mac (e.g. a fleet reached over Tailscale), you can now make the app a real background service instead of opening Pinokio and clicking Start every time.

New sidebar button **❤️ Install as Startup Service** installs a macOS **launchd LaunchAgent** that:

- runs the server (`serve.sh` → uvicorn on **47870**) **at login**, so it returns automatically after a reboot;
- **restarts on crash** via launchd `KeepAlive`;
- ships a **health watchdog** agent (`watchdog.sh`, every 60s) that hits `/api/health` and relaunches the server if it hangs (alive-but-unresponsive — which KeepAlive can't catch).

No sudo needed (per-user agent). Once installed, the sidebar switches to a **service-mode menu** (see below) for managing it. Service logs go to `logs/service/`.

New files: `serve.sh`, `watchdog.sh`, `install_service.sh`, `uninstall_service.sh`, `service.js`, `unservice.js`. The serve/watchdog scripts are **self-locating** (resolve paths from their own folder) so the same files work on any Mac/username. The per-machine `service/.installed` marker (drives the menu) is gitignored.

### Service mode — manage it entirely from the sidebar
Once the service is installed, Pinokio no longer "sees" the app as running (launchd owns it, not Pinokio's Start). So the sidebar now switches to a dedicated **service-mode menu** that avoids the old contradiction (a "Start" button that would fight the service for the port):

- **Open UI (service)** / **Open in Browser** — go straight to the running server on its fixed port; you no longer need Pinokio's Start to reach it.
- **Check Service Status** (`service_status.js` → `status_service.sh`) — shows the launchd agent state, a live `/api/health` ping (✅ running / ❌ not responding), and the tail of the service log, all in the terminal. This is how you know it's actually up.
- **Restart Service** (`service_restart.js` → `restart_service.sh`) — `launchctl kickstart -k` for a manual kick.
- **Service Logs** — opens `logs/service/`.
- **Uninstall Startup Service** — removes both agents + the marker; the normal Start button comes back.

The "Start" button is hidden while the service is installed, so the two can't collide.

### Docs — power-cut recovery, explained
The install button prints, and the README documents, the three one-time **admin** settings needed for full hands-off recovery after a power outage (the button does NOT change these — you do them once per machine):
1. `sudo pmset -a autorestart 1` — power on automatically when electricity returns.
2. **Auto-login** — required so the Apple GPU (Metal/MLX) is available; a pre-login daemon can't use it.
3. **FileVault off** — otherwise reboot stops at the encrypted-disk password screen and never reaches login.

### Verified
- Headless launch path tested live: `conda_env/bin/python -m uvicorn backend.main:app` with `HF_HOME` set boots and answers `/api/health` (200) on a throwaway port, then shuts down clean.
- Shell scripts `bash -n` clean; plists pass `plutil -lint`; all `.js` parse.

### Notes
- MINOR bump — new feature, no new Python deps. `Update` from the sidebar to get the files, then click **Install as Startup Service** on each Mac.
- Use the **service OR** Pinokio's **Start** — not both (they share port 47870).

---

## [1.5.3] — 2026-06-06

### Fixed — downloads now grab companion codecs too (no surprise second download)

Some engines load a **second** model — an audio codec / tokenizer that lives in a *different* HF repo — at generation time. Downloading just the catalog model left that companion missing, so the first **Generate** triggered a surprise download (you saw it on Marvis: `tokenizer-e351c8d8-checkpoint125.safetensors` downloading at 59% mid-generation — that's the **Mimi codec** from `kyutai/moshiko-pytorch-bf16`).

Now a model download is **complete on the first run**:

- **Companion fetch** — after the main model, the downloader pulls each companion (verified against the engine source):
  - **Marvis** → `kyutai/moshiko-pytorch-bf16` (just the 1 Mimi codec file — the repo is ~15 GB, we take only what's needed)
  - **Orpheus** → `mlx-community/snac_24khz`
  - **Chatterbox** → `mlx-community/S3TokenizerV2`
  - (Voxtral, Qwen3, Kokoro, VoxCPM, OmniVoice, Spark, VibeVoice, F5 are self-contained — no companion.)
- **Honest "cached" badge** — a model now reads `cached` only when its companions are present too. Until then it shows `partial`, so the Models tab never claims "ready" while a hidden codec is still missing. Re-downloading fills in whatever's absent (resumable, won't re-fetch what you have).
- **Accurate progress** — the download size/percent now includes companion bytes.

### Notes

- Backend change — `Update` from the Pinokio sidebar, then Stop + Start the server. No new Python deps, no reinstall.
- Already-downloaded models keep working; their companions were pulled lazily in earlier sessions and are now recognized by the badge.

---

## [1.5.2] — 2026-06-06

### Changed — all results now live in one history list + clearer rows + a real Download button

Generate-tab output cleanup, all per the request:

- **Single results list.** Removed the separate "Latest generation" panel that sat in the generate area. Every finished result — newest first — now appears in **Recent generations** instead of the newest one being split out up top. While a job runs you get a small "⏳ Generating speech… your result will appear in Recent generations below" status; the moment it finishes, it lands at the top of the list. (Errors land there too, with their message.)
- **Easier-to-read attributes.** The model / voice / seed / render-time tags went from faint grey monospace text to readable bordered pills with icons (🎙 model · 🗣 voice · 🎲 seed · ⏱ render time).
- **Unmistakable Download button.** Each row's download went from a tiny `⬇` icon to a full **⬇ Download** button — bigger, boxed, filled accent color, with the ghost "↻ Reuse" stacked beneath it so the primary action is obvious.

### Notes

- Pure frontend (HTML/CSS/JS) — PATCH bump. Just `Update` from the Pinokio sidebar and hard-refresh the web UI (the assets are cache-busted on load).
- The old generate-area "Copy URL" action was part of the removed panel; Download + Reuse remain on every history row.

---

## [1.5.1] — 2026-06-05

### Fixed — Voxtral generation failed with "tekken tokenizers require mistral-common[audio]"

Voxtral-4B-TTS (added in 1.5.0) couldn't generate — its tekken tokenizer loads through `mistral-common`, and the audio path needs the `[audio]` extra. mlx-audio imports it *lazily* at tokenizer-load, so the engine module imported fine (which is why the 1.5.0 wiring check passed) but actual generation raised `RuntimeError: Voxtral TTS tekken tokenizers require mistral-common[audio]`.

**Fix:** added `mistral-common[audio]>=1.5` to `requirements-generation.txt` and installed it. Verified the two engine guards now clear — `MistralTokenizer` imports and `encode_speech_request` is present. (Marvis was double-checked too: its sesame-engine runtime deps — `mlx_lm`, the mimi codec, tokenizers — are all already present, no extra needed.)

> ⚠️ **Re-run "Install Generation"** from the Pinokio sidebar to pick up `mistral-common[audio]`, then Stop + Start the server.

### Added — clickable voice buttons for preset-voice families

Instead of typing a voice name into a free-text field, you now get a row of clickable voice buttons for families with a **verified** roster:

- **Voxtral** — 20 buttons (♂/♀, grouped label per language)
- **Marvis** — 2 (Conversational A/B)
- **Orpheus** — 8 (Tara, Leah, Jess, Mia, Zoe, Dan, Leo, Zac)
- **Kokoro-MLX** — its existing voice list, now as buttons

Clicking a button sets the voice and highlights it. The free-text field stays below as a custom override. Every button's id is verified against the installed engine source (Voxtral `VOICE_MAP`, Marvis `SPEAKER_PROMPTS`), so a click can't produce a phantom voice. **KittenTTS** and **VibeVoice** keep the free-text field — their exact rosters aren't verifiable without the model on disk, and I won't render buttons I can't guarantee.

### Notes

- The voice-button UI is pure frontend; the Voxtral fix needs the dependency install above.
- `audit_truth.py`: still 15 families, NO DRIFT.

---

## [1.5.0] — 2026-06-05

### Added — 2 new preset-voice TTS families: Voxtral-4B-TTS + Marvis TTS

Both are MLX-native, run on 8 GB Apple Silicon, and ship their own built-in voices (no cloning). Each voice was verified against the installed mlx-audio engine code — no phantom voices.

- **Voxtral-4B-TTS** (`mlx-community/Voxtral-4B-TTS-2603-mlx-4bit` + `-bf16`) — **20 preset voices across 9 languages** (en/fr/es/de/it/pt/nl/ar/hi). The voice name picks the language: `casual_male`, `cheerful_female`, `fr_female`, `hi_male`, … (the full `VOICE_MAP` is baked into the engine). Faster-than-real-time at 4-bit. Adds de/it/pt/nl/ar coverage Qwen3-TTS doesn't have.
- **Marvis TTS** (`Marvis-AI/marvis-tts-250m-v0.1`) — a 250M CSM/Llama conversational model by the mlx-audio author, built for low-latency streaming. 2 built-in voices: `conversational_a` (female), `conversational_b` (male). Fully self-contained — its prompt clips ship in the repo and `config.text_tokenizer` points back at itself, so it never falls back to the gated `sesame/csm-1b`.

Both use the generic mlx-audio worker (`voice_picker` mode) — no new worker code, no new Python deps (mlx-audio already bundles the `voxtral_tts` and `sesame` engines; verified they import clean in the installed env).

### Considered but NOT added — MeloTTS

Dropped on purpose. mlx-audio's `melotts` engine needs a converted repo (`bert_weights.npz` + sanitized weights); the original `myshell-ai/MeloTTS-*` repos ship PyTorch `.pth` instead, and no MLX-converted MeloTTS exists on the Hub. Wiring it would have been a guaranteed load failure, so it's intentionally left out rather than shipped broken.

### Fixed — MLX-only filter no longer hides MLX families

While wiring the above, found the `apple_optimized` flag (which the default-ON "🍎 MLX only" filter keys off) only credited `-mlx`-suffixed families plus `qwen3-tts`/`orpheus`. That silently hid **kittentts, vibevoice, omnivoice** (and would have hidden the two new families) from the Models tab under the default filter, even though all are MLX. Now every mlx-audio family is correctly marked `apple_optimized`.

### Notes

- New model families, but **no reinstall needed** — just `Update` from the Pinokio sidebar, then download Voxtral / Marvis from the Models tab.
- `audit_truth.py`: 15 families, NO DRIFT — every catalog family is wired and dispatched.

---

## [1.4.4] — 2026-06-05

### Fixed — Qwen3-TTS CustomVoice: removed 2 phantom preset speakers (Ethan, Chelsie)

Picking **Ethan** (or **Chelsie**) on the Qwen3-TTS CustomVoice model failed every time with the cryptic *"RuntimeError: mlx-audio didn't produce a wav file."* The real cause was buried one layer down:

```
ValueError: Speaker 'Ethan' not supported.
Available: ['serena','vivian','uncle_fu','ryan','aiden','ono_anna','sohee','eric','dylan']
```

The CustomVoice model ships **exactly 9 speakers** (verified against the model's own `config.json` → `spk_id` map). Our `QWEN3_PRESET_SPEAKERS` list carried **11** — two phantoms (`Ethan`, `Chelsie`) copied from an older Qwen roster that this model doesn't contain. They appeared in the dropdown and even passed the app's own validation (which was built from the same bad list), so the failure only surfaced as the generic no-wav wall from mlx-audio's silently-swallowed exception.

**Fix:** trimmed the list to the model's real 9 — Ryan, Aiden, Serena, Vivian, Uncle_Fu, Dylan, Eric, Ono_Anna, Sohee. The list is now documented as deriving from the model's `spk_id` map, with a guard note against re-adding speakers the model can't voice. (mlx-audio matches names case-insensitively, so the capitalised display IDs resolve fine.)

### Audit — checked every model's voice capability against its actual engine

Per the "verify, don't assume" rule, I introspected the installed mlx-audio engines + downloaded model files for **all** families. Result: Qwen3-TTS was the *only* family advertising voices the engine rejects. Full capability map recorded:

| Family | Voice mechanism | Status |
|---|---|---|
| Qwen3-TTS CustomVoice | 9 named presets | **fixed (was 11)** |
| Qwen3-TTS Base | clone (reference) | ✓ correct |
| Qwen3-TTS VoiceDesign | natural-language voice prompt | ✓ correct |
| VoxCPM2 / VoxCPM v1 | zero-shot / voice-design / clone — **no named presets** | ✓ correct |
| Kokoro | 28 named presets (curated English subset of 54) — all valid | ✓ correct |
| Orpheus / KittenTTS / VibeVoice | free-text voice field (tara, dan, leah…) | ✓ correct |
| Spark-TTS | attribute-based (gender + pitch) OR clone | ✓ correct |
| Chatterbox / F5-TTS / OmniVoice | clone (reference) only | ✓ correct |
| Bark | preset speakers (v2/&lt;lang&gt;_speaker_N) | ✓ valid format |

### Notes

- PATCH bump — catalog/metadata fix within an existing family. Run `Update` from the Pinokio sidebar.
- Image / Music apps unaffected — they have no preset-voice lists (the bug class is VoiceStudio-specific). Their analogous drift is already guarded by `audit_truth.py`.

---

## [1.4.3] — 2026-05-27

### Fixed — "Processor not found" on transcription (affected ALL Whisper models, not just q4)

A transcription attempt returned `400: "Processor not found. Make sure the model was loaded with a HuggingFace processor."` The report attributed it to the quantized `whisper-large-v3-turbo-q4` repo "missing its HF processor," with the suggested fix being to download the full 1.6 GB `whisper-large-v3-turbo` instead.

**Verified the claim — it's wrong, and the suggested fix wouldn't have worked.** Checked all six whisper repos' file manifests on Hugging Face:

```
mlx-community/whisper-large-v3-turbo      → config.json, weights.safetensors   ❌ no processor
mlx-community/whisper-large-v3-turbo-q4   → config.json, weights.npz           ❌ no processor
mlx-community/whisper-large-v3-mlx        → config.json, weights.npz           ❌ no processor
mlx-community/whisper-small-mlx           → config.json, weights.npz           ❌ no processor
mlx-community/whisper-base-mlx            → config.json, weights.npz           ❌ no processor
mlx-community/whisper-tiny                → config.json, weights.npz           ❌ no processor
```

**None of them bundle the HF processor** (`preprocessor_config.json`, tokenizer, vocab). The full `whisper-large-v3-turbo` has the exact same problem as the q4 — downloading it would have hit the identical error after 1.6 GB. The error is universal, not q4-specific.

### Root cause

mlx-audio's whisper `post_load_hook` runs `WhisperProcessor.from_pretrained(<local snapshot>)`. Since the mlx-community repos don't ship processor files, that call fails, `model._processor` is left `None`, and `get_tokenizer()` raises "Processor not found" at transcribe time.

### Fix

mlx-audio computes the mel spectrogram **itself** from the model's own config (`log_mel_spectrogram(audio, n_mels=self.dims.n_mels)`) and uses the processor **only** for its tokenizer. So `_get_model()` now attaches a tokenizer-providing `WhisperProcessor` from the model's **base OpenAI repo** (which *do* ship the processor) whenever the loaded model has none:

```python
_PROCESSOR_BASE = {
    "mlx-community/whisper-large-v3-turbo":    "openai/whisper-large-v3-turbo",
    "mlx-community/whisper-large-v3-turbo-q4": "openai/whisper-large-v3-turbo",
    "mlx-community/whisper-large-v3-mlx":      "openai/whisper-large-v3",
    "mlx-community/whisper-small-mlx":         "openai/whisper-small",
    "mlx-community/whisper-base-mlx":          "openai/whisper-base",
    "mlx-community/whisper-tiny":              "openai/whisper-tiny",
}
# in _get_model, after load_model:
if getattr(model, "_processor", None) is None:
    model._processor = WhisperProcessor.from_pretrained(_PROCESSOR_BASE[repo])
```

The processor is ~2 MB of JSON/vocab (not model weights), fetched once and cached in `HF_HOME`. This makes **every** Whisper model work — including the 0.5 GB q4 you already downloaded. **You do not need to download the 1.6 GB version.**

All six OpenAI base repos were confirmed to ship the processor before wiring this.

### Notes

- PATCH bump (1.4.2 → 1.4.3) — backend fix in `transcription.py`. No new deps. **Stop → Start** the server (the new model-load path is read at import).
- First transcription with each model does a one-time ~2 MB processor fetch (needs network); cached thereafter. If the modal is offline on first run, you get a clean error explaining the fetch is needed — not a cryptic "Processor not found."
- The `whisper-large-v3-turbo-q4` is still the right pick for your 8 GB M1 — this fix unblocks it.

### Changed — Subtitles tab moved next to Generate + Whisper models surfaced in Models tab

Two bits of feedback after v1.4.1:

1. **"I couldn't find the Whisper models in the Models tab."** Correct — the
   Whisper models live in their own registry (`WHISPER_MODELS` in
   `transcription.py`), separate from the TTS `catalog.py` that drives the Models
   grid. They were only downloadable from the Subtitles tab. Now they're surfaced
   in the Models tab too, where users expect all downloads to live.
2. **"Subtitles should be next to Generate, before Models."** Moved.

**Tab reorder:** `Generate · Subtitles · Models · Downloads · Import · Voices · API · Settings` (Subtitles was last, now second).

**Whisper models in the Models tab:** new "🎬 Subtitle models (Whisper · speech-to-text)" section at the top of the Models page, above the TTS family grid. It's a separate card block (not mixed into the TTS family filter system — they're STT, not TTS) showing each Whisper model's label, repo, size, note, cache state (`✓ ready` / `not downloaded`), and a one-click orange Download button for uncached ones. Driven by the same `/api/transcribe/availability` data as the Subtitles tab, so download state stays in sync between the two surfaces.

**Loaded at startup:** `refreshTranscribe()` now runs in `init()` (after catalog + voices), so the Models-tab Whisper section is populated no matter which tab you open first — not just after visiting Subtitles.

**Minor:** `downloadWhisperModel()` now sets `stt.model = repo` so the per-card "Downloading…" label tracks the right card, and the Subtitles-tab dropdown auto-selects whatever you just downloaded.

### Notes

- PATCH bump (1.4.1 → 1.4.2) — UI placement + discoverability. No backend change, no new deps. `Update` → reload (the v1.3.6 cache-busting picks up the new assets automatically).
- **Reminder:** the STT API routes (`/api/transcribe*`) shipped in v1.4.0 require a server **Stop → Start** to be live. If `/api/transcribe/availability` 404s, the Models-tab Whisper section + Subtitles tab will be empty until you restart the Voice Studio server.
- Whisper still downloads through the existing generic `/api/downloads` — the Models-tab button and the Subtitles-tab button both hit it. Nothing new on the backend.

---

## [1.4.1] — 2026-05-27

### Added — Subtitles UI tab (transcribe tester + Whisper model download)

v1.4.0 shipped the STT/subtitle API but was API-only (the consumer is Story Studio over the network). This adds a **Subtitles** tab to the Voice Studio web UI so you can transcribe and download Whisper models directly, without curl or a second app.

**The tab (`tab==='subtitles'`):**
- **Whisper model picker** — dropdown of all 6 registry models with size, cache state (`✓ ready` / `— not downloaded`), and the recommended marker. Shows the model's note below.
- **One-click download** — if the selected model isn't cached, an orange Download button POSTs to the existing `/api/downloads` and then polls `/api/transcribe/availability` every 4s until it flips to cached (re-enabling Transcribe automatically). Progress also shows in the Downloads tab.
- **Drag-drop / click-to-pick audio** — reuses the existing `.voice-dropzone` styling. Accepts WAV/MP3/M4A/FLAC/OGG.
- **Options** — optional language code (blank = auto-detect) + word-level-timestamps checkbox.
- **Result panel** — Text / SRT / VTT view toggle, with Copy and (for SRT/VTT) a Download button that builds a blob from the current view. Header shows detected language, duration, line count, and elapsed transcription time.

**Wiring (`app.js`):**
- New `stt` state object + `sttSelectedModel` getter.
- Handlers: `refreshTranscribe`, `downloadWhisperModel` (with cache-state polling), `onSubtitlePick` / `onSubtitleDrop` / `_setSubtitleFile`, `runTranscribe` (multipart POST with a live elapsed counter), `subtitleBlobUrl` (for the download link).
- `subtitles` added to the hash-route whitelist (`#subtitles` deep-links + auto-loads availability). Also fixed: `voices` was missing from that whitelist — added it too.
- 409 ("model not downloaded") surfaces a clear "Model not downloaded yet" hint pointing at the download button.

**Nav + CSS:**
- New **Subtitles** tab button between Voices and API.
- Subtitle-specific CSS (two-column grid, format tabs, monospace output box). Reuses the existing dropzone + `download-btn` (orange) classes.

### Notes

- PATCH bump (1.4.0 → 1.4.1) — pure UI surface for the already-shipped v1.4.0 STT API. No backend change, no new deps. `Update` → Stop → Start. (Thanks to v1.3.6's `__APP_VERSION__` cache-busting, the new JS/CSS load automatically — no manual hard-refresh needed this time.)
- The API contract is unchanged — Story Studio's integration (per `docs/SUBTITLES.md`) is unaffected. This tab just gives you a local way to test transcription and pre-download Whisper models.

---

## [1.4.0] — 2026-05-27

### Added — Speech-to-text / subtitle API (Whisper)

Voice Studio now does STT, not just TTS. Story Studio (the YouTube-asset app that
already calls our TTS endpoints) needs timestamped subtitles for the narration it
generates. Rather than stand up a separate service, this adds Whisper-based
transcription to the existing server.

**Why here and not a separate app:** `mlx-audio` (already a dependency for the MLX
TTS engines) ships a complete STT subsystem — Whisper + a dozen other ASR models.
So this was wiring, not a new install. `whisper-tiny` was even already in the HF
cache. One service, one Tailscale endpoint, one thing to keep alive. And TTS audio
is pristine, so Whisper transcription of our own output is near-perfect.

Full integration guide for the consuming app: **`docs/SUBTITLES.md`**.

### New module: `app/backend/transcription.py`

- `TranscriptionManager` — lazy-loads + caches one Whisper model, transcribes
  audio → text + timestamped segments. Follows every standard from this release
  cycle:
  - **Explicit-path loading (v1.3.5):** passes the local snapshot `Path` to
    `mlx_audio.stt.load_model`, never a repo ID — immune to cache-layout drift.
  - **Shared `_GEN_LOCK` (from generation.py):** STT and TTS serialize on one GPU
    lock so two MLX models can't both spike Metal memory → OOM.
  - **MLX cache release (v1.2.7):** frees buffers on model switch + after each job.
  - **No silent downloads:** if the requested model isn't cached, raises cleanly
    (surfaced as HTTP 409) instead of pulling 1.6 GB mid-request.
- `WHISPER_MODELS` registry — 6 verified mlx-community repos (turbo /
  turbo-q4 / large-v3 / small / base / tiny), all confirmed live with real sizes.
- `segments_to_srt()` / `segments_to_vtt()` — hand-written formatters, full control
  over the cue format. Returns ready-to-write SRT + VTT strings.

### New endpoints (in `main.py`)

- **`GET /api/transcribe/availability`** — STT readiness + per-model cache state +
  the recommended default. Mirrors `/api/generate/availability`.
- **`POST /api/transcribe`** (multipart) — supply audio via either a `file` upload
  (universal) **or** a `job_id` (transcribe a previous TTS output with no
  re-upload — efficient same-machine path). Optional `model`, `language`,
  `word_timestamps`. Returns `{ text, language, duration, model, segments, srt,
  vtt }`. Clean error codes: 404 (job/file missing), 400 (bad params), 409 (model
  not downloaded — caller should download + retry).

### Downloading Whisper models

Reuses the **existing generic** `POST /api/downloads {repo}` — no new download
path. `mlx-community/whisper-large-v3-turbo` (~1.6 GB) is the recommended first
download; `...-turbo-q4` (~0.5 GB) for 8 GB Macs. The availability endpoint reports
which are cached.

### Notes

- MINOR bump (1.3.6 → 1.4.0) — new capability (STT) + new endpoints. **No new
  Python deps** — `mlx-audio` already provides the STT stack, so a plain `Update`
  → Stop → Start is enough (no need to re-run Install Generation, though it's
  harmless if you do).
- **What we did NOT use:** `whisperx` — it pins heavy torch/pyannote deps, the same
  trap that made us skip Coqui XTTS. Plain mlx-audio Whisper is clean + native.
- **Upgrade path noted:** `mlx-audio` also ships `qwen3_forced_aligner`, which
  aligns *known text* to audio for perfect word timestamps — relevant because
  Story Studio already has the script text. Not wired yet; flagged for later.
- No UI tab yet — this release is API-first since the consumer is Story Studio over
  the network. A "Subtitles" tab (drag-drop tester + click-to-download Whisper
  models) is an easy follow-up if wanted.

---

## [1.3.6] — 2026-05-27

### Fixed — Voice library Edit button + orange Download button invisible due to stale browser cache

User restarted the server after v1.3.3 (which added the ✏️ Edit button and the orange Download button), but the Edit button "doesn't work." Server logs were clean. The actual cause:

The HTML `<script>` and `<link>` tags had **manually-set cache-bust query strings** (`?v=phase2-repo-persist-1`, `?v=phase2-logo-1`) that **hadn't been bumped since v1.1.8**. Pinokio's embedded webview (and any modern browser) caches assets based on URL — so with the URL unchanged across 5 patch releases, the browser kept serving the cached v1.1.8 `app.js` that has no `openVoiceEditor` function. The `✏️` button rendered but its `@click="openVoiceEditor(v)"` resolved to `undefined` and silently did nothing.

The `NoCacheStaticMiddleware` (which sets `Cache-Control: no-store, no-cache, must-revalidate`) is in place but Pinokio's WKWebView ignores it. Cache-busting query strings are the bulletproof signal.

### Fixed (proper structural fix, not just a one-off bump)

Rather than manually bumping the cache-bust strings every release and hoping I don't forget next time, the `/` route now reads `index.html` and **substitutes `__APP_VERSION__` tokens with the current `APP_VERSION`** at request time:

```python
@app.get("/", response_class=Response)
def index() -> Response:
    html = (FRONTEND_DIR / "index.html").read_text()
    html = html.replace("__APP_VERSION__", APP_VERSION)
    return Response(content=html, media_type="text/html")
```

And the HTML now uses sentinel tokens:

```html
<link rel="stylesheet" href="/assets/style.css?v=__APP_VERSION__" />
<script defer src="/assets/prompts.js?v=__APP_VERSION__"></script>
<script defer src="/assets/app.js?v=__APP_VERSION__"></script>
<script defer src="/assets/alpine.min.js?v=__APP_VERSION__"></script>
```

Every VERSION bump now auto-busts all browser caches. Never have to remember to manually bump a cache-bust string again.

### Notes

- PATCH bump (1.3.5 → 1.3.6) — 2-line addition to `main.py`, 4-line edit to `index.html`. No new deps, no schema change. Run `Update` → Stop → Start.
- **One special instruction for this update**: after restarting, do a **hard refresh of the Voice Studio page** (⌘⇧R in most browsers, or click Pinokio's refresh button while holding ⇧). The current cached HTML still has the old `?v=phase2-...` URLs — once you hard-refresh, you get the new HTML with `?v=1.3.6` URLs, which will then auto-bust every future release.
- After v1.3.6, all of v1.3.3's UI changes (Edit button, orange Download button) become visible. v1.3.4's F5-TTS fix and v1.3.5's path-standard refactors were backend-only and were never affected.

### Lesson archived

The lesson "always bump cache-bust strings on frontend changes" is now structurally enforced — there's nothing to remember. Added to my cross-session memory notes for this project.

---

## [1.3.5] — 2026-05-27

### Codified — Worker model-loading standard (defense-in-depth across all workers)

Following the F5-TTS re-download bug (v1.3.4), establishing a project-wide standard so this class of bug doesn't recur in future workers.

**The rule:** every worker in `app/backend/generation.py` must resolve the local HF Hub snapshot path and pass it **explicitly** to the loader. Never pass a HF repo ID string when the loader will accept an absolute path.

**Why:** different upstream libraries use different cache backends. The standard `huggingface_hub` cache lives at `${HF_HOME}/hub/models--<org>--<repo>/...`, but some libraries — notably `cached_path` (used by F5-TTS) — have their own cache layout. When a worker passes a repo string and the library internally uses `cached_path`, it looks in the wrong directory and silently re-downloads. Passing an explicit absolute path bypasses the library's cache lookup entirely.

### Refactored — `_voxcpm_get_model` and `_bark_get_model`

Both workers previously passed the HF repo ID:

```python
# Before (works today via huggingface_hub, but one upstream change away from the F5-TTS bug)
voxcpm.VoxCPM.from_pretrained(repo, local_files_only=True, ...)
BarkModel.from_pretrained(repo)
```

Now they resolve the snapshot path via the existing `_mlx_audio_snapshot_path()` walker (which is generic — works for any HF Hub repo, not just mlx-audio ones) and pass it explicitly:

```python
# After
snapshot_path = self._mlx_audio_snapshot_path(repo)
voxcpm.VoxCPM.from_pretrained(str(snapshot_path), local_files_only=True, ...)
BarkModel.from_pretrained(str(snapshot_path), local_files_only=True)
AutoProcessor.from_pretrained(str(snapshot_path), local_files_only=True)
```

Both transformers' `from_pretrained` and voxcpm's `from_pretrained` accept absolute local paths interchangeably with repo IDs. The behavior is identical when the cache is healthy; the difference is **what happens when something goes wrong** — repo IDs can trigger surprise downloads, local paths can't.

### Documented — `voicestudio-mac/CLAUDE.md`

Added a new section: **"Worker Model-Loading Standard (added v1.3.5)"** that codifies the rule, explains why, shows the pattern, and lists every existing worker's compliance status:

| Worker | Pattern | Status |
|---|---|---|
| `_generate_mlx_audio` | `load_model(snapshot_path)` (Path, not str — v1.2.8) | ✅ |
| `_generate_omnivoice` | `OmniVoiceMLX.from_pretrained(str(snapshot_path))` | ✅ |
| `_generate_f5_tts` | `F5TTS(ckpt_file=…, vocab_file=…)` (v1.3.4) | ✅ |
| `_generate_voxcpm` | `voxcpm.VoxCPM.from_pretrained(str(snapshot_path), local_files_only=True)` (v1.3.5) | ✅ |
| `_generate_bark` | `BarkModel.from_pretrained(str(snapshot_path), local_files_only=True)` (v1.3.5) | ✅ |
| `_generate_kokoro` | `KPipeline(lang_code=…)` — no path API, trusts HF_HOME | 🔒 limitation |

Kokoro is the only exception — KPipeline doesn't accept a path argument, so it must trust HF_HOME via env var. Documented in the worker comment.

### Notes

- PATCH bump (1.3.4 → 1.3.5) — defensive refactor of two existing workers + documentation. No new deps, no schema change, no behavior change when cache is healthy. Run `Update` → Stop → Start.
- Workers behave identically when everything is in order; the change matters when an upstream library updates and starts using a different cache backend. We're now insulated from that.
- New workers in the future MUST follow this pattern — see `CLAUDE.md` for the boilerplate. Adding a `🔒 limitation` row to the table is fine if the loader genuinely doesn't take a path; silently passing a repo ID is not.

---

## [1.3.4] — 2026-05-27

### Fixed — F5-TTS re-downloading the 1.35 GB checkpoint even when already cached

User noticed the terminal log showed F5-TTS downloading `F5TTS_v1_Base/model_1250000.safetensors` (1.35 GB) after the v1.3.3 generate attempt — even though `SWivid/F5-TTS` was already in the HF cache via the Models-tab download. Two cache copies ended up on disk, wasting ~1.3 GB.

### Root cause

F5-TTS's `F5TTS.__init__` uses **`cached_path`** (a separate library from `huggingface_hub`) to fetch its main checkpoint:

```python
# f5_tts/api.py:80
cached_path(f"hf://SWivid/{repo_name}/{model}/model_{ckpt_step}.{ckpt_type}", cache_dir=hf_cache_dir)
```

`cached_path` has **its own cache layout** that's incompatible with the standard HF Hub format:

| Cache type | Layout |
|---|---|
| Standard HF Hub (what `snapshot_download` uses) | `{HF_HOME}/`**`hub/`**`models--<org>--<repo>/snapshots/<hash>/...` |
| `cached_path` (what F5-TTS uses) | `{cache_dir}/models--<org>--<repo>/snapshots/<hash>/...` (no `hub/` segment) |

So when v1.3.0 passed `hf_cache_dir={HF_HOME}` to `F5TTS()`, `cached_path` looked for `{HF_HOME}/models--SWivid--F5-TTS/...` (no `hub/`), didn't find it, downloaded fresh. The existing files at `{HF_HOME}/hub/models--SWivid--F5-TTS/...` were invisible to `cached_path` because of the layout mismatch.

This wasn't a regression — F5-TTS has always had this behavior. v1.3.0 just didn't account for it.

### Fix

In `_f5_tts_get_model()`, locate the checkpoint + vocab files in our standard HF Hub cache (via the existing `_mlx_audio_snapshot_path()` walker) and pass them **explicitly** to F5TTS via `ckpt_file=` and `vocab_file=`. F5TTS skips `cached_path` entirely when these are non-empty:

```python
snapshot_path = self._mlx_audio_snapshot_path(repo)
ckpt_file = snapshot_path / "F5TTS_v1_Base" / "model_1250000.safetensors"
vocab_file = snapshot_path / "F5TTS_v1_Base" / "vocab.txt"
# ... validate they exist, raise clean RuntimeError if not ...
F5TTS(model="F5TTS_v1_Base", ckpt_file=str(ckpt_file), vocab_file=str(vocab_file), ...)
```

The VoCoS vocoder (~50 MB) still auto-downloads on first load via `hf_hub_download`, which **does** respect `HF_HOME` correctly — small enough to leave alone.

### Cleanup task for users

If you generated with F5-TTS on v1.3.0 / v1.3.1 / v1.3.2 / v1.3.3, your cache likely has **two copies of the checkpoint**:

```
cache/HF_HOME/hub/models--SWivid--F5-TTS/     ← original (1.3 GB), keep this
cache/HF_HOME/models--SWivid--F5-TTS/         ← duplicate (1.3 GB), safe to delete
```

After updating to v1.3.4, you can reclaim ~1.3 GB with:

```bash
rm -rf cache/HF_HOME/models--SWivid--F5-TTS/
```

(Note: NO `hub/` in that path — that's the duplicate from `cached_path`.) The original at `cache/HF_HOME/hub/...` is what v1.3.4 uses.

### Notes

- PATCH bump (1.3.3 → 1.3.4) — one function rewrite in `generation.py`. No new deps, no schema change. Run `Update` → Stop → Start.
- Verified the fix doesn't break first-time-install flow: if the user runs `F5-TTS` without having downloaded `SWivid/F5-TTS` first, the explicit path check raises a clean `RuntimeError("F5-TTS checkpoint missing at ... — Re-download SWivid/F5-TTS from the Models tab")` instead of silently triggering a 1.35 GB out-of-band download. Forcing the through-the-Models-tab flow makes downloads visible, resumable, and cancellable.

---

## [1.3.3] — 2026-05-27

### Added — Voice library edit + orange Download button

User feedback after F5-TTS landed:

1. **No way to retrofit a transcript onto an existing voice.** F5-TTS requires a transcript per reference clip. Voices uploaded before v1.3.0 typically don't have one — and the only fix was deleting and re-uploading. Now there's an Edit button.
2. **The Download button on each voice card was unreadable on dark mode.** It used `btn ghost small` styling — basically transparent. Now it's a real orange button.

### Added — `PATCH /api/voices/{voice_id}` endpoint

- New `VoiceLibrary.update()` method in `voices.py` (alongside the existing `add()` / `delete()` / `get()`). Accepts any subset of: `name`, `language`, `gender`, `license`, `notes`, `source_url`, `transcript`. Fields not in the request are left unchanged; empty string clears clearable fields (notes / source_url / transcript).
- `update_voice()` route in `main.py` with an `UpdateVoiceBody` pydantic model. Returns 400 on validation errors (bad license/gender enum, name too long, etc.) and 404 if the voice_id doesn't exist.
- Audio file is **never** touched. Only `metadata.json` + `transcript.txt` on disk get rewritten. Voice ID, audio_extension, duration_seconds, sample_rate, channels, created_at, and permission_acknowledged all stay frozen — by design.

### Added — Edit UI on each voice card

- New ✏️ button next to the existing ✕ delete button in the card header.
- Click opens a modal pre-populated with the voice's current metadata (name, language, gender, license, notes, transcript).
- Transcript field is the big win — the modal fetches the current transcript via `GET /api/voices/{id}` on open so users can edit instead of retype.
- Save calls `PATCH /api/voices/{voice_id}`, replaces the local entry with the server response, and toasts confirmation.

### Changed — Voice card "Download" button is now orange

- Was: `<a class="btn ghost small" ...>⬇ Download</a>` — basically invisible on dark mode.
- Now: `<a class="btn download-btn" ...>⬇ Download WAV</a>` with dedicated CSS using `--warn` (`#f3b562` orange) as the background. Dark text on bright background for ≥AA contrast. Real button affordance.

### Notes

- PATCH bump (1.3.2 → 1.3.3) — backend addition + frontend addition, no schema breakage, no new deps. Run `Update` → Stop → Start (server restart picks up the new PATCH route).
- The Edit modal intentionally doesn't let you change the audio file. Audio changes mean a new reference clip with different waveform characteristics — should be a new library entry, not an in-place update. If a clip is bad, delete + re-add.
- The transcript file lives at `cache/voices/<voice_id>/transcript.txt` (separate from `metadata.json`). Editing to an empty string deletes the file and sets `has_transcript=false`; engines that require a transcript (F5-TTS) will then reject the voice.

---

## [1.3.2] — 2026-05-27

### Fixed — Diagnostics page falsely reporting F5-TTS as `Missing: f5_tts vocos`

User ran Install Generation after the v1.3.0 update, the install completed successfully (`f5-tts==1.1.20`, `vocos==0.1.0`, `cached-path==1.8.10`, etc. all installed per the pip log), but the Generate-tab diagnostics page still showed:

> ⛔ **f5-tts** · Missing: `f5_tts vocos` · Requires: `f5_tts torch vocos soundfile`

while every other engine was Ready.

**Root cause:** the diagnostics endpoint has two separate data structures:

1. `_PACKAGE_CHECKLIST` — the list of packages to actually probe with `_probe_package` (i.e. try importing).
2. `_ENGINE_REQUIREMENTS` — what packages each engine needs.

The "missing" check (`generation.py:506`) does `if not pkg_status.get(p)` — a package not in the **checklist** returns `None` from `pkg_status.get()`, which is falsy → falsely flagged as missing. When I added F5-TTS in v1.3.0, I added `f5_tts` and `vocos` to `_ENGINE_REQUIREMENTS["f5-tts"]` but **forgot to add them to `_PACKAGE_CHECKLIST`**. The diagnostics never actually probed them, just defaulted them to "missing."

Same bug for **3 other engines that were entirely invisible** in the diagnostics table: `kittentts`, `vibevoice`, `omnivoice`. They work fine (anyone can use them via the model picker), but they had no entry in `_ENGINE_REQUIREMENTS` at all, so the engine-readiness table just didn't include them. v1.2.0 (omnivoice) and v1.2.1 (kittentts + vibevoice) added the families and dispatch but skipped the diagnostics-side bookkeeping.

### Changes (both in `app/backend/generation.py`)

**`_PACKAGE_CHECKLIST`** — added 3 entries so the probe actually runs against them:

```python
("f5_tts",    "F5-TTS flow-matching TTS engine"),
("vocos",     "VoCoS vocoder used by F5-TTS"),
("omnivoice", "OmniVoice diffusion-LM TTS (ailuntx/OmniVoice-MLX)"),
```

**`_ENGINE_REQUIREMENTS`** — added 3 rows:

```python
"kittentts":  ["mlx", "mlx_audio", "soundfile", "numpy"],
"vibevoice":  ["mlx", "mlx_audio", "soundfile", "numpy"],
"omnivoice":  ["omnivoice", "torch", "transformers", "soundfile", "numpy"],
```

### Verification

Running `diagnostics()` inside the conda env now reports:

```
engines: 13, ready: 13/13
  kokoro             ✅ READY
  voxcpm             ✅ READY
  voxcpm-mlx         ✅ READY
  bark               ✅ READY
  qwen3-tts          ✅ READY
  kokoro-mlx         ✅ READY
  chatterbox-mlx     ✅ READY
  spark-tts-mlx      ✅ READY
  orpheus            ✅ READY
  kittentts          ✅ READY
  vibevoice          ✅ READY
  omnivoice          ✅ READY
  f5-tts             ✅ READY
```

**All 13 engines fully ready.** Was 10 visible engines, 9 ready in the user's screenshot before the fix.

### Notes

- PATCH bump (1.3.1 → 1.3.2) — pure bookkeeping fix in `generation.py`. No catalog change, no schema change, no new deps. `Update` → Stop → Start (server restart needed to reload `_PACKAGE_CHECKLIST` and `_ENGINE_REQUIREMENTS` at module load).
- F5-TTS was actually working all along since v1.3.0 + the user's Install Generation succeeded — only the diagnostics view was lying. Same for omnivoice / kittentts / vibevoice: they just weren't being reported.
- A nicer long-term fix would be auto-deriving `_PACKAGE_CHECKLIST` from `_ENGINE_REQUIREMENTS.values()` (union of all packages mentioned). Would have prevented this bug in the first place. Not done in this patch — out of scope, but flagged.

---

## [1.3.1] — 2026-05-26

### Removed — Dead `chatterbox`, `spark-tts`, `xtts` family stubs

The catalog had 3 families that have never had a working worker — they always raised `NotImplementedError` when picked. Cleaning them out so the catalog reflects only what actually works.

**Dropped families + their single ModelEntry each:**

- `chatterbox` (`ResembleAI/chatterbox`) — PyTorch original of Chatterbox. Fully covered by the `chatterbox-mlx` family (7 entries: chatterbox-mlx-4bit / -8bit, chatterbox-4bit / -8bit / -fp16, chatterbox-turbo-4bit / -8bit). On Apple Silicon the MLX variants are smaller, faster, same MIT license, and offer the exact same voice-cloning + exaggeration knob. No reason to keep the PyTorch stub around.
- `spark-tts` (`SparkAudio/Spark-TTS-0.5B`) — PyTorch original of Spark-TTS. Fully covered by the `spark-tts-mlx` family (4 entries: 4-6bit, 6bit, 8bit, bf16). Same reasoning as Chatterbox.
- `xtts` (`coqui/XTTS-v2`) — Coqui multilingual voice cloning. **The license isn't the deciding factor** (F5-TTS is also CPML / non-commercial and we just wired it in v1.3.0). The deciding factor is the `TTS` pip package: it **pins old torch versions** that would break the existing voxcpm / qwen3 / etc. stack. Re-adding it would mean a separate venv, vendored inference code, or both. Not worth the maintenance for a single non-commercial family when VoxCPM2 covers most of the same multilingual ground.

### Code cleanup

- Removed 3 `Family(...)` entries from `FAMILIES` dict in `catalog.py`.
- Removed 3 `ModelEntry(...)` rows from `CATALOG` tuple.
- Removed the `elif family in ("chatterbox", "spark-tts"):` and `elif family == "xtts":` branches from `_dispatch_txt2speech` in `generation.py`.
- Removed dead entries from `_ENGINE_REQUIREMENTS` dict (the `chatterbox` / `spark-tts` / `xtts` requirements were used to display "needs these packages" UI hints — useless for families that don't exist).
- Updated the module-level docstring to reflect the new wired list (13 families) + an explicit "Removed in v1.3.1" section so future devs don't accidentally re-add them.

### Audit

`audit_truth.py`: **NO DRIFT.** 13 families, **13 wired**, **0 unwired**. First time the catalog is 100% wired since the project started.

### Notes

- PATCH bump (1.3.0 → 1.3.1) — pure catalog cleanup. No functionality lost since these stubs never worked. No new deps, no schema change. Run `Update` from the Pinokio sidebar, then Stop → Start.
- If anyone had localStorage prefs (per-model presets from v1.1.8) pointing at the removed repos, those entries become orphaned but harmless — the frontend's `_initGenPersistence()` validates the stored `lastRepo` against the live catalog before restoring, and unknown repos just fall back to the default-selected model.
- The HF cache (if you ever downloaded `ResembleAI/chatterbox`, `SparkAudio/Spark-TTS-0.5B`, or `coqui/XTTS-v2`) is left on disk. Catalog removal doesn't delete files. You can manually purge them from `cache/HF_HOME/hub/` to reclaim disk space — they'd be wasted otherwise.

---

## [1.3.0] — 2026-05-26

### Added — F5-TTS family wired (Phase 2.2)

User reported all unwired engines they had downloaded — turned out F5-TTS was the only one they actually had cached (`SWivid/F5-TTS`). The other three unwired families (`chatterbox` PyTorch, `spark-tts` PyTorch, `xtts`) had no downloads and are covered by either their MLX siblings (chatterbox-mlx, spark-tts-mlx) or have license restrictions (XTTS). So this release focuses on F5-TTS only.

**What's new:**
- `_have_f5_tts()` import probe (`generation.py:198`) — checks for `f5_tts.api.F5TTS`.
- `_f5_tts_get_model()` — lazy-load + cache an `F5TTS` instance per repo with proper eviction on switch. F5-TTS auto-resolves checkpoint files from `HF_HOME`, so no manual path wiring needed — the user's pre-downloaded `SWivid/F5-TTS` snapshot just works.
- `_generate_f5_tts()` — full voice-cloning worker. Maps existing UI controls onto F5-TTS knobs (`inference_timesteps → nfe_step`, `cfg_value → cfg_strength`, `speed → speed`). Reuses the same voice-library + transcript loading pattern as other clone-capable engines.
- Dispatch in `_dispatch_txt2speech` (`generation.py:780`) replaces the prior `NotImplementedError`.
- `_WIRED_FAMILIES` now includes `f5-tts` — audit_truth.py: **NO DRIFT**, 16 families, 13 wired, 0 commission/omission lies.
- `/api/generate/availability` now reports `f5_tts_available`.

**Frontend:**
- `isF5TTS(repo)` helper in `app.js`.
- F5-TTS folded into `passesLibraryVoice` so the submit payload includes `voice_library_id` + `ref_transcript`.
- `canSubmit` gates the Generate button when F5-TTS is selected without a library voice (engine has no zero-shot mode).
- Dedicated UI block in `index.html` between the chatterbox-mlx/spark-mlx clone section and the spark style hint: voice picker + transcript override field. Voice options show `✓ transcript` / `⚠ no transcript` per entry so users know whether F5-TTS will accept it.
- Speed slider folded in.
- Catalog entry's `use_cases` updated to remove the "worker not yet wired" line and add: "Auto-chunks long text at ~135 chars + 0.15s crossfade — no manual splitting needed."

### New dependency

`requirements-generation.txt` adds:

```
f5-tts>=1.1.0
```

This transitively pulls in `vocos`, `cached_path`, `torchdiffeq`, `x_transformers`, `ema_pytorch`, `librosa`, `pydub`, and a handful of other deps. Most are small. `f5-tts` itself is actively maintained and modern-torch-compatible — no version pin conflicts expected with the existing torch 2.12 + transformers 5.9 + diffusers 0.37 stack.

### How to use

1. **Update from sidebar** → **Stop → Install Generation** (picks up `f5-tts` + transitive deps) → **Start**.
2. The cached `SWivid/F5-TTS` snapshot (already on disk) is auto-found via `HF_HOME` — no re-download needed.
3. In the Generate tab, pick `F5-TTS v1 Base` from the model dropdown.
4. **Mandatory**: pick a voice from the Voices library. F5-TTS has no zero-shot mode — it MUST have a reference clip.
5. **Mandatory**: that voice must have a transcript (either stored in the library OR provided as override in the Reference transcript field). Generation will fail with a clear error if both are missing.
6. Hit Generate. Long text auto-chunks internally at ~135 chars with 0.15s crossfade.

### Coverage update

Catalog: 16 families. Wired: 13 (added f5-tts). Still-unwired NotImplementedError stubs: 3 (`chatterbox` PyTorch, `spark-tts` PyTorch, `xtts`). For the first two, MLX siblings (`chatterbox-mlx`, `spark-tts-mlx`) cover the use case at higher quality-per-byte. XTTS is intentionally not wired — Coqui's `TTS` package pins old torch versions and would break voxcpm/qwen3/etc.

### Notes

- MINOR bump (1.2.8 → 1.3.0) — new engine family + new Python dep, per `README.md` versioning rules. Requires re-running Install Generation.
- F5-TTS `text_guidance.soft_max_chars` stays `null` (unlimited) — engine auto-chunks transparently per the v1.2.4 audit. No change to chip text or UI hint.
- If `Install Generation` fails on `f5-tts` install, log the pip error and we'll add a constraint or git+ install. Most likely cause would be a transitive dep (e.g. `gradio>=6.0.0` if a newer gradio breaks something), but our env doesn't use gradio so it should install side-by-side without issues.

---

## [1.2.8] — 2026-05-26

### Fixed — Spark-TTS dispatch (`ValueError: Model type qwen2 not supported for tts`)

User downloaded `mlx-community/Spark-TTS-0.5B-6bit`, tried to generate, got:

```
ValueError: Model type qwen2 not supported for tts.
ModuleNotFoundError: No module named 'mlx_audio.tts.models.qwen2'
```

Bug was in **our** `_mlx_audio_get_model()`. It called `load_model(str(snapshot_path))` — stringified the Path. mlx-audio's `get_model_name_parts()` behaves differently for `str` vs `Path`:

- **`Path`**: walks `.parts`, finds the `models--mlx-community--Spark-TTS-0.5B-6bit` segment, parses → `["spark", "tts", "0.5b", "6bit", ...]`. Dispatch sees `"spark"` in available models → routes to `mlx_audio.tts.models.spark`. ✅
- **`str`**: just lowercases and takes the last `/` segment. For our cache layout, that's the snapshot hash → `["be15d8bf101a4a400c568b387fb69dce0d37239b"]`. Dispatch falls back to `config.json`'s `model_type`. ❌

Spark-TTS uniquely depends on the name-parts fallback because its `config.json` reports `model_type: "qwen2"` (just the LM backbone — Spark wraps Qwen2.5-0.5B). All other mlx-audio families work because their `config.json` reports a recognized model_type directly (e.g. `voxcpm2`, `qwen3_tts`, `kokoro`).

Fix: **drop the `str()` wrapper** — pass `snapshot_path` directly. One-line change in `generation.py:952`, plus an explanatory comment so this doesn't regress.

Verified empirically by reproducing mlx-audio's `get_model_name_parts()` against the actual cached snapshot path — Path form returns `["spark", "tts", "0.5b", "05b", "6bit", "spark_tts", ...]` and dispatch correctly resolves `model_type="spark"`.

### Affects

All 4 mlx-community Spark-TTS variants in our catalog were broken by this:

- `mlx-community/Spark-TTS-0.5B-4-6bit`
- `mlx-community/Spark-TTS-0.5B-6bit`
- `mlx-community/Spark-TTS-0.5B-8bit`
- `mlx-community/Spark-TTS-0.5B-bf16`

After v1.2.8 + restart, all should dispatch correctly. No re-download needed — the cached snapshots are fine; only the loader was wrong.

### Notes

- PATCH bump (1.2.7 → 1.2.8) — one-line `generation.py` fix + 9-line explanatory comment. No schema, no new deps. Run `Update` → Stop → Start.
- The `str()` wrapper has been there since the initial commit. It went undetected because every other mlx-audio family happens to have a recognized `model_type` in its `config.json`, so the name-parts fallback was never the deciding factor. Spark-TTS is the only one in our catalog that needed it.

---

## [1.2.7] — 2026-05-26

### Fixed — MLX cache leak between sequential mlx-audio jobs (real root cause of the OOM)

Story studio's follow-up test exposed the actual root cause behind the v1.2.6 OOM, not just a "the cap was too high" symptom:

**The data point that broke v1.2.6's assumption:**
- Story studio submitted two sequential requests, both UNDER the v1.2.6 cap of 1500 chars:
  - Job `2181b6a957f1` — 1330 chars → ✅ Done (the 1 WAV the user got)
  - Job `ee3ec2687a51` — 1450 chars → 💀 **Metal OOM mid-gen** (`alloc 11.89 GB > 9.5 GB cap`)
- Same machine, same engine, same precision. The cap should have protected both. It didn't, because the cap isn't what's actually constraining things.

**Root cause: MLX has its own allocation cache that survives across `generate_audio()` calls.** Each sequential VoxCPM2-mlx voice-cloning call stacks fresh activation tensors on top of the previous call's residue. Job 1 leaves ~7 GB of buffers cached; job 2 adds ~5 GB of its own; total exceeds the M4's 9.5 GB per-Metal-buffer cap → process aborts.

**`_release_device_memory()` already existed but didn't help here** — it only cleared PyTorch's MPS cache (`torch.mps.empty_cache()`). MLX's cache is a separate allocator and was never being cleared. And it was only called on *repo switch* (in `_mlx_audio_get_model` when loading a different model), not between successive calls to the same repo.

**The fix (two parts):**

1. **`_release_device_memory()` now also clears MLX's cache.** Best-effort import of `mlx.core` and call `mx.metal.clear_cache()` (or `mx.clear_cache()` for older MLX versions). Silently no-ops if MLX isn't installed. ~10 LOC at `generation.py:514`.

2. **`_generate_mlx_audio()` calls `_release_device_memory("mps")` in its `finally` block** so memory is released after every job, not just on repo switch. The cached `self._mlx_audio_model` stays loaded (model weights aren't the OOM trigger; activation buffers are). Only the per-generation buffers get freed. ~3 LOC at `generation.py:1024`.

### Changed — `voxcpm` + `voxcpm-mlx` soft cap 1500 → 800 (quality cliff, not just memory)

User listened to the 1330-char output that DID succeed and reported the voice **becomes jibberish past ~30 sec of generated audio**. So the practical per-call ceiling isn't the Metal cap — it's voice consistency. ~30 sec audio @ ~13 chars/sec speech ≈ ~400 chars; soft cap set to 800 (~60 sec) as a reasonable upper bound (slight quality degradation but still usable for most content). Users who care about consistency should target ~400-500 chars per chunk.

Updated notes accordingly:

> **Best at ~800 chars (~60 sec audio) per call. Past ~30 sec, voice tends to drift / become jibberish — split into multiple shorter requests.**

Source comments in catalog.py distinguish **engine ceiling** (4096 tokens / 11 min audio per OpenBMB), **hardware ceiling** (Metal per-buffer cap on M4 16 GB), and **quality ceiling** (~30 sec audio empirical from user testing) so future audits don't conflate these three.

### What's still NOT fixed

API callers can still bypass the soft cap (story studio's chunking ignores chip text — it just hits `/api/generate/txt2speech` with whatever it has). The proper structural fix is still the **runtime memory gate**: a per-family `estimate_memory_bytes(input_chars)` that raises `RuntimeError` BEFORE `generate_audio()` even attempts the alloc, so one bad request fails its own job instead of crashing the server. Still flagged as P1 TODO.

The v1.2.7 cache-clearing makes that gate less urgent — sequential calls now start clean. Combined with the lower cap, story studio's chunked workflow should now work end-to-end without crashing. If you hit another OOM, paste the new log line — the math (alloc-bytes-requested vs Metal-cap) will tell us what number to use for the runtime gate.

### Notes

- PATCH bump (1.2.6 → 1.2.7) — adds 2 small code blocks to `generation.py` + catalog cap drop. No new deps, no schema. Run `Update` from the Pinokio sidebar, then Stop → Start (server restart is required to load the new `_release_device_memory` + finally block).
- Other mlx-audio families (kokoro-mlx, chatterbox-mlx, spark-tts-mlx, qwen3-tts, orpheus, kittentts, vibevoice) ALL benefit from the cache-clear since they share `_generate_mlx_audio` — they just weren't triggering the OOM because their activation footprints are smaller. The fix is universal across the family.

---

## [1.2.6] — 2026-05-26

### Fixed — VoxCPM soft cap lowered 3000 → 1500 (Metal OOM on 16 GB Macs)

Story studio hit voicestudio with a 2755-char voice-cloning request on `mlx-community/VoxCPM2-4bit`. The job ran ~3-4 minutes then **crashed the entire server**:

```
[metal::malloc] Attempting to allocate 13133537280 bytes which is greater than
the maximum allowed buffer size of 9534832640 bytes.
Abort trap: 6
```

= 13.1 GB requested vs the M4's ~9.5 GB **per-Metal-buffer cap**. Process aborted instantly; full server crash (not a job failure).

**Root cause of my v1.2.4 miscall**: I bumped `voxcpm` + `voxcpm-mlx` soft caps to 3000 chars based on OpenBMB's documented architecture (`max_tokens=4096` audio tokens @ 6.25 Hz ≈ 11 min audio). But "engine architecture allows it" ≠ "your 16 GB Mac can hold it." VoxCPM is diffusion-based — activation buffers grow linearly with output audio length, and at ~3 minutes of generation the working tensors spike past Metal's per-buffer ceiling. The audit grounded the cap in the engine's spec, but should have grounded it in the *machine's* spec.

**The math from the crash data:**
- 2755 chars triggered 13.13 GB request → exceeds 9.53 GB Metal cap by 38%.
- Ratio of safe (9.53) ÷ requested (13.13) = 0.73.
- 2755 × 0.73 ≈ ~2000 chars as a tight ceiling. With safety margin for other apps: **~1500**.

**Changes:**
- `voxcpm` family `text_guidance.soft_max_chars`: 3000 → **1500**
- `voxcpm-mlx` family `text_guidance.soft_max_chars`: 3000 → **1500**
- Both notes now warn explicitly: *"On 16 GB Macs, longer voice-cloning calls can OOM Metal — split into multiple requests."*
- Source comments above each `TextGuidance` block now distinguish **engine ceiling** (4096 tokens / 11 min) from **hardware ceiling** (~1500 chars on M-series 16 GB).

### What this does NOT yet fix

The fix is preventive — the soft cap blocks the chip text from misleading users. But it's still a *soft* cap. A caller hitting the API directly (e.g., story studio's API integration) can ignore the chip and submit any length. The proper fix is a **runtime memory gate** in `_generate_voxcpm` / `_generate_mlx_audio` that estimates Metal buffer need from input length × engine factor and raises a clear `RuntimeError` BEFORE the alloc attempt — so a single bad request fails its own job instead of crashing the server.

Flagged as TODO. Approach: introduce `MAX_ALLOC_BYTES = 9_500_000_000` (M-series per-buffer Metal cap) and a per-family `estimate_memory_bytes(input_chars)` function. When over the cap, raise before calling `generate_audio()`. Won't ship until we have empirical data on the linear coefficient.

### Notes

- PATCH bump (1.2.5 → 1.2.6) — pure cap correction + note rewrite. No schema, no code path, no new deps. Run `Update` from the Pinokio sidebar, then Stop → Start.
- The other 14 families' caps stay where v1.2.4 set them — they're either far below their hardware ceilings already, or don't have the diffusion-activation-growth profile that triggers this kind of OOM.
- This is the third time this exact Metal OOM has shown up in the project history. v1.2.2 documented it as a workaround note. v1.2.4 inadvertently re-opened it by raising the cap. v1.2.6 closes it for VoxCPM specifically. The right structural fix is the runtime memory gate — file as P1 for next iteration.

---

## [1.2.5] — 2026-05-24

### Fixed — Hint chip text shortened from dev-grade docs to user-friendly one-liners

The v1.2.4 audit landed correct numbers but a side effect was that every `text_guidance.note` ballooned into a multi-sentence source citation (XTTS hit **455 chars**, F5-TTS **421 chars**, Orpheus **431 chars**). Those notes flow straight into the chip above the textarea, so users were seeing a wall of dev-speak instead of a usable hint.

All 16 notes rewritten to **80-121 chars**, action-first. The audit citation moved to a Python comment immediately above each `TextGuidance(...)` block so the source trail stays in `catalog.py` for anyone reading the file.

Before / after example (Bark):

> **Before (361 chars):** Hard cap from upstream. Suno's own FAQ states 'output is limited to ~13-14 seconds' because Bark is GPT-style with a fixed 1024-token semantic/coarse context window. ~150 chars maps to that ceiling at neutral narration pace; past it, output hallucinates or goes silent. Our worker feeds the whole text in one shot, so the cliff is real — split into short lines.
>
> **After (103 chars):** Hard cap ~150 chars (~13 sec). Past the cap, Bark hallucinates or goes silent — split into short lines.

Same information density user actually needs (cap, what happens past it, what to do); citation now lives in a `# Audit (v1.2.4): ...` comment above the block.

### Length stats

| family | new char count |
|---|---:|
| spark-tts / spark-tts-mlx | 81 |
| kokoro / kokoro-mlx | 92 |
| voxcpm / voxcpm-mlx | 96 |
| chatterbox / chatterbox-mlx | 101 |
| bark | 103 |
| kittentts | 105 |
| xtts | 107 |
| orpheus | 108 |
| vibevoice | 113 |
| qwen3-tts | 114 |
| f5-tts | 115 |
| omnivoice | 121 |

Median ~104 chars. No note over 121 chars. The chip block can now fit comfortably in one or two visual lines.

### Notes

- PATCH bump (1.2.4 → 1.2.5) — pure copy edit on `text_guidance.note` fields + comment additions. No schema, no value changes, no new deps. Run `Update` from the Pinokio sidebar, then Stop → Start.
- The Generate-button warning and counter line under the textarea also already auto-pull from `text_guidance` — they update with the new values transparently. No frontend code changes.
- Full audit trail (file paths, line numbers, formulas) is preserved in v1.2.4's CHANGELOG entry above and in `# Audit (v1.2.4):` comments throughout `catalog.py`.

---

## [1.2.4] — 2026-05-24

### Fixed — All 16 family `text_guidance.soft_max_chars` audited against upstream source

Followup to v1.2.3 (where VoxCPM was the only family fixed). The remaining 14 families have now all been verified against either upstream docs, the model card, or — most reliably — the actual code in the installed `mlx-audio`, `transformers`, or `voxcpm` packages. Notes now cite the exact file, line, or constant the cap comes from, so future audits don't have to redo this work.

**Changed values (engine could handle far more than the guess admitted):**

| Family | Old | New | Source |
|---|---:|---:|---|
| `qwen3-tts` | 400 | **3000** | `mlx_audio/tts/models/qwen3_tts/qwen3_tts.py:1149` — `max_tokens=4096` per segment @ 12 Hz token rate ≈ 5.7 min audio. Plus `split_pattern="\n"` for transparent text splitting. |
| `spark-tts` / `spark-tts-mlx` | 400 | **750** | `mlx_audio/tts/models/spark/spark.py:229` — `max_tokens=3000` per call @ BiCodec ~50 Hz ≈ 60 sec audio ≈ ~780 chars in English. |
| `f5-tts` | 400 | **null (unlimited)** | `f5_tts/infer/utils_infer.py` — `chunk_text(max_chars=135)` internally splits any input into 135-char chunks and stitches with 0.15 sec crossfade. The engine handles long-form transparently; soft cap was meaningless. |
| `omnivoice` | 600 | **null (unlimited)** | `mlx_audio/tts/models/omnivoice/omnivoice.py:483` — flow-matching (diffusion), not autoregressive. Takes explicit `duration_s` or estimates from text + ref clip via `RuleDurationEstimator`. No per-call cliff. |

**Guesses that landed correct (kept as-is, only the `note` was updated to cite the source):**

| Family | Cap | Source |
|---|---:|---|
| `bark` | 150 | Suno's official GitHub FAQ: *"output is limited to ~13-14 seconds — Bark is GPT-style with a fixed context window"* + transformers `BarkSemanticConfig.block_size=1024`. |
| `orpheus` | 170 | `mlx_audio/tts/models/llama/llama.py:367, 525` — `max_tokens=1200` per segment. Orpheus emits ~85 SNAC tokens/sec → 1200 tokens ≈ 14 sec audio. |
| `xtts` | 250 | Coqui's `TTS/tts/layers/xtts/tokenizer.py` — `char_limits` dict hardcodes per-language caps. English=250 (exact match). Note now lists all 16 language caps including CJK floor (ja=71). |
| `chatterbox` / `chatterbox-mlx` | 500 | `mlx_audio/tts/models/chatterbox_turbo/chatterbox_turbo.py:859` — `max_chars_per_chunk = (max_tokens // 8) * 4`. Default `max_tokens=1000` → exactly 500 chars per chunk. |

**Kept null/unlimited (engine auto-chunks transparently, soft cap would mislead):**

- `kokoro`, `kokoro-mlx`: KPipeline sentence-chunks via `split_pattern=r"\n+"`. Unchanged from v1.1.8.
- `kittentts`: `mlx_audio/tts/models/kitten_tts/kitten_tts.py:42` — `chunk_text(max_len=400)`. Per-chunk ceiling exists (400 chars) but engine auto-chunks; tiny model makes long-form cheap. Note now cites the source.
- `vibevoice`: `mlx_audio/tts/models/vibevoice/vibevoice.py:397` — `max_tokens=512` per segment (~500 chars / ~43 sec). Streaming architecture multi-segments transparently. Note now warns: if you hit voice drift on very long calls, break manually.

### Side observations (not fixed in this version, flagged for follow-up)

- **OmniVoice voice cloning now works upstream**: `mlx_audio/tts/models/omnivoice/omnivoice.py:483` exposes `ref_audio` + `ref_text` parameters. Our `_generate_omnivoice` worker (added in v1.2.0) raises `NotImplementedError` when `voice_library_id` is set — that error message is stale now that mlx-audio's port supports cloning. Worth wiring up in a future PATCH.
- **mlx-audio's OmniVoice port supersedes the `ailuntx/OmniVoice-MLX` git install**: our `requirements-generation.txt` pulls in `ailuntx/OmniVoice-MLX` as a separate package, but mlx-audio now ships its own port. Consolidating onto mlx-audio's path would remove a dependency. Not urgent — both work.

### Notes

- PATCH bump (1.2.3 → 1.2.4) — pure soft-cap corrections + note enrichment, no code path changes, no new deps. Run `Update` from the Pinokio sidebar, then Stop → Start.
- All notes now reference specific file paths + line numbers so the audit trail is captured in-source.
- `audit_truth.py` still reports **NO DRIFT** — 16 families, 12 wired, 0 commission/omission lies.

---

## [1.2.3] — 2026-05-24

### Fixed — VoxCPM `text_guidance.soft_max_chars` raised from 600 → 3000 (was a guess)

The 600-char soft cap I shipped in v1.1.8 for both `voxcpm` and `voxcpm-mlx` wasn't from any official source — I picked it as a conservative "one paragraph" heuristic. After verifying against upstream:

- **OpenBMB model card** (openbmb/VoxCPM2): documents an 8192-token architecture max and 6.25 Hz LM token rate. No char-level cap published. Only qualitative warning: *"Occasional instability may occur with very long or highly expressive inputs."*
- **`voxcpm` Python package** (PyTorch reference, `core.py:189`): generation defaults to `max_len=4096` audio tokens.
- **`mlx-audio` voxcpm worker** (`mlx_audio/tts/models/voxcpm/voxcpm.py:259`): same `max_tokens=4096` default. Config also exposes `max_length=8192` as the architecture cap.

4096 audio tokens at 6.25 Hz ≈ **655 seconds ≈ 11 minutes of audio per call** — roughly 8,000-10,000 characters of English text. Our 600-char cap was ~7% of what the engine actually supports.

New value: **3000 chars (~3 minutes audio)** for both `voxcpm` and `voxcpm-mlx`. Well under the 4096-token ceiling, but high enough to cover a full audiobook chapter section in one call. The `note` field now cites the official numbers (token rate + architecture max) so future audits don't have to redo this work.

### Notes

- PATCH bump (1.2.2 → 1.2.3) — pure soft-cap correction, no code path changes. Run `Update` from the Pinokio sidebar.
- **The same audit hasn't been done for the other 14 families.** Numbers I cited for Bark (150), Orpheus (170), XTTS (250), F5-TTS (400), Chatterbox (500), Spark-TTS (400), Qwen3-TTS (400), and OmniVoice (600) were also rough heuristics — Bark / Orpheus / XTTS are at least grounded in well-known training-window constraints, but the others deserve the same source-checking pass if you start running into the soft cap on them. Ping me when you do.
- "Unlimited" families (Kokoro, Kokoro-MLX) stay as-is — KPipeline really does sentence-chunk to arbitrary length.

---

## [1.2.2] — 2026-05-24

### Fixed — Phantom `Spark-TTS-0.5B-4bit` catalog entry replaced with real variants

The catalog row for `mlx-community/Spark-TTS-0.5B-4bit` pointed at a HuggingFace repo that **doesn't exist** (the API returns HTTP 401 for that exact name). Anyone who clicked Download on that card would see the request silently fail with no clear error. Verified against the live HF API: the only mlx-community Spark-TTS variants that actually exist are `bf16`, `4-6bit`, `6bit`, and `8bit`.

- **Removed**: `mlx-community/Spark-TTS-0.5B-4bit` (phantom).
- **Added**: `mlx-community/Spark-TTS-0.5B-4-6bit` (mixed quant, ~1.6 GB) — now the recommended starter.
- **Added**: `mlx-community/Spark-TTS-0.5B-6bit` (~1.7 GB).
- **Added**: `mlx-community/Spark-TTS-0.5B-bf16` (~2.3 GB, full precision).
- **Kept**: `mlx-community/Spark-TTS-0.5B-8bit` (~1.7 GB) — was always real.
- Updated sizes are HEAD-request-verified against `model.safetensors`: 4-6bit=0.30 GB · 6bit=0.41 GB · 8bit=0.54 GB · bf16=1.01 GB. Each repo also bundles `wav2vec2-large-xlsr-53` (~1.26 GB) as a reference encoder — that's the bulk of the on-disk size.

### Diagnosed — Server crashes from Metal allocation OOM during VoxCPM2 load

Server crash logged at `logs/api/start.js/latest`:

```
libc++abi: terminating due to uncaught exception of type std::runtime_error:
[metal::malloc] Attempting to allocate 12111175680 bytes which is greater
than the maximum allowed buffer size of 9534832640 bytes.
```

That's ~12 GB requested against the M4's ~9.5 GB Metal buffer limit. Most likely trigger: loading `VoxCPM2-bf16` (4.96 GB on disk → unpacks to ~8-10 GB at runtime) for generation, exceeding the per-buffer cap. The 4-bit variant should stay under the cap.

Not a code change in this version — just documenting the failure mode. **Workaround**: prefer `VoxCPM2-4bit` over `bf16` on 16 GB Macs, or close other RAM-heavy apps before generating. A real fix would need either chunked loading in upstream `mlx-audio` or runtime gating in `generation.py` based on the variant's expected unpacked size — flagged for a future iteration.

### Notes

- PATCH bump (1.2.1 → 1.2.2) — catalog correctness fix, no new deps, no schema changes. Run `Update` from the Pinokio sidebar, then Stop → Start.
- If you already had `mlx-community/Spark-TTS-0.5B-4bit` queued or partially downloaded in localStorage, that entry will simply disappear from the Models tab after Update (nothing to remove from disk since nothing was downloaded).
- The other 3 Spark-TTS variants in the catalog (`8bit`, `6bit`, `4-6bit`, `bf16`) work via the existing `_generate_mlx_audio` dispatch — no new worker code needed.

---

## [1.2.1] — 2026-05-24

### Added — KittenTTS, VibeVoice, and refreshed Chatterbox MLX builds

Three more MLX-native families wired up. All ride the existing `mlx-audio` `load_model` path — no new Python deps, just catalog entries + `MLX_AUDIO_FAMILIES` table rows + frontend voice-picker hints.

- **KittenTTS** (`kittentts` family) — KittenML's ultra-tiny preset-voice TTS, Apache-2.0. Smaller than Kokoro by an order of magnitude. 4 entries: `kitten-tts-mini-0.8-4bit` (recommended, ~70 MB), `kitten-tts-mini-0.8-fp16`, `kitten-tts-micro-0.8-4bit`, `kitten-tts-nano-0.8-fp16` (smallest in the catalog at ~30 MB). 8 preset voices: Bella, Jasper, Luna, Bruno, Rosie, Hugo, Kiki, Leo. **Requires `espeak-ng` on the system** — install with `brew install espeak-ng` if generation fails.
- **VibeVoice Realtime** (`vibevoice` family) — Microsoft's MIT-licensed 0.5B Qwen2.5-based streaming TTS. 3 entries: `VibeVoice-Realtime-0.5B-4bit` (recommended), `-8bit`, `-fp16`. Designed for low-latency / long-form streaming. Preset voice names like `en-Emma_woman`. English-only today.
- **Chatterbox 2026 MLX builds** — added 5 new ModelEntry rows to the existing `chatterbox-mlx` family pointing at the newer mlx-community conversions (Jan 2026, mlx-audio 0.2.7): `chatterbox-4bit` (recommended, smaller than the old build), `chatterbox-8bit`, `chatterbox-fp16` (full precision), `chatterbox-turbo-4bit` (Resemble's faster Turbo variant), `chatterbox-turbo-8bit`. The older `chatterbox-mlx-4bit/8bit` entries are kept — users with those downloads still work.

### Coverage update

`audit_truth.py` reports **NO DRIFT** — catalog now has 16 families, 12 wired (added kittentts + vibevoice to `_WIRED_FAMILIES`). 4 still-roadmap families (`chatterbox`, `f5-tts`, `spark-tts`, `xtts`) remain as PyTorch placeholders that raise `NotImplementedError`.

### Frontend tweaks

- `isKittenTts(repo)` + `isVibeVoice(repo)` helpers added to `app.js`.
- Both folded into `isMlxVoicePicker` (gets the free-form voice text input) and `isMlxAudio` (gets the speed slider).
- Voice-picker placeholder updated to show one example per family; hint text now lists KittenTTS voice names + the espeak-ng caveat, and notes VibeVoice's `lang-name_gender` naming convention.

### Notes

- PATCH bump (1.2.0 → 1.2.1) — pure catalog + wiring additions, no new Python deps, no breaking changes. Run `Update` from the Pinokio sidebar.
- If KittenTTS or VibeVoice fail to import after Update, the `Engines ready` chip in the Models tab will stay grey for those families. Run `Install Generation` to refresh `mlx-audio` to the latest version (some KittenTTS / VibeVoice readers need mlx-audio ≥ 0.2.7).
- Orpheus was checked but skipped — the collection page 404'd and the existing 4-bit / 8-bit / bf16 entries already cover the main precisions. Let me know if you want me to add specific extra variants (5-bit / 6-bit / fp16).

---

## [1.2.0] — 2026-05-24

### Added — OmniVoice (MLX) family

k2-fsa's [OmniVoice](https://github.com/k2-fsa/OmniVoice) — a 0.6B diffusion-language-model TTS with **646-language** support and natural-language voice design — wired up via [ailuntx's experimental MLX port](https://github.com/ailuntx/OmniVoice-MLX). This is the broadest multilingual coverage in the catalog (next nearest is VoxCPM2 at ~30 languages), and one of the few permissively-licensed (Apache-2.0) options for commercial work.

- **4 new catalog entries** (`app/backend/catalog.py`):
  - `mlx-community/OmniVoice-4bit` — 0.5 GB, recommended starter, 8 GB Mac friendly
  - `mlx-community/OmniVoice-8bit` — 0.9 GB, higher-precision quant
  - `mlx-community/OmniVoice-bfloat16` — 1.3 GB, reference quality
  - `mlx-community/OmniVoice-fp32` — 2.4 GB, dense fp32 baseline
- **New `omnivoice` family** in `FAMILIES` with `text_guidance` (auto-split, ~600 chars / ~40s soft cap).
- **`_generate_omnivoice` worker** in `app/backend/generation.py` — uses `from omnivoice.mlx import OmniVoiceMLX`. Hybrid stack: diffusion LM in MLX, Higgs audio tokenizer on PyTorch (both already required by other families). Per-repo model eviction on switch since unified memory can't hold two diffusion-LM TTS instances at once.
- **`omnivoice` added to `_WIRED_FAMILIES`** + `audit_truth.py` reports **NO DRIFT** (14 families, 10 wired, 0 commission/omission lies).
- **`/api/generate/availability` reports `omnivoice_available`** based on a 3-layer import probe (`omnivoice.mlx.OmniVoiceMLX`).
- **Frontend** (`app/frontend/index.html` + `app.js`):
  - New `isOmniVoice(repo)` helper.
  - Dedicated `Voice description (required)` block — same control surface as VoxCPM2 voice-design but with OmniVoice-specific copy + inline non-verbal symbol hints (`[laughter]`, `[cough]`).
  - Speed slider also surfaces (worker accepts `speed`, clamped to 0.5–2.0).
  - `canSubmit` blocks Generate when no voice description is provided.

### Limitations (intentional, will revisit)

- **Voice cloning is not yet wired on the MLX backend.** The official PyTorch API supports `ref_audio` + `ref_text` cloning, but the experimental `OmniVoice-MLX` loader only exposes voice-design (`instruct=...`). Selecting a reference voice from your library with OmniVoice raises a clear `NotImplementedError` pointing at clone-capable alternatives (VoxCPM2, Spark-TTS, Chatterbox). When the upstream MLX loader adds clone support we'll wire it in a PATCH bump.
- **Upstream MLX backend is marked "experimental"** by its author. Quality may vary by language — feedback welcome.
- `omnivoice` does NOT use the `mlx-audio` package shared by the other 6 MLX families; it has its own loader. That's why `_generate_omnivoice` is a separate worker rather than another row in `MLX_AUDIO_FAMILIES`.

### New dependency

`requirements-generation.txt` adds `omnivoice @ git+https://github.com/ailuntx/OmniVoice-MLX.git`. **Run "Install Generation" from the Pinokio sidebar** to pick up the new package, then Stop → Start the server.

### Notes

- MINOR bump (1.1.8 → 1.2.0) — new engine family + new Python dep, per `README.md` versioning rules.
- No breaking changes to existing engines or APIs.
- Soft-cap chars guess of 600 is conservative; tighten or loosen `FAMILIES["omnivoice"].text_guidance` in `catalog.py` if real-world results suggest a different ceiling.

---

## [1.1.8] — 2026-05-24

### Added — Per-family text-length guidance + soft-block on hard-cap engines

Until now the Generate tab gave no signal about how much text each TTS engine could reasonably take. Bark would silently hallucinate past ~13 seconds, Orpheus and XTTS have similar training-window cliffs, and chunked engines (Kokoro, F5, VoxCPM, Chatterbox, Spark, Qwen3) cleanly auto-split — but the UI didn't tell you which was which.

- **New `TextGuidance` field on every `Family`** (`app/backend/catalog.py`) — three fields per engine: `soft_max_chars` (rough character threshold, `None` for engines with no practical cap), `chunking` (`"unlimited"` / `"auto-split"` / `"hard-cap"`), and a one-liner `note`. Surfaced through `serialize_family()` so the frontend can read it via `/api/catalog`. Populated honestly per engine: Kokoro and Kokoro-MLX flagged `unlimited`, Bark (150) / Orpheus (170) / XTTS (250) flagged `hard-cap`, the other 8 families flagged `auto-split` with conservative chunk-size hints.
- **Hint chip above the textarea** — color-coded by chunking: green `∞` for unlimited, blue `✂` for auto-split, amber `⚠` for hard-cap. Surfaces the engine's real constraint before you hit Generate.
- **Model-aware counter under the textarea** — was `420 chars · ~28s of audio`. Now appends `· over recommended 400-char chunk size` (auto-split engines) or `· ⚠ exceeds Suno Bark's 150-char cap` (hard-cap engines) when text crosses the threshold. Counter text turns amber to match.
- **Two-click soft-block for hard-cap engines** — when text exceeds `soft_max_chars` AND the family is `hard-cap`, the Generate button turns amber and the label flips to `⚠ Click again to generate anyway`. Second click submits normally. Editing the text or switching models resets the confirmation. Auto-split and unlimited engines never block — hint only.

### Added — Per-model preset persistence

Voice / speed / seed / cfg knobs now persist across restarts, keyed by repo so each model remembers its own settings. Same localStorage pattern as the existing Models-tab filter prefs.

- **Two new localStorage keys** (`app/frontend/app.js`): `voicestudio.gen.presets` is `{ [repo]: { field: value, ... } }`, `voicestudio.gen.lastRepo` is the last-active repo. Restored after `refreshCatalog()` + `refreshGenAvailability()` + `refreshVoices()` so option lists are populated when fields hydrate.
- **Allowlist of 13 fields** persisted per repo: `voice`, `preset_speaker`, `bark_voice_preset`, `voice_library_id`, `speed`, `seed`, `batchCount`, `cfg_value`, `inference_timesteps`, `normalize_text`, `instruct`, `voice_design_prompt`, `ref_transcript`. Transient session state (`jobs`, `submitting`, `currentJob`, `text`, `overCapConfirmed`) is intentionally excluded.
- **Watchers re-save on any field change.** `$watch("gen.repo")` additionally pulls in the new repo's preset *after* `onModelChange()`'s default-snap runs — `$watch` fires on the microtask after the synchronous `@change` handler, so snap → restore order is correct.
- **Last-repo restore is validated**: if the stored `lastRepo` references a model you've since uninstalled, restore quietly skips and falls back to the default-selected model.
- Stale presets for uninstalled models stay in localStorage harmlessly; if you reinstall later, the old settings come back.

### Notes

- PATCH bump — pure UX additions, no breaking changes, no new Python deps. Run `Update` from the Pinokio sidebar.
- The text in the textarea is intentionally **not** persisted — that's a different feature (would balloon storage on long inputs and stale content from yesterday rarely matches today's intent).
- Soft-block character thresholds (`soft_max_chars`) are conservative best-effort values pulled from each engine's training-window or upstream docs. If real-world experience says a number's too tight or too loose, edit `FAMILIES["…"].text_guidance` in `catalog.py`.

---

## [1.1.7] — 2026-05-24

### Fixed — Cancelled queued jobs no longer pop back to "queued" in the UI

Follow-up to v1.1.6. Same race + same fix as ImageStudio v1.3.2. The worker entry (`_run_txt2speech`) had a redundant `job.state = "queued"` BEFORE `with _GEN_LOCK:`. If the user clicked Cancel between `submit_job()` returning and the worker thread actually being scheduled, the worker would re-assert `state="queued"` and clobber the cancel decision. The `cancel_event` flag survived, so the worker eventually settled `state="cancelled"` once it acquired the lock — but by then the previous synthesis had finished and minutes had passed, during which the cancelled card was visibly stuck in the queue UI.

Removed the redundant assignment. The dataclass default already initializes `state="queued"`, so it was dead code — except in the cancel-race window where it was actively destructive.

### Notes

- PATCH bump — UX bugfix, no schema or dependency changes. Run `Update` from the Pinokio sidebar.

---

## [1.1.6] — 2026-05-24

### Fixed — Cancel button works for queued jobs (and explains itself for running jobs)

Mirrored from ImageStudio v1.3.1 (per the "apply UX wins to all 3 apps" rule). VoiceStudio had the same latent bug: `manager.cancel()` only set `cancel_event`, so queued jobs blocked on `_GEN_LOCK` couldn't react until the running synthesis finished. Clicking ✕ Cancel on a queued job appeared to do nothing.

- **Backend (`generation.py`):** `manager.cancel()` immediately flips queued jobs to `state="cancelled"` + `finished_at` + persists. Worker still safely no-ops when it later wakes up and sees `cancel_event.is_set()`.
- **Frontend (`app.js`):** `cancelPending()` toasts differently depending on state:
  - **Queued** → "✓ Cancelled — Queued job removed." (instant)
  - **Running** → "⏸ Cancel signal sent" + honest about why: mlx-audio TTS engines (Kokoro, VoxCPM, Chatterbox, Orpheus, Spark, Qwen3-TTS) are blocking synthesis calls that don't honor mid-flight cancellation. The result gets discarded after synthesis finishes.

### Notes

- PATCH bump — UX bugfix, no schema or dependency changes. Run `Update` from the Pinokio sidebar.

---

## [1.1.5] — 2026-05-24

### Changed — MLX-only filter ON by default + persistent preferences

Same change as ImageStudio v1.2.2. Models tab opens with `🍎 Apple Silicon (MLX) only` pre-toggled, hiding the 9 non-MLX entries (PyTorch Kokoro / VoxCPM v1 / Bark + 4 PyTorch roadmap engines + VoxCPM v2). On your M4 this turns 25 cards → 16 cards on first load.

User's MLX + Fits-my-Mac choices persist via localStorage (`voicestudio.modelFilters.*` keys).

### Notes

- Non-destructive — catalog unchanged. Untoggle MLX-only to see everything (PyTorch Bark's tag system, VoxCPM v1's voice cloning, etc).
- PATCH bump — `Update` from Pinokio.

---

## [1.1.4] — 2026-05-24

### Added — `audit_truth.py` script

Mirrors the v1.2.1 ImageStudio tool. AST-parses `catalog.py` + `generation.py` to detect drift between `_WIRED_FAMILIES` and actual dispatch coverage. Handles the VoiceStudio-specific `MLX_AUDIO_FAMILIES` config-table pattern (where 6 families share one `_generate_mlx_audio` worker).

```
python3 audit_truth.py            # human report
python3 audit_truth.py --strict   # exit non-zero on drift
```

Result: `✓ NO DRIFT` — all 9 wired families (kokoro, voxcpm, bark + 6 mlx-audio: qwen3-tts, voxcpm-mlx, kokoro-mlx, chatterbox-mlx, spark-tts-mlx, orpheus) verified against actual dispatch.

Documented in README "Truth audit (for contributors)" section.

### Notes

- PATCH bump — pure dev tooling, no runtime change.

---

## [1.1.3] — 2026-05-24

Mirrors v1.1.2 + v1.1.3 UX wins from ImageStudio (per the "apply UX wins across all 3 apps" rule).

### Added — collapse-by-default model cards (was v1.1.2 in ImageStudio)

- **Compact model cards** — cards default to showing only label + chips + repo + size + hardware + capabilities. The `best_for` line, use-case bullets, and "Saved at" path are hidden behind a per-card `▾ Show details` toggle. With 25 models in the catalog this turns the Models tab from a wall of text into a scannable gallery.
- **Bulk expand/collapse** — `▾ Expand all` / `▴ Collapse all` toolbar buttons operate on the currently-filtered list.
- **MLX-only filter chip** — `🍎 Apple Silicon (MLX) only` toggle. On VoiceStudio this filters 25 → 16 (cuts the 4 PyTorch-only roadmap engines + PyTorch Kokoro/VoxCPM v1/Bark).
- **Fits my Mac filter chip** — `🖥 Fits my Mac (16 GB)` toggle. Hides only "risky" models; "tight" still shows since they might be acceptable with apps closed.

### Added — filter feedback clarity (was v1.1.3 in ImageStudio)

- **Active chips now announce themselves**: 2px bold border, 45% saturated background, white text, and a ✓ prefix so toggled-on chips are unmistakable.
- **Smart empty state**: when filters yield 0 results, you see a list of every active filter as red ✕ chips — click one to remove just that filter instead of nuking everything.

### Notes

- PATCH bump — pure UX additions, no breaking changes, no new Python deps.
- Just run `Update` from the Pinokio sidebar; no re-install needed.

---

## [1.1.1] — 2026-05-24

### Added

- **Sidebar port display + external-browser escape hatch.** The Pinokio sidebar now shows a `Port 47870 · Open in Browser` item whenever the server is running. Two benefits:
  - **Visibility**: the port number is always readable in the sidebar — if the embedded webview ever caches a black screen, you can read the port and type `localhost:47870` into Chrome / Safari instead of being stranded.
  - **One-click escape**: clicking the item opens the WebUI in your system default browser via `web.open` with `target="_blank"`.

### Why

The embedded webview occasionally caches a broken state across restarts. Hard-refresh inside the webview doesn't always help, and without knowing the port the user has no way out.

### Files

- New: `open_external.js` (5-line wrapper around `web.open`)
- Modified: `pinokio.js` adds the port display + escape-hatch item to the `running.start` menu branch

### Notes

- PATCH bump — pure UX addition, no breaking changes, no new Python deps.
- Just run `Update` from the Pinokio sidebar; no re-install needed.

---

## [1.1.0] — 2026-05-24

### Added

- **Hardware fit detection** per model card. Detects your Mac's chip + unified memory via sysctl and shows a color-coded chip on each model:
  - 🟢 **fits** — your RAM ≥ 1.5× the model's floor (plenty of headroom)
  - 🟡 **tight** — meets the floor but close other apps before generating
  - 🔴 **may not fit** — below the floor, will swap or OOM
- **"Your Mac" banner** at the top of the Models tab showing detected chip + RAM, so the per-card fit chips have a clear anchor.
- **Structured use cases** per model — all 25 entries populated with ✅ "good at" / ⚠️ "weak at" / ❌ "avoid" bullets. Highlights TTS-specific gotchas honestly:
  - VoxCPM v1 **requires** a reference transcript for cloning (empty transcript will error)
  - Kokoro is **English-only** and **can't clone** — uses fixed voicepacks
  - Bark is **slow** (30-60 sec per clip) and **inconsistent** — not for long-form
  - Chatterbox-MLX exaggeration > 0.7 gets unstable
  - 4-bit MLX quants can fumble on rare-word pronunciation
  - Orpheus has 8 preset voices (tara/dan/leah/+5) and inline emotion tags
- **`/api/system`** endpoint exposing the chip + RAM snapshot.
- **`fit` field** in `/api/catalog` per model — `{state, label, hint, actual_gb, required_gb}`.

### Notes

- No new Python dependencies — `system_info.py` uses stdlib `subprocess` + macOS's built-in `sysctl`.
- Mirrors the same Tier 1 hardware-fit pattern shipped in ImageStudio v1.1.0.
- Just run `Update` from the Pinokio sidebar; no re-install needed.

---

## [1.0.0] — 2026-05-24

First versioned release. Covers all work from the initial scaffold through Phase D (mlx-community catalog expansion).

### Engines wired (9 families)

PyTorch-based:

- **Kokoro v1.0** (82M) — tiny + real-time English TTS, 28 preset voicepacks, MIT
- **VoxCPM v1 / v2** — OpenBMB's multilingual TTS with voice cloning + emotion control
- **Suno Bark (full + small)** — expressive TTS with `[laughter]` / `[singing]` / `[MUSIC]` tags

MLX-native (via `mlx-audio`):

- **Qwen3-TTS** — Alibaba's TTS in 3 modes: CustomVoice (preset speakers), VoiceDesign (natural-language voice prompt), Base (voice cloning)
- **VoxCPM2 (MLX)** — 4-bit / 8-bit / bf16 variants, 30-language, 48 kHz studio quality
- **Kokoro (MLX)** — same Kokoro at lower memory footprint, no PyTorch needed
- **Chatterbox (MLX)** — Resemble AI's voice cloning with exaggeration/intensity dial
- **Spark-TTS (MLX)** — SparkAudio's zero-shot cloning + natural-language style control
- **Orpheus (MLX)** — Canopy Labs' 3B LLaMA-arch TTS with `<laugh>` / `<sigh>` inline tags

### Roadmap engines (catalog-only, worker not yet wired)

F5-TTS, original PyTorch Chatterbox, original PyTorch Spark-TTS, Coqui XTTS-v2

### Architecture

- **Generalized mlx-audio worker** — one `_generate_mlx_audio` function handles all 6 mlx-audio families via per-family mode resolvers + the `MLX_AUDIO_FAMILIES` config table. Adding a new mlx-audio model is now: 1 catalog entry + (sometimes) 1 config row, no new worker code.
- **3-state diagnostic system** — every engine reports `deps_ok` (packages importable) + `wired` (worker exists) + `ready` (both). UI shows which engines need install vs which are roadmap.
- **Per-engine memory management** — each worker owns a model cache that evicts on repo switch to fit Apple Silicon unified memory.
- **`/api/diagnostics`** endpoint surfaces package health + engine status to the frontend.

### Voice library

- Upload, browser-record (24 kHz mono WAV via MediaRecorder + AudioContext), or import from a seed catalog (public-domain LibriVox)
- Per-voice transcript (recommended for VoxCPM v1, optional for others)
- Engine-agnostic — same voice works with any cloning-capable family

### Generate UX

- **Queue panel** — pending + running jobs visible with per-row cancel buttons
- **Batch counter** — submit N sequential generations with auto-incrementing seeds
- **History pagination** — per-row metadata (model, voice, duration), 12 per page
- **Library filters** — search + family chips + status chips + capability chips + sort
- **Bark tag chips** — click to insert `[laughter]` / `[singing]` / `♪ ♪` at cursor
- **Per-engine controls** — engines surface only the knobs they support; defaults snap to each family's sweet spot on model switch
- **Slider + number input pairs** — type 0.93 or drag, both work

### Frontend

- Alpine.js SPA (no build step), Alpine loaded locally
- Sticky topbar (z-index 20) + sticky library toolbar (`top: var(--topbar-height)`)
- Live JS toast system + SSE job stream (`/api/generate/jobs/<id>/stream`)
- NoCacheStaticMiddleware to prevent webview from holding old HTML

### Backend

- FastAPI + uvicorn, port 47870
- `_GEN_LOCK` serializes GPU-bound generations
- Job history persisted to `app/output/.history.json` (survives restarts)
- HF cache structure detection + flat-folder import (for legacy launcher imports)

---

## Format reference

```
## [X.Y.Z] — YYYY-MM-DD

### Added
- New engines / models / UI features

### Changed
- Behavior changes to existing features

### Fixed
- Bug fixes

### Removed
- Dropped engines / deprecated UI

### Notes
- Migration steps, breaking-change details, etc.
```

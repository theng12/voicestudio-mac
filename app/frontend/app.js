/* global Alpine */

function studio() {
  return {
    // ──────── state ────────
    tab: "generate",
    // Models tab sub-view: TTS catalog, transcription, or managed disk inventory.
    modelsSubtab: "generator",
    health: { ok: false },
    showWhatsNew: false,
    releaseNotesCurrent: "",
    releaseNotes: [],
    // Hardware snapshot from /api/system — populated once on init().
    // Used by the Models tab to render per-card fit chips comparing each
    // model's memory floor against the user's actual RAM.
    system: { chip: null, chip_tier: null, unified_memory_gb: null },
    // ──────── RAM slider (Models tab hardware planner) ────────
    // `ramGb` is the effective unified-memory budget used to score every
    // model's fit chip LIVE on the client (no /api round-trip). It defaults
    // to the detected RAM but the user can drag/type it to preview a
    // different machine — e.g. plan which models a future 512 GB Mac could
    // run before buying it. Seeded in _initRamPlanner() after /api/system.
    ramGb: null,
    ramIsDetected: true,          // false once the user overrides the slider
    ramTiers: [8, 16, 24, 32, 48, 64, 128, 256, 512],
    families: {},
    models: [],
    jobs: [],
    candidates: [],
    modelStorage: {
      loading: false,
      error: "",
      cache_root: "",
      notice_path: "",
      summary: { families: 0, packages: 0, models: 0, dependencies: 0, legacy: 0, unknown: 0, bytes_total: 0 },
      groups: [],
    },
    pendingDownload: null,
    confirmDialog: null,           // in-app confirm modal (webview-safe replacement for confirm())
    downloadToken: "",
    importForm: { source_path: "", repo: "" },
    importMessage: "",
    importMessageKind: "error",   // "success" | "error" — drives styling of the inline message
    importResult: null,            // last successful result, kept on screen with target path until next submit
    _streamHandle: null,
    _genStreamHandle: null,
    _refreshHandle: null,
    _tickHandle: null,
    // True once the user (or a successful persistence restore) has set gen.repo.
    // While true, _reconcileSelectedModel() refuses to override gen.repo unless
    // the chosen model is truly gone from generationModels — protects against
    // transient catalog-refresh races resetting the user's choice to the first
    // compatible model every 4 seconds (the bug fixed in phase2-repo-persist-1).
    _repoUserConfirmed: false,
    _lastRandomPromptIndex: -1,
    _nowSec: Math.floor(Date.now() / 1000),   // reactive "now" for live duration display

    // ──────── generate sub-state (TTS) ────────
    gen: {
      available: false,            // backend reports torch/transformers OK
      kokoro_available: false,     // kokoro package importable
      qwen3_available: false,      // mlx-audio importable
      diffusers_available: false,  // for Phase 2.1+ engines
      error: null,
      device: null,                // "mps" | "cuda" | "cpu"
      kokoro_voices: [],           // [{id, label, lang, gender}, ...]
      qwen3_preset_speakers: [],   // [{id, lang, gender, description}, ...]
      voxtral_voices: [],          // [{id, lang, gender, label}, ...]
      marvis_voices: [],           // [{id, lang, gender, label}, ...]
      orpheus_voices: [],          // [{id, lang, gender, label}, ...]
      vibevoice_voices: [],        // exact checkpoint roster; experimental entries are labelled
      qwen3_voice_design_examples: [],  // [string, ...]
      lang_names: {},
      wired_families: [],
      mode: "txt2speech",
      repo: "",
      text: "",
      // Kokoro
      voice: "af_bella",
      kokoro_blend_voice: "",
      kokoro_language: "a",
      language: "",
      speed: 1.0,
      temperature: 0.8,
      seed: -1,
      // Long-form delivery is catalog-gated. Auto leaves the audited model
      // policy in charge; Custom sends a verified section-size override.
      section_size_mode: "auto",
      section_max_characters: 280,
      // Qwen3-TTS — CustomVoice
      preset_speaker: "Ryan",
      instruct: "",
      // Qwen3-TTS — VoiceDesign
      voice_design_prompt: "",
      // Voice cloning (Qwen3 Base + future engines)
      voice_library_id: "",
      ref_transcript: "",
      // VoxCPM
      voxcpm_available: false,
      voxcpm_emotion_examples: [],
      cfg_value: 2.0,
      inference_timesteps: 7,
      normalize_text: false,
      voxcpm_warmup_patches: 0,
      voxcpm_max_tokens: 2000,
      chatterbox_cfg_weight: 0.5,
      chatterbox_repetition_penalty: 1.2,
      chatterbox_min_p: 0.05,
      chatterbox_top_p: 1.0,
      // Bark
      bark_available: false,
      bark_voice_preset: "v2/en_speaker_6",
      bark_temperature: 0.7,
      bark_max_coarse_history: 60,
      bark_sliding_window_len: 60,
      bark_allow_early_stop: true,
      bark_voice_presets: [],     // populated from /api/generate/availability
      bark_tags: [],              // populated from /api/generate/availability
      // OmniVoice (MLX voice design + cloning)
      omnivoice_available: false,
      omnivoice_num_steps: 32,
      omnivoice_guidance_scale: 2.0,
      omnivoice_duration_s: null,
      // Fish Audio S2 Pro (MLX)
      fish_temperature: 0.7,
      fish_top_p: 0.7,
      fish_top_k: 30,
      fish_max_tokens: 1024,
      // Audio8 TTS Preview (MLX / arktts)
      audio8_temperature: 0.7,
      audio8_top_p: 0.9,
      audio8_top_k: 50,
      audio8_max_tokens: 512,
      // MOSS-TTS-Nano (MLX)
      moss_temperature: 0.8,
      moss_top_p: 0.95,
      moss_top_k: 25,
      moss_repetition_penalty: 1.2,
      // Echo-TTS (MLX diffusion) — only real SamplerConfig fields; the engine
      // silently drops anything else (including temperature and speed).
      echo_num_steps: 40,
      echo_cfg_scale_text: 3.0,
      echo_cfg_scale_speaker: 8.0,
      // F5-TTS (SWivid flow-matching, voice-cloning only — no zero-shot mode)
      f5_tts_available: false,
      // Batch / queue — Level 2 of the queue UX. Pinning a seed makes each
      // batch job get seed, seed+1, seed+2... (reproducible variations);
      // a random seed (-1) gives each its own fresh random.
      batchCount: 1,
      submitting: false,
      clearArmed: false,           // two-click confirm for "Clear history" (webview-safe)
      deleteArmed: null,           // job.id currently armed for a two-click single delete
      pruneArmed: null,            // prune mode currently armed for a two-click confirm
      autoPlay: false,             // auto-play the newest result when a generation finishes
      jobs: [],
      currentJob: null,
      // Two-click confirm for hard-cap engines (Bark / Orpheus / XTTS) when
      // the user exceeds the family's soft_max_chars. Reset whenever the
      // user edits the text or switches models — see safeSubmit().
      overCapConfirmed: false,
    },

    // ──────── Subtitles / transcription ────────
    stt: {
      available: null,        // null=unknown, true/false after refreshTranscribe
      models: [],             // [{repo,label,size_gb,note,recommended,cached}]
      model: "",              // selected transcription repo
      language: "en",
      wordTimestamps: false,
      file: null,             // File object
      fileName: "",
      fileSize: "",
      dragOver: false,
      downloading: false,
      running: false,
      elapsed: 0,
      error: "",
      result: null,           // { text, language, duration, model, segments, srt, vtt, elapsed_seconds }
      view: "text",           // text | srt | vtt
      _elapsedHandle: null,
      _blobUrl: null,
    },

    // ──────── Generation-history pagination ────────
    historyPage: 0,
    historyPageSize: 10,

    // ──────── Models-tab library filters ────────
    // All filtering is client-side over `this.models` — no backend changes.
    // Empty Set = "no filter applied for this dimension" (i.e. show all).
    modelFilters: {
      search: "",
      families: new Set(),         // family ids (e.g. "kokoro")
      statuses: new Set(),         // "cached" | "partial" | "absent" | "engine-ready"
      capabilities: new Set(),     // "tts", "voice-cloning", etc.
      // v1.1.2 — quick filter chips
      mlxOnly: false,              // hide non-MLX entries
      fitsMyMac: false,            // hide entries where fit.state === 'risky'
      // v1.7 — segmented RAM-fit filter, scored against the RAM slider:
      // "all" | "ok" (green) | "tight" (yellow) | "over" (red)
      fitLevel: "all",
      sortBy: "default",           // "default" | "name" | "size-asc" | "size-desc"
      advancedOpen: false,
      openFamilies: new Set(),
      // Per-repo "show full details" toggle. Cards default to compact —
      // use_cases + best_for + saved-loc are hidden until the user expands.
      expandedRepos: new Set(),
    },

    // ──────── voice library (Phase A) ────────
    voices: [],
    voiceUploader: {
      open: false,
      uploading: false,
      transcribing: false,
      error: "",
      // audio source mode: 'upload' | 'paste' | 'record'
      source: "upload",
      // file selection (shared across all 3 sources)
      audioBlob: null,            // File or Blob, ready to upload
      audioFilename: "",          // display name
      audioSizeBytes: 0,
      audioPreviewUrl: "",        // object URL for the <audio> preview
      dragOver: false,
      // recording sub-state
      recordPhase: "idle",        // 'idle' | 'requesting' | 'countdown' | 'recording' | 'preview' | 'error'
      recordCountdown: 0,
      recordElapsed: 0,
      recordLevel: 0,             // 0-1 instantaneous mic level for VU meter
      recordError: "",
      recordMaxSeconds: 15,
      // form fields
      name: "",
      language: "en",
      gender: "f",
      license: "self-owned",
      source_url: "",
      notes: "",
      transcript: "",
      permission_acknowledged: false,
    },

    // Edit-existing-voice modal (separate from upload — no audio change). Used
    // most commonly to add a transcript to a clip that was uploaded without
    // one, so it works with F5-TTS (which requires a transcript).
    voiceEditor: {
      open: false,
      saving: false,
      error: "",
      voice: null,        // the Voice being edited (read-only reference)
      // editable fields — pre-populated from voice on open
      name: "",
      language: "en",
      gender: "f",
      license: "self-owned",
      notes: "",
      transcript: "",
    },

    // Internal recording handles — kept off voiceUploader to avoid Alpine
    // reactivity churn on every audio sample.
    _rec_stream: null,
    _rec_mediaRecorder: null,
    _rec_chunks: [],
    _rec_audioContext: null,
    _rec_analyser: null,
    _rec_levelTimer: null,
    _rec_elapsedTimer: null,
    _rec_countdownTimer: null,
    _rec_startTime: 0,

    // Seed catalog (public-domain voices)
    seedCatalog: [],
    seedCatalogOpen: false,
    seedCatalogLoading: false,
    seedCatalogAddingId: null,

    // ──────── diagnostics (dependency checklist) ────────
    diag: {
      device: null,
      packages: [],
      engines: [],
      any_missing: false,
      ready_count: 0,
      total_engines: 0,
      _lastFetched: 0,
    },

    // Toast notifications (auto-dismiss after 5s)
    toasts: [],
    _toastSeq: 0,
    _jobStatePrev: {},   // map jobId → previous state, used to detect transitions for toasts

    // ──────── settings ────────
    settings: {
      hf_token_set: false,
      hf_token_masked: "",
      tokenInput: "",
      showToken: false,
      busy: false,
      message: "",
      messageKind: "info",   // "success" | "error" | "info"
    },
    autoUpdate: {
      loaded: false,
      busy: false,
      message: "",
      messageKind: "info",
      state: "idle",
      installed_version: "",
      latest_version: null,
      last_checked: null,
      next_check: null,
      last_update_result: null,
      defer_reason: null,
      rollback: null,
      details: [],
      update_available: false,
      scheduler: { installed: false },
      release_notes_url: "",
      settings: { mode: "off", frequency: "daily", maintenance_hour: 2, idle_only: true },
      draft: { mode: "off", frequency: "daily", maintenance_hour: 2, idle_only: true },
      dirty: false,
    },
    memoryPolicy: {
      mode: "performance", default_mode: "performance", idle_seconds: null,
      loaded_models: [], model_idle_seconds: null, next_release_at: null,
      last_release_at: null, last_release_reason: null, release_count: 0,
      // A release count is only readable next to the process start it was
      // counted from — a restart zeroes the counter while job history survives.
      counters_since: null, process: { started_at: null, uptime_seconds: null },
      process_title: "Voice Studio Mac", process_title_applied: false,
      loaded: false, busy: false, message: "", messageKind: "info",
      draft: { mode: "performance" }, dirty: false,
    },

    // ──────── network/connectivity (where the API can be reached) ────────
    conn: {
      listen_port: null,
      bind_port: 47870,        // the true uvicorn --port from start.js;
                                // refreshed from /api/connectivity on load
      bind_host: "0.0.0.0",
      request_port: null,
      scheme: "http",
      client_url: "",
      addresses: [],
      share_local_enabled: false,
      share_local_port_fixed: null,
      share_passcode_set: false,
      pinokio_ui_port: 42000,
    },

    // ──────── lifecycle ────────
    /** Measure the actual height of .topbar and expose it as a CSS variable
     *  so sticky elements below (e.g. .library-toolbar) can offset themselves
     *  correctly even when the topbar wraps to multiple rows on narrow widths. */
    _syncTopbarHeight() {
      const el = document.querySelector('.topbar');
      if (!el) return;
      const h = Math.ceil(el.getBoundingClientRect().height);
      document.documentElement.style.setProperty('--topbar-height', h + 'px');
    },

        async init() {
      await this.refreshReleaseNotes();
      await this.refreshHealth();
      await this.refreshSystem();
      // Seed the RAM-slider budget from detected RAM (or a saved override)
      // now that /api/system has populated `system`.
      this._initRamPlanner();
      this._syncTopbarHeight();
      window.addEventListener('resize', () => this._syncTopbarHeight());
      // Also re-measure on next animation frame in case fonts/layout settle late.
      requestAnimationFrame(() => this._syncTopbarHeight());
      await this.refreshCatalog();
      await this.refreshModelStorage();
      // After catalog loads we know whether MLX models exist — set the MLX-only
      // filter default based on that (and respect any user-saved preference).
      this._initFilterPreferences();
      this._initFamilyLibrary();
      await this.refreshGenAvailability();
      // Deep engine diagnostics intentionally import every model stack. Let
      // the core UI finish loading first, then validate those packages in the
      // background so a restart never leaves the interface waiting on PyTorch.
      setTimeout(() => this.refreshDiagnostics(), 750);
      await this.refreshSettings();
      await this.refreshVoices();
      // Transcription availability — so the Models tab's model section is
      // populated regardless of which tab the user opens first.
      this.refreshTranscribe();
      // Restore last-used model + per-repo gen settings AFTER catalog +
      // availability + voices are loaded so option lists are populated.
      this._initGenPersistence();
      this.startJobStream();
      this.startGenStream();
      this.refreshOutputStats();
      this.refreshStoragePolicy();
      // The catalog needs to reflect cache state changes during downloads,
      // so we re-poll it on a slower cadence than the per-job stream.
      this._refreshHandle = setInterval(() => this.refreshCatalog(), 4000);
      // 1Hz tick so live elapsed-time displays update without per-component timers.
      this._tickHandle = setInterval(() => { this._nowSec = Math.floor(Date.now() / 1000); }, 1000);
      this._autoUpdateHandle = setInterval(() => {
        if (this.tab === "settings" || ["checking", "updating", "restarting", "deferred"].includes(this.autoUpdate.state)) {
          this.refreshAutoUpdate(true);
        }
        if (this.tab === "settings") this.refreshMemoryPolicy(true);
      }, 5000);
      // Route via hash so the sidebar buttons in pinokio.js can deep-link.
      const applyHash = () => {
        const h = (location.hash || "").replace(/^#\/?/, "");
        if (["generate", "models", "downloads", "imports", "voices", "subtitles", "api", "settings"].includes(h)) this.tab = h;
        if (h === "imports") this.scanImports();
        if (h === "settings") this.refreshSettings();
        if (h === "subtitles") this.refreshTranscribe();
      };
      window.addEventListener("hashchange", applyHash);
      applyHash();

      // ── Keyboard shortcuts ──
      // Cmd/Ctrl+Enter from anywhere on the Generate tab submits.
      // (The textarea already has its own @keydown.cmd.enter; this global
      // handler covers focus on other controls.)
      document.addEventListener("keydown", (e) => {
        const isMeta = e.metaKey || e.ctrlKey;
        if (isMeta && e.key === "Enter" && this.tab === "generate") {
          e.preventDefault();
          this.safeSubmit();
        } else if (e.key === "Escape") {
          if (this.showWhatsNew) this.showWhatsNew = false;
          else if (this.pendingDownload) this.pendingDownload = null;
        }
      });

      // Drop the hard-cap confirmation any time the user changes the text or
      // switches models — re-cross over the cap should require a fresh ack.
      this.$watch("gen.text", () => { this.gen.overCapConfirmed = false; });
      this.$watch("gen.repo", () => { this.gen.overCapConfirmed = false; });

      // ── Clipboard paste → voice upload audio (only when voice modal is open) ──
      document.addEventListener("paste", (e) => {
        if (!this.voiceUploader.open) return;
        const items = e.clipboardData?.items || [];
        for (const it of items) {
          if (it.kind === "file" && it.type.startsWith("audio/")) {
            const blob = it.getAsFile();
            if (blob) {
              e.preventDefault();
              this._acceptVoiceFile(blob);
              return;
            }
          }
        }
      });
    },

    // ─── RAM slider + client-side hardware fit ────────────────────────
    /** Effective RAM budget (GB) used for fit scoring: the slider value,
     *  falling back to detected RAM, then a neutral 16 GB if nothing's known. */
    get effectiveRam() {
      return this.ramGb || this.system.unified_memory_gb || 16;
    },
    /** Count of downloaded transcription models — drives the
     *  Audio Transcriber sub-tab's "ready" badge. */
    get sttReadyCount() {
      return (this.stt?.models || []).filter(m => m.cached).length;
    },
    /** Client-side fit verdict for a model's memory floor vs effectiveRam.
     *  Mirrors backend system_info.fit_for() (1.5× = comfortable, 1.0× =
     *  tight, below = over budget) so the RAM slider re-scores every card
     *  instantly without hitting the server. Returns the same shape the
     *  backend `fit` field used, so fitChipLabel() works unchanged. */
    fitFor(minGb) {
      const actual = this.effectiveRam;
      const floor = Number(minGb);
      if (!Number.isFinite(floor) || floor <= 0) {
        return {
          state: "unqualified",
          actual_gb: actual,
          required_gb: null,
          hint: "No unified-memory floor is published until controlled qualification completes.",
        };
      }
      const headroom = actual / floor;
      let state;
      if (headroom >= 1.5)      state = "ok";
      else if (headroom >= 1.0) state = "tight";
      else                      state = "risky";
      const hint = headroom >= 1.5
        ? `${actual} GB is ≥1.5× this model's ${minGb} GB floor — comfortable headroom.`
        : headroom >= 1.0
          ? `${actual} GB just clears the ${minGb} GB floor — close other apps before loading.`
          : `${actual} GB is below the ${minGb} GB floor — it would swap heavily or fail to load.`;
      return { state, actual_gb: actual, required_gb: Number(minGb) || 0, hint };
    },
    /** Set the RAM-slider budget (clamped + rounded). Persisted so the
     *  preview survives reloads. */
    setRam(gb) {
      const v = Math.max(1, Math.min(1024, Math.round(Number(gb) || 0)));
      this.ramGb = v;
      this.ramIsDetected = (v === this.system.unified_memory_gb);
      this._persistFilterPref("ramGb", v);
    },
    /** Seed the RAM slider from a saved override or the detected RAM. Called
     *  from init() after /api/system has populated `system`. */
    _initRamPlanner() {
      try {
        const saved = localStorage.getItem("voicestudio.modelFilters.ramGb");
        if (saved !== null && !isNaN(+saved)) {
          this.ramGb = +saved;
          this.ramIsDetected = (+saved === this.system.unified_memory_gb);
          return;
        }
      } catch {}
      this.ramGb = this.system.unified_memory_gb || 16;
      this.ramIsDetected = !!this.system.unified_memory_gb;
    },
    /** "✨ Best for your RAM" — the highest-quality model in each use-case
     *  bucket that still fits the current RAM budget (fit state ≠ risky).
     *  "Highest quality" is approximated by the heaviest tier that fits
     *  (bigger memory floor → bigger params / higher precision), nudged by
     *  an explicit "recommended" label. Re-computes live as the slider moves. */
    get bestPicks() {
      const fits = (m) => ["ok", "tight"].includes(
        this.fitFor(m.min_unified_memory_gb).state
      );
      const score = (m) => (Number(m.min_unified_memory_gb) || 0) * 1000
                         + (Number(m.size_gb) || 0) * 10
                         + (/recommended/i.test(m.label || "") ? 5 : 0);
      const pick = (predicate) => {
        const c = (this.models || []).filter(m => fits(m) && predicate(m));
        if (!c.length) return null;
        return c.slice().sort((a, b) => score(b) - score(a))[0];
      };
      const hasCap = (m, cap) => (m.capabilities || []).includes(cap);
      const buckets = [
        { id: "overall",      label: "Best overall",       icon: "🏆", model: pick(() => true) },
        { id: "cloning",      label: "Best voice cloning",  icon: "🧬", model: pick(m => hasCap(m, "voice-cloning")) },
        { id: "multilingual", label: "Best multilingual",   icon: "🌍", model: pick(m => hasCap(m, "multilingual")) },
        { id: "expressive",   label: "Best expressive",     icon: "🎭", model: pick(m => hasCap(m, "expressive")) },
        { id: "streaming",    label: "Best for streaming",  icon: "⚡", model: pick(m => hasCap(m, "streaming")) },
      ];
      // De-dup: if two buckets resolve to the same repo, keep the first.
      const seen = new Set();
      return buckets.filter(b => {
        if (!b.model || seen.has(b.model.repo)) return false;
        seen.add(b.model.repo);
        return true;
      });
    },

    // ─── Library filters (Models tab) ─────────────────────────────────
    /** Apply ALL active filters + sort, return models grouped by family.
     *  Returns `{familyId: [models...]}`. Families with no surviving
     *  models are still keys (empty arrays) so the template can show
     *  "0 of N" — caller can choose to hide empty groups. */
    get filteredModelsByFamily() {
      const f = this.modelFilters;
      const q = (f.search || "").trim().toLowerCase();

      // 1. Per-model filter
      const matches = (m) => {
        // Family chip filter
        if (f.families.size > 0 && !f.families.has(m.family)) return false;
        // Status chip filter — supports cache state + the synthetic "engine-ready"
        if (f.statuses.size > 0) {
          const state = m.cache?.state || "absent";
          const isReady = this.isModelReady(m.repo);
          const matchesState = f.statuses.has(state) || (f.statuses.has("engine-ready") && isReady);
          if (!matchesState) return false;
        }
        // Capability filter (multi-select AND)
        if (f.capabilities.size > 0) {
          const caps = new Set(m.capabilities || []);
          for (const wanted of f.capabilities) {
            if (!caps.has(wanted)) return false;
          }
        }
        // Apple Silicon (MLX) filter — only show pre-quantized MLX entries.
        if (f.mlxOnly && !m.apple_optimized) return false;
        // Segmented RAM-fit filter — scored live against the RAM slider.
        if (f.fitLevel && f.fitLevel !== "all") {
          const st = this.fitFor(m.min_unified_memory_gb).state;
          if (f.fitLevel === "ok"    && st !== "ok")    return false;
          if (f.fitLevel === "tight" && st !== "tight") return false;
          if (f.fitLevel === "over"  && st !== "risky") return false;
        }
        // Legacy "Fits my Mac" toggle — hide entries that would OOM/swap.
        // Now scored client-side so it tracks the RAM slider too.
        if (f.fitsMyMac && !["ok", "tight"].includes(this.fitFor(m.min_unified_memory_gb).state)) return false;
        // Free-text search across label + repo + best_for
        if (q) {
          const hay = (
            (m.label || "") + " " + (m.repo || "") + " " + (m.best_for || "")
          ).toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      };

      // 2. Group surviving models by family
      const out = {};
      for (const m of this.models) {
        if (!matches(m)) continue;
        (out[m.family] ||= []).push(m);
      }

      // 3. Within-family sort
      const cmp = (() => {
        switch (f.sortBy) {
          case "name":      return (a, b) => (a.label || "").localeCompare(b.label || "");
          case "size-asc":  return (a, b) => (a.size_gb || 0) - (b.size_gb || 0);
          case "size-desc": return (a, b) => (b.size_gb || 0) - (a.size_gb || 0);
          default:          return (a, b) => (a.size_gb || 0) - (b.size_gb || 0);
        }
      })();
      for (const fam of Object.keys(out)) out[fam].sort(cmp);
      return out;
    },

    /** Union of every capability across the entire catalog — used to
     *  derive the capability filter chips. */
    get availableCapabilities() {
      const set = new Set();
      for (const m of this.models) {
        for (const c of (m.capabilities || [])) set.add(c);
      }
      const order = { tts: 0, "voice-cloning": 1, expressive: 2, multilingual: 3, streaming: 4 };
      return Array.from(set).sort((a, b) => (order[a] ?? 99) - (order[b] ?? 99) || a.localeCompare(b));
    },

    /** All families that have at least one model in the catalog — used
     *  for the family filter chips. */
    get availableFamilies() {
      const seen = new Set();
      const out = [];
      for (const m of this.models) {
        if (seen.has(m.family)) continue;
        seen.add(m.family);
        out.push({ id: m.family, label: m.family_label || this.families?.[m.family]?.label || m.family });
      }
      return out.sort((a, b) => a.label.localeCompare(b.label));
    },
    get visibleFamilies() {
      const families = Object.values(this.families || {})
        .map(f => ({ ...f, models: this.filteredModelsByFamily[f.id] || [] }))
        .filter(f => f.models.length > 0);
      const rank = (f) => {
        const cached = f.models.some(m => m.cache?.state === "cached") ? 0 : 1;
        const fits = f.models.some(m => ["ok", "tight"].includes(this.fitFor(m.min_unified_memory_gb).state)) ? 0 : 1;
        return cached * 100 + fits * 10;
      };
      return families.sort((a, b) => rank(a) - rank(b) || a.label.localeCompare(b.label));
    },
    familyCapabilities(family) {
      const caps = new Set();
      for (const m of (family.models || [])) for (const cap of (m.capabilities || [])) caps.add(cap);
      return Array.from(caps);
    },
    familyRuntimeLabel(family) {
      const hasMlx = (family.models || []).some(m => m.apple_optimized);
      const hasOther = (family.models || []).some(m => !m.apple_optimized);
      return hasMlx && hasOther ? "MLX + PyTorch" : hasMlx ? "Apple MLX" : "PyTorch / MPS";
    },
    familyMemoryLabel(family) {
      if ((family.models || []).some(m => !Number.isFinite(Number(m.min_unified_memory_gb)) || Number(m.min_unified_memory_gb) <= 0)) {
        return "Memory qualification pending";
      }
      const floors = (family.models || []).map(m => Number(m.min_unified_memory_gb));
      return floors.length ? `from ${Math.min(...floors)} GB RAM` : "RAM varies";
    },
    familyCachedCount(family) { return (family.models || []).filter(m => m.cache?.state === "cached").length; },
    isRecommendedFamily(family) {
      return !!this.bestPicks[0] && (family.models || []).some(m => m.repo === this.bestPicks[0].model.repo);
    },
    familyTone(family) {
      const caps = this.familyCapabilities(family);
      if (caps.includes("voice-cloning")) return "tone-edit";
      if (caps.includes("streaming")) return "tone-streaming";
      if (caps.includes("multilingual")) return "tone-mps";
      return "tone-mlx";
    },
    modelVariantLabel(model) {
      const familyLabel = this.families?.[model.family]?.label || model.family_label || "";
      let label = model.label || model.repo;
      if (familyLabel && label.toLowerCase().startsWith(familyLabel.toLowerCase())) {
        label = label.slice(familyLabel.length).replace(/^\s*(?:[-—:]+)\s*/, "");
      }
      return label || "Standard";
    },
    modelRuntimeLabel(model) { return model.apple_optimized ? "Apple MLX" : "PyTorch / MPS"; },
    modelFormatLabel(model) {
      const label = model.label || "";
      const match = label.match(/(?:4-6|4|6|8)-bit|bf16|fp16|fp32/i);
      return match ? match[0].replace(/^./, c => c.toUpperCase()) + " weights" : "Standard weights";
    },
    modelRoleLabel(model) {
      const label = model.label || "";
      if (/recommended/i.test(label)) return "Recommended";
      if (/smallest|nano/i.test(label)) return "Smallest";
      if (/4-bit/i.test(label)) return "Fastest loads";
      if (/8-bit/i.test(label)) return "Balanced";
      if (/full precision|bf16|fp16|fp32/i.test(label)) return "Full fidelity";
      return "";
    },

    /** Total counts for the "Showing N of M" header. */
    get filteredModelTotalCount() {
      const grouped = this.filteredModelsByFamily;
      return Object.values(grouped).reduce((s, list) => s + list.length, 0);
    },

    get hasActiveFilters() {
      const f = this.modelFilters;
      return !!(f.search.trim() || f.families.size || f.statuses.size || f.capabilities.size
                || f.mlxOnly || f.fitsMyMac || (f.fitLevel && f.fitLevel !== "all"));
    },
    // ─── Filter manipulation methods ─────────────────────────────────
    toggleFamilyFilter(familyId) {
      const s = this.modelFilters.families;
      if (s.has(familyId)) s.delete(familyId); else s.add(familyId);
      // Trigger Alpine reactivity for Set mutations (Alpine doesn't track Set
      // membership changes deeply — reassign to force re-render).
      this.modelFilters.families = new Set(s);
    },
    toggleStatusFilter(status) {
      const s = this.modelFilters.statuses;
      if (s.has(status)) s.delete(status); else s.add(status);
      this.modelFilters.statuses = new Set(s);
    },
    toggleCapabilityFilter(cap) {
      const s = this.modelFilters.capabilities;
      if (s.has(cap)) s.delete(cap); else s.add(cap);
      this.modelFilters.capabilities = new Set(s);
    },
    /** Opt-in filter for MLX-native model weights. */
    toggleMlxFilter() {
      this.modelFilters.mlxOnly = !this.modelFilters.mlxOnly;
    },
    /** Toggle "Fits my Mac" — hides entries that would OOM/swap. Persists. */
    toggleFitsMyMacFilter() {
      this.modelFilters.fitsMyMac = !this.modelFilters.fitsMyMac;
    },
    /** Helper: write a filter preference to localStorage. App-namespaced. */
    _persistFilterPref(name, value) {
      try {
        localStorage.setItem(`voicestudio.modelFilters.${name}`, String(value));
      } catch {}
    },
    /** Format/fit filters never persist: opening Models must show the catalog. */
    _initFilterPreferences() {
      try {
        this.modelFilters.mlxOnly = false;
        this.modelFilters.fitsMyMac = false;
        localStorage.removeItem("voicestudio.modelFilters.mlxOnly");
        localStorage.removeItem("voicestudio.modelFilters.fitsMyMac");
      } catch {}
    },
    _initFamilyLibrary() {
      if (this.modelFilters.openFamilies.size) return;
      const cached = this.models.find(m => m.cache?.state === "cached");
      const fitting = this.models.find(m => ["ok", "tight"].includes(this.fitFor(m.min_unified_memory_gb).state));
      const first = cached || fitting || this.models[0];
      this.modelFilters.openFamilies = new Set(first ? [first.family] : []);
    },
    // ──────── Per-model gen-state persistence ────────
    // localStorage keys: voicestudio.gen.presets is { [repo]: { field: value, ... } },
    // voicestudio.gen.lastRepo is the last-active repo string. Restored on init.
    _GEN_PRESET_KEY: "voicestudio.gen.presets",
    _GEN_LAST_REPO_KEY: "voicestudio.gen.lastRepo",
    // Fields snapshotted into the per-repo preset. Picked to cover every voice /
    // tone / shape setting on every engine without dragging along transient
    // session state (jobs, submitting, text content, etc).
    _GEN_PRESET_FIELDS: [
      "voice", "kokoro_blend_voice", "kokoro_language", "preset_speaker", "bark_voice_preset", "voice_library_id",
      "language", "speed", "temperature", "seed", "batchCount",
      "section_size_mode", "section_max_characters",
      "cfg_value", "inference_timesteps", "normalize_text",
      "voxcpm_warmup_patches", "voxcpm_max_tokens",
      "instruct", "voice_design_prompt",
      "chatterbox_cfg_weight", "chatterbox_repetition_penalty",
      "chatterbox_min_p", "chatterbox_top_p",
      "bark_temperature", "bark_max_coarse_history", "bark_sliding_window_len", "bark_allow_early_stop",
      "omnivoice_num_steps", "omnivoice_guidance_scale", "omnivoice_duration_s",
      "fish_temperature", "fish_top_p", "fish_top_k", "fish_max_tokens",
      "audio8_temperature", "audio8_top_p", "audio8_top_k", "audio8_max_tokens",
      "moss_temperature", "moss_top_p", "moss_top_k", "moss_repetition_penalty",
      "echo_num_steps", "echo_cfg_scale_text", "echo_cfg_scale_speaker",
    ],

    _loadAllGenPresets() {
      try {
        const raw = localStorage.getItem(this._GEN_PRESET_KEY);
        return raw ? (JSON.parse(raw) || {}) : {};
      } catch { return {}; }
    },
    _saveAllGenPresets(map) {
      try { localStorage.setItem(this._GEN_PRESET_KEY, JSON.stringify(map)); } catch {}
    },
    /** Snapshot the current gen.* fields into localStorage under gen.repo. */
    _saveCurrentGenPreset() {
      const repo = this.gen.repo;
      if (!repo) return;
      const map = this._loadAllGenPresets();
      const preset = {};
      for (const f of this._GEN_PRESET_FIELDS) preset[f] = this.gen[f];
      map[repo] = preset;
      this._saveAllGenPresets(map);
      try { localStorage.setItem(this._GEN_LAST_REPO_KEY, repo); } catch {}
    },
    /** Pull the stored preset for `repo` into the live gen.* fields. No-op
     *  when no preset exists yet — fields keep whatever onModelChange() or
     *  the previous repo left behind. */
    _restoreGenPresetForRepo(repo) {
      if (!repo) return;
      const preset = this._loadAllGenPresets()[repo];
      if (!preset) {
        const control = this.generationModels.find(model => model.repo === repo)
          ?.long_form_delivery?.section_size_control;
        if (control) {
          this.gen.section_size_mode = "auto";
          this.gen.section_max_characters = control.default_custom ?? 280;
        }
        return;
      }
      for (const f of this._GEN_PRESET_FIELDS) {
        if (preset[f] !== undefined) this.gen[f] = preset[f];
      }
    },
    /** Called once after init() has the catalog + availability lists. Restores
     *  the last-used repo (if it's still cached) and its preset, then arms
     *  watchers so further changes persist automatically. */
    _initGenPersistence() {
      try {
        const lastRepo = localStorage.getItem(this._GEN_LAST_REPO_KEY);
        if (lastRepo && this.generationModels.some(m => m.repo === lastRepo)) {
          this.gen.repo = lastRepo;
          // Mark as authoritative so the 4s catalog poll's _reconcileSelectedModel
          // doesn't override this restore on a transient cache-state hiccup.
          this._repoUserConfirmed = true;
        } else if (this.gen.repo) {
          // No saved lastRepo, but refreshCatalog() already picked a default.
          // Treat that as authoritative too — otherwise the poll could keep
          // re-snapping it if the catalog order changes between requests.
          this._repoUserConfirmed = true;
        }
      } catch {}
      this._restoreGenPresetForRepo(this.gen.repo);

      // Watchers — registered AFTER the initial restore so the restore itself
      // doesn't fire a redundant save round. Repo changes additionally pull
      // in the new repo's preset (after onModelChange()'s default-snap, since
      // $watch fires on the microtask AFTER the synchronous @change handler).
      // Any repo change after init counts as a user-authoritative choice.
      this.$watch("gen.repo", (newRepo) => {
        if (newRepo) this._repoUserConfirmed = true;
        this._restoreGenPresetForRepo(newRepo);
        this._saveCurrentGenPreset();
      });
      for (const f of this._GEN_PRESET_FIELDS) {
        this.$watch(`gen.${f}`, () => this._saveCurrentGenPreset());
      }
    },

    /** Per-card expand/collapse (cards default to compact). */
    isModelExpanded(repo) {
      return this.modelFilters.expandedRepos.has(repo);
    },
    toggleModelExpanded(repo) {
      const s = this.modelFilters.expandedRepos;
      if (s.has(repo)) s.delete(repo); else s.add(repo);
      this.modelFilters.expandedRepos = new Set(s);
    },
    toggleFamilyOpen(familyId) {
      const s = this.modelFilters.openFamilies;
      if (s.has(familyId)) s.delete(familyId); else s.add(familyId);
      this.modelFilters.openFamilies = new Set(s);
    },
    isStatusFiltered(status)     { return this.modelFilters.statuses.has(status); },
    isCapFiltered(cap)           { return this.modelFilters.capabilities.has(cap); },
    isFamilyOpen(familyId) {
      return this.modelFilters.openFamilies.has(familyId) || !!this.modelFilters.search.trim();
    },
    clearAllFilters() {
      this.modelFilters.search = "";
      this.modelFilters.families = new Set();
      this.modelFilters.statuses = new Set();
      this.modelFilters.capabilities = new Set();
      this.modelFilters.mlxOnly = false;
      this.modelFilters.fitsMyMac = false;
      this.modelFilters.fitLevel = "all";
      this.modelFilters.sortBy = "default";
      // expandedRepos intentionally NOT reset — separate user concern.
      // ramGb intentionally NOT reset — it's a hardware setting, not a filter.
    },
    get activeDownloadCount() {
      return this.jobs.filter(j => ["queued", "running", "cancelling"].includes(j.state)).length;
    },

    get finishedDownloadCount() {
      return this.jobs.filter(j => ["done", "error", "cancelled"].includes(j.state)).length;
    },

    // ──────── generate-tab derived ────────
    get cachedModels() {
      return this.models.filter(m => m.cache?.state === "cached");
    },

    get generationModels() {
      return this.models.filter(m => m.cache?.state === "cached");
    },

    /** Local models grouped into one <optgroup> per family, so the picker reads
     *  the same way the Models tab does. HTML can't nest optgroups, so families
     *  become the groups rather than sitting under a single "Local" heading.
     *  Families keep catalog order; a model whose family is missing from the
     *  families map still shows up under its raw family id rather than vanishing. */
    get localFamilyGroups() {
      const groups = [];
      const byId = new Map();
      for (const m of this.generationModels) {
        let g = byId.get(m.family);
        if (!g) {
          g = {
            id: m.family,
            label: this.families?.[m.family]?.label || m.family_label || m.family,
            models: [],
          };
          byId.set(m.family, g);
          groups.push(g);
        }
        g.models.push(m);
      }
      return groups;
    },

    /** Companion models (codec / tokenizer repos in a separate HF repo) that a
     *  family's engine loads alongside the model itself. These are a real part
     *  of the download cost — Echo-TTS pulls a 1.87 GB Fish S1 codec on top of
     *  its 5.6 GB weights — but were previously invisible in the UI. Declared
     *  per family in catalog.FAMILY_COMPANIONS, so any model of the family
     *  carries the same list. */
    familyCompanions(family) {
      const m = (family?.models || []).find(x => (x.cache?.companions || []).length);
      return m ? m.cache.companions : [];
    },
    /** True on-disk footprint for one model including its companions, or null
     *  when the family has none (then the plain download size already tells the
     *  whole story). */
    modelTotalBytes(m) {
      return m?.cache?.bytes_with_companions || null;
    },
    companionStateLabel(state) {
      if (state === "cached") return "ready";
      if (state === "partial") return "partial";
      return "not downloaded";
    },

    get modeCompatibleModels() {
      // Show only cached models that declare TTS support.
      return this.generationModels.filter(m => (m.capabilities || []).includes("tts"));
    },

    get selectedModel() {
      return this.generationModels.find(m => m.repo === this.gen.repo) || null;
    },

    get sectionSizeControl() {
      return this.selectedModel?.long_form_delivery?.section_size_control || null;
    },

    get sectionSizeControlSupported() {
      return !!this.sectionSizeControl;
    },

    get sectionSizeValue() {
      return Number(this.gen.section_max_characters);
    },

    get sectionSizeIsValid() {
      const c = this.sectionSizeControl;
      return !c || this.gen.section_size_mode === "auto" || (
        Number.isInteger(this.sectionSizeValue)
        && this.sectionSizeValue >= c.minimum
        && this.sectionSizeValue <= c.maximum
      );
    },

    resetSectionSizeToAuto() {
      this.gen.section_size_mode = "auto";
    },

    get selectedVoiceSummary() {
      if (!this.selectedModel) return "—";
      const qwenMode = this.qwen3Mode(this.gen.repo);
      if (qwenMode === "custom") return this.gen.preset_speaker || "Choose speaker";
      if (this.isBark(this.gen.repo)) return this.gen.bark_voice_preset || "Random voice";
      const cloneMode = qwenMode === "clone"
                     || this.isMlxCloner(this.gen.repo) || this.isF5TTS(this.gen.repo);
      if (cloneMode && this.gen.voice_library_id) {
        return this.voices.find(v => v.id === this.gen.voice_library_id)?.name
            || "Reference voice";
      }
      if (qwenMode === "design" || this.isOmniVoice(this.gen.repo)) return "Designed voice";
      if (this.isMlxVoicePicker(this.gen.repo) || this.isSparkTtsMlx(this.gen.repo)) {
        if (this.isKokoroMlx(this.gen.repo) && this.gen.kokoro_blend_voice) {
          return `${this.gen.voice} + ${this.gen.kokoro_blend_voice}`;
        }
        return this.gen.voice || "Model default";
      }
      return "Model default";
    },

    get selectedLibraryVoice() {
      return this.voices.find(v => v.id === this.gen.voice_library_id) || null;
    },

    get selectedStoredTranscript() {
      return (this.selectedLibraryVoice?.transcript || "").trim();
    },

    onReferenceVoiceChange() {
      // An override belongs to one specific clip. Never carry it to another
      // voice, where it would misalign the new audio with the old transcript.
      this.gen.ref_transcript = "";
    },

    referenceTranscriptForRequest() {
      return (this.gen.ref_transcript || "").trim()
          || this.selectedStoredTranscript
          || null;
    },

    // Per-family text-length guidance for the currently-selected model.
    // Returns null when no model is selected or the family has no guidance —
    // the UI hides the hint chip in that case.
    get currentTextGuidance() {
      const m = this.selectedModel;
      if (!m) return null;
      const fam = this.families?.[m.family];
      return fam?.text_guidance || null;
    },

    // True when the user's text exceeds the family's soft cap. Families with
    // soft_max_chars=null (unlimited) never trigger this.
    get textOverSoftCap() {
      const g = this.currentTextGuidance;
      if (!g || g.soft_max_chars == null) return false;
      return this.gen.text.length > g.soft_max_chars;
    },

    // True when the family has a *hard* cliff (Bark / Orpheus / XTTS) AND
    // the user's text exceeds it. Drives the soft-block confirm prompt.
    get textHardCapExceeded() {
      const g = this.currentTextGuidance;
      if (!g || g.chunking !== "hard-cap" || g.soft_max_chars == null) return false;
      return this.gen.text.length > g.soft_max_chars;
    },

    get genWiredFamilies() {
      return this.gen.wired_families || [];
    },

    // Subtitles: selected model row, including engine capability truth.
    get sttSelectedModel() {
      return (this.stt.models || []).find(m => m.repo === this.stt.model) || null;
    },
    get sttWordTimestampsSupported() {
      return !this.sttSelectedModel
        || this.sttSelectedModel.supports_word_timestamps !== false;
    },
    selectTranscriptionModel(repo) {
      this.stt.model = repo;
      if (!this.sttWordTimestampsSupported) this.stt.wordTimestamps = false;
    },

    get canSubmit() {
      if (this.gen.submitting) return false;
      if (!this.gen.available) return false;
      if (!this.gen.repo) return false;
      if (!this.gen.text.trim()) return false;
      if (!this.isModelReady(this.gen.repo)) return false;
      if (this.sectionSizeControlSupported
          && this.gen.section_size_mode === "custom" && !this.sectionSizeIsValid) return false;
      // Per-mode validation
      const mode = this.qwen3Mode(this.gen.repo);
      if (mode === "design" && !this.gen.voice_design_prompt.trim()) return false;
      if (mode === "clone"  && !this.gen.voice_library_id) return false;
      if (mode === "custom" && !this.gen.preset_speaker) return false;
      if (this.isOmniVoice(this.gen.repo)
          && !this.gen.voice_library_id && !this.gen.voice_design_prompt.trim()) return false;
      // Chatterbox is voice-cloning only; prevent a guaranteed backend error.
      if (this.isChatterboxMlx(this.gen.repo) && !this.gen.voice_library_id) return false;
      if (this.isChatterboxMlx(this.gen.repo) && !this.chatterboxLanguageCodes().includes(this.gen.language)) return false;
      // F5-TTS requires a library voice (voice cloning only — no zero-shot).
      if (this.isF5TTS(this.gen.repo) && !this.gen.voice_library_id) return false;
      return true;
    },

    get submitHint() {
      if (this.gen.submitting) return "";
      if (!this.gen.available) return "Install the generation engine to continue.";
      if (!this.gen.repo) return "Choose a downloaded model to continue.";
      if (!this.gen.text.trim()) return "Type some text to enable Generate.";
      if (!this.isModelReady(this.gen.repo)) return "This model is not ready yet.";
      if (this.sectionSizeControlSupported
          && this.gen.section_size_mode === "custom" && !this.sectionSizeIsValid) {
        const c = this.sectionSizeControl;
        return `Enter a whole number from ${c.minimum} to ${c.maximum}.`;
      }
      const mode = this.qwen3Mode(this.gen.repo);
      if (mode === "design" && !this.gen.voice_design_prompt.trim()) return "Describe the voice you want.";
      if (mode === "clone" && !this.gen.voice_library_id) return "Pick a reference voice from your library.";
      if (mode === "custom" && !this.gen.preset_speaker) return "Pick a preset speaker.";
      if (this.isOmniVoice(this.gen.repo)
          && !this.gen.voice_library_id && !this.gen.voice_design_prompt.trim()) {
        return "Choose a reference voice or describe the voice traits below.";
      }
      if ((this.isChatterboxMlx(this.gen.repo) || this.isF5TTS(this.gen.repo)) && !this.gen.voice_library_id) {
        return "Pick a reference voice from your library.";
      }
      if (this.isChatterboxMlx(this.gen.repo) && !this.chatterboxLanguageCodes().includes(this.gen.language)) {
        return "Choose a supported Chatterbox language.";
      }
      return "Complete the required fields to continue.";
    },

    /** Jobs that are queued OR currently running — i.e. work the user has
     *  submitted but hasn't finished yet. Sorted oldest-first so the queue
     *  reads top-down in submission order. */
    get pendingJobs() {
      return (this.gen.jobs || [])
        .filter(j => j.state === "queued" || j.state === "running")
        .sort((a, b) => (a.started_at || 0) - (b.started_at || 0));
    },
    get queuedCount() {
      return (this.gen.jobs || []).filter(j => j.state === "queued").length;
    },
    get runningJob() {
      return (this.gen.jobs || []).find(j => j.state === "running") || null;
    },
    get hasPending() {
      return this.pendingJobs.length > 0;
    },

    get outputSizeLabel() {
      return humanBytes(this.outputStats.bytes || 0);
    },

    get recentJobs() {
      // Sorted newest-first. Includes the latest at index 0 for the UI's
      // recent-grid which slices [1..].
      return (this.gen.jobs || []).filter(j => j.state === "done" || j.state === "error" || j.state === "cancelled");
    },

    /** History entries other than the current "Latest generation" — the
     *  recent-grid renders this paginated. */
    get historyJobs() {
      // v1.5.2: ALL finished results live here (newest first), including the
      // most recent one. Previously index 0 was carved out for a separate
      // "Latest generation" panel in the generate area; that panel is gone now,
      // so every result shows in this single history list.
      return this.recentJobs;
    },

    get historyPageCount() {
      return Math.max(1, Math.ceil(this.historyJobs.length / this.historyPageSize));
    },

    /** Current-page slice of history. Clamps page if filters reduced the list. */
    get pagedHistoryJobs() {
      const total = this.historyJobs.length;
      const last = Math.max(0, this.historyPageCount - 1);
      if (this.historyPage > last) this.historyPage = last;
      const start = this.historyPage * this.historyPageSize;
      return this.historyJobs.slice(start, start + this.historyPageSize);
    },

    historyNextPage() { if (this.historyPage < this.historyPageCount - 1) this.historyPage += 1; },
    historyPrevPage() { if (this.historyPage > 0) this.historyPage -= 1; },

    /** Pretty model label for a history job — falls back to the repo path
     *  if the model is no longer in the catalog (e.g. user removed it). */
    historyModelLabel(job) {
      const repo = job?.params?.repo;
      if (!repo) return "(unknown model)";
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.label || repo;
    },

    /** Voice / mode descriptor for a history job. Engine-aware — picks the
     *  right field per family. */
    historyVoiceLabel(job) {
      const p = job?.params || {};
      const repo = p.repo || "";
      const m = (this.models || []).find(x => x.repo === repo);
      const family = m?.family;

      // Per-family voice display
      if (family === "kokoro") {
        return p.voice ? `voice: ${p.voice}` : "voice: default";
      }
      if (family === "qwen3-tts") {
        if (p.preset_speaker) return `speaker: ${p.preset_speaker}`;
        if (p.voice_design_prompt) return `design: "${p.voice_design_prompt.slice(0, 40)}…"`;
        if (p.voice_library_id) return `clone: ${this._voiceNameById(p.voice_library_id)}`;
        return "default";
      }
      if (family === "voxcpm-mlx") {
        const parts = [];
        if (p.voice_library_id) parts.push(`clone: ${this._voiceNameById(p.voice_library_id)}`);
        if (p.voice_design_prompt) parts.push(`design: "${p.voice_design_prompt.slice(0, 30)}…"`);
        if (p.instruct) parts.push(`emotion: "${p.instruct.slice(0, 30)}"`);
        return parts.join(" · ") || "default voice";
      }
      if (family === "bark") {
        return p.bark_voice_preset ? `preset: ${p.bark_voice_preset}` : "random voice";
      }
      return "";
    },

    _voiceNameById(id) {
      const v = (this.voices || []).find(x => x.id === id);
      return v?.name || id || "(unknown voice)";
    },

    // ──────── API tab derived ────────
    get apiBase() {
      return window.location.origin;
    },

    get curlExample() {
      const base = this.apiBase;
      const repo = this.gen.repo || "mlx-community/Kokoro-82M-bf16";
      const body = JSON.stringify({
        repo,
        text: "Welcome to Voice Studio.",
        voice: "af_bella",
        speed: 1.0,
      });
      return [
        "# 1. Start speech generation — returns a job id immediately",
        "curl -s -X POST " + base + "/api/generate/txt2speech \\",
        "  -H 'content-type: application/json' \\",
        "  -d '" + body + "'",
        "# → returns: {\"job\": {\"id\": \"abc123\", \"state\": \"queued\", ...}}",
        "",
        "# 2. Poll the job until state == done",
        "curl -s " + base + "/api/generate/jobs/abc123",
        "",
        "# 3. Save the WAV to disk",
        "curl -s -o speech.wav " + base + "/api/generate/jobs/abc123/audio",
      ].join("\n");
    },

    get jsExample() {
      const base = this.apiBase;
      const repo = this.gen.repo || "mlx-community/Kokoro-82M-bf16";
      const lines = [
        "const SERVER = " + JSON.stringify(base) + ";",
        "",
        "// 1. Kick off generation",
        "const start = await fetch(SERVER + '/api/generate/txt2speech', {",
        "  method: 'POST',",
        "  headers: { 'content-type': 'application/json' },",
        "  body: JSON.stringify({",
        "    repo: " + JSON.stringify(repo) + ",",
        "    text: 'Welcome to Voice Studio.',",
        "    voice: 'af_bella', speed: 1.0,",
        "  }),",
        "}).then(r => r.json());",
        "",
        "// 2. Poll once per second until done",
        "let job = start.job;",
        "while (job.state !== 'done' && job.state !== 'error') {",
        "  await new Promise(r => setTimeout(r, 1000));",
        "  job = (await fetch(SERVER + '/api/generate/jobs/' + job.id).then(r => r.json())).job;",
        "}",
        "if (job.state === 'error') throw new Error(job.error);",
        "",
        "// 3. job.output_url is a relative path — fetch and play as a Blob",
        "const blob = await fetch(SERVER + job.output_url).then(r => r.blob());",
        "const url = URL.createObjectURL(blob);",
        "new Audio(url).play();",
      ];
      return lines.join("\n");
    },

    get reDownloadExample() {
      const base = this.apiBase;
      const sampleId = this.gen.jobs.find(j => j.state === "done")?.id || "abc123def456";
      return [
        "# Inspect job metadata (params, seed, output_url, duration, state)",
        "curl -s " + base + "/api/generate/jobs/" + sampleId + " | jq",
        "",
        "# Re-download the WAV",
        "curl -s -o speech.wav " + base + "/api/generate/jobs/" + sampleId + "/audio",
        "",
        "# Python equivalent",
        "import requests",
        "r = requests.get(" + JSON.stringify(base + "/api/generate/jobs/" + sampleId) + ").json()",
        "print('seed used:', r['job']['resolved_seed'])",
        "print('prompt:', r['job']['params']['prompt'])",
        "audio = requests.get(" + JSON.stringify(base + "/api/generate/jobs/" + sampleId + "/audio") + ").content",
        "open('speech.wav', 'wb').write(audio)",
      ].join("\n");
    },

    get listJobsExample() {
      const base = this.apiBase;
      return [
        "# Returns ALL persisted jobs (last 200), latest first",
        "curl -s " + base + "/api/generate/jobs | jq",
        "",
        "# Just the ids + text, for quick browsing",
        "curl -s " + base + "/api/generate/jobs | \\",
        "  jq -r '.jobs[] | \"\\(.id)  \\(.state)  \\(.params.text // \"(no text)\")\"'",
        "",
        "# Find a job by text fragment",
        "curl -s " + base + "/api/generate/jobs | \\",
        "  jq '.jobs[] | select(.params.text | test(\"welcome\"; \"i\"))'",
      ].join("\n");
    },

    get pythonExample() {
      const base = this.apiBase;
      const repo = this.gen.repo || "mlx-community/Kokoro-82M-bf16";
      const lines = [
        "import time, requests",
        "",
        "SERVER = " + JSON.stringify(base),
        "",
        "# 1. Kick off generation",
        "r = requests.post(f'{SERVER}/api/generate/txt2speech', json={",
        "    'repo': " + JSON.stringify(repo) + ",",
        "    'text': 'Welcome to Voice Studio.',",
        "    'voice': 'af_bella', 'speed': 1.0,",
        "})",
        "r.raise_for_status()",
        "job_id = r.json()['job']['id']",
        "",
        "# 2. Poll until done",
        "while True:",
        "    job = requests.get(f'{SERVER}/api/generate/jobs/{job_id}').json()['job']",
        "    if job['state'] == 'done':",
        "        break",
        "    if job['state'] == 'error':",
        "        raise RuntimeError(job['error'])",
        "    time.sleep(1)",
        "",
        "# 3. Save the WAV",
        "audio = requests.get(f'{SERVER}/api/generate/jobs/{job_id}/audio').content",
        "with open('speech.wav', 'wb') as f:",
        "    f.write(audio)",
        "print(f\"saved speech.wav ({len(audio)//1000} KB, {job['duration_seconds']:.1f}s)\")",
      ];
      return lines.join("\n");
    },

    // ──────── fetch helpers ────────
    /** Fetch the host's chip + RAM snapshot. Used once at init — hardware
     *  doesn't change while the app is running. */
    async refreshSystem() {
      try {
        const r = await fetch("/api/system");
        this.system = await r.json();
      } catch {
        // Leave defaults — fit chips render as "unknown", banner stays hidden.
      }
    },

    async refreshHealth() {
      try {
        const r = await fetch("/api/health");
        this.health = await r.json();
      } catch {
        this.health = { ok: false };
      }
    },

    async refreshReleaseNotes() {
      try {
        const r = await fetch("/api/release-notes", { cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        this.releaseNotesCurrent = data.current_version || this.health.app_version || "unknown";
        this.releaseNotes = Array.isArray(data.releases) ? data.releases : [];
      } catch {
        this.releaseNotes = [];
      }
    },

    async refreshCatalog() {
      try {
        const r = await fetch("/api/catalog");
        const data = await r.json();
        this.families = data.families;
        this.models = data.models;
        this._reconcileSelectedModel();
      } catch {
        /* keep last good state */
      }
    },

    async refreshModelStorage() {
      this.modelStorage.loading = true;
      this.modelStorage.error = "";
      try {
        const r = await fetch("/api/model-storage", { cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        this.modelStorage = { ...this.modelStorage, ...data, loading: false, error: "" };
      } catch (e) {
        this.modelStorage.loading = false;
        this.modelStorage.error = String(e);
      }
    },

    storageTypeLabel(type) {
      return {
        model: "Model",
        dependency: "Required dependency",
        legacy: "Legacy",
        unknown: "Unrecognised",
      }[type] || type;
    },

    storageTypeClass(type) {
      return {
        model: "ok",
        dependency: "info",
        legacy: "warn",
        unknown: "warn",
      }[type] || "neutral";
    },

    storageParentLabel(repo) {
      const model = (this.models || []).find(m => m.repo === repo);
      const sttModel = (this.stt?.models || []).find(m => m.repo === repo);
      return model?.label || sttModel?.label || repo;
    },

    completeStorageDependency(item) {
      const parentRepo = item?.used_by?.[0];
      if (!parentRepo) return;
      const parent = (this.models || []).find(m => m.repo === parentRepo)
        || (this.stt?.models || []).find(m => m.repo === parentRepo);
      if (parent) this.confirmDownload(parent);
    },

    async removeStoragePackage(item) {
      if (!item?.removal?.allowed) return;
      const size = humanBytes(item.cache?.bytes_total || 0);
      const warning = item.type === "model"
        ? "This removes the complete local model package. You can download it again later."
        : "This removes the complete cache package and any unfinished transfer data inside it.";
      const accepted = await this.askConfirm(
        `Remove ${item.label}?`,
        `${warning}\n\n${item.repo}\nDisk space: ${size}`,
        "Remove package",
      );
      if (!accepted) return;
      try {
        const r = await fetch("/api/model-storage/" + encodeURIComponent(item.repo), { method: "DELETE" });
        if (!r.ok) {
          const error = await r.json().catch(() => ({}));
          throw new Error(error.detail || `HTTP ${r.status}`);
        }
        const data = await r.json();
        this.modelStorage = { ...this.modelStorage, ...data.inventory, loading: false, error: "" };
        await this.refreshCatalog();
        await this.refreshTranscribe();
        this.pushToast({ kind: "info", icon: "🧹", title: "Model package removed",
          body: `${item.label} · ${humanBytes(data.freed_bytes || 0)} freed` });
      } catch (e) {
        this.pushToast({ kind: "error", icon: "✗", title: "Couldn't remove model package", body: String(e) });
        await this.refreshModelStorage();
      }
    },

    _reconcileSelectedModel() {
      // The <select> visually displays the first option even when gen.repo is
      // empty, but Alpine's x-model only updates on user change events. Without
      // this, submitGenerate() trips its "pick a cached model" guard even
      // though the UI looks like one is selected. So we pick the first
      // mode-compatible cached model on load, and re-pick if the user's choice
      // truly disappears from the cached list.
      //
      // IMPORTANT: this is called on EVERY catalog refresh (every 4s via the
      // polling interval). If the user has authoritatively chosen a model
      // (`_repoUserConfirmed=true`), we MUST NOT override it just because a
      // transient catalog payload doesn't list it as "mode compatible" — only
      // a genuine disappearance from generationModels should trigger a reset.
      // Previously this used `modeCompatibleModels` which made any momentary
      // race (cache.status_snapshot reporting "partial" while a download is
      // being indexed, etc.) snap the selection back to the first model.
      const currentRepo = this.gen.repo;
      const cached = this.generationModels;

      if (this._repoUserConfirmed && currentRepo) {
        // User has made an explicit choice. Keep it as long as it's still
        // cached at all — don't second-guess based on capability filters.
        if (cached.some(m => m.repo === currentRepo)) return;
      } else if (currentRepo && cached.some(m => m.repo === currentRepo)) {
        // No user confirmation yet but gen.repo somehow already matches a
        // cached model (e.g. set by some other code path) — treat that as
        // valid too. The dropdown only shows generationModels anyway.
        return;
      }

      // gen.repo is empty OR the chosen model is no longer cached. Snap to
      // the first compatible cached model as a sensible default.
      const compatible = this.modeCompatibleModels;
      this.gen.repo = compatible[0]?.repo || cached[0]?.repo || "";
    },

    startJobStream() {
      if (this._streamHandle) this._streamHandle.close();
      const es = new EventSource("/api/downloads/stream");
      es.addEventListener("snapshot", e => {
        try {
          const payload = JSON.parse(e.data);
          this.jobs = payload.jobs || [];
        } catch { /* swallow */ }
      });
      es.onerror = () => {
        // Browser will auto-reconnect; just trace once for debugging.
        // console.debug("SSE disconnected, will reconnect");
      };
      this._streamHandle = es;
    },

    // ──────── download flow ────────
    confirmDownload(model) {
      this.pendingDownload = model;
      this.downloadToken = "";
    },

    async startDownload() {
      if (!this.pendingDownload) return;
      const repo = this.pendingDownload.repo;
      const isTranscription = this.stt.models.some((m) => m.repo === repo);
      const body = { repo, token: this.downloadToken || null };
      this.pendingDownload = null;
      try {
        await fetch("/api/downloads", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        });
        // Transcription and TTS downloads use the same confirm
        // modal and the same /api/downloads call, but each needs its own
        // follow-up refresh so the UI notices completion (v1.7.4).
        if (isTranscription) {
          this._pollTranscriptionUntilCached(repo);
        } else {
          await this.refreshCatalog();
        }
      } catch (e) {
        alert("Failed to start download: " + e);
      }
    },

    async cancelDownload(jobId) {
      try {
        await fetch("/api/downloads/" + encodeURIComponent(jobId), { method: "DELETE" });
      } catch { /* surfaced via stream on next tick */ }
    },

    // ──────── settings ────────
    async refreshSettings() {
      try {
        const r = await fetch("/api/settings");
        const data = await r.json();
        this.settings.hf_token_set = !!data.hf_token_set;
        this.settings.hf_token_masked = data.hf_token_masked || "";
      } catch { /* keep last */ }
      // Connectivity panel is on the same tab — refresh it at the same time.
      await this.refreshConnectivity();
      await this.refreshAutoUpdate(true);
      await this.refreshMemoryPolicy(true);
    },

    async refreshAutoUpdate(silent = false) {
      try {
        const r = await fetch("/api/auto-update/status", { cache: "no-store" });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || ("HTTP " + r.status));
        this.applyAutoUpdateStatus(data);
      } catch (e) {
        if (!silent) {
          this.autoUpdate.message = String(e.message || e);
          this.autoUpdate.messageKind = "error";
        }
      }
    },

    applyAutoUpdateStatus(data, forceDraft = false) {
      const savedSettings = data.settings ? { ...data.settings } : null;
      Object.assign(this.autoUpdate, data, { loaded: true });
      // Settings status refreshes every five seconds. Preserve a user's
      // in-progress form draft instead of replacing it with persisted values.
      if (savedSettings && (forceDraft || !this.autoUpdate.dirty)) {
        this.autoUpdate.draft = savedSettings;
        this.autoUpdate.dirty = false;
      }
    },

    markAutoUpdateDirty() {
      this.autoUpdate.dirty = true;
      this.autoUpdate.message = "";
      this.autoUpdate.messageKind = "info";
    },

    autoUpdateTime(value) {
      if (!value) return "Not yet";
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? "Not yet" : date.toLocaleString();
    },

    async saveAutoUpdate() {
      this.autoUpdate.busy = true;
      this.autoUpdate.message = "Saving and validating the schedule…";
      this.autoUpdate.messageKind = "info";
      try {
        const r = await fetch("/api/auto-update/settings", {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify(this.autoUpdate.draft),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || ("HTTP " + r.status));
        this.applyAutoUpdateStatus(data, true);
        this.autoUpdate.message = data.settings.mode === "off"
          ? "Saved. Automatic updates are off and the schedule is unloaded."
          : "Saved. The updater schedule is installed and verified.";
        this.autoUpdate.messageKind = "success";
      } catch (e) {
        this.autoUpdate.message = String(e.message || e);
        this.autoUpdate.messageKind = "error";
      } finally {
        this.autoUpdate.busy = false;
      }
    },

    async autoUpdateAction(action, body = {}) {
      this.autoUpdate.busy = true;
      this.autoUpdate.message = action === "check" ? "Checking safely…" : "Starting the update helper…";
      this.autoUpdate.messageKind = "info";
      try {
        const r = await fetch(`/api/auto-update/${action}`, {
          method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || ("HTTP " + r.status));
        this.applyAutoUpdateStatus(data);
        this.autoUpdate.message = body.after_current
          ? "Queued. The updater will retry automatically when Voice Studio is idle."
          : (action === "check" ? "Check started. Status will refresh automatically." : "Update started. This page may reconnect during restart.");
        this.autoUpdate.messageKind = "success";
      } catch (e) {
        this.autoUpdate.message = String(e.message || e);
        this.autoUpdate.messageKind = "error";
      } finally {
        this.autoUpdate.busy = false;
      }
    },

    async refreshMemoryPolicy(silent = false, forceDraft = false) {
      try {
        const r = await fetch("/api/memory-policy", { cache: "no-store" });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || ("HTTP " + r.status));
        const saved = data.mode;
        Object.assign(this.memoryPolicy, data, { loaded: true });
        if (forceDraft || !this.memoryPolicy.dirty) {
          this.memoryPolicy.draft = { mode: saved };
          this.memoryPolicy.dirty = false;
        }
      } catch (e) {
        if (!silent) {
          this.memoryPolicy.message = String(e.message || e);
          this.memoryPolicy.messageKind = "error";
        }
      }
    },

    markMemoryPolicyDirty() {
      this.memoryPolicy.dirty = true;
      this.memoryPolicy.message = "";
      this.memoryPolicy.messageKind = "info";
    },

    memoryPolicyTime(value) {
      if (!value) return "Not scheduled";
      const n = Number(value);
      const date = new Date(n < 1e12 ? n * 1000 : n);
      return Number.isNaN(date.getTime()) ? "Not scheduled" : date.toLocaleString();
    },

    memoryPolicyUptimeLabel() {
      const seconds = Number(this.memoryPolicy.process?.uptime_seconds);
      if (!Number.isFinite(seconds) || seconds < 0) return "Unknown";
      if (seconds < 90) return `${Math.round(seconds)}s`;
      if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
      if (seconds < 172800) return `${(seconds / 3600).toFixed(1)}h`;
      return `${(seconds / 86400).toFixed(1)}d`;
    },

    memoryPolicyReleaseCountLabel() {
      const count = Number(this.memoryPolicy.release_count) || 0;
      const since = this.memoryPolicy.counters_since;
      if (!since) return String(count);
      // "0" on its own is ambiguous: it can mean the idle-release thread never
      // fired, or that a restart zeroed the counter minutes ago.
      return `${count} since ${this.memoryPolicyTime(since)}`;
    },

    memoryModelsLabel() {
      const values = this.memoryPolicy.loaded_models || [];
      if (!values.length) return "None loaded";
      return values.map((item) => `${String(item[0]).split("/").pop()} · ${item[1]}`).join(" + ");
    },

    async saveMemoryPolicy() {
      this.memoryPolicy.busy = true;
      this.memoryPolicy.message = "Saving memory mode…";
      this.memoryPolicy.messageKind = "info";
      try {
        const r = await fetch("/api/memory-policy", {
          method: "PUT", headers: { "content-type": "application/json" },
          body: JSON.stringify(this.memoryPolicy.draft),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || ("HTTP " + r.status));
        Object.assign(this.memoryPolicy, data, {
          loaded: true, draft: { mode: data.mode }, dirty: false,
          message: "Memory mode saved.", messageKind: "success",
        });
      } catch (e) {
        this.memoryPolicy.message = String(e.message || e);
        this.memoryPolicy.messageKind = "error";
      } finally {
        this.memoryPolicy.busy = false;
      }
    },

    async releaseMemory() {
      this.memoryPolicy.busy = true;
      this.memoryPolicy.message = "Releasing local voice and transcription memory…";
      this.memoryPolicy.messageKind = "info";
      try {
        const r = await fetch("/api/memory/release", { method: "POST" });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || ("HTTP " + r.status));
        const message = data.last_release_details?.released
          ? "TTS and transcription models unloaded; accelerator caches cleared."
          : "Allocator caches cleared; no local voice model was loaded.";
        Object.assign(this.memoryPolicy, data, { loaded: true, message, messageKind: "success" });
        this.pushToast({ kind: "success", icon: "✓", title: "Memory released", body: message });
      } catch (e) {
        this.memoryPolicy.message = String(e.message || e);
        this.memoryPolicy.messageKind = "error";
        this.pushToast({ kind: "error", icon: "✗", title: "Couldn't release memory", body: this.memoryPolicy.message });
      } finally {
        this.memoryPolicy.busy = false;
      }
    },

    async refreshConnectivity() {
      try {
        const r = await fetch("/api/connectivity");
        const data = await r.json();
        Object.assign(this.conn, data);
      } catch { /* keep last */ }
    },

    async saveSettings() {
      const token = (this.settings.tokenInput || "").trim();
      if (!token) {
        this.settings.message = "Paste a token first (it should start with hf_…).";
        this.settings.messageKind = "error";
        return;
      }
      this.settings.busy = true;
      this.settings.message = "";
      try {
        const r = await fetch("/api/settings", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ hf_token: token }),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || ("HTTP " + r.status));
        this.settings.hf_token_set = !!data.hf_token_set;
        this.settings.hf_token_masked = data.hf_token_masked || "";
        this.settings.tokenInput = "";       // clear the input after save
        this.settings.showToken = false;
        this.settings.message = `Saved. Future downloads will use this token automatically.`;
        this.settings.messageKind = "success";
        this.pushToast({ kind: "success", icon: "✓", title: "HF token saved",
          body: this.settings.hf_token_masked });
      } catch (e) {
        this.settings.message = String(e.message || e);
        this.settings.messageKind = "error";
        this.pushToast({ kind: "error", icon: "✗", title: "Couldn't save token",
          body: this.settings.message });
      } finally {
        this.settings.busy = false;
      }
    },

    async testToken() {
      // Test the input field if non-empty; otherwise test the saved token.
      const candidate = (this.settings.tokenInput || "").trim();
      this.settings.busy = true;
      this.settings.message = "Testing…";
      this.settings.messageKind = "info";
      try {
        const r = await fetch("/api/settings/test-hf-token", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(candidate ? { hf_token: candidate } : {}),
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || ("HTTP " + r.status));
        const who = data.name || "your account";
        this.settings.message = `✓ Valid. Logged in as ${who}${data.type ? " (" + data.type + ")" : ""}.`;
        this.settings.messageKind = "success";
        this.pushToast({ kind: "success", icon: "✓", title: "Token valid",
          body: `Hi ${who}` });
      } catch (e) {
        this.settings.message = `✗ ${e.message || e}`;
        this.settings.messageKind = "error";
        this.pushToast({ kind: "error", icon: "✗", title: "Token invalid",
          body: this.settings.message });
      } finally {
        this.settings.busy = false;
      }
    },

    async clearToken() {
      if (!await this.askConfirm("Remove saved token?", "Downloads will fall back to anonymous mode — lower rate limits and no gated repos.", "Remove token")) return;
      this.settings.busy = true;
      this.settings.message = "";
      try {
        const r = await fetch("/api/settings", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ hf_token: "" }),
        });
        const data = await r.json();
        this.settings.hf_token_set = !!data.hf_token_set;
        this.settings.hf_token_masked = data.hf_token_masked || "";
        this.settings.message = "Token cleared.";
        this.settings.messageKind = "info";
        this.pushToast({ kind: "info", icon: "🧹", title: "HF token cleared" });
      } catch (e) {
        this.settings.message = String(e.message || e);
        this.settings.messageKind = "error";
      } finally {
        this.settings.busy = false;
      }
    },

    async clearFinishedDownloads() {
      try {
        const r = await fetch("/api/downloads", { method: "DELETE" });
        const data = await r.json().catch(() => ({}));
        // Stream will refresh the list on next tick; do an optimistic prune too
        // so the UI feels snappy.
        this.jobs = this.jobs.filter(j => !["done", "error", "cancelled"].includes(j.state));
        this.pushToast({ kind: "info", icon: "🧹", title: `Cleared ${data.cleared ?? 0} finished` });
      } catch (e) {
        this.pushToast({ kind: "error", icon: "✗", title: "Couldn't clear downloads", body: String(e) });
      }
    },

    // ──────── imports flow ────────
    async scanImports() {
      try {
        const r = await fetch("/api/imports/scan");
        const data = await r.json();
        this.candidates = data.candidates || [];
      } catch { /* keep last */ }
    },

    async submitImport(mode = "link") {
      this.importMessage = "";
      this.importResult = null;
      if (mode === "move") {
        const sp = this.importForm.source_path || "(empty)";
        if (!await this.askConfirm(
          "Move into HF cache?",
          `${sp}\n\nThis physically relocates the folder — the source path will be gone afterwards.`,
          "Move"
        )) {
          return;
        }
      }
      try {
        const r = await fetch("/api/imports", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ ...this.importForm, mode }),
        });
        const data = await r.json();
        if (!r.ok) {
          this.importMessage = data.detail || "Import failed.";
          this.importMessageKind = "error";
          this.pushToast({ kind: "error", icon: "✗", title: "Import failed",
            body: data.detail || "(see network tab)" });
          return;
        }
        const verb = data.mode === "move" ? "Moved" : "Linked";
        this.importMessage = `${verb} ${data.repo}`;
        this.importMessageKind = "success";
        this.importResult = data;
        this.pushToast({
          kind: "success", icon: "✓",
          title: `${verb} ${data.repo}`,
          body: `→ ${data.target}`,
        });
        this.importForm = { source_path: "", repo: "" };
        await this.refreshCatalog();
      } catch (e) {
        this.importMessage = String(e);
        this.importMessageKind = "error";
        this.pushToast({ kind: "error", icon: "✗", title: "Import failed", body: String(e) });
      }
    },

    async linkCandidate(c) {
      this.importForm.source_path = c.source_path;
      this.importForm.repo = c.repo;
      await this.submitImport("link");
      await this.scanImports();
    },

    async moveCandidate(c) {
      this.importForm.source_path = c.source_path;
      this.importForm.repo = c.repo;
      await this.submitImport("move");
      await this.scanImports();
    },

    // ──────── generate flow ────────
    // ──────── voice library ────────
    async refreshVoices() {
      try {
        const r = await fetch("/api/voices");
        if (!r.ok) return;
        const data = await r.json();
        this.voices = data.voices || [];
      } catch { /* keep last */ }
    },

    get canSubmitVoice() {
      const u = this.voiceUploader;
      if (!u.audioBlob) return false;
      if (!u.name.trim()) return false;
      if (!u.language) return false;
      if (!u.gender) return false;
      if (!u.license) return false;
      if (!u.permission_acknowledged) return false;
      return true;
    },

    openVoiceUploader() {
      this.resetVoiceUploader();
      this.voiceUploader.open = true;
    },

    closeVoiceUploader() {
      this._recCleanup();
      this.clearVoiceUploaderAudio();
      this.voiceUploader.open = false;
    },

    resetVoiceUploader() {
      this.clearVoiceUploaderAudio();
      Object.assign(this.voiceUploader, {
        uploading: false,
        transcribing: false,
        error: "",
        name: "",
        language: "en",
        gender: "f",
        license: "self-owned",
        source_url: "",
        notes: "",
        transcript: "",
        permission_acknowledged: false,
      });
    },

    clearVoiceUploaderAudio() {
      const u = this.voiceUploader;
      if (u.audioPreviewUrl) {
        try { URL.revokeObjectURL(u.audioPreviewUrl); } catch { /* ignore */ }
      }
      u.audioBlob = null;
      u.audioFilename = "";
      u.audioSizeBytes = 0;
      u.audioPreviewUrl = "";
      u.dragOver = false;
    },

    _acceptVoiceFile(file) {
      if (!file) return;
      // Light MIME / extension sniff — actual format validation happens server-side.
      const okExts = [".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac"];
      const lower = (file.name || "").toLowerCase();
      const hasOkExt = okExts.some(e => lower.endsWith(e));
      const looksAudio = (file.type || "").startsWith("audio/");
      if (!hasOkExt && !looksAudio) {
        this.voiceUploader.error = "Not an audio file. Use WAV / MP3 / M4A / FLAC / OGG / OPUS / AAC.";
        return;
      }
      this.clearVoiceUploaderAudio();
      this.voiceUploader.error = "";
      this.voiceUploader.audioBlob = file;
      this.voiceUploader.audioFilename = file.name || "reference.wav";
      this.voiceUploader.audioSizeBytes = file.size || 0;
      this.voiceUploader.audioPreviewUrl = URL.createObjectURL(file);
    },

    handleVoiceDrop(event) {
      this.voiceUploader.dragOver = false;
      const file = event.dataTransfer?.files?.[0];
      this._acceptVoiceFile(file);
    },

    handleVoiceFileInput(event) {
      const file = event.target.files?.[0];
      this._acceptVoiceFile(file);
      // Reset the input so picking the same file twice still triggers @change.
      try { event.target.value = ""; } catch { /* ignore */ }
    },

    async transcribeVoiceClip() {
      const u = this.voiceUploader;
      if (!u.audioBlob || u.transcribing) return;
      u.transcribing = true;
      u.error = "";
      try {
        // The Voices tab can be opened before the Models tab has populated STT
        // state, so make sure we have a current availability/model list first.
        if (this.stt.available === null || !this.stt.models.length) {
          await this.refreshTranscribe();
        }
        if (!this.stt.available) {
          throw new Error("Transcription is unavailable. Check the Transcriber setup in Models first.");
        }

        // Prefer the selected model, but fall back to any already-downloaded
        // transcription model so this one-click helper does not require setup
        // in another tab.
        let model = this.stt.models.find(m => m.repo === this.stt.model);
        if (!model?.cached) {
          model = this.stt.models.find(m => m.cached);
          if (model) this.stt.model = model.repo;
        }
        if (!model?.cached) {
          throw new Error("Download a transcription model from Models → Transcriber, then try again.");
        }

        const fd = new FormData();
        fd.append("file", u.audioBlob, u.audioFilename || "reference.wav");
        fd.append("model", model.repo);
        if (u.language) fd.append("language", u.language);
        const r = await fetch("/api/transcribe", { method: "POST", body: fd });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          u.error = (r.status === 409 ? "Model not downloaded yet. " : "")
            + this._formatApiError(err, r.status);
          return;
        }
        const data = await r.json();
        const text = (data.text || "").trim();
        if (!text) throw new Error("The transcription model did not detect speech in this clip.");
        u.transcript = text;
        this.pushToast({ kind: "success", icon: "📝", title: "Transcript ready",
          body: `Review it below before adding ${u.name ? `“${u.name}”` : "the voice"} to your library.` });
      } catch (e) {
        u.error = String(e);
      } finally {
        u.transcribing = false;
      }
    },

    async submitVoiceUpload() {
      const u = this.voiceUploader;
      if (!this.canSubmitVoice) return;
      u.uploading = true;
      u.error = "";
      try {
        const fd = new FormData();
        fd.append("audio", u.audioBlob, u.audioFilename);
        fd.append("name", u.name);
        fd.append("language", u.language);
        fd.append("gender", u.gender);
        fd.append("license", u.license);
        fd.append("source_url", u.source_url || "");
        fd.append("notes", u.notes || "");
        fd.append("transcript", u.transcript || "");
        fd.append("permission_acknowledged", String(!!u.permission_acknowledged));
        const r = await fetch("/api/voices", { method: "POST", body: fd });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          u.error = this._formatApiError(err, r.status);
          return;
        }
        const { voice } = await r.json();
        this.voices = [voice, ...this.voices];
        this.pushToast({ kind: "success", icon: "🎙️", title: "Voice added",
          body: voice.name });
        this.closeVoiceUploader();
      } catch (e) {
        u.error = String(e);
      } finally {
        u.uploading = false;
      }
    },

    // ──────── voice upload source switcher ────────
    setVoiceSource(src) {
      // Cancel any active recording when switching tabs.
      if (this.voiceUploader.source === "record" && src !== "record") {
        this._recCleanup();
      }
      this.voiceUploader.source = src;
      this.voiceUploader.error = "";
    },

    // ──────── browser-record (MediaRecorder + WAV encoding) ────────
    async startRecording() {
      const u = this.voiceUploader;
      u.recordError = "";
      u.recordPhase = "requesting";

      // 1. Request mic
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
      } catch (e) {
        u.recordError =
          "Microphone access denied or unavailable. " +
          "If your browser blocked it, look for the mic icon in the address bar and allow access. " +
          "(Error: " + (e.message || e.name || e) + ")";
        u.recordPhase = "error";
        return;
      }
      this._rec_stream = stream;

      // 2. Set up MediaRecorder. Browser picks the encoding (usually webm/opus
      //    on Chrome/Edge, mp4/aac on Safari). We re-encode to WAV after stop.
      let recorder;
      try {
        // Try preferred mimeType, fall back to default if unsupported.
        const preferred = "audio/webm";
        const mime = MediaRecorder.isTypeSupported?.(preferred) ? preferred : "";
        recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      } catch (e) {
        this._recCleanup();
        u.recordError = "MediaRecorder failed to initialize: " + (e.message || e);
        u.recordPhase = "error";
        return;
      }
      this._rec_mediaRecorder = recorder;
      this._rec_chunks = [];
      recorder.ondataavailable = (ev) => {
        if (ev.data && ev.data.size > 0) this._rec_chunks.push(ev.data);
      };
      recorder.onstop = () => { this._recOnStop(); };

      // 3. VU meter setup via Web Audio API.
      try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        const ctx = new Ctx();
        const src = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 1024;
        src.connect(analyser);
        this._rec_audioContext = ctx;
        this._rec_analyser = analyser;
      } catch (e) {
        // VU meter is nice-to-have; recording still works if this fails.
        console.warn("VU meter setup failed:", e);
      }

      // 4. 3-2-1 countdown, then start the actual capture.
      u.recordPhase = "countdown";
      u.recordCountdown = 3;
      this._rec_countdownTimer = setInterval(() => {
        u.recordCountdown -= 1;
        if (u.recordCountdown <= 0) {
          clearInterval(this._rec_countdownTimer);
          this._rec_countdownTimer = null;
          this._startCapture();
        }
      }, 700);   // a tick under 1s — feels snappy without being rushed
    },

    _startCapture() {
      const u = this.voiceUploader;
      u.recordPhase = "recording";
      u.recordElapsed = 0;
      u.recordLevel = 0;
      this._rec_startTime = performance.now();

      // Start MediaRecorder. Chunks accumulate in _rec_chunks via ondataavailable.
      try {
        this._rec_mediaRecorder.start();
      } catch (e) {
        u.recordError = "Failed to start recorder: " + (e.message || e);
        u.recordPhase = "error";
        this._recCleanup();
        return;
      }

      // VU meter polling (animation frame loop — cheap).
      const analyser = this._rec_analyser;
      const buf = analyser ? new Uint8Array(analyser.frequencyBinCount) : null;
      const tickLevel = () => {
        if (u.recordPhase !== "recording") return;
        if (analyser && buf) {
          analyser.getByteTimeDomainData(buf);
          // Compute RMS over the window, normalize to 0-1.
          let sum = 0;
          for (let i = 0; i < buf.length; i++) {
            const v = (buf[i] - 128) / 128;
            sum += v * v;
          }
          const rms = Math.sqrt(sum / buf.length);
          // Light visual scaling so quiet voices still show movement.
          u.recordLevel = Math.min(1, rms * 2.5);
        }
        this._rec_levelTimer = requestAnimationFrame(tickLevel);
      };
      tickLevel();

      // Elapsed timer + auto-stop at max.
      this._rec_elapsedTimer = setInterval(() => {
        const elapsedMs = performance.now() - this._rec_startTime;
        u.recordElapsed = Math.min(u.recordMaxSeconds, elapsedMs / 1000);
        if (u.recordElapsed >= u.recordMaxSeconds) {
          this.stopRecording();
        }
      }, 100);
    },

    stopRecording() {
      const u = this.voiceUploader;
      if (u.recordPhase !== "recording") return;
      // The recorder's onstop handler does the heavy lifting (encode → WAV).
      try {
        this._rec_mediaRecorder.stop();
      } catch (e) {
        u.recordError = "Stop failed: " + (e.message || e);
        u.recordPhase = "error";
        this._recCleanup();
      }
    },

    async _recOnStop() {
      const u = this.voiceUploader;
      // Stop timers + stream tracks; keep AudioContext briefly for decoding.
      if (this._rec_elapsedTimer) { clearInterval(this._rec_elapsedTimer); this._rec_elapsedTimer = null; }
      if (this._rec_levelTimer) { cancelAnimationFrame(this._rec_levelTimer); this._rec_levelTimer = null; }
      if (this._rec_stream) {
        for (const t of this._rec_stream.getTracks()) t.stop();
      }

      // Concatenate the captured chunks into a single Blob.
      const recordedBlob = new Blob(this._rec_chunks, {
        type: this._rec_mediaRecorder.mimeType || "audio/webm",
      });
      this._rec_chunks = [];

      // Decode the captured Blob → AudioBuffer → re-encode as WAV. This way
      // the backend always sees a WAV file regardless of which browser the
      // user is on (Chrome → webm/opus, Safari → mp4/aac, etc.).
      let wavBlob;
      try {
        const arrayBuf = await recordedBlob.arrayBuffer();
        const ctx = this._rec_audioContext || new (window.AudioContext || window.webkitAudioContext)();
        // decodeAudioData wants an ArrayBuffer it can detach; use a copy so
        // we don't trip "detached buffer" issues on retries.
        const audioBuf = await ctx.decodeAudioData(arrayBuf.slice(0));
        // Downsample to 24 kHz mono via OfflineAudioContext — gives a sensible
        // file size + matches the sample rate of most TTS engines.
        const targetSr = 24000;
        const offline = new OfflineAudioContext(1, Math.ceil(audioBuf.duration * targetSr), targetSr);
        const src = offline.createBufferSource();
        src.buffer = audioBuf;
        src.connect(offline.destination);
        src.start(0);
        const rendered = await offline.startRendering();
        wavBlob = this._encodeWav(rendered);
      } catch (e) {
        u.recordError = "Failed to encode recording: " + (e.message || e);
        u.recordPhase = "error";
        this._recCleanup();
        return;
      }

      // Stage the WAV as the upload blob, transition to preview.
      this.clearVoiceUploaderAudio();
      u.audioBlob = wavBlob;
      u.audioFilename = "recorded.wav";
      u.audioSizeBytes = wavBlob.size;
      u.audioPreviewUrl = URL.createObjectURL(wavBlob);
      u.recordPhase = "preview";

      // AudioContext + stream cleanup AFTER decoding (we needed the ctx).
      if (this._rec_audioContext) {
        try { await this._rec_audioContext.close(); } catch {}
        this._rec_audioContext = null;
      }
      this._rec_stream = null;
      this._rec_mediaRecorder = null;
      this._rec_analyser = null;
    },

    discardRecording() {
      this.clearVoiceUploaderAudio();
      this.voiceUploader.recordPhase = "idle";
      this.voiceUploader.recordError = "";
    },

    _recCleanup() {
      // Hard-stop everything. Used when the user switches tabs or cancels.
      if (this._rec_elapsedTimer)   { clearInterval(this._rec_elapsedTimer); this._rec_elapsedTimer = null; }
      if (this._rec_levelTimer)     { cancelAnimationFrame(this._rec_levelTimer); this._rec_levelTimer = null; }
      if (this._rec_countdownTimer) { clearInterval(this._rec_countdownTimer); this._rec_countdownTimer = null; }
      if (this._rec_mediaRecorder && this._rec_mediaRecorder.state !== "inactive") {
        try { this._rec_mediaRecorder.stop(); } catch {}
      }
      if (this._rec_stream) {
        for (const t of this._rec_stream.getTracks()) t.stop();
        this._rec_stream = null;
      }
      if (this._rec_audioContext) {
        try { this._rec_audioContext.close(); } catch {}
        this._rec_audioContext = null;
      }
      this._rec_mediaRecorder = null;
      this._rec_analyser = null;
      this._rec_chunks = [];
      this.voiceUploader.recordPhase = "idle";
    },

    /**
     * Encode a Web Audio AudioBuffer as a 16-bit PCM WAV Blob. Plain old WAV
     * header + interleaved samples — no external library needed. Mono only
     * (we downsampled to 1ch in the OfflineAudioContext above).
     */
    _encodeWav(audioBuffer) {
      const numChannels = 1;
      const sampleRate = audioBuffer.sampleRate;
      const samples = audioBuffer.getChannelData(0);
      const numSamples = samples.length;

      const bytesPerSample = 2;
      const blockAlign = numChannels * bytesPerSample;
      const byteRate = sampleRate * blockAlign;
      const dataSize = numSamples * blockAlign;
      const buffer = new ArrayBuffer(44 + dataSize);
      const view = new DataView(buffer);

      const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
      writeStr(0,  "RIFF");
      view.setUint32(4,  36 + dataSize, true);
      writeStr(8,  "WAVE");
      writeStr(12, "fmt ");
      view.setUint32(16, 16, true);              // PCM chunk size
      view.setUint16(20, 1, true);               // PCM format
      view.setUint16(22, numChannels, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, byteRate, true);
      view.setUint16(32, blockAlign, true);
      view.setUint16(34, 16, true);              // bits per sample
      writeStr(36, "data");
      view.setUint32(40, dataSize, true);

      // Interleaved sample data — clamp float [-1,1] to int16 range.
      let off = 44;
      for (let i = 0; i < numSamples; i++) {
        const s = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
        off += 2;
      }
      return new Blob([buffer], { type: "audio/wav" });
    },

    // ──────── public-domain seed catalog ────────
    async openSeedCatalog() {
      this.seedCatalogOpen = true;
      if (this.seedCatalog.length > 0) return;
      this.seedCatalogLoading = true;
      try {
        const r = await fetch("/api/voices/seed-catalog");
        if (!r.ok) return;
        const data = await r.json();
        this.seedCatalog = data.entries || [];
      } catch { /* keep last */ }
      finally { this.seedCatalogLoading = false; }
    },
    closeSeedCatalog() {
      this.seedCatalogOpen = false;
    },
    async addFromSeed(entry) {
      if (this.seedCatalogAddingId) return;
      this.seedCatalogAddingId = entry.id;
      try {
        const r = await fetch("/api/voices/from-seed", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ seed_id: entry.id }),
        });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          this.pushToast({ kind: "error", icon: "✗", title: "Couldn't add voice",
            body: this._formatApiError(err, r.status) });
          return;
        }
        const { voice } = await r.json();
        this.voices = [voice, ...this.voices];
        this.pushToast({ kind: "success", icon: "🎙️", title: "Added from public-domain catalog",
          body: voice.name });
      } catch (e) {
        this.pushToast({ kind: "error", icon: "✗", title: "Couldn't add voice", body: String(e) });
      } finally {
        this.seedCatalogAddingId = null;
      }
    },

    // ── Voice editor (PATCH /api/voices/{id}) ──
    // Most common use case: a voice was uploaded without a transcript, and
    // the user now wants to use it with F5-TTS (which requires a transcript).
    // Also lets users fix typos in name / change license / etc. without
    // re-uploading the audio.
    async openVoiceEditor(voice) {
      // Fetch the transcript fresh from the API so we get current state
      // (the listing response doesn't include the transcript body).
      let transcript = "";
      try {
        const r = await fetch("/api/voices/" + encodeURIComponent(voice.id));
        if (r.ok) {
          const data = await r.json();
          // GET /api/voices/{id} returns the voice flat at the top level
          // and tucks the transcript into a separate `transcript` field.
          transcript = data.transcript || "";
        }
      } catch {}
      Object.assign(this.voiceEditor, {
        open: true,
        saving: false,
        error: "",
        voice,
        name: voice.name || "",
        language: voice.language || "en",
        gender: voice.gender || "f",
        license: voice.license || "self-owned",
        notes: voice.notes || "",
        transcript,
      });
    },
    closeVoiceEditor() {
      this.voiceEditor.open = false;
      this.voiceEditor.voice = null;
    },
    async submitVoiceEdit() {
      const e = this.voiceEditor;
      if (!e.voice) return;
      e.saving = true;
      e.error = "";
      try {
        // PATCH with only the editable fields. Backend treats missing keys
        // as "unchanged" and empty strings as "clear" (for notes/transcript).
        const body = {
          name: e.name,
          language: e.language,
          gender: e.gender,
          license: e.license,
          notes: e.notes,
          transcript: e.transcript,
        };
        const r = await fetch("/api/voices/" + encodeURIComponent(e.voice.id), {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          e.error = this._formatApiError(err, r.status);
          return;
        }
        const data = await r.json();
        // Replace the local entry with the updated server copy.
        const updated = data.voice;
        const idx = this.voices.findIndex(v => v.id === updated.id);
        if (idx >= 0) this.voices.splice(idx, 1, updated);
        this.pushToast({
          kind: "info", icon: "✓",
          title: "Voice updated",
          body: updated.name + (updated.has_transcript ? " · transcript saved" : ""),
        });
        this.closeVoiceEditor();
      } catch (err) {
        e.error = String(err);
      } finally {
        e.saving = false;
      }
    },

    async deleteVoice(voice) {
      if (!await this.askConfirm(`Remove "${voice.name}"?`, "The reference clip is deleted from disk; engines that cached its embeddings will lose them.", "Remove voice")) return;
      try {
        const r = await fetch("/api/voices/" + encodeURIComponent(voice.id), { method: "DELETE" });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          this.pushToast({ kind: "error", icon: "✗", title: "Couldn't delete voice",
            body: this._formatApiError(err, r.status) });
          return;
        }
        this.voices = this.voices.filter(v => v.id !== voice.id);
        this.pushToast({ kind: "info", icon: "🗑", title: "Voice removed", body: voice.name });
      } catch (e) {
        this.pushToast({ kind: "error", icon: "✗", title: "Couldn't delete voice", body: String(e) });
      }
    },

    genderLabel(g) {
      return ({ m: "♂ male", f: "♀ female", n: "neutral" })[g] || g;
    },

    licenseLabel(lic) {
      return ({
        "self-owned":    "self-owned",
        "permission":    "permission",
        "public-domain": "public domain",
        "unknown":       "unknown",
      })[lic] || lic;
    },

    async refreshDiagnostics() {
      try {
        const r = await fetch("/api/generate/diagnostics");
        if (!r.ok) return;
        const data = await r.json();
        this.diag.device = data.device || null;
        this.diag.packages = data.packages || [];
        this.diag.engines = data.engines || [];
        this.diag.any_missing = !!data.any_missing;
        this.diag.ready_count = data.ready_count || 0;
        this.diag.total_engines = data.total_engines || 0;
        this.diag._lastFetched = Date.now();
      } catch { /* keep last */ }
    },

    async refreshGenAvailability() {
      try {
        const r = await fetch("/api/generate/availability");
        const data = await r.json();
        this.gen.available = !!data.available;
        this.gen.kokoro_available = !!data.kokoro_available;
        this.gen.qwen3_available = !!data.qwen3_available;
        this.gen.diffusers_available = !!data.diffusers_available;
        this.gen.error = data.error;
        this.gen.device = data.device;
        this.gen.kokoro_voices = data.kokoro_voices || [];
        this.gen.qwen3_preset_speakers = data.qwen3_preset_speakers || [];
        this.gen.voxtral_voices = data.voxtral_voices || [];
        this.gen.marvis_voices = data.marvis_voices || [];
        this.gen.orpheus_voices = data.orpheus_voices || [];
        this.gen.vibevoice_voices = data.vibevoice_voices || [];
        this.gen.qwen3_voice_design_examples = data.qwen3_voice_design_examples || [];
        this.gen.voxcpm_available = !!data.voxcpm_available;
        this.gen.voxcpm_emotion_examples = data.voxcpm_emotion_examples || [];
        this.gen.bark_available = !!data.bark_available;
        this.gen.bark_voice_presets = data.bark_voice_presets || [];
        this.gen.bark_tags = data.bark_tags || [];
        this.gen.omnivoice_available = !!data.omnivoice_available;
        this.gen.f5_tts_available = !!data.f5_tts_available;
        this.gen.lang_names = data.lang_names || {};
        this.gen.wired_families = data.wired_families || [];
      } catch {
        this.gen.available = false;
      }
    },

    // ──────── TTS helpers ────────
    isQwen3(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "qwen3-tts";
    },
    isVoxCPMMlx(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "voxcpm-mlx";
    },
    isBark(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "bark";
    },
    // ── New mlx-audio families (Phase D). All ride the unified _generate_mlx_audio
    //    backend worker — UI helpers exist for fine-grained control rendering.
    isKokoroMlx(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "kokoro-mlx";
    },
    isChatterboxMlx(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "chatterbox-mlx";
    },
    chatterboxLanguageCodes() {
      const model = (this.models || []).find(x => x.repo === this.gen.repo);
      return model?.language_support?.enumeration_status === "exact"
        ? (model.language_support.codes || []) : [];
    },
    languageSupportLabel(model) {
      const support = model?.language_support;
      if (!support) return (model?.languages || []).join(", ");
      if (support.enumeration_status === "exact") {
        return `${(support.codes || []).length} languages · exact`;
      }
      if (support.enumeration_status === "claimed_count") {
        return `${support.claimed_count} languages · claimed`;
      }
      if (support.enumeration_status === "claimed_lower_bound") {
        return `${support.claimed_lower_bound}+ languages · claimed`;
      }
      return "Language coverage not listed";
    },
    isSparkTtsMlx(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "spark-tts-mlx";
    },
    isOrpheus(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "orpheus";
    },
    isOmniVoice(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "omnivoice";
    },
    isFishAudio(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "fish-audio-mlx";
    },
    isAudio8(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "arktts";
    },
    isMossTtsNano(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "moss-tts-nano";
    },
    isEchoTts(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "echo-tts";
    },
    isF5TTS(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "f5-tts";
    },
    isKittenTts(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "kittentts";
    },
    isVibeVoice(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "vibevoice";
    },
    isVoxtral(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "voxtral-tts";
    },
    isMarvis(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      return m?.family === "marvis";
    },
    /** True for any mlx-audio-backed family that takes a free-form preset voice
     *  name (no library cloning, no reference clip). Used for the simple
     *  voice-picker UI block. */
    isMlxVoicePicker(repo) {
      return this.isKokoroMlx(repo) || this.isOrpheus(repo)
          || this.isKittenTts(repo) || this.isVibeVoice(repo)
          || this.isVoxtral(repo) || this.isMarvis(repo);
    },
    /** Verified preset-voice roster for the current voice-picker family, or []
     *  when we don't have a confirmed list (KittenTTS → free-text).
     *  Drives the clickable voice buttons. Each entry: {id, label, lang, gender}. */
    presetVoiceOptions(repo) {
      if (this.isVoxtral(repo))   return this.gen.voxtral_voices || [];
      if (this.isMarvis(repo))    return this.gen.marvis_voices || [];
      if (this.isOrpheus(repo))   return this.gen.orpheus_voices || [];
      if (this.isVibeVoice(repo)) return this.gen.vibevoice_voices || [];
      if (this.isKokoroMlx(repo)) return this.kokoroVoicesForLanguage();
      return [];
    },
    /** True when the current family has clickable voice buttons available. */
    hasVoiceButtons(repo) {
      return this.presetVoiceOptions(repo).length > 0;
    },
    /** Set the active preset voice from a button click. */
    selectVoice(id) {
      this.gen.voice = id;
      if (this.isKokoroMlx(this.gen.repo)) {
        this.gen.kokoro_language = id.slice(0, 1);
        if (this.gen.kokoro_blend_voice.slice(0, 1) !== this.gen.kokoro_language) {
          this.gen.kokoro_blend_voice = "";
        }
      }
    },
    /** True for any mlx-audio-backed family that supports voice cloning from
     *  the Voices library. Used to show the voice-library picker. */
    isMlxCloner(repo) {
      return this.isVoxCPMMlx(repo) || this.isChatterboxMlx(repo)
          || this.isSparkTtsMlx(repo) || this.isOmniVoice(repo)
          || this.isFishAudio(repo) || this.isAudio8(repo) || this.isMossTtsNano(repo)
          || this.isEchoTts(repo)
          || (this.models || []).find(x => x.repo === repo)?.family === "longcat-audiodit";
    },
    /** Group Bark voice presets by language for the optgroup picker. */
    barkPresetsByLang() {
      const out = {};
      for (const v of (this.gen.bark_voice_presets || [])) {
        (out[v.lang] ||= []).push(v);
      }
      return out;
    },
    /** Insert a Bark tag at the current cursor position in the text-to-speak
     *  textarea. Falls back to appending if we can't find the cursor. */
    insertBarkTag(tag) {
      const textarea = document.querySelector("textarea.tts-text");
      if (!textarea) {
        const cur = this.gen.text || "";
        const sep = cur && !cur.endsWith(" ") ? " " : "";
        this.gen.text = cur + sep + tag + " ";
        return;
      }
      const start = textarea.selectionStart ?? this.gen.text.length;
      const end   = textarea.selectionEnd   ?? this.gen.text.length;
      const before = this.gen.text.slice(0, start);
      const after  = this.gen.text.slice(end);
      // Insert with a space before if needed (so [laughter] doesn't fuse to
      // the previous word). No trailing space — let the user keep typing.
      const needsPad = before && !before.endsWith(" ");
      const insert = (needsPad ? " " : "") + tag;
      this.gen.text = before + insert + after;
      // Restore focus + put the cursor right after the inserted tag.
      this.$nextTick?.(() => {
        const newPos = start + insert.length;
        textarea.focus();
        try { textarea.setSelectionRange(newPos, newPos); } catch {}
      });
    },
    /** Any MLX-audio-backed family. Single point of truth — keep in sync with
     *  the backend's MLX_AUDIO_FAMILIES table. */
    isMlxAudio(repo) {
      return this.isQwen3(repo) || this.isVoxCPMMlx(repo) || this.isKokoroMlx(repo)
          || this.isChatterboxMlx(repo) || this.isSparkTtsMlx(repo) || this.isOrpheus(repo)
          || this.isKittenTts(repo) || this.isVibeVoice(repo)
          || this.isVoxtral(repo) || this.isMarvis(repo) || this.isOmniVoice(repo)
          || this.isFishAudio(repo) || this.isAudio8(repo) || this.isMossTtsNano(repo)
          || this.isEchoTts(repo)
          || this.isBark(repo);
    },
    setVoxcpmEmotionExample(text) {
      this.gen.voice_design_prompt = text;
    },
    voxcpmModeLabel() {
      const hasReference = !!this.gen.voice_library_id;
      const hasTranscript = !!this.referenceTranscriptForRequest();
      const hasDesign = !!(this.gen.voice_design_prompt || "").trim();
      if (hasReference && hasTranscript && hasDesign) return "Ultimate clone + style";
      if (hasReference && hasTranscript) return "Ultimate clone";
      if (hasReference && hasDesign) return "Reference clone + style";
      if (hasReference) return "Reference clone";
      if (hasDesign) return "Voice design";
      return "Zero-shot voice";
    },
    onModelChange() {
      // The user has explicitly picked a model. Mark as authoritative so the
      // 4s catalog poll's _reconcileSelectedModel doesn't override the choice
      // if a transient catalog-refresh race makes the model briefly appear
      // not-cached. (The $watch on gen.repo also sets this, but flipping it
      // here too means we don't depend on watcher ordering.)
      this._repoUserConfirmed = true;
      // Apply per-family default knob values when the user switches engines.
      // Saves the user from having to remember each model's sweet-spot defaults.
      if (this.isVoxCPMMlx(this.gen.repo) && !this.gen.inference_timesteps) {
        this.gen.inference_timesteps = 7;
      }
      // Chatterbox-MLX reuses cfg_value as its exaggeration dial (0.0-1.0).
      // VoxCPM's default 2.0 would be clamped to 1.0 by the backend, but
      // the UI would show a confusing out-of-range value — snap to 0.5
      // (Chatterbox sweet spot per Resemble's docs) on switch.
      if (this.isChatterboxMlx(this.gen.repo)) {
        if (this.gen.cfg_value > 1.0 || this.gen.cfg_value < 0.0) {
          this.gen.cfg_value = 0.5;
        }
        if (!this.chatterboxLanguageCodes().includes(this.gen.language)) {
          this.gen.language = "en";
        }
      } else if (this.gen.cfg_value < 0.5) {
        // Coming back from Chatterbox to a VoxCPM model — restore cfg=2.0
        // if the user left a sub-VoxCPM-range value behind.
        if (this.isVoxCPMMlx(this.gen.repo)) {
          this.gen.cfg_value = 2.0;
        }
      }
      if (this.isKokoroMlx(this.gen.repo)) {
        const languages = this.kokoroLanguageOptions().map(item => item.code);
        if (!languages.includes(this.gen.kokoro_language)) this.gen.kokoro_language = "a";
        if (!this.kokoroVoicesForLanguage().some(item => item.id === this.gen.voice)) {
          this.gen.voice = this.kokoroVoicesForLanguage()[0]?.id || "af_heart";
        }
      }
    },
    /** Returns "custom" | "design" | "clone" | null based on the repo name. */
    qwen3Mode(repo) {
      if (!this.isQwen3(repo)) return null;
      const name = (repo || "").toLowerCase();
      if (name.includes("voicedesign")) return "design";
      if (name.includes("customvoice")) return "custom";
      if (name.includes("base"))        return "clone";
      return "custom";
    },
    qwen3PresetSpeakersFor(lang) {
      return (this.gen.qwen3_preset_speakers || []).filter(s => s.lang === lang);
    },
    setVoiceDesignExample(text) {
      this.gen.voice_design_prompt = text;
    },
    isModelWired(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      if (!m) return false;
      return (this.gen.wired_families || []).includes(m.family);
    },
    // ──────── per-model dependency lookup (wired to diagnostics) ────────
    modelEngine(repo) {
      const m = (this.models || []).find(x => x.repo === repo);
      if (!m) return null;
      return (this.diag.engines || []).find(e => e.family === m.family) || null;
    },
    isModelReady(repo) {
      if (!repo) return false;
      const e = this.modelEngine(repo);
      // No diagnostic data yet → don't block. We assume ready until we know
      // otherwise; the backend will still 503 on submit if it's actually broken.
      if (!e) return true;
      return !!e.ready;
    },
    modelDepsOk(repo) {
      // Packages are importable — the family just might not have a worker wired up yet.
      const e = this.modelEngine(repo);
      if (!e) return true;
      // Older backends only sent `ready` — fall back to that.
      if (typeof e.deps_ok === "boolean") return e.deps_ok;
      return !!e.ready;
    },
    modelMissingDeps(repo) {
      const e = this.modelEngine(repo);
      return e ? (e.missing || []) : [];
    },
    modelOptionLabel(m) {
      const e = (this.diag.engines || []).find(x => x.family === m.family);
      if (!e || e.ready) return m.label;
      // Distinguish "missing packages" (fixable by user) from "worker in roadmap"
      // (not the user's fault — just hasn't shipped yet).
      if (e.deps_ok === true && e.wired === false) {
        return `🕓 ${m.label} — worker in roadmap`;
      }
      return `⚠ ${m.label} — needs ${(e.missing || []).join(", ")}`;
    },
    kokoroLanguageOptions() {
      const counts = {};
      for (const voice of (this.gen.kokoro_voices || [])) counts[voice.lang] = (counts[voice.lang] || 0) + 1;
      return Object.keys(counts).map(code => ({
        code,
        label: this.gen.lang_names[code] || code.toUpperCase(),
        count: counts[code],
      }));
    },
    kokoroVoicesForLanguage() {
      return (this.gen.kokoro_voices || []).filter(voice => voice.lang === this.gen.kokoro_language);
    },
    onKokoroLanguageChange() {
      const choices = this.kokoroVoicesForLanguage();
      if (!choices.some(item => item.id === this.gen.voice)) this.gen.voice = choices[0]?.id || "";
      if (!choices.some(item => item.id === this.gen.kokoro_blend_voice)) this.gen.kokoro_blend_voice = "";
    },

    huggingFaceUrl(repo) {
      if (!repo) return "";
      return `https://huggingface.co/${repo}`;
    },
    randomTextPrompt() {
      if (!window.SAMPLE_PROMPTS || !window.SAMPLE_PROMPTS.length) return;
      let idx;
      do {
        idx = Math.floor(Math.random() * window.SAMPLE_PROMPTS.length);
      } while (window.SAMPLE_PROMPTS.length > 1 && idx === this._lastRandomPromptIndex);
      this._lastRandomPromptIndex = idx;
      this.gen.text = window.SAMPLE_PROMPTS[idx];
    },

    startGenStream() {
      if (this._genStreamHandle) this._genStreamHandle.close();
      const es = new EventSource("/api/generate/stream");
      es.addEventListener("snapshot", e => {
        try {
          const payload = JSON.parse(e.data);
          const incoming = (payload.jobs || []).slice().sort((a, b) => (b.started_at || 0) - (a.started_at || 0));

          // Detect state transitions running/queued → done/error/cancelled, fire a toast.
          for (const j of incoming) {
            const prev = this._jobStatePrev[j.id];
            const terminal = ["done", "error", "cancelled"];
            if (prev && prev !== j.state && terminal.includes(j.state) && !terminal.includes(prev)) {
              this._notifyJobFinished(j);
            }
            this._jobStatePrev[j.id] = j.state;
          }

          this.gen.jobs = incoming;
          // Keep the currentJob reference fresh so progress updates flow.
          if (this.gen.currentJob) {
            const updated = this.gen.jobs.find(j => j.id === this.gen.currentJob.id);
            if (updated) this.gen.currentJob = updated;
          }
          // If we have no current job but there's a running/done one, surface it.
          if (!this.gen.currentJob && this.gen.jobs.length) {
            this.gen.currentJob = this.gen.jobs[0];
          }
          // Manage the busy flag.
          const running = this.gen.jobs.find(j => j.state === "running" || j.state === "queued");
          this.gen.busy = !!running;
          if (running) {
            // Use the real fields the job actually has: `progress` (0..1) and
            // `started_at`. The old label read current_step/total_steps, which
            // don't exist on the job → "Generating… undefined/undefined".
            const pct = Math.round((running.progress || 0) * 100);
            const elapsed = running.started_at
              ? Math.max(0, Math.floor(Date.now() / 1000) - Math.floor(running.started_at)) : 0;
            const chunkTotal = Number(running.chunk_total || 0);
            const chunkIndex = Number(running.chunk_index || 0);
            this.gen.busyLabel = "Generating…"
              + (pct > 0 ? ` ${pct}%` : "")
              + (chunkTotal > 1 ? ` · part ${Math.max(1, chunkIndex)}/${chunkTotal}` : "")
              + (elapsed ? ` · ${elapsed}s` : "");
          }
        } catch { /* swallow */ }
      });
      es.onerror = () => { /* auto-reconnects */ };
      this._genStreamHandle = es;
    },

    _notifyJobFinished(job) {
      if (job.state === "done") {
        this.pushToast({
          kind: "success",
          icon: "✓",
          title: "Generation done",
          body: this.formatDuration(job.duration_seconds) + (job.params?.prompt ? ` · "${job.params.prompt.slice(0, 50)}"` : ""),
        });
        this._tryNativeNotification("VoiceStudio · done", job.params?.prompt?.slice(0, 80) || "");
        this._flashTabTitle("✓ Done");
        if (this.gen.autoPlay && job.output_url) {
          try { new Audio(job.output_url).play().catch(() => {}); } catch { /* ignore */ }
        }
        this.refreshOutputStats();               // a new file landed — refresh the disk figure
      } else if (job.state === "error") {
        this.pushToast({
          kind: "error",
          icon: "✗",
          title: "Generation error",
          body: job.error || "(see server terminal)",
        });
        this._tryNativeNotification("VoiceStudio · error", job.error || "");
        this._flashTabTitle("✗ Error");
      } else if (job.state === "cancelled") {
        this.pushToast({ kind: "warn", icon: "⏹", title: "Generation cancelled" });
      }
    },

    // Soft-block wrapper for hard-cap engines (Bark / Orpheus / XTTS). When
    // the user's text exceeds the family's soft_max_chars, the first click
    // arms `gen.overCapConfirmed`; a second click then calls submitGenerate.
    // Engines with auto-split / unlimited chunking skip this entirely.
    safeSubmit() {
      if (!this.canSubmit) return;
      if (this.textHardCapExceeded && !this.gen.overCapConfirmed) {
        this.gen.overCapConfirmed = true;
        return;
      }
      this.submitGenerate();
    },

    async submitGenerate() {
      if (!this.canSubmit) return;
      if (!this.gen.available) {
        this.pushToast({ kind: "warn", icon: "⚠", title: "Engine not installed",
          body: "Click Install Generation in the Pinokio sidebar." });
        return;
      }
      if (!this.selectedModel) {
        this.pushToast({ kind: "warn", icon: "⚠", title: "Pick an available model first",
          body: "Download a model from the Models tab." });
        return;
      }
      if (!this.gen.text.trim()) return;

      this._requestNotificationPermission();
      this.gen.submitting = true;

      // Batch handling — submit N requests sequentially. Seed strategy:
      //   - If user pinned a seed (≥ 0), batch jobs get seed, seed+1, seed+2...
      //     (each one reproducible, but distinct variations).
      //   - If seed is -1 (random), each job gets its own backend-resolved
      //     random seed.
      const count = Math.max(1, Math.min(8, this.gen.batchCount | 0));
      const baseSeed = this.gen.seed;
      const usingRandomSeed = baseSeed == null || baseSeed < 0;

      const buildBody = (seedForThis) => {
        const repo = this.gen.repo;
        const mode = this.qwen3Mode(repo);

        // Voice field: passed for the MLX voice-picker families (Kokoro and
        // Orpheus) and Spark-TTS-MLX, which accepts an optional preset voice.
        const passesVoice = this.isMlxVoicePicker(repo) || this.isSparkTtsMlx(repo);

        // Instruct / voice description: Qwen3 custom (tone), Qwen3 design (full
        // prompt), VoxCPM2 (voice/style control), Spark-TTS-MLX (style hint),
        // and Orpheus (optional style nudge).
        const passesInstruct = mode === "custom" || mode === "design"
                            || this.isVoxCPMMlx(repo)
                            || this.isSparkTtsMlx(repo) || this.isOrpheus(repo)
                            || this.isFishAudio(repo);

        const passesDesignPrompt = mode === "design" || this.isVoxCPMMlx(repo)
                                || this.isSparkTtsMlx(repo) || this.isOmniVoice(repo)
                                || this.isFishAudio(repo);

        // Voice library: every cloner family + Qwen3 clone mode + F5-TTS.
        const passesLibraryVoice = mode === "clone"
                                || this.isMlxCloner(repo)
                                || this.isF5TTS(repo);

        const body = {
          repo,
          text: this.gen.text.trim(),
          voice: passesVoice
                 ? ([this.gen.voice, this.isKokoroMlx(repo) ? this.gen.kokoro_blend_voice : ""]
                    .map(value => (value || "").trim()).filter(Boolean).join(",") || null)
                 : null,
          language: (this.isKokoroMlx(repo) ? this.gen.kokoro_language : this.gen.language || "").trim() || null,
          speed: Number(this.gen.speed),
          temperature: Number(this.gen.temperature),
          seed: seedForThis,
          preset_speaker: mode === "custom" ? (this.gen.preset_speaker || null) : null,
          instruct: passesInstruct ? ((this.gen.instruct || "").trim() || null) : null,
          voice_design_prompt: passesDesignPrompt
                               ? (this.gen.voice_design_prompt || "").trim() || null
                               : null,
          voice_library_id: passesLibraryVoice ? (this.gen.voice_library_id || null) : null,
          ref_transcript: passesLibraryVoice
                          ? this.referenceTranscriptForRequest()
                          : null,
          // cfg_value doubles as Chatterbox's exaggeration knob — the backend
          // resolver re-interprets per family. inference_timesteps only matters
          // for VoxCPM v2 (uses_cfg=true).
          cfg_value: Number(this.gen.cfg_value),
          inference_timesteps: Number(this.gen.inference_timesteps),
          normalize_text: !!this.gen.normalize_text,
          voxcpm_warmup_patches: Number(this.gen.voxcpm_warmup_patches),
          voxcpm_max_tokens: Number(this.gen.voxcpm_max_tokens),
          chatterbox_cfg_weight: Number(this.gen.chatterbox_cfg_weight),
          chatterbox_repetition_penalty: Number(this.gen.chatterbox_repetition_penalty),
          chatterbox_min_p: Number(this.gen.chatterbox_min_p),
          chatterbox_top_p: Number(this.gen.chatterbox_top_p),
          omnivoice_num_steps: Number(this.gen.omnivoice_num_steps),
          omnivoice_guidance_scale: Number(this.gen.omnivoice_guidance_scale),
          omnivoice_duration_s: this.gen.omnivoice_duration_s === null
                                || this.gen.omnivoice_duration_s === ""
                                ? null : Number(this.gen.omnivoice_duration_s),
          fish_temperature: Number(this.gen.fish_temperature),
          fish_top_p: Number(this.gen.fish_top_p),
          fish_top_k: Number(this.gen.fish_top_k),
          fish_max_tokens: Number(this.gen.fish_max_tokens),
          audio8_temperature: Number(this.gen.audio8_temperature),
          audio8_top_p: Number(this.gen.audio8_top_p),
          audio8_top_k: Number(this.gen.audio8_top_k),
          audio8_max_tokens: Number(this.gen.audio8_max_tokens),
          moss_temperature: Number(this.gen.moss_temperature),
          moss_top_p: Number(this.gen.moss_top_p),
          moss_top_k: Number(this.gen.moss_top_k),
          moss_repetition_penalty: Number(this.gen.moss_repetition_penalty),
          echo_num_steps: Number(this.gen.echo_num_steps),
          echo_cfg_scale_text: Number(this.gen.echo_cfg_scale_text),
          echo_cfg_scale_speaker: Number(this.gen.echo_cfg_scale_speaker),
          bark_voice_preset: this.isBark(repo)
                             ? (this.gen.bark_voice_preset || null)
                             : null,
          bark_temperature: Number(this.gen.bark_temperature),
          bark_max_coarse_history: Number(this.gen.bark_max_coarse_history),
          bark_sliding_window_len: Number(this.gen.bark_sliding_window_len),
          bark_allow_early_stop: !!this.gen.bark_allow_early_stop,
        };

        if (this.sectionSizeControlSupported && this.gen.section_size_mode === "custom") {
          if (this.sectionSizeIsValid) body.section_max_characters = this.sectionSizeValue;
        }
        return body;
      };

      let lastJob = null;
      for (let i = 0; i < count; i++) {
        const seedForThis = usingRandomSeed ? -1 : (Number(baseSeed) + i);
        try {
          const r = await fetch("/api/generate/txt2speech", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(buildBody(seedForThis)),
          });
          if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            this.pushToast({ kind: "error", icon: "✗", title: "Submit failed",
              body: this._formatApiError(err, r.status) });
            break;
          }
          const { job } = await r.json();
          lastJob = job;
        } catch (e) {
          this.pushToast({ kind: "error", icon: "✗", title: "Submit failed",
            body: String(e) });
          break;
        }
      }

      if (lastJob) {
        this.gen.currentJob = lastJob;
        if (count > 1) {
          this.pushToast({ kind: "info", icon: "▶", title: `Queued ${count} jobs`,
            body: "They'll generate one after another. Cancel any from the queue panel." });
        }
      }
      // The SSE stream turns off busy indicators when each job finishes.
      // submitting=false just unblocks the button so the user can queue more.
      setTimeout(() => { this.gen.submitting = false; }, 300);
    },

    _formatApiError(payload, status) {
      // FastAPI returns Pydantic validation errors as detail = [{type, loc, msg, input}, ...]
      // and HTTPException errors as detail = "string". Render both readably so
      // the toast doesn't show "[object Object]".
      if (!payload || payload.detail == null) {
        return "HTTP " + status;
      }
      const d = payload.detail;
      if (typeof d === "string") return d;
      if (Array.isArray(d)) {
        return d.map(e => {
          if (!e || typeof e !== "object") return String(e);
          const path = Array.isArray(e.loc) ? e.loc.filter(x => x !== "body").join(".") : "";
          const msg = e.msg || JSON.stringify(e);
          return path ? `${path}: ${msg}` : msg;
        }).join(" · ");
      }
      try { return JSON.stringify(d); } catch { return String(d); }
    },

    /** Cancel an individual queued / running job from the queue UI. The
     *  backend's DELETE handles both cases:
     *  - queued: backend immediately flips state → "cancelled" so the UI
     *    reflects it on the next SSE snapshot (~1 s). The worker still
     *    safely no-ops when it later wakes up and sees cancel_event set.
     *  - running: mlx-audio TTS engines (Kokoro, VoxCPM, Chatterbox, Orpheus,
     *    Spark, Qwen3-TTS) are blocking synthesis calls that don't honor
     *    mid-flight cancellation. We can only set cancel_event so the result
     *    is discarded after synthesis finishes. */
    async cancelPending(job) {
      if (!job || !job.id) return;
      const wasRunning = job.state === "running";
      try {
        const r = await fetch("/api/generate/jobs/" + encodeURIComponent(job.id), { method: "DELETE" });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          this.pushToast({ kind: "warn", icon: "⚠", title: "Couldn't cancel",
            body: this._formatApiError(err, r.status) });
          return;
        }
        if (wasRunning) {
          this.pushToast({
            kind: "info", icon: "⏸",
            title: "Cancel signal sent",
            body: "Running jobs can't stop mid-synthesis (mlx-audio TTS engines don't honor cancellation). " +
                  "The result will be discarded when synthesis finishes.",
          });
        } else {
          this.pushToast({ kind: "info", icon: "✓", title: "Cancelled", body: "Queued job removed." });
        }
      } catch (e) {
        this.pushToast({ kind: "error", icon: "✗", title: "Cancel failed", body: String(e) });
      }
    },

    /** Truncate a string to N chars with an ellipsis — used in the queue UI
     *  where text lines need to stay one line. */
    truncateText(s, n = 60) {
      if (!s) return "";
      return s.length > n ? s.slice(0, n) + "…" : s;
    },

    async clearHistory() {
      // Two-click confirm instead of native confirm(): Pinokio's embedded webview
      // can silently block window.confirm() (it returns false), which made this
      // button appear to do nothing. First click arms the button; a second click
      // within 3s actually clears.
      if (!this.gen.clearArmed) {
        this.gen.clearArmed = true;
        clearTimeout(this._clearArmTimer);
        this._clearArmTimer = setTimeout(() => { this.gen.clearArmed = false; }, 3000);
        return;
      }
      clearTimeout(this._clearArmTimer);
      this.gen.clearArmed = false;
      try {
        const r = await fetch("/api/generate/jobs", { method: "DELETE" });
        if (!r.ok) throw new Error("HTTP " + r.status);
        // Backend removed the finished jobs; keep any active ones on screen.
        // The SSE stream reconciles to the trimmed list on its next tick.
        this.gen.currentJob = null;
        this.gen.jobs = (this.gen.jobs || []).filter(j => ["queued", "running", "cancelling"].includes(j.state));
        this._jobStatePrev = {};
        this.pushToast({ kind: "info", icon: "🧹", title: "History cleared",
          body: "The WAV files stay in your outputs folder." });
      } catch (e) {
        this.pushToast({ kind: "error", icon: "✗", title: "Couldn't clear history", body: String(e) });
      }
    },

    /** Open the outputs folder (where every generated WAV lands) in Finder.
     *  Derived from any generated file's absolute path, so it needs no extra
     *  endpoint and always points at the real folder on this machine. */
    openOutputsFolder() {
      const withPath = (this.gen.jobs || []).find(j => j.output_path);
      if (withPath && withPath.output_path) {
        const dir = withPath.output_path.replace(/[/\\][^/\\]+$/, "");   // strip the filename
        this.revealInFolder(dir);
      } else {
        this.pushToast({ kind: "info", icon: "📂", title: "No generations yet",
          body: "Generate something first — then this opens the folder with all your audio." });
      }
    },

    /** Delete one finished generation (removes it from history AND deletes the
     *  WAV). Two-click confirm — first click arms this row, second deletes. */
    deleteGeneration(job) {
      if (this.gen.deleteArmed !== job.id) {
        this.gen.deleteArmed = job.id;
        clearTimeout(this._deleteArmTimer);
        this._deleteArmTimer = setTimeout(() => { this.gen.deleteArmed = null; }, 3000);
        return;
      }
      clearTimeout(this._deleteArmTimer);
      this.gen.deleteArmed = null;
      this._doDeleteGeneration(job);
    },
    async _doDeleteGeneration(job) {
      try {
        const r = await fetch("/api/generate/history/" + encodeURIComponent(job.id), { method: "DELETE" });
        if (!r.ok) throw new Error("HTTP " + r.status);
        this.gen.jobs = (this.gen.jobs || []).filter(j => j.id !== job.id);
        this.refreshOutputStats();
        this.pushToast({ kind: "info", icon: "🗑", title: "Generation deleted" });
      } catch (e) {
        this.pushToast({ kind: "error", icon: "✗", title: "Couldn't delete",
          body: "This needs the latest backend — run Update once from the Pinokio sidebar." });
      }
    },

    // ──────── outputs folder disk usage ────────
    outputStats: { bytes: 0, count: 0, loaded: false },
    storagePolicy: {
      enabled: true, retention_days: 30, max_gb: 80, used_bytes: 0,
      over_limit: false, loaded: false, busy: false, message: "",
    },
    async refreshOutputStats() {
      try {
        const r = await fetch("/api/output/stats");
        if (!r.ok) return;                         // endpoint not live until next Update
        const d = await r.json();
        this.outputStats = { bytes: d.bytes || 0, count: d.count || 0, loaded: true };
      } catch { /* keep last */ }
    },
    async refreshStoragePolicy() {
      try {
        const r = await fetch("/api/storage-policy");
        if (!r.ok) return;
        const d = await r.json();
        this.storagePolicy = { ...this.storagePolicy, ...d, loaded: true, busy: false };
      } catch { /* keep last */ }
    },
    async saveStoragePolicy() {
      this.storagePolicy.busy = true;
      this.storagePolicy.message = "Saving policy…";
      try {
        const r = await fetch("/api/storage-policy", {
          method: "PUT", headers: { "content-type": "application/json" },
          body: JSON.stringify({
            enabled: !!this.storagePolicy.enabled,
            retention_days: Number(this.storagePolicy.retention_days),
            max_gb: Number(this.storagePolicy.max_gb),
          }),
        });
        if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
        const d = await r.json();
        this.storagePolicy = { ...this.storagePolicy, ...d, loaded: true, busy: false,
          message: "Saved. This Mac will enforce the policy automatically." };
        this.pushToast({ kind: "info", icon: "✓", title: "Storage policy saved",
          body: `${d.retention_days} days · ${d.max_gb} GB hard cap` });
      } catch (e) {
        this.storagePolicy.busy = false;
        this.storagePolicy.message = String(e);
        this.pushToast({ kind: "error", icon: "✗", title: "Couldn't save storage policy", body: String(e) });
      }
    },
    async cleanStoragePolicyNow() {
      this.storagePolicy.busy = true;
      this.storagePolicy.message = "Checking completed outputs…";
      try {
        const r = await fetch("/api/storage-policy/cleanup", {
          method: "POST", headers: { "content-type": "application/json" }, body: "{}",
        });
        if (!r.ok) throw new Error((await r.json()).detail || `HTTP ${r.status}`);
        const d = await r.json();
        this.storagePolicy = { ...this.storagePolicy, ...d, loaded: true, busy: false,
          message: `Cleanup complete · ${d.deleted || 0} removed · ${humanBytes(d.freed_bytes || 0)} freed.` };
        await this.refreshOutputStats();
        this.pushToast({ kind: "info", icon: "🧹", title: "Cleanup complete",
          body: `${d.deleted || 0} file${d.deleted === 1 ? "" : "s"} removed · ${humanBytes(d.freed_bytes || 0)} freed` });
      } catch (e) {
        this.storagePolicy.busy = false;
        this.storagePolicy.message = String(e);
        this.pushToast({ kind: "error", icon: "✗", title: "Couldn't clean outputs", body: String(e) });
      }
    },
    /** mode: "keep50" keeps the newest 50; "old30" deletes files older than 30 days. */
    async pruneOutputs(mode) {
      const body = mode === "old30" ? { older_than_days: 30 } : { keep_last: 50 };
      const label = mode === "old30" ? "older than 30 days" : "all but the newest 50";
      if (this.gen.pruneArmed !== mode) {
        this.gen.pruneArmed = mode;
        clearTimeout(this._pruneArmTimer);
        this._pruneArmTimer = setTimeout(() => { this.gen.pruneArmed = null; }, 3000);
        return;
      }
      clearTimeout(this._pruneArmTimer);
      this.gen.pruneArmed = null;
      try {
        const r = await fetch("/api/output/prune", {
          method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error("HTTP " + r.status);
        const d = await r.json();
        await this.refreshOutputStats();
        this.pushToast({ kind: "info", icon: "🧹", title: "Outputs pruned",
          body: `Deleted ${d.deleted} file${d.deleted === 1 ? "" : "s"} (${humanBytes(d.freed_bytes || 0)}) — kept ${label === "older than 30 days" ? "recent" : "the newest 50"}.` });
      } catch (e) {
        this.pushToast({ kind: "error", icon: "✗", title: "Couldn't prune",
          body: "This needs the latest backend — run Update once from the Pinokio sidebar." });
      }
    },

    // ──────── in-app confirm (webview-safe) ────────
    // Native window.confirm() is silently blocked by Pinokio's embedded webview
    // (returns false), so destructive actions using it appeared to do nothing.
    // askConfirm() opens an in-app modal and resolves true/false when the user
    // chooses. Usage: `if (!await this.askConfirm("Title", "body")) return;`
    askConfirm(title, body, confirmLabel = "Confirm") {
      return new Promise((resolve) => {
        this.confirmDialog = { title, body, confirmLabel, resolve };
      });
    },
    _resolveConfirm(value) {
      if (this.confirmDialog) {
        const r = this.confirmDialog.resolve;
        this.confirmDialog = null;
        r(value);
      }
    },

    // ──────── toasts / native notification / tab title ────────

    pushToast(t) {
      const id = ++this._toastSeq;
      this.toasts.push({ id, ...t });
      const ttl = t.kind === "error" ? 8000 : 4500;
      setTimeout(() => this.dismissToast(id), ttl);
    },

    dismissToast(id) {
      this.toasts = this.toasts.filter(t => t.id !== id);
    },

    _requestNotificationPermission() {
      // Only ask once per session. User must accept once; thereafter it's
      // remembered by the browser. Failing silently is fine.
      if (typeof Notification === "undefined") return;
      if (Notification.permission === "default") {
        try { Notification.requestPermission(); } catch { /* ignore */ }
      }
    },

    _tryNativeNotification(title, body) {
      if (typeof Notification === "undefined") return;
      if (Notification.permission !== "granted") return;
      // Don't pop a notification if the page is currently visible — toasts cover that case.
      if (document.visibilityState === "visible") return;
      try {
        const n = new Notification(title, { body, silent: false });
        setTimeout(() => n.close(), 6000);
      } catch { /* some browsers/contexts restrict this; ignore */ }
    },

    _flashTabTitle(label) {
      // Briefly mutate document.title to grab attention in a background tab,
      // then restore the original after 6s OR on tab focus.
      const original = "VoiceStudio (Mac)";
      document.title = `${label} · ${original}`;
      const restore = () => {
        document.title = original;
        document.removeEventListener("visibilitychange", restore);
      };
      document.addEventListener("visibilitychange", restore);
      setTimeout(restore, 6000);
    },

    formatDuration(sec) {
      if (sec == null || isNaN(sec)) return "—";
      sec = Math.round(sec);
      if (sec < 60) return `${sec}s`;
      if (sec < 3600) {
        const m = Math.floor(sec / 60);
        const s = sec % 60;
        return `${m}m ${s.toString().padStart(2, "0")}s`;
      }
      // Download ETAs on a slow/throttled connection can legitimately reach
      // hour/day scale — "734m 12s" is as unreadable as the bug this rollup
      // fixes. Job render durations (the other caller) never hit this branch.
      if (sec < 86400) {
        const h = Math.floor(sec / 3600);
        const m = Math.floor((sec % 3600) / 60);
        return `${h}h ${m.toString().padStart(2, "0")}m`;
      }
      const d = Math.floor(sec / 86400);
      const h = Math.floor((sec % 86400) / 3600);
      return `${d}d ${h.toString().padStart(2, "0")}h`;
    },

    formatBytes(bytes) {
      return humanBytes(bytes || 0);
    },

    friendlyJobError(error) {
      const raw = String(error || "").trim();
      if (!raw) return "Generation failed";
      if (raw.includes("parameters not in model") || raw.includes("weight.scales")) {
        return "The downloaded model weights are not compatible with this engine.";
      }
      if (raw.includes("didn't produce a wav file")) {
        return "The model did not produce audio. Open details for the engine error.";
      }
      const firstLine = raw.split("\n").find((line) => line.trim()) || raw;
      return firstLine.length > 180 ? `${firstLine.slice(0, 177)}…` : firstLine;
    },

    downloadFilename(job) {
      if (!job) return "speech.wav";
      const text = (job.params?.text || "speech")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 40) || "speech";
      const seed = job.resolved_seed ?? "seed";
      const voice = job.params?.voice ? `-${job.params.voice}` : "";
      const extension = /\.mp3$/i.test(job.output_path || "") ? "mp3" : "wav";
      return `${text}${voice}-${seed}-${job.id}.${extension}`;
    },

    reuseParams(job) {
      const p = job?.params;
      if (!p) return;
      this.tab = "generate";
      if (p.repo) {
        const stillAvailable = this.generationModels.some(m => m.repo === p.repo);
        if (stillAvailable) {
          this.gen.repo = p.repo;
          this._repoUserConfirmed = true;
        }
      }
      this.gen.text = p.text || "";
      if (p.voice) {
        const [voice, blend = ""] = p.voice.split(",");
        this.gen.voice = voice;
        this.gen.kokoro_blend_voice = this.isKokoroMlx(p.repo) ? blend : "";
      }
      if (p.language) {
        if (this.isKokoroMlx(p.repo)) this.gen.kokoro_language = p.language;
        else this.gen.language = p.language;
      }
      if (typeof p.speed === "number") this.gen.speed = p.speed;
      if (typeof p.temperature === "number") this.gen.temperature = p.temperature;
      const reuseSeed = job.resolved_seed ?? p.seed;
      if (typeof reuseSeed === "number") this.gen.seed = reuseSeed;
      // Qwen3-TTS mode params
      if (p.preset_speaker)       this.gen.preset_speaker = p.preset_speaker;
      if (p.instruct)             this.gen.instruct = p.instruct;
      if (p.voice_design_prompt)  this.gen.voice_design_prompt = p.voice_design_prompt;
      if (p.voice_library_id)     this.gen.voice_library_id = p.voice_library_id;
      if (p.ref_transcript)       this.gen.ref_transcript = p.ref_transcript;
      if (typeof p.cfg_value === "number")           this.gen.cfg_value = p.cfg_value;
      if (typeof p.inference_timesteps === "number") this.gen.inference_timesteps = p.inference_timesteps;
      if (typeof p.normalize_text === "boolean")     this.gen.normalize_text = p.normalize_text;
      if (typeof p.voxcpm_warmup_patches === "number") this.gen.voxcpm_warmup_patches = p.voxcpm_warmup_patches;
      if (typeof p.voxcpm_max_tokens === "number") this.gen.voxcpm_max_tokens = p.voxcpm_max_tokens;
      if (typeof p.chatterbox_cfg_weight === "number") this.gen.chatterbox_cfg_weight = p.chatterbox_cfg_weight;
      if (typeof p.chatterbox_repetition_penalty === "number") this.gen.chatterbox_repetition_penalty = p.chatterbox_repetition_penalty;
      if (typeof p.chatterbox_min_p === "number") this.gen.chatterbox_min_p = p.chatterbox_min_p;
      if (typeof p.chatterbox_top_p === "number") this.gen.chatterbox_top_p = p.chatterbox_top_p;
      if (p.bark_voice_preset !== undefined) this.gen.bark_voice_preset = p.bark_voice_preset || "";
      if (typeof p.bark_temperature === "number") this.gen.bark_temperature = p.bark_temperature;
      if (typeof p.bark_max_coarse_history === "number") this.gen.bark_max_coarse_history = p.bark_max_coarse_history;
      if (typeof p.bark_sliding_window_len === "number") this.gen.bark_sliding_window_len = p.bark_sliding_window_len;
      if (typeof p.bark_allow_early_stop === "boolean") this.gen.bark_allow_early_stop = p.bark_allow_early_stop;
      if (typeof p.omnivoice_num_steps === "number") this.gen.omnivoice_num_steps = p.omnivoice_num_steps;
      if (typeof p.omnivoice_guidance_scale === "number") this.gen.omnivoice_guidance_scale = p.omnivoice_guidance_scale;
      this.gen.omnivoice_duration_s = typeof p.omnivoice_duration_s === "number"
                                      ? p.omnivoice_duration_s : null;
      if (typeof p.fish_temperature === "number") this.gen.fish_temperature = p.fish_temperature;
      if (typeof p.fish_top_p === "number") this.gen.fish_top_p = p.fish_top_p;
      if (typeof p.fish_top_k === "number") this.gen.fish_top_k = p.fish_top_k;
      if (typeof p.fish_max_tokens === "number") this.gen.fish_max_tokens = p.fish_max_tokens;
      if (typeof p.audio8_temperature === "number") this.gen.audio8_temperature = p.audio8_temperature;
      if (typeof p.audio8_top_p === "number") this.gen.audio8_top_p = p.audio8_top_p;
      if (typeof p.audio8_top_k === "number") this.gen.audio8_top_k = p.audio8_top_k;
      if (typeof p.audio8_max_tokens === "number") this.gen.audio8_max_tokens = p.audio8_max_tokens;
      if (typeof p.moss_temperature === "number") this.gen.moss_temperature = p.moss_temperature;
      if (typeof p.moss_top_p === "number") this.gen.moss_top_p = p.moss_top_p;
      if (typeof p.moss_top_k === "number") this.gen.moss_top_k = p.moss_top_k;
      if (typeof p.moss_repetition_penalty === "number") this.gen.moss_repetition_penalty = p.moss_repetition_penalty;
      if (typeof p.echo_num_steps === "number") this.gen.echo_num_steps = p.echo_num_steps;
      if (typeof p.echo_cfg_scale_text === "number") this.gen.echo_cfg_scale_text = p.echo_cfg_scale_text;
      if (typeof p.echo_cfg_scale_speaker === "number") this.gen.echo_cfg_scale_speaker = p.echo_cfg_scale_speaker;
    },

    async revealInFolder(path) {
      if (!path) return;
      try {
        const r = await fetch("/api/reveal", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ path }),
        });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          this.pushToast({ kind: "error", icon: "✗", title: "Couldn't open in Finder",
            body: err.detail || ("HTTP " + r.status) });
        }
      } catch (e) {
        this.pushToast({ kind: "error", icon: "✗", title: "Couldn't open in Finder", body: String(e) });
      }
    },

    // ──────── Subtitles / STT handlers ────────
    async refreshTranscribe() {
      try {
        const r = await fetch("/api/transcribe/availability");
        const data = await r.json();
        this.stt.available = !!data.available;
        this.stt.models = data.models || [];
        // Pick a default model: keep current if still listed, else the
        // recommended one, else first.
        const stillThere = this.stt.models.some(m => m.repo === this.stt.model);
        if (!stillThere) {
          this.selectTranscriptionModel(data.default_model
            || (this.stt.models.find(m => m.recommended) || this.stt.models[0] || {}).repo
            || "");
        } else {
          this.selectTranscriptionModel(this.stt.model);
        }
      } catch {
        this.stt.available = false;
      }
    },
    _pollTranscriptionUntilCached(repo) {
      this.selectTranscriptionModel(repo); // sync selection + download label
      this.stt.downloading = true;
      // Poll availability until the model flips to cached, so the UI
      // re-enables Transcribe without a manual refresh.
      const deadline = Date.now() + 30 * 60 * 1000;   // 30 min ceiling
      const tick = async () => {
        await this.refreshTranscribe();
        const m = this.stt.models.find(x => x.repo === repo);
        if (m && m.cached) { this.stt.downloading = false; return; }
        if (Date.now() > deadline) { this.stt.downloading = false; return; }
        setTimeout(tick, 4000);
      };
      setTimeout(tick, 4000);
    },
    _setSubtitleFile(file) {
      if (!file) return;
      if (!/^audio\//.test(file.type) && !/\.(wav|mp3|m4a|flac|ogg|opus|aac)$/i.test(file.name || "")) {
        this.stt.error = "Not an audio file. Use WAV / MP3 / M4A / FLAC / OGG.";
        return;
      }
      this.stt.error = "";
      this.stt.file = file;
      this.stt.fileName = file.name || "audio.wav";
      // Route through the shared humanBytes() (decimal) instead of a
      // duplicate binary computation, so this matches every other byte
      // display in the app (v1.7.3).
      this.stt.fileSize = humanBytes(file.size || 0);
    },
    onSubtitlePick(e) {
      const f = e.target.files && e.target.files[0];
      this._setSubtitleFile(f);
      e.target.value = "";   // allow re-pick of same file
    },
    onSubtitleDrop(e) {
      this.stt.dragOver = false;
      const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      this._setSubtitleFile(f);
    },
    async runTranscribe() {
      if (!this.stt.file || this.stt.running) return;
      this.stt.running = true;
      this.stt.error = "";
      this.stt.result = null;
      this.stt.elapsed = 0;
      this.stt._elapsedHandle = setInterval(() => { this.stt.elapsed += 1; }, 1000);
      try {
        const fd = new FormData();
        fd.append("file", this.stt.file);
        if (this.stt.model) fd.append("model", this.stt.model);
        if (this.stt.language.trim()) fd.append("language", this.stt.language.trim());
        if (this.stt.wordTimestamps && this.sttWordTimestampsSupported) {
          fd.append("word_timestamps", "true");
        }
        const r = await fetch("/api/transcribe", { method: "POST", body: fd });
        if (!r.ok) {
          const err = await r.json().catch(() => ({}));
          // 409 = model not downloaded → nudge toward the download button.
          this.stt.error = (r.status === 409 ? "Model not downloaded yet. " : "")
            + this._formatApiError(err, r.status);
          return;
        }
        this.stt.result = await r.json();
        this.stt.view = "text";
      } catch (e) {
        this.stt.error = String(e);
      } finally {
        clearInterval(this.stt._elapsedHandle);
        this.stt.running = false;
      }
    },
    /** Build (and cache) a blob URL for the current SRT/VTT view so the
     *  download link has real content. Revokes the previous one. */
    subtitleBlobUrl() {
      if (!this.stt.result) return "#";
      if (this.stt._blobUrl) { try { URL.revokeObjectURL(this.stt._blobUrl); } catch {} }
      const body = this.stt.view === "srt" ? this.stt.result.srt
                 : this.stt.view === "vtt" ? this.stt.result.vtt
                 : this.stt.result.text;
      const mime = this.stt.view === "vtt" ? "text/vtt" : "text/plain";
      this.stt._blobUrl = URL.createObjectURL(new Blob([body], { type: mime }));
      return this.stt._blobUrl;
    },

    async copyText(text) {
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        // Fallback for non-secure contexts
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); } catch {}
        ta.remove();
      }
    },

    // ──────── formatters ────────
    formatGb(gb) {
      // Decimal (÷/×1000), matching humanBytes() and the catalog's own
      // size_gb convention (v1.7.2/v1.7.3 fix) — NOT ×1024. A model listed
      // as 0.34 GB (e.g. Kokoro) must show "340 MB", not "348 MB"; the ×1024
      // version silently inflated every sub-1GB model's advertised size by
      // ~2.4%, which then wouldn't match the file's real size on disk.
      if (gb < 1) return Math.round(gb * 1000) + " MB";
      return gb.toFixed(1) + " GB";
    },

    cardClass(m) {
      return m.cache.state;
    },

    /** Short label for the hardware-fit chip on a model card. Mirrors the
     *  backend's `fit.state` enum: ok / tight / risky / unknown. */
    fitChipLabel(fit) {
      if (!fit) return "";
      const map = {
        ok:      "✓ fits",
        tight:   "⚠ tight",
        risky:   "✗ may not fit",
        unknown: "? fit unknown",
        unqualified: "⏳ test pending",
      };
      return map[fit.state] || "";
    },

    memoryFloorLabel(model) {
      const floor = Number(model?.min_unified_memory_gb);
      return Number.isFinite(floor) && floor > 0 ? `${floor} GB+` : "Not yet qualified";
    },

    /** Bullet glyph for each use_case kind. */
    useCaseIcon(kind) {
      const map = { good: "✅", weak: "⚠️", avoid: "❌" };
      return map[kind] || "•";
    },

    cacheChipLabel(state) {
      return { cached: "cached", partial: "partial", absent: "not downloaded" }[state] || state;
    },

    cacheChipClass(state) {
      return { cached: "ok", partial: "warn", absent: "" }[state] || "";
    },

    capabilityLabel(c) {
      return {
        "voice-cloning": "voice cloning",
        multilingual: "multilingual",
        expressive: "expressive",
        "voice-mixing": "voice mixing",
        streaming: "streaming",
      }[c] || c;
    },

    stateChipClass(state) {
      if (state === "done") return "ok";
      if (state === "error") return "bad";
      if (state === "cancelled" || state === "cancelling") return "warn";
      return "";
    },

    downloadCaption(j) {
      const done = humanBytes(j.bytes_observed || 0);
      let line = done;
      if (j.bytes_total > 0) {
        const total = humanBytes(j.bytes_total);
        const pct = j.percent != null ? j.percent.toFixed(1) + "%" : "";
        line = `${done} / ${total}  ${pct}`;
      }
      // Surface the live byte-rate so users can tell at a glance whether the
      // download is actually progressing vs. wedged.
      if (j.state === "running" && j.speed_bps > 0) {
        line += ` · ${humanBytes(j.speed_bps)}/s`;
        if (j.eta_seconds != null && isFinite(j.eta_seconds)) {
          line += ` · ETA ${this.formatDuration(j.eta_seconds)}`;
        }
      } else if (j.state === "running") {
        // No measured speed yet (just started). Still tell the user it's alive.
        line += " · measuring…";
      }
      if (j.state === "running" && j.bytes_unverified_inventory > 0) {
        line += ` · ${humanBytes(j.bytes_unverified_inventory)} existing cache pending verification`;
      }
      return line;
    },
  };
}

function humanBytes(n) {
  // Decimal (SI, ÷1000) — NOT binary ÷1024. This must match the catalog's
  // static `size_gb` values (computed from HF's decimal byte counts) and
  // Hugging Face's own website, or live download progress visibly disagrees
  // with the "X GB" size shown before downloading (e.g. a 1,613,979,758-byte
  // file is legitimately "1.6 GB" decimal but only "1.5 GiB" if divided by
  // 1024^3 — same bytes, two different-looking numbers, no bug in either
  // reading alone, just a units mismatch). Confirmed live against a real
  // whisper-large-v3-turbo download job.
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1000 && i < units.length - 1) { n /= 1000; i++; }
  return n.toFixed(n < 10 ? 2 : 1) + " " + units[i];
}

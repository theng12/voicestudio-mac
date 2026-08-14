# LongCat and Offline Fleet SSD Design

## Outcome

Voice Studio adds LongCat AudioDiT 1B 4-bit as an internal Apple-silicon
voice-cloning candidate for 16 GB and 24 GB Macs. The TerraNash SSD carries
the model, its tokenizer companion, and the owner-approved fleet voice
references so a newly installed Mac can be prepared without downloading them.

LongCat is not published as a GenStudio production route by this change. It
must first pass owner listening across several saved voices and difficult
long-form scripts.

## Voice Studio

- Reuse the pinned `mlx-audio` runtime and the existing shared MLX worker.
- Add one `longcat-audiodit` catalog family and the
  `mlx-community/LongCat-AudioDiT-1B-4bit` checkpoint.
- Require a saved or private reference voice with its transcript. Generate
  with APG guidance, CFG strength 4.0, 16 steps, and the job seed.
- Reuse the common sentence-safe long-form renderer with a measured
  280-character section ceiling and 180 ms joins.
- Publish a 16 GB floor and recommend 24 GB for comfortable concurrent fleet
  operation. Do not advertise 8 GB eligibility.
- Preserve the existing worker evidence, memory release, progress,
  cancellation-between-sections, and revision reporting paths.
- Keep the model internal/non-routable until a hash-bound model audit approves
  it for GenStudio.

## SSD staging and restore

- Continue using the existing two commands: installation first, model/voice
  copy second. Do not create another installer.
- Stage every complete local catalog model already cached on the source Mac.
  Do not delete SSD packages merely because a Studio was offline or a model
  was absent during a later staging run.
- Treat staging as additive and idempotent. A matching complete package is
  skipped; replacement happens only when the staged package is incomplete or
  differs from the source package.
- Store fleet-managed saved voices under `studio-models/voices/<voice-id>`.
  The manifest records the stable ID and reference SHA-256.
- Restore a missing voice atomically. Skip an identical ID/hash. Refuse an
  ID/hash conflict rather than overwriting either copy.
- Continue applying catalog memory floors during restore. LongCat therefore
  copies only to 16 GB and 24 GB Macs unless the operator explicitly requests
  all models.

## Duplicate checkout protection

For Hub, Image, and Voice Studio, installation accepts either the canonical
folder (`voicestudio-mac`) or the historical Pinokio folder
(`voicestudio-mac.git`) when its Git origin matches the expected repository.
Every later install/start action uses the detected folder name. If both exist,
the canonical folder wins and the installer reports the legacy duplicate; it
does not delete customer files automatically.

## Safety and verification

- No new Python dependency, cloud API, service, or fleet credential is added.
- Tests cover catalog/runtime wiring, cloning kwargs, long-form policy,
  hardware floor, legacy checkout reuse, idempotent model staging, voice
  identity conflicts, and usernames/absolute-path independence.
- Voice Studio ships as 2.1.0 because this is a new model family. Studio Hub
  ships as 2.7.0 because the SSD/bootstrap behavior is a new operator feature.
- The connected SSD is updated only after both repositories pass focused and
  full verification.

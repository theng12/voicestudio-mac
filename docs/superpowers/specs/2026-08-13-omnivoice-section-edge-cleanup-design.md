# OmniVoice Section Edge Cleanup Design

## Goal

Remove short OmniVoice conditioning/noise artifacts from independently rendered
section boundaries without cutting words, crossfading speech, or changing the
established 300 ms sentence, 600 ms paragraph, and 180 ms soft-join pacing.

## Confirmed cause

Voice Studio renders and validates every long-form section independently, then
`_join_long_form_wavs()` copies every source frame into the final WAV before it
inserts the selected join silence. OmniVoice currently has no section-edge
cleanup. Noise emitted before the real onset or after the real ending therefore
survives at the beginning of the file or inside an otherwise silent join gap.

## Selected approach

Add one OmniVoice-only, join-time section cleanup step. It analyzes a bounded
300 ms trim region at each end of the generated section using a 10 ms RMS energy
envelope and an adaptive speech threshold. A boundary is usable only when the
detector sees sustained speech rather than an isolated energetic frame. The
retained audio begins slightly before the detected onset and ends slightly after
the detected ending so quiet consonants and natural releases remain intact.

Word preservation is the primary safety rule:

- Never remove a fixed duration.
- Never trim farther than 300 ms from either edge.
- Preserve a protective 20 ms pad around detected sustained speech.
- If a sustained boundary cannot be established, leave that edge unchanged.
- If cleanup would leave too little valid audio, leave the whole section
  unchanged and let the existing artifact validation continue normally.
- Apply cleanup only to OmniVoice. Every other family keeps its current bytes.

This is deliberately fail-open for audio: an ambiguous artifact may remain, but
ambiguous speech is not removed.

## Edge fades and pacing

After any conservative trim decision, apply a half-cosine fade over approximately
10 ms at the beginning and end of every OmniVoice section. The fade changes only
the retained section itself; it never overlaps another section, so there is no
speech crossfade. Fade length is pre-scaled by the selected generation speed, as
join silence already is, so the delivered artifact retains an approximately
10 ms audible fade after the final pitch-preserving tempo pass.

The existing boundary classifier and its pause sequence remain authoritative:

- ordinary sentence: 300 ms
- paragraph: 600 ms
- soft internal split: 180 ms

Cleanup finishes before `_join_long_form_wavs()` inserts those exact pauses.

## Implementation boundary

`app/backend/generation.py` owns the implementation because it already owns
section validation, stitching, and final tempo processing. A focused helper will
rewrite only temporary OmniVoice section WAVs, atomically, before they enter the
joiner. It will return trim evidence for concise generation logs. No request,
Hub, GenStudio, voice, model-weight, or download interface changes.

The OmniVoice model audit record advances to describe the new private edge
policy. That intentionally creates a new exact contract for GenStudio approval;
the model weights and runtime revision do not change.

## Verification

Behavioral tests use real WAV fixtures and the real cleanup/join functions. They
cover:

- a 270 ms low-energy conditioning blob before sustained speech;
- isolated trailing edge noise ranging from 17 ms through 260 ms;
- clean speech that begins immediately, proving no samples are trimmed;
- an ambiguous or too-short section, proving cleanup becomes a no-op;
- mono and stereo WAVs;
- approximately 10 ms non-crossfaded fades;
- exact preservation of the 300/600/180 ms inserted gaps;
- absence of this cleanup for non-OmniVoice families;
- the updated audited contract and release metadata.

Focused tests run first, followed by the complete Voice Studio suite, dependency
integrity checks, Python and launcher syntax checks, and repository release
validation. The live Pinokio-managed service is not restarted during development.


# Smedley Project Review voice

Implemented September 3, 2026. The project-review dialog uses the existing local V6 speech output with Smedley's explicitly selected Jarnathan voice (`c6SfcYrb2t09NHXiT80T`), without inheriting an earlier Argus voice override. The ID was verified against Rick's ElevenLabs document in the API Keys folder. Both natural conversation and engineering summaries use this voice. Biggy, Argus and the shared service default are unchanged. Room/headset routing and mute remain owned by the existing audio controls and sidecar.

## Speaking policy

Jarnathan change verification: the voice-selection test failed against the prior Austin fallback, then all 16 project-review speech tests passed after the change. A short local speech request using the documented Jarnathan ID returned `status=completed`, `returncode=0`, `waited=true`. The live server serves the updated client script; existing tabs need a refresh. A separate legacy Smedley-extension test still fails because the installed extension lacks `__smedleyPttOwnsVoiceUntil`; neither that extension nor its ownership behavior was changed in this voice-selection task.

Follow-up verification (September 3, 10:07 UTC): Rick's open review had still posted no voice ID, producing `DEFAULT_AUSTIN`. Selection now travels from the review speech endpoint (`voice_id`, `voice_name`, `assistant_identity`) to the browser and local speech sink. Missing/malformed Smedley IDs fail closed instead of falling back to Austin. After an idle backend restart and refreshing the empty browser composer, a real Project Review test displayed “Ready, Rick.” The sink logged `assistant_identity=smedley voice_id=c6SfcYrb2t09NHXiT80T fallback_used=false`, and playback returned HTTP 200 after 4.73 seconds. The written reply took 2.81 seconds. No warning was visible after completion. Thirty speech/review-lifecycle tests passed. This real dialog test supersedes the earlier direct-sink-only verification; one clearly marked voice-test exchange was added to the existing review, with no document work or approval changes.

- Short, ordinary fast-lane conversation speaks its cleaned reply directly. No second model call.
- Governed document work, status reports, formatted criteria and long replies speak a separate natural briefing: at most two sentences, requested maximum 65 words, hard 650-character limit. The local V6 light model summarizes the completed public answer, retaining uncertainty, approval conditions and next steps.
- Full written answers remain unchanged. Tables, code blocks, tool messages, raw JSON, progress logs, hidden/reasoning blocks and unfinished/cancelled/interrupted turns are not narrated.
- Summary failure reports that the spoken reply could not be prepared while preserving the written reply. It never falls back to reading the full engineering output. A lost playback acknowledgement is reported as unconfirmed playback, not proof that voice is unavailable.

## Ownership and lifecycle

Only sending a new review message in a tab arms that tab's voice gate. Opening an existing review, reading its history and polling do not arm speech. A completed-reply fingerprint includes session, message count, timestamp and public content. Repeated polls cannot replay the same armed reply.

The explicit POST `/api/biggy/projects/reviews/dialog/speech` validates the Biggy/Smedley project-session boundary and the current completed-reply fingerprint before and after preparation. It prepares text only; GET/poll endpoints neither generate summaries nor play sound. The initiating tab owns playback through the existing serialized V6 sink. Close, cancel, project switch and a newer send invalidate pending preparation and queued chunks. Already-dispatched playback remains controlled by the existing audio service/mute control.

Review speech uses process-local browser state only; no transcript rewriting or persistent auto-read state is introduced. Reopening or reloading a tab starts unarmed. Error messages are visible, not silently reported as playback success.

## Verification

- New regression cases failed before implementation and passed afterwards.
- 84 focused voice, review, lifecycle, awareness and neighboring tests passed.
- JavaScript syntax and whitespace checks passed.
- Real local model sample: an 80-row engineering-result fixture became a two-sentence briefing in 1.25 seconds. It retained that extraction values were unverified and terminal-temperature/fault-current confirmation was required before approval.
- Ordinary greeting preparation needed no model call.
- A short local `/speak` check returned HTTP 200, `status=completed`, `returncode=0`, `waited=true`; elapsed 12.15 seconds includes synthesis and full playback, not time-to-first-audio. Physical audio quality was not independently measured.
- A separate browser tab loaded the updated script and audio-mute state with no captured JavaScript warnings/errors. Rick's existing Chrome tab could not attach to browser automation and was not reloaded or modified. It needs one refresh to load the new client hook. No test messages were inserted into the active production project review.

No engineering finding is approved by this voice change. No model/provider or Orb layout change was made.

## September 3 follow-up: false unavailable warning and slow routing

Production logs recorded five `/api/extensions/biggy-brand/sidecar/speak` responses with HTTP 502 at approximately 10,004 ms on September 3, while Rick reported audible playback. The proxy's generic 10-second timeout was shorter than `wait=true` synthesis plus playback. The earlier direct sidecar smoke test bypassed this proxy and did not catch the mismatch.

- Only local Biggy/Smedley `/speak` POST requests with boolean `wait=true` receive a 180-second proxy budget. Other requests retain their existing timeout and provenance/auth checks.
- The browser waits up to 190 seconds per speech chunk, without automatic retries or generic timeout toasts. This is a completion deadline, not a delay before speech starts. Acknowledgement loss must not replay speech or claim the audio stopped.
- `MEDIA:` artifact paths are excluded from spoken text and summary input.
- Restrictive instructions such as “Read no docs or tables unless specifically asked” remain conversational. Genuine immediate actions still route to governed review. This restriction had incorrectly launched a heavy turn before voice preparation even started.
- 102 focused routing, voice, sidecar, awareness and review-lifecycle tests passed. A real loopback HTTP fixture delayed its playback acknowledgement beyond 10 seconds and returned completion successfully through the actual proxy implementation. No production messages, documents or approvals were created by these tests.
- JavaScript syntax and whitespace checks passed. Existing open browser tabs need a refresh to receive the client-side deadline and corrected wording; do not discard Rick's unsent draft or attachments to force that refresh.

# Doubao TTS 2.0 Config Plan

## Requirement

Agents must treat Doubao under Video Director as a voice synthesis path for
`video` and `draft` outputs unless the user explicitly asks for a future,
separate voice cloning or avatar capability.

## Current State

- The installed Skill is the whole repository and uses `video` / `draft`
  templates for the normal output modes.
- The `video` and `draft` templates use the V3 HTTP Chunked path with
  `api_key`, built-in `resource_id=seed-tts-2.0`, and built-in
  `speaker_id=zh_male_jieshuoxiaoming_uranus_bigtts`.
- Some agents may still infer old Doubao fields from prior knowledge, such as
  app id, access token, cluster, and voice type.
- The runtime fallback resource id previously pointed at `seed-icl-2.0`, which is
  a voice clone resource rather than the default voice synthesis resource.
- The current Skill only needs TTS configuration; avatar, voice clone, audio
  delivery, generic cloud API configuration, `cloud.template.json`, and
  `--mode cloud` should not be part of the normal TTS setup.

## Plan

1. Update `SKILL.md` so agents only request the Doubao TTS 2.0 voice synthesis
   inputs required by the selected path.
2. Update `runtime/cloud_production.py` so the fallback resource id is
   `seed-tts-2.0` and Doubao TTS does not require generic cloud API config.
3. Move the TTS config surface into the `video` and `draft` templates instead
   of making it cloud-mode specific.
4. Adjust config materialization so it can enable TTS for normal output modes
   and does not add avatar flags to the TTS config.
5. Remove the cloud template and cloud mode entrypoint so agents do not infer a
   separate cloud-only TTS path.
6. Verify through the public macOS launcher help and config generation path.

## Definition of Done

- Agents are told not to ask for `DOUBAO_APP_ID`, `DOUBAO_ACCESS_TOKEN`,
  `DOUBAO_CLUSTER`, or `DOUBAO_VOICE_TYPE` for Doubao TTS 2.0.
- The voice synthesis path uses `DOUBAO_TTS_API_KEY`, built-in `resource_id`,
  and built-in default `speaker_id`.
- Voice clone resources remain opt-in and are not part of the Doubao TTS default.
- Generated `video` and `draft` configs can enable TTS without `--mode cloud`
  and do not include avatar, voice clone, audio delivery, or generic cloud API
  placeholder settings.
- User-facing Doubao TTS config includes a concise Chinese note explaining that
  `seed-tts-2.0` is for ordinary voice synthesis and `seed-icl-2.0` is voice
  cloning, not ordinary TTS.
- The default speaker is `zh_male_jieshuoxiaoming_uranus_bigtts`.

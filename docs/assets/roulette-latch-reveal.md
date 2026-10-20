# Roulette light-clunk reveal

The reveal uses **lightclunk1.wav** by Brian MacIntosh (BMacZero), from
[Mechanical Sounds](https://opengameart.org/content/mechanical-sounds), published
under [CC0](https://creativecommons.org/publicdomain/zero/1.0/).

Source: https://opengameart.org/sites/default/files/lightclunk1.wav

Source SHA-256: `d5a2aa8764c02924f6ed6fbaad0c650ab2d57ec57a626cee9e6645f941dbc8fa`.

This replaces the heavy [casino slam](roulette-casino-slam.md). The user selected
the “Real light clunk + heartbeat + glow” audition. The mechanical layer is a
recording; the double heartbeat and quiet harmonic glow are original synthesis,
baked into the same buffer rather than generated at runtime.

The audition mix was rendered at 44100 Hz. The recorded clunk has a 65 Hz
high-pass, silence trimming, short edge fades, and peak gain 0.28. Heartbeats
begin at 0.08 and 0.31 seconds, with damped 76 Hz and 91 Hz bodies and quiet,
filtered low-frequency noise. Their combined RMS over the first 0.65 seconds is
approximately 0.1723, a 1.5 dB increase over the selected audition. The glow adds
slowly opening 523.25 Hz and 783.99 Hz tones, with detuned
overtones and unequal decays. A quiet, diffuse stereo room supplies the tail.
The clunk and glow retain their selected audition levels.

For embedding, the audition's rising lead-in is excluded, its stereo landing is
averaged to mono, and it is resampled to 22050 Hz using a polyphase filter.
The 3.2-second landing is padded to four seconds and rounded to signed 16-bit
little-endian PCM. It remains a single cancellable buffer using the existing
shared mute, exit, visibility, and Next/Back cleanup. Playback gain 1.4 compensates
for the shared output gain 0.7, keeping audition loudness within about 2%.

Embedded PCM: 176400 bytes, mono 22050 Hz, four seconds including silence padding.

SHA-256: `4588d2e69c3b81a7dcc3aeb5b91c1192c5dc10fc8293fb93561332fb87d8e0b1`.

No runtime asset requests, new dependencies, or separate reverb lifecycle.

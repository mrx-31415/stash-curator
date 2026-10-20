# Roulette cinematic rise

The rising sweep uses the public high-quality preview of
[Cinematic Woosh SFX-011.wav](https://freesound.org/people/AudioPapkin/sounds/648732/)
by AudioPapkin, published under [CC0](https://creativecommons.org/publicdomain/zero/1.0/).
The publisher describes field recordings processed in REAPER. Credit is optional
under CC0 and retained here.

Downloaded preview: https://cdn.freesound.org/previews/648/648732_8698658-hq.mp3

Preview SHA-256: `dc6a69e920fb8f1a43dee573149fa9039ce832de5b2d172c0101f67563413cd7`

The riser is a one-second seamless circular overlap of three 0.6-second grains
from the mono 22050 Hz float recording. Grain starts are 0.72, 0.85, and 0.96
seconds; the middle grain is reversed. Their circular output offsets are 0, 0.31,
and 0.67 seconds. Each grain is weighted by `sin(pi * i / (length - 1)) ** 2`,
summed into the circular buffer, peak-normalized to 0.8, and rounded to signed
16-bit PCM using scale 32767. Indices truncate fractional samples. This preserves
the source's changing frequency texture without an exposed oscillator note.

Riser PCM: 44100 bytes, SHA-256:
`0b9c3c0f0514e73a7622e797a6fdf978f9746e0dbdb2a6fbee1946ba1362c8a1`

The loop plays at 0.8 speed. Gathering starts it at 18% of the build envelope,
beneath the card shuffle. Spin reuses those voices without restarting, opening
the filter and raising gain with actual wheel progress until landing stops them.
The riser PCM is embedded alongside the shuffle and the separate
[clunk, heartbeat, and glow](roulette-latch-reveal.md), avoiding runtime requests or codec
initialization. Mute, exit, and tab
visibility cleanup stop recordings and synthesis together; no independent reverb
graph can keep sounding after cancellation.

# Roulette card-shuffle recording

The opening gather plays an edited version of **shuffleandbridge.wav** from
[Playing Card Sounds](https://opengameart.org/content/playing-card-sounds) by
Brian MacIntosh (BMacZero), published under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).
Credit is optional under the publisher's license; it is retained here.

Original download: https://opengameart.org/sites/default/files/shuffleandbridge.wav

Original SHA-256:
`7178fdd4b85875fc74aa0aaf534acbec8dad393006156cf7e679443dd6a4f85b`

The edit removes the pause between the shuffle and bridge, adds short edge fades,
and converts to mono, signed 16-bit little-endian PCM at 22050 Hz. The recording
is embedded as base64 in `createRouletteSound` so playback needs no additional
asset request or codec initialization. The rise uses a separate
[cinematic recording](roulette-cinematic-sound.md), and the landing uses a
[slam-and-chip mix](roulette-casino-slam.md).

Reproduce the PCM from the original file with an existing FFmpeg installation:

```bash
ffmpeg -hide_banner -loglevel error -y -i shuffleandbridge.wav \
  -filter_complex '[0:a]atrim=0:0.72,asetpts=PTS-STARTPTS,afade=t=in:d=0.005,afade=t=out:st=0.70:d=0.02[a];[0:a]atrim=start=1.27,asetpts=PTS-STARTPTS,afade=t=in:d=0.005,afade=t=out:st=0.5:d=0.03[b];[a][b]concat=n=2:v=0:a=1,aresample=22050[out]' \
  -map '[out]' -ac 1 -c:a pcm_s16le -f s16le card-shuffle.pcm
```

Edited PCM: 55106 bytes (about 1.25 seconds), SHA-256:
`e260501fe95976cb418a8a62adcef32a1d1fb111c65b0f2e2fbe950e30807f0f`

Playback adjusts the speed slightly to fit gathering time, with a bounded rate
of 0.85–1.2. It uses the same mute, cancellation, visibility, and cleanup rules as
the other effects.

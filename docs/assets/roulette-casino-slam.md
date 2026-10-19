# Roulette casino slam

The landing combines two real-world recordings, both published under
[CC0](https://creativecommons.org/publicdomain/zero/1.0/):

- [clatter10 by SilverDubloons](https://freesound.org/people/SilverDubloons/sounds/817567/):
  clay poker chips dropped on wood.
- [Seismic Slam by magnuswaker](https://freesound.org/people/magnuswaker/sounds/531862/):
  a heavy layered foley impact. The publisher describes its timbre as harsh and
  slightly clipped; the mix filters its top end rather than adding synthetic bass.

Credit is optional under CC0 and retained here. The publicly available high-quality
previews were used; the original downloads require a Freesound login.

| Input | Public preview | SHA-256 |
| --- | --- | --- |
| chips.mp3 | https://cdn.freesound.org/previews/817/817567_15868577-hq.mp3 | `839b339176dcfe3ca49436e8a3a8e6e0311bbefcbc351c08fc900b6f3c240167` |
| seismic.mp3 | https://cdn.freesound.org/previews/531/531862_11537497-hq.mp3 | `06d4ddab757f2af3c4e5cd3f163621ffffb79e36ff6bf0839f6e17118085ac6f` |

The heavy slam supplies the main impact and sustained body; trimmed chips supply
a quieter accent. Filtering softens the slam's top end and emphasizes upper bass
for small speakers. A diffuse room reverb extends its decay under the reveal;
peak normalization retains headroom. No pitched oscillator or pitch sweep is
added. First reproduce the dry mix with an existing FFmpeg installation:

```bash
ffmpeg -hide_banner -loglevel error -y -i seismic.mp3 -i chips.mp3 \
  -filter_complex '[0:a]atrim=end=1.8,asetpts=PTS-STARTPTS,highpass=f=40,lowpass=f=5000,equalizer=f=180:t=q:w=0.8:g=3,volume=0.8[slam];[1:a]atrim=start=0.08:end=0.58,asetpts=PTS-STARTPTS,highpass=f=600,volume=0.12[chips];[slam][chips]amix=inputs=2:normalize=0,apad=whole_dur=1.8,atrim=end=1.8,afade=t=in:d=0.002,afade=t=out:st=1.5:d=0.3,alimiter=limit=0.9:level=false,aresample=22050[out]' \
  -map '[out]' -ac 1 -c:a pcm_s16le -f s16le heavy-casino-slam.pcm
```

Dry output: mono signed 16-bit little-endian PCM, 22050 Hz, 79380 bytes (1.8 seconds).
SHA-256: `90819244dff7113c5861e6bd0f9946ffe96cda6ee16d85f1c13437dd958c4d80`.

Then bake a deterministic, filtered diffuse impulse response into the mix using
the existing development NumPy dependency (not a runtime dependency). Predelay
keeps the attack clear; early reflections give it a room, and a dense four-second
RT60 envelope supplies the late decay. The complete recording fades out at four
seconds. This avoids adding a runtime reverb graph with a separate cleanup path.

```python
from pathlib import Path
import numpy as np

rate = 22050
dry = np.frombuffer(Path("heavy-casino-slam.pcm").read_bytes(), dtype="<i2").astype(float) / 32768
n = 3 * rate
t = np.arange(n) / rate
ir = np.random.default_rng(531862).standard_normal(n)
frequencies = np.fft.rfftfreq(n, 1 / rate)
ir = np.fft.irfft(np.fft.rfft(ir) / (1 + (frequencies / 2600) ** 2), n)
ir *= np.exp(-np.log(1000) * t / 4) * (1 - np.exp(-t / .018))
ir[:int(.025 * rate)] = 0
ir /= np.linalg.norm(ir)
for time, gain in [(.031, .23), (.053, .18), (.079, .12), (.113, .10)]:
    ir[int(time * rate)] += gain
size = 1 << (len(dry) + len(ir) - 2).bit_length()
wet = np.fft.irfft(np.fft.rfft(dry, size) * np.fft.rfft(ir, size), size)
wet = wet[:len(dry) + len(ir) - 1]
rms = lambda samples: np.sqrt(np.mean(samples * samples))
wet *= .65 * rms(dry[:int(.8 * rate)]) / rms(wet[:int(.8 * rate)])
result = wet[:4 * rate].copy()
result[:len(dry)] += dry
result *= min(1, .9 / np.max(np.abs(result)))
result[int(3.6 * rate):] *= np.linspace(1, 0, int(.4 * rate))
Path("reverb-casino-slam.pcm").write_bytes(np.rint(result * 32767).astype("<i2").tobytes())
```

Embedded output: 176400 bytes (four seconds), mono 22050 Hz signed 16-bit PCM.
SHA-256: `91baaac137bbe5ebd1c497398e14abc6436a11173f669771fc5d586219e5f3f8`.
Playback stays at original speed and uses the existing shared mute/cancellation
lifecycle. Next/Back stop the previous tail before returning to the wheel.

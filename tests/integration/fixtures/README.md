The silent, ten-second Roulette video is synthetic test media:

```bash
ffmpeg -f lavfi -i color=c=0x29231b:s=160x90:r=5 -t 10 -c:v libx264 -pix_fmt yuv420p -movflags +faststart roulette.mp4
```

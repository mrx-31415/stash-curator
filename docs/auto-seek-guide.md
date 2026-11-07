---
title: Auto Seek guide
description: Install, use and tune Auto Seek, the Stash plugin that skips to where the action starts.
icon: auto-seek.svg
---

# Auto Seek guide

Auto Seek finds where the action starts in each scene and skips there. This guide
covers installing it, using it in the player, its settings, the background task,
and what to do when something goes wrong. For the overview, see the
[Auto Seek page]({{ '/auto-seek/' | relative_url }}).

## Install

Auto Seek is a separate plugin from Curator and works without it. It needs
**Stash v0.31** and the `python` that Stash already runs plugins with; no Python
packages are needed.

1. In Stash, open **Settings → Plugins → Available Plugins**, select **Add Source**
   and add `https://mrx-31415.github.io/stash-curator/index.yml`. (Already added for
   Curator? Then it's there.)
2. Install **Auto Seek**, then select **Reload plugins**.
3. Open Stash in your browser once. Auto Seek then downloads, in the background on the
   server, its image model (89 MB, from
   [Hugging Face](https://huggingface.co/mrx-31415/auto-seek)) and an ONNX Runtime
   build for your server (8–80 MB). Each file is checked against a pinned checksum.

### Supported servers

| Server | Runtime | Status |
|---|---|---|
| Docker (Stash's official image), x86-64 | Alpine's ONNX Runtime 1.23 | Tested |
| Linux x86-64 | Microsoft's ONNX Runtime 1.31 | Tested |
| Docker, ARM64 and 32-bit ARM | Alpine's ONNX Runtime 1.23 | New, untested |
| Linux ARM64, Windows x86-64 and ARM64, Apple Silicon Macs | Microsoft's ONNX Runtime 1.31 | New, untested |

Intel Macs and 32-bit ARM outside Docker have no ONNX Runtime build, so Auto Seek
reports that it can't run there. Docker users get the right build without doing
anything.

## In the player

- **Skip intro** appears on the picture while there is still an intro to skip. While
  the server is working the start out, a light band sweeps across it; when it shows
  an arrow, a tap jumps there. A toast confirms the jump and offers **Undo**.
- The **target** button in the control bar does the same from the controls.
- **The scan chart** sits just above the seek bar while the controls show: one bar
  per frame the server looked at, taller the surer it was that the action had
  started, amber once past the threshold, and a line at the start it picked (white
  when it's your own). Hide it with *Hide the scan chart*.
- **The flag** button sets the start yourself: pause where the action really starts
  and tap it. That scene starts there from now on, and a new model never overrides
  it. Tap Undo on the toast to put the previous start back.
- With **Skip automatically** on, a scene that starts playing from the beginning
  jumps to the start by itself. A resume point past the intro wins, and so does
  seeking on your own while it waits.

Scenes that already have a start point open with it ready. Others take a few seconds
the first time, while the server works it out.

## Background work

- **Settings → Tasks → Find start points** analyses every scene without a start
  point, newest first, one at a time, at low priority. It's safe to stop at any time;
  each answer is saved as it's found, and the next run continues where this one
  stopped. Scenes it can't analyse (a broken file, say) are remembered and skipped
  until the model changes.
- **New scenes** are queued as a library scan adds them, and a background worker on
  the server analyses them one at a time. Turn this off with *Don't analyse new
  scenes*.

As a guide, a scene took 3–5 seconds on a home NAS running Stash in Docker, mostly
spent cutting frames. A library of 10,000 scenes takes about 14 hours in the
background.

## Settings

| Setting | What it does |
|---|---|
| Skip automatically | Jump to the start when a scene starts playing from the beginning. Off by default. |
| Lead-in (seconds) | Jump this many seconds before the detected start. Default 8. |
| Hide the scan chart | Don't draw the scored frames above the seek bar. |
| Don't analyse new scenes | Only analyse scenes when opened or when you run the task. |
| CPU threads per analysis | Threads the image model may use. Default 2. |
| Don't download the model | Never download the model or runtime. Auto Seek then stays unavailable. |

## How it works

Auto Seek scores single frames with a tuned version of CLIP, an image model, which
says how likely it is that the action has started by that frame. It scores the 12
points Stash's preview uses, stopping early once two in a row are clearly past the
start. Where the scores jump, it scans the stretch between, then halves the gap a
few times to land within seconds. That is about 16 frames per scene.

Frames are cut by Stash's own ffmpeg straight into the model's input format and
scored on the server through ONNX Runtime. Results are kept per scene in the
plugin's own database (`data/cache.sqlite3` in the plugin folder), so each scene is
worked out once per model.

### Accuracy

Auto Seek was tuned and tested on one library, so take this as a first impression
rather than a promise. On 196 of its scenes whose start points were picked and
checked by hand, and held out of training, the search landed within 60 seconds of
the hand-picked start in 79% of them. When it misses, it is more often late than early. Typical causes:

- **Late:** people are still dressed when the action begins, or the opening is slow
  and builds up.
- **Early:** undressing, or an interview, without action.

Mark the right start with the flag and that scene is fixed for good.

## Privacy

Everything runs on your server. Frames never leave it, and nothing about your
library, your viewing or your marks is sent anywhere. The only network requests are
the one-off downloads of the model (Hugging Face) and the runtime (GitHub), from
the server.

## Troubleshooting

**The pill says the model is still downloading.** The first download can take a few
minutes. If it never finishes, check that the Stash server can reach
`huggingface.co` and `github.com`, and that *Don't download the model* is off. A
failed download is retried the next time Stash is opened.

**"Auto Seek can't run on this server."** No ONNX Runtime build exists for this
platform; see [Supported servers](#supported-servers).

**It takes long for one scene.** A busy server queues the analysis behind other
ffmpeg work, such as Stash's own generate tasks or the background task. Very large
files on slow network storage take longest. The player stops waiting after a while
and plays from where it is.

**The first scene after a restart is slow.** The model is read once from the plugin
folder and copied to the server's temporary folder; later loads use that copy.

**It picked the wrong start.** Use the flag. If one kind of scene is consistently
wrong, [open an issue](https://github.com/mrx-31415/stash-curator/issues) describing
the kind of opening (no screenshots needed).

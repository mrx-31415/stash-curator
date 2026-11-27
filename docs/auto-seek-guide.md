---
title: Auto Seek guide
description: Install, use and tune Auto Seek, the Stash plugin that skips to where the action starts and maps every act across the scene.
icon: auto-seek.svg
---

# Auto Seek guide

Auto Seek finds where the action starts in each scene and skips there, and shows
every act it sees across the scene on a timeline under the player. This guide covers
installing it, using it in the player, choosing what counts as the start, the
timeline, its settings, the background task, and what to do when something goes
wrong. For the overview, see the
[Auto Seek page]({{ '/auto-seek/' | relative_url }}).

## Install

Auto Seek is a separate plugin from Curator and works without it. It needs
**Stash v0.31** and the `python` that Stash already runs plugins with; no Python
packages are needed.

1. In Stash, open **Settings → Plugins → Available Plugins**, select **Add Source**
   and add `https://mrx-31415.github.io/stash-plugins/main/index.yml`.
2. Install **Auto Seek**, then select **Reload plugins**.
3. Open Stash in your browser once. Auto Seek then downloads, in the background on the
   server, its image model (about 90 MB for the fast model, 103 MB for the accurate
   one, from [Hugging Face](https://huggingface.co/mrx-31415/auto-seek)) and an ONNX
   Runtime build for your server (8–80 MB). Each file is checked against a pinned
   checksum.

Installed from Curator's source (`https://mrx-31415.github.io/stash-curator/index.yml`)?
That keeps receiving updates. To move to the new source, uninstall Auto Seek there and
install it from the one above, in either order: your start points and the starts you
marked carry over the first time it runs. Don't delete the old plugin folder by hand
before that.

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

## Choose what counts as the start

Everyone draws the line between intro and action differently. Under **Settings →
Plugins → Auto Seek**, **Start at** picks it:

| Start at | Counts as the start |
|---|---|
| **Oral, hands or sex** (default) | Oral, handjobs, fingering, titjobs, any sex position or a finish. Kissing, tease and other foreplay don't count yet. |
| **Kissing or later** | The same, plus kissing. |
| **Sex positions only** | Skips oral and hands as well. |
| **Foreplay or later** *(experimental)* | Massage, worship, masturbation and kissing count too; tease doesn't. |
| **Anything, tease included** *(experimental)* | Even a striptease counts. |

<figure class="capture guide-capture">
  <img src="{{ '/assets/auto-seek-start-at.png' | relative_url }}" alt="Auto Seek's Start at setting: a dropdown set to Oral, hands or sex above a search box and the acts in seven groups, from Tease to Finish, with the ones that count highlighted" width="771" height="495" loading="lazy">
  <figcaption>Start at, under Settings → Plugins → Auto Seek.</figcaption>
</figure>

Below the dropdown, every act the model knows is shown in its group, with the ones
that count highlighted. Tap acts, or a group's name, to make your own pick, and type
in the search box (`doggy`, `cum`, `kissing`…) to find one. Your own pick is
experimental: the start is the first frame that shows one of your acts, and short or
rare acts (69, titjob, fingering, tease) are found less reliably.

Changing **Start at** works the start points out again with the new choice. Starts
you marked with the flag stay.

**Model** picks between two sizes of the same model. **Fast** (the default) takes about
0.15 s a frame on two CPU threads. **Accurate** takes about four times as long and
finds starts more accurately, most of all where sex positions begin. Only the chosen
model is downloaded, and switching works the start points out again.

## The act timeline

<figure class="capture guide-capture">
  <img src="{{ '/assets/auto-seek-timeline.gif' | relative_url }}" alt="The Acts panel under Stash's player: hovering a lane shows that moment's frame, tapping an act's name steps through its stretches, Ctrl + scroll zooms in to per-frame bars, a ruler and a row of frames, and Fit shows the whole scene again" width="760" height="538" loading="lazy">
  <figcaption>The act timeline: hover, step through an act by its name, zoom in, pan, and Fit. Footage pixelated; the scores are the model's real ones for that scene.</figcaption>
</figure>

After the start, Auto Seek scans the whole scene in the background and shows every
act it sees in an **Acts** panel under the player. It fills in live while the scan
runs, with an amber line and a thumbnail showing how far it has got.

- **One lane per act**, in the order the acts first show, lined up with the seek bar.
  A solid block marks each stretch where the act clearly is, and a faint curve shows
  the score in between. A white mark sits where the act first clearly shows. Acts the
  model never gets sure about fold away under **Show N more**.
- **Top act**, above the lanes, shows the act the model is surest of through the
  scene. **Now:** in the header names the act on screen, and its lane lights up.
- **Hover or drag** over a lane to see that moment's frame and which acts it shows.
  Tap a lane to play from there.
- **Tap an act's name** to step through it: the first tap goes to where it first
  shows, each next tap to its next stretch, and then back round to the first. The
  marks under the name show which stretch you're at.
- **Zoom in** with Ctrl + scroll (or pinch on a trackpad or phone) where you point,
  or with the **−** / **+** buttons. **Fit** shows the whole scene again, and a double
  click fits the stretch you clicked. Drag the lanes, scroll sideways or drag the
  window on the Top act strip to move along. Zoomed in, the lanes show one bar per
  frame scanned, with a dashed line at the threshold, a ruler shows the time, and from
  five minutes or less a row of Stash's preview frames opens above the lanes. Tap a
  frame to play from there.
- Tap **Acts** in the header to fold the panel away; it stays folded on other scenes
  until you open it again.

A stretch starts where the act clearly shows (80%) and lasts while its score stays
above 50%, so a score wobbling round the line doesn't split it. Stretches of the
same act up to a minute apart join, and ones shorter than 30 seconds are left out.
Scenes under 10 minutes use shorter limits.

The scan looks at one frame every 10 seconds by default, so a 30-minute scene is
about 180 frames. **Timeline detail** changes the spacing; **Don't scan whole
scenes** turns the scan and the panel off and finds only the start.

## Background work

- **Settings → Tasks → Find start points** analyses every scene without a start
  point, newest first, one at a time, at low priority, and scans its timeline too
  unless *Don't scan whole scenes* is on. It's safe to stop at any time;
  each answer is saved as it's found, and the next run continues where this one
  stopped. Scenes it can't analyse (a broken file, say) are remembered and skipped
  until the model changes.
- **New scenes** are queued as a library scan adds them, and a background worker on
  the server analyses them one at a time. Turn this off with *Don't analyse new
  scenes*.

As a guide, finding the start took 3–5 seconds a scene with the fast model on a home
NAS running Stash in Docker, mostly spent cutting frames. The whole-scene scan looks
at many more frames, so it takes minutes a scene rather than seconds, and the
accurate model about four times as long per frame. A scene you open goes first, and
a background scan pauses for it and continues afterwards.

## Settings

| Setting | What it does |
|---|---|
| Start at | What counts as the start; see [Choose what counts as the start](#choose-what-counts-as-the-start). Default *Oral, hands or sex*. |
| Model | *Fast* (the default) or *Accurate*, about four times slower per frame. |
| Don't scan whole scenes | Find only the start; no act timeline. |
| Timeline detail (seconds) | Seconds between the frames the whole-scene scan looks at, 2–120. Default 10. |
| Skip automatically | Jump to the start when a scene starts playing from the beginning. Off by default. |
| Lead-in (seconds) | Jump this many seconds before the detected start. Default 3. |
| Hide the Skip intro button | Hide the button on the picture and in the control bar. The scan chart and *Skip automatically* still work. |
| Hide the scan chart | Don't draw the scored frames above the seek bar. |
| Don't analyse new scenes | Only analyse scenes when opened or when you run the task. |
| CPU threads per analysis | Threads the image model may use. Default 2. |
| Don't download the model | Never download the model or runtime. Auto Seek then stays unavailable. |

## How it works

Auto Seek scores single frames with a tuned version of CLIP, an image model, which
gives each frame a score for each of 26 acts. A frame's start score is the chance
that it shows any act that counts under **Start at**, and a frame only counts as sure
as the frame 10 seconds after it, so a single misleading frame doesn't decide the
start. It scores the 12 points Stash's preview uses, plus at least one frame every 90
seconds, stopping early once the action is clearly on. Where the scores jump, it scans
the stretch between, then halves the gap a few times to land within seconds.

The whole-scene scan then scores frames at the timeline spacing from start to end and
keeps every act's score per frame. Where an act first clearly shows is narrowed down
the same way, to within a few seconds.

Frames are cut by Stash's own ffmpeg straight into the model's input format and
scored on the server through ONNX Runtime. Results are kept per scene in the
plugin's own database (`data/cache.sqlite3` in the plugin folder), so each scene is
worked out once per model.

### Accuracy

Auto Seek was tuned and tested on one library, so take this as a first impression
rather than a promise. On 210 of its scenes whose start points were checked by hand,
and held out of training, the search landed within 60 seconds of the checked start:

| Start at | Fast model | Accurate model |
|---|---|---|
| Oral, hands or sex | 77% | 78% |
| Kissing or later | 76% | 76% |
| Sex positions only | 38% | 65% |

With the default **Start at**, the accurate model picks late in 11% of scenes and
early in 10%. Typical causes:

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

**The timeline stays empty or stops partway.** The scan runs after the start is
found, one scene at a time, and pauses while a scene you opened is worked out; it
continues where it stopped. Check that *Don't scan whole scenes* is off. A scene
whose file can't be read shows an error in the panel.

**The act timeline names the wrong act.** It judges single frames, so acts that look
alike from one angle (spooning and doggy style, say) get mixed up, and short acts are
found less reliably. Zoom in to see the frame-by-frame scores.

**It picked the wrong start.** Use the flag. If one kind of scene is consistently
wrong, [open an issue](https://github.com/mrx-31415/stash-auto-seek/issues) describing
the kind of opening (no screenshots needed).

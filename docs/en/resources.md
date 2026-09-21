# Space and memory

Every number here was measured on a real receiver — a 2 GB box running a live
480p IPTV channel with Persian translation switched on — not estimated.

---

## Space on the receiver

| | |
|---|---|
| Installed size | **16 MB**, in 141 files |
| Download size | about 15 MB |
| Where it goes | `/usr/lib/enigma2/python/Plugins/Extensions/PIIP` |

What takes up the space:

| Part | Size |
|---|---|
| Artwork — backgrounds, icons, buttons | 15 MB |
| Translation engine | 804 KB |
| Screens | 764 KB |
| Helpers and utilities | 500 KB |
| Providers (M3U, Xtream, Stalker) | 320 KB |
| Everything else | under 50 KB |

The test suite is included on purpose, so that the plugin can be checked on
the receiver itself after an image update: run
`python /usr/lib/enigma2/python/Plugins/Extensions/PIIP/tests/run_all.py`.

### If flash space is tight

The artwork is the only large part. Backgrounds can be deleted without breaking
anything — the screens simply fall back to a plain colour:

```bash
rm /usr/lib/enigma2/python/Plugins/Extensions/PIIP/icons/bg_*.png
```

That brings the plugin down to about 4 MB. They come back the next time you
install or upgrade.

The cover and logo cache is stored on your hard disk, not in flash, and is set
by *Poster / Art Cache Directory* in the settings.

---

## Memory

Enigma2 itself used 198 MB on the test receiver with the plugin loaded. On top
of that, PIIP starts a small set of helper processes only while something is
playing:

| Process | What it does | Memory (RSS) |
|---|---|---|
| ffmpeg (mix) | Mixes translated speech into the stream | 22 MB |
| python (audio helper) | Talks to Gemini, times the speech | 21 MB |
| ffmpeg (capture) | Extracts the channel's sound | 18 MB |
| ffmpeg (source) | Fetches the channel and repackages it | 16 MB |
| python (engine) | Drives the pipeline | 14 MB |
| python (relay) | Holds the fixed A/V delay in RAM | 13 MB |
| python (HTTP relay) | Feeds the prepared stream to Enigma2 | 10 MB |

| Situation | Extra memory used by PIIP |
|---|---|
| Plugin installed, not open | none — nothing is running |
| Browsing the menus | a few MB inside Enigma2 |
| Playing **without** translation | **about 30 MB** (source ffmpeg + engine only) |
| Playing **with** translation | **about 115 MB** (all seven processes) |

On the 2 GB test receiver, 1.37 GB remained available while translating.

> **About these numbers.** RSS counts shared libraries once per process, so the
> true total is somewhat lower than the sum of the rows. Treat 115 MB as a safe
> upper bound rather than an exact figure.

### The delay buffer

The largest single block of memory is the delay that keeps the picture and the
translated speech together: about 12 seconds of the channel's stream, held in
RAM by the relay process. At a typical 1.2 Mbit/s that is under 2 MB; on a
high-bitrate HD channel it grows, which is one reason *Stream bitrate while
translating* defaults to 3 Mbit/s.

---

## Processor

The video is **copied, never re-encoded**. Only the audio is processed. This is
why a 4K channel costs the receiver no more than a standard-definition one, and
why an older box can play channels it could never transcode.

---

## Network

| | |
|---|---|
| Incoming | whatever the channel needs, typically 1–3 Mbit/s |
| Outgoing to Gemini | about 256 kbit/s while translating (16 kHz mono audio) |
| Incoming from Gemini | about 384 kbit/s of translated speech |

A 2 Mbit/s connection is enough for a 480p channel with translation. For HD
channels, allow the channel's own bitrate plus roughly 1 Mbit/s.

---

## How to measure it yourself

Connect by SSH and run:

```bash
du -sh /usr/lib/enigma2/python/Plugins/Extensions/PIIP
```

```bash
free -m
```

```bash
ps w | grep -E "PIIP|ffmpeg" | grep -v grep
```

To see the memory of one process, take its number from the first column of
`ps w` and run `grep VmRSS /proc/<number>/status`.

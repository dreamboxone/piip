# PIIP

**Watch IPTV on your satellite receiver, and hear it in your own language — live.**

PIIP is a plugin for Enigma2 receivers (Dreambox, Vu+, Zgemma, Octagon and
similar boxes). It plays IPTV channels, films and series, and while a channel
is playing it listens to the original sound, translates it, and speaks the
translation out loud in Persian, Arabic, English or Turkish.

🇮🇷 **[راهنمای فارسی](README.fa.md)** — the same guide in Persian.

> **New to all this? Start here.** The [Getting Started guide](docs/en/getting-started.md)
> assumes you have never used SSH, never installed a plugin, and do not know
> what an M3U playlist is. It explains every step.

---

## What you need

| | |
|---|---|
| A receiver | Any Enigma2 box: arm64, armhf or mipsel. One package fits all three. |
| An IPTV subscription | An M3U link, Xtream Codes login, or a Stalker portal. |
| `ffmpeg` on the receiver | Almost every image already has it. |
| A Gemini API key | Only if you want translation. It is free to create. |

Translation is **off** until you switch it on, because it uses your Gemini
account for every minute you watch. Everything else works without a key.

---

## Install in three steps

**1.** Download `enigma2-plugin-extensions-piip_1.0_all.deb` (or `.ipk`) from the
[Releases page](https://github.com/dreamboxone/piip/releases).

**2.** Copy it to the receiver and install it:

```bash
scp enigma2-plugin-extensions-piip_1.0_all.deb root@RECEIVER_IP:/tmp/
```

```bash
ssh root@RECEIVER_IP "dpkg -i /tmp/enigma2-plugin-extensions-piip_1.0_all.deb"
```

On images that use `opkg` instead of `dpkg`, use the `.ipk` file:

```bash
ssh root@RECEIVER_IP "opkg install /tmp/enigma2-plugin-extensions-piip_1.0_all.ipk"
```

**3.** The receiver restarts itself. Open **Menu → Plugins → PIIP**.

Never used `scp` or `ssh`? The [Getting Started guide](docs/en/getting-started.md)
shows you exactly what to type, on Windows, macOS and Linux, with pictures of
each step in words.

**To remove it:** `dpkg -r enigma2-plugin-extensions-piip` (or
`opkg remove enigma2-plugin-extensions-piip`). See
[Install and remove](docs/en/install.md) for a full clean-up.

---

## How much space and memory does it use?

Measured on a real receiver, not estimated:

| | |
|---|---|
| Download size | about 15 MB |
| Space on the receiver | **16 MB** (15 MB of that is the background artwork) |
| Memory while browsing menus | a few MB inside Enigma2 |
| Memory while translating live TV | **about 115 MB** across its helper processes |
| Memory while playing **without** translation | about 30 MB |
| CPU | video is never re-encoded, so a 4K channel costs no more than an SD one |

On a receiver with 2 GB of RAM this leaves well over a gigabyte free.
[Full breakdown](docs/en/resources.md).

---

## Documentation

| Guide | What it covers |
|---|---|
| [Getting Started](docs/en/getting-started.md) | For complete beginners: SSH, API keys, your first channel |
| [Install and remove](docs/en/install.md) | Both package formats, upgrades, full clean-up |
| [Every setting explained](docs/en/options.md) | All 40+ options, what each one does, what to set it to |
| [Remote control keys](docs/en/remote-keys.md) | Every button while watching |
| [Space and memory](docs/en/resources.md) | Measured numbers, and how to shrink them |
| [Troubleshooting](docs/en/troubleshooting.md) | Symptoms, causes, fixes, and how to read the logs |
| [Building from source](docs/en/build.md) | How the `.deb` and `.ipk` are produced |

---

## What it can do

- **Live translation** of the channel's speech into Persian, Arabic, English
  or Turkish, mixed over the original sound with two independent volumes.
- **Three kinds of source:** M3U playlists, Xtream Codes, and Stalker portals.
- **Films and series** with seasons, episodes and resume-where-you-left-off.
- **Programme guide** from your provider or from an XMLTV file, exportable to
  EPGImport.
- **Bouquets:** put IPTV channels into the receiver's own channel list so you
  can zap to them with the normal remote — with or without translation.
- **Subtitles:** search and download from OpenSubtitles and SubDL, with timing
  adjustment.
- **4K without strain:** the picture is copied through untouched.

---

## Privacy and cost

- The plugin runs entirely on your receiver. It sends no telemetry.
- Channel audio is sent to Google's Gemini service **only while translation is
  switched on**, and only with your own API key.
- Google charges your account for that audio. Try short sessions first.
- The local stream server and resolver listen on `127.0.0.1` only — nothing on
  your network can reach them.

---

## Support

- Telegram: [t.me/routekernel1](https://t.me/routekernel1)
- YouTube: [@routekernel](https://youtube.com/@routekernel)
- Problems and ideas: [GitHub Issues](https://github.com/dreamboxone/piip/issues)

---

## Licence

© 2026 Routekernel. All rights reserved. Use and redistribution are governed
by [LICENSE](LICENSE).

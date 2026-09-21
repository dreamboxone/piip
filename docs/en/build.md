# Building from source

You do not need this page to use PIIP — ready-made packages are on the
[Releases page](https://github.com/dreamboxone/piip/releases). Read on only if
you want to build them yourself or change the plugin.

---

## What you need

- Python 3.8 or newer, on any computer: Windows, macOS or Linux.
- Nothing else. No `dpkg`, no `opkg`, no compiler, no Linux machine.

The packages are written directly by Python, because a `.deb` (and an `.ipk`,
which uses the same format) is just an `ar` archive holding three members.

---

## Get the source

```bash
git clone https://github.com/dreamboxone/piip.git
```

```bash
cd piip
```

---

## Run the tests first

```bash
python PIIP/tests/run_all.py
```

You should see a summary ending in something like
`1559 checks passed, 0 failed, 0 suites crashed`.

The suite runs on a desktop computer: Enigma2 itself is replaced by a stub, so
screens, skins, playlists, providers and the translation helpers are all
exercised without a receiver.

One of the suites is a static audit for **Python 2.7 compatibility** — receivers
in the field still run Python 2.7, and this computer cannot execute it, so every
module is parsed and checked for syntax and library calls that do not exist
there. If you edit the plugin, keep that suite green.

> On Windows, if Persian text in the output raises a `UnicodeEncodeError`, run
> `set PYTHONIOENCODING=utf-8` first (PowerShell: `$env:PYTHONIOENCODING='utf-8'`).

---

## Build the packages

```bash
python packaging/build_deb.py
```

```bash
python packaging/build_ipk.py
```

Both write into `dist/`:

```
dist/enigma2-plugin-extensions-piip_1.0_all.deb
dist/enigma2-plugin-extensions-piip_1.0_all.ipk
```

Each is about 15 MB and contains 141 files.

---

## Check what you built

```bash
python packaging/verify_deb.py dist/enigma2-plugin-extensions-piip_1.0_all.deb
```

This unpacks the archive again and checks that every source file is present,
that nothing unexpected was added, that the extracted files match the source
byte for byte, and that the icon is a valid PNG.

---

## Change the version number

The version lives in one place:

```python
# packaging/build_deb.py
VERSION = '1.0'
```

`build_ipk.py` imports it, so both packages always carry the same number.

---

## How the package is put together

| Member | What it holds |
|---|---|
| `debian-binary` | The text `2.0` |
| `control.tar.gz` | The package description and the four maintainer scripts |
| `data.tar.gz` | The plugin, under `usr/lib/enigma2/python/Plugins/Extensions/PIIP` |

The maintainer scripts:

| Script | When it runs | What it does |
|---|---|---|
| `preinst` | Before unpacking | Deletes any previous version of the plugin folder |
| `postinst` | After unpacking | Prints what is still missing, then restarts Enigma2 |
| `prerm` | Before removal | Explains how to clean up settings and bouquets |

`postinst` restarts Enigma2 in the foreground, trying `systemctl`, then
`/etc/init.d/enigma2`, then `init 4` / `init 3`, and finally `killall`. It runs
in the foreground on purpose: a backgrounded restart is killed along with
dpkg's process group before it ever fires.

### Why one package for every receiver

The plugin is pure Python, so the package is marked `Architecture: all` and the
same file installs on arm64, armhf and mipsel. The difference between `.deb` and
`.ipk` is only the control stanza — `opkg` resolves dependencies itself and
wants `Depends:`, while `dpkg` on DreamOS is happy with `Recommends:`.

---

## Project layout

```
PIIP/                 the plugin, exactly as it is installed
  plugin.py           settings and the Enigma2 entry points
  main.py             the plugin's first screen
  screens/            every screen, including player.py
  providers/          M3U, Xtream Codes and Stalker clients
  translate/          the translation engine
    e2dub/            the audio pipeline: capture, relay, Gemini, mixing
  utils/              skins, subtitles, bouquets, artwork, logging
  tests/              the test suite (also shipped, to run on the receiver)
  icons/              backgrounds and artwork
packaging/            the package builders and the verifier
docs/                 this documentation
```

---

## Installing what you built

```bash
scp dist/enigma2-plugin-extensions-piip_1.0_all.deb root@RECEIVER_IP:/tmp/
```

```bash
ssh root@RECEIVER_IP "dpkg -i /tmp/enigma2-plugin-extensions-piip_1.0_all.deb"
```

While developing it is often quicker to copy a single file and restart Enigma2:

```bash
scp PIIP/screens/player.py root@RECEIVER_IP:/usr/lib/enigma2/python/Plugins/Extensions/PIIP/screens/
```

```bash
ssh root@RECEIVER_IP "rm -f /usr/lib/enigma2/python/Plugins/Extensions/PIIP/screens/player.pyo; killall -9 enigma2"
```

Delete the matching `.pyo` file, or the receiver keeps running the old compiled
copy.

# Install, upgrade and remove

If you have never used SSH, read [Getting started](getting-started.md) first —
it explains each command instead of assuming it.

---

## Which package do I need?

| Your image | Package |
|---|---|
| DreamOS — Dreambox One / Two, DM900, DM920 | `.deb` |
| OpenPLi, OpenATV, OpenViX, VTi, Egami, Zgemma stock and most others | `.ipk` |
| Not sure | Try `.deb`; if you get `dpkg: command not found`, use `.ipk` |

Both packages contain exactly the same plugin and are marked `all`, which means
one file installs on **arm64, armhf and mipsel** receivers alike. There is
nothing to choose based on your processor.

---

## Install

**1. Copy the file to the receiver** (run this on your computer):

```bash
scp enigma2-plugin-extensions-piip_1.0_all.deb root@RECEIVER_IP:/tmp/
```

**2. Install it** (run this on the receiver, over SSH or Telnet):

```bash
dpkg -i /tmp/enigma2-plugin-extensions-piip_1.0_all.deb
```

or

```bash
opkg install /tmp/enigma2-plugin-extensions-piip_1.0_all.ipk
```

**3. That is all.** The installer restarts Enigma2 by itself, and deletes the
package file from `/tmp` afterwards. The picture returns after a few seconds.

Then: **Menu → Plugins → PIIP**

### What the installer tells you

After installing, it prints reminders for anything still missing — the Gemini
key, a playlist file, or `ffmpeg`. Reading those three lines saves a lot of
time.

### What it puts where

| Path | What |
|---|---|
| `/usr/lib/enigma2/python/Plugins/Extensions/PIIP` | The plugin itself |
| `/root/m3u.txt` | An empty playlist file, created for you |
| `/etc/enigma2/piip_*.json` | Your settings and saved servers |
| `/etc/enigma2/userbouquet.piip_*.tv` | Bouquets you export |
| `/etc/epgimport/piip.*` | Guide files for EPGImport |
| `/tmp/piip_*.log` | Logs — cleared at every reboot |

---

## Upgrade

Install the new package exactly the same way. The installer removes the old
version first.

**Your settings, saved servers, bouquets and API key are kept.** They live
outside the plugin folder.

---

## Remove

```bash
dpkg -r enigma2-plugin-extensions-piip
```

or

```bash
opkg remove enigma2-plugin-extensions-piip
```

This leaves your settings and bouquets in place, so that reinstalling brings
everything back as it was.

### Remove everything, including settings

```bash
rm -f /etc/enigma2/userbouquet.piip_*.tv /etc/enigma2/piip_*.json /etc/epgimport/piip.*
```

Then restart the receiver.

Your API key in `/root/apikey.txt` is never touched by installing or removing.
Delete it by hand if you want it gone:

```bash
rm -f /root/apikey.txt
```

---

## Installing without a computer

Some images can install a package from the receiver itself:

**Menu → Plugins → (blue button) → Install local extension**

Put the file on a USB stick, plug it in, and pick it from there. The exact menu
wording differs between images.

---

## Common install problems

| What you see | What to do |
|---|---|
| `dpkg: command not found` | Your image uses opkg. Use the `.ipk`. |
| `opkg: command not found` | Your image uses dpkg. Use the `.deb`. |
| `Permission denied` when copying | You are not connecting as `root`. Use `root@ADDRESS`, not your own user name. |
| `Connection refused` | SSH is switched off on the receiver: **Menu → Setup → System → Network → Network Services**. |
| The plugin does not appear in the menu | Enigma2 did not restart. Run `killall -9 enigma2`, or reboot the receiver. |
| Nothing plays after installing | `ffmpeg` is missing. Install it with `opkg install ffmpeg` or `apt-get install ffmpeg`. |

More symptoms in [Troubleshooting](troubleshooting.md).

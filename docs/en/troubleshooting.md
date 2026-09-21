# Troubleshooting

Work down this page: the first section covers what goes wrong most often.

Before anything else, run **Check receiver requirements** from the plugin's
main menu. It examines `ffmpeg`, your API key, network, ports and free space,
and says in plain words what is missing.

---

## Playback

### Nothing plays — the screen stays black

1. Open the settings (**INFO**) and set **Default Live Stream Type** to
   `5002 (exteplayer3)`. This alone fixes most cases, especially on DreamOS.
2. If films work but live does not (or the other way round), remember there are
   two separate settings: *Default Live Stream Type* and
   *Default VOD Stream Type*.
3. Check `ffmpeg` is installed: type `ffmpeg -version` over SSH. If it is
   missing, install it with `opkg install ffmpeg` or `apt-get install ffmpeg`.

### The playlist will not load

From the plugin's main menu choose **Test playlists**. It shows each playlist's
address (with the password hidden), the HTTP code the server returned, and the
server's answer. Then:

| Code | Meaning | What to do |
|---|---|---|
| `401` | Wrong username or password | Check your subscription details |
| `403` | The server is blocking you | PIIP retries automatically with a player-like identity; if it still fails, test the address in a browser — some providers block by country or by device |
| `404` | Wrong address | Ask your provider for the current link |
| `429` | Too many requests | Wait a few minutes; you have hit the provider's limit |

### The picture freezes or stutters

- Set **Stream bitrate while translating** to `1.5 Mbit/s`.
- Try `5002 (exteplayer3)` as the stream type.
- Check whether the channel plays smoothly with translation **off** (red
  button). If it stutters even then, the problem is the stream or your
  connection, not the translation.

### The picture disappears for a few seconds now and then

The receiver's decoder briefly lost the local stream and reattached. Version 1.0
raises the decoder's buffer to 5 seconds to absorb short hiccups. If you still
see it, note the time and look at `/tmp/piip_dub.log` around it — the line
`Native Enigma2 HTTP/TS client connected` marks each reattachment.

---

## Translation

### No translation at all

1. Is it switched on? The **red** button while watching, or *Translation
   enabled* in the settings.
2. Is the key there? Over SSH: `wc -c /root/apikey.txt` should print about 40.
3. Run **Check receiver requirements**.
4. Look at the log: `tail -30 /tmp/piip_dub.log`. A line containing `401` or
   `403` means the key is wrong or not enabled for the Gemini API.

### It starts and then stops after a few minutes

Usually the Gemini quota or billing on your Google account. Check your usage at
<https://aistudio.google.com>. The log shows the reason:

```bash
grep -i "retrying\|quota\|denied" /tmp/piip_dub.log | tail
```

### The translation is behind the picture

A few seconds behind is normal and unavoidable — see *A note about the delay* in
[Getting started](getting-started.md).

If it drifts much further, PIIP corrects it by itself: about once a minute it
briefly stops feeding audio to the model so it can catch up with the picture.
During that moment a phrase or two goes untranslated. You can see the measured
lag in the log:

```bash
grep "Audio flow" /tmp/piip_dub.log | tail -5
```

The `drift=` value is how many seconds behind the translation was. Values under
about 10 are normal. Lower **Max backlog** in the settings to keep it tighter,
at the cost of skipping more speech.

### The translated speech cuts out

The delay is too short for your connection. Raise it with the **green** button
while watching, or *Delay* in the settings.

### Songs and music come out as nonsense

Expected. The translation model is built for speech; sung lyrics defeat it.
Press the **red** button to switch translation off during music and hear the
original at full volume.

### The lips do not match the picture

Change the delay by a second or two with the **green** button.

---

## Subtitles

| Problem | Fix |
|---|---|
| Nothing is found | Check the OpenSubtitles or SubDL key in the settings, and *Subtitle Language* |
| They run early or late | Keys `2` and `8` while watching, half a second per press |
| They drift further apart as the film goes on | Wrong frame rate: keys `4` and `6` |
| They do not show at all | Key `0` toggles them |

---

## Bouquets

| Problem | Fix |
|---|---|
| Channels in the bouquet do not play | Enigma2 was not restarted after exporting. The Bouquets screen shows the resolver's state. |
| Bouquet channels have no translation | Switch on *Translated audio in bouquets*. Zapping then takes a few seconds longer. |
| The bouquet is empty after reinstalling | Export it again from the Bouquets menu. |

---

## Reading the logs

All logs are in `/tmp`, so they are cleared at every reboot.

| File | What it records |
|---|---|
| `/tmp/piip_dub.log` | Translation: connection, timing, drift, buffers |
| `/tmp/piip_engine.log` | The source stream: the channel, ffmpeg, restarts |
| `/tmp/piip_resolver.log` | Bouquet channel resolution |
| `/tmp/piip_ui.log` | The screens |

Useful commands over SSH:

```bash
tail -40 /tmp/piip_dub.log
```

```bash
grep "Audio flow" /tmp/piip_dub.log | tail -5
```

```bash
grep -iE "error|failed|retrying" /tmp/piip_engine.log | tail -20
```

**Before posting a log anywhere, check it for your subscription address and
password.** PIIP hides your API key, but a stream URL can contain your login.

---

## Starting again from scratch

If the plugin is behaving strangely and nothing else helps:

```bash
dpkg -r enigma2-plugin-extensions-piip
```

```bash
rm -f /etc/enigma2/piip_*.json /etc/enigma2/userbouquet.piip_*.tv
```

Then install the package again. Your API key in `/root/apikey.txt` survives
this.

---

## Still stuck?

- Telegram: [t.me/routekernel1](https://t.me/routekernel1)
- [Open an issue](https://github.com/dreamboxone/piip/issues) and include:
  your receiver model and image, the plugin version, what you did, what
  happened, and the last 40 lines of the relevant log — with any password or
  subscription link removed.

# Every setting explained

Open the settings with **PIIP → INFO**, or from the main menu of the plugin.

Move with `↑` `↓`, change a value with `←` `→`, and press the **green** button
to save. Nothing is saved until you press green.

The list below follows the same order as the screen.

---

## The first group — files, subtitles and lists

### OpenSubtitles API Key
Lets PIIP search the OpenSubtitles website for subtitle files.
Get a free key at <https://www.opensubtitles.com/consumers> (create an account,
then *New consumer*). Leave it empty if you do not want subtitles from there.

### Download / Subtitle Directory
Where downloaded films and subtitle files are saved.
**Default:** `/media/hdd/movie/`
Use a folder on a hard disk or USB stick, never on the receiver's internal flash
— flash memory is small and wears out.

### Poster / Art Cache Directory
Where cover images and channel logos are kept so they do not have to be
downloaded again.
**Default:** `/media/hdd/.piip_cache/`
Safe to delete by hand at any time; it fills up again as needed.

### Subtitle Position
Where subtitles appear on screen: **Bottom**, **Middle** or **Top**.
**Default:** Bottom. Choose Top if your TV crops the bottom of the picture.

### Subtitle Size
**Small**, **Medium**, **Large** or **Extra large**.
**Default:** Medium. Pick Large on a big TV or if you sit far away.

### Subtitle Color
**White**, **Yellow** or **Green**.
**Default:** White. Yellow is easier to read over a bright picture.

### Default VOD Stream Type
Which internal player Enigma2 uses for films and series. This is the single most
useful setting when something refuses to play.

| Value | When to use it |
|---|---|
| `4097 (gstreamer)` | The default. Works on most images. |
| `5002 (exteplayer3)` | Try this first if playback does not start, or the picture stutters. Often the best choice on DreamOS. |
| `8193 (ServiceURL)` | Rare; some images need it for HTTPS links. |
| `8197 (widevine)` | Only for DRM-protected content. |

### Show +18 Adult Content
Whether categories your provider marks as adult appear in the lists.
**Default:** No.

### Items per Page (Poster Count)
How many films or series are shown on one page: 10, 20, 30, 40 or 50.
**Default:** 20. Lower numbers feel faster on an older receiver because fewer
cover images have to be fetched at once.

### VOD/Series Skin Style
How films and series are presented:

| Value | Looks like |
|---|---|
| `Default` | A plain list. Fastest. |
| `Hybrid carousel` | A sliding row of covers. |
| `Cover collection` | A grid of covers. |
| `2D cover collection` | A flat grid, lighter on the receiver. |

---

## PIIP extras

### SubDL API key
A second subtitle source, useful because it often has Persian subtitles that
OpenSubtitles does not. Free key at <https://subdl.com>.

### Subtitle Language
Which language subtitles are searched for: **Persian**, **Arabic**, **English**
or **Turkish**.
**Default:** Persian.

### TMDB API key
Optional. With a key from <https://www.themoviedb.org/settings/api>, PIIP can
show proper posters and descriptions for films whose artwork your provider does
not supply.

### WebIF port
The port of the small built-in web page for managing PIIP from a browser.
**Default:** `8914`. Only change it if another program on the receiver already
uses that number.

---

## Guide

### Guide enabled
Whether the programme guide (now playing / next) is shown and kept up to date.
**Default:** Yes. Switching it off saves a little memory and network traffic on
a slow line.

### XMLTV URL
Only needed for M3U playlists that do not carry guide information themselves.
Paste the address of an XMLTV file your provider gave you. Leave empty
otherwise — Xtream and Stalker sources always bring their own guide.

---

## Stalker portals

### Portal list URL
Where the **LOAD ONLINE** button in the Stalker screen fetches a list of public
portals from. Most people never touch this.
**Default:** `https://satelliweb.gt.tc/stalker_list.log`

---

## Bouquets

A *bouquet* is a channel list inside the receiver itself. Exporting IPTV
channels into one lets you zap to them with the normal remote, next to your
satellite channels, without opening the plugin at all.

### Translated audio in bouquets
Whether channels zapped from a bouquet also get the live translation.

| Value | What happens |
|---|---|
| No (default) | Zapping is instant. No translation. |
| Yes | Every zap starts the translation pipeline, which takes a few extra seconds before the picture appears. |

### Resolver port
The internal helper that turns a bouquet entry into a real stream listens on
this port, on `127.0.0.1` only.
**Default:** `8913`. Change it only if it clashes with another plugin —
HybridIPTV, for instance, uses `8903`.

---

## Advanced

Most people never need this group. Change one thing at a time.

### Default Live Stream Type
The same choice as *Default VOD Stream Type*, but for live channels.
**Default:** `4097 (gstreamer)`. If live channels will not start, try
`5002 (exteplayer3)`.

### ffmpeg
The command used to run ffmpeg.
**Default:** `ffmpeg`. Set a full path such as `/usr/bin/ffmpeg` only if the
plugin reports that it cannot find it.

### Local stream port
The port on which PIIP serves the prepared stream to Enigma2, on `127.0.0.1`.
**Default:** `8901`.

### Control port
The port PIIP's screens use to talk to the playback engine, on `127.0.0.1`.
**Default:** `8902`.

### User agent
The name PIIP gives when it asks your provider for a stream. Some providers
block anything that does not look like a normal player.
**Default:** a Qt/WebKit identifier that most providers accept. Change it only
if your provider told you to.

---

## Translation

This is the group that matters most for translation quality.

### Translation enabled
The master switch.
**Default:** No — because translation costs money for every minute you watch.
You can also toggle it while watching with the **red** button.

### API key
Your Gemini key, if you would rather type it here than put it in a file.

**The file wins.** PIIP looks in this order and uses the first it finds:

1. the `GEMINI_API_KEY` environment variable
2. `/root/apikey.txt`
3. `/etc/enigma2/piip_apikey.txt` — survives reinstalling the plugin
4. `apikey.txt` next to the plugin folder
5. this field

Spaces, quotation marks and Windows line endings are removed automatically. The
key is never printed in full on screen, in a log, or in the process list.

### Model override
Leave empty. PIIP uses `gemini-3.5-live-translate-preview`, the model built for
speech-to-speech translation. The field exists so that a newer model can be used
one day without waiting for a plugin update.

### Target language
The language you want to hear: **Persian**, **Arabic**, **English** or
**Turkish**.
**Default:** Persian.

### Delay
How long the picture is held back so the translated speech can catch up with
it, in seconds.
**Range:** 1 to 12. **Default:** 6.

This is a *minimum*. PIIP measures the real round trip when playback starts and
settles on whatever is actually needed, usually about 12 seconds. A larger value
is safer on a slow connection; a smaller one puts you closer to live but risks
the translation being cut off.

You can also change it while watching with the **green** button.

### Max backlog
How far the translation is allowed to fall behind the picture, in seconds,
before PIIP steps in.
**Range:** 2 to 20. **Default:** 6.

**Why this exists.** The translation engine speaks more slowly than dense live
speech arrives, so on a talkative channel it falls further behind every minute —
after five minutes you could be hearing the translation of a scene that has
already ended. PIIP measures this and briefly stops feeding it audio so it can
catch up with the picture.

The cost is that a phrase or two is not translated each time it catches up. A
smaller value keeps the translation tightly in sync but skips more; a larger one
translates more but drifts further.

### Stream bitrate while translating
Many IPTV channels offer the same programme in several qualities. While
translating, PIIP can ask for a lighter one so the receiver keeps up.

| Value | Meaning |
|---|---|
| `Automatic (best)` | Always take the highest quality on offer. |
| `1.5 Mbit/s` | Safest on a slow line. |
| `3 Mbit/s` | **Default.** Measured as the best balance on a real receiver. |
| `5 Mbit/s` | Only on a fast line and a strong receiver. |

This only applies to channels that actually offer a choice; others play exactly
as they are.

### Channel volume
How loud the **original** sound of the channel is underneath the translation, as
a percentage.
**Range:** 0 to 100. **Default:** 30.

0 means the original is silent. Values above 100 are not offered because they
would only distort the mix.

### Translation volume
How loud the **translated** speech is, as a percentage.
**Range:** 0 to 100. **Default:** 100.

Both volumes can be changed instantly while watching with the arrow keys.

---

## Settings that are not on this screen

### Your subscription
Chosen from the plugin's main menu (**Xtream Codes**, **M3U Playlist**,
**Stalker Portal**) and stored in the saved-server list, so you can keep several
subscriptions and switch between them with the **MENU** button.

### Subtitle timing
Adjusted while watching, not here — keys `2` and `8` shift subtitles earlier or
later, keys `4` and `6` change the frame rate they were timed for. See
[Remote control keys](remote-keys.md).

# Remote control keys

## While a channel, film or episode is playing

| Key | What it does |
|---|---|
| **OK** | Open the channel list, to jump to another channel without leaving playback |
| **↑ / ↓** | Volume of the **original channel** sound |
| **→ / ←** | Volume of the **translated** speech |
| **RED** | Translation on / off |
| **GREEN** | Change the delay (cycles through the available values) |
| **YELLOW** | Skip back 60 seconds — films and series only |
| **BLUE** | Skip forward 60 seconds — films and series only |
| **MENU** | Show or hide the information panel by hand |
| **INFO** | Technical status: engine state, buffer, bitrate, connection |
| **EXIT** | Stop playback and go back |
| **0** | Subtitles on / off |
| **1** | Search and download subtitles for what you are watching |
| **2 / 8** | Move subtitles earlier / later, half a second at a time |
| **3** | Switch the player (gstreamer ↔ exteplayer3) without going to settings |
| **4 / 6** | Change the frame rate the subtitles were timed for |
| **5** | Programme guide for this channel |
| **7** | Change the aspect ratio (how 4:3 material fills a 16:9 screen) |

### The information panel

The panel at the bottom of the screen disappears on its own **five seconds
after the picture appears**, and any key brings it back for another five.

While the channel is still opening, or reconnecting after a problem, it stays on
screen on purpose — it is the only place that tells you what the receiver is
busy with.

The state text means:

| Text | Meaning |
|---|---|
| `buffering... 4s` | The channel is opening. |
| `buffering translation... 9s` | The translation pipeline is being built. |
| `connecting to Gemini...` | Contacting the translation service. |
| `waiting for translation...` | Connected; the first speech has not arrived yet. |
| `translation buffering...` | Speech is arriving and being lined up with the picture. |
| `translating` | Working normally. You are hearing the translation. |
| `playing` | Playing without translation. |
| `stream lost - retry in 4s` | The stream stopped; PIIP is reconnecting by itself. |

---

## In the lists (channels, films, series)

| Key | What it does |
|---|---|
| **OK** | Open the selected item |
| **↑ / ↓** | Move through the list |
| **← / →** | Previous / next page |
| **EXIT** | Back |
| **INFO** | Programme guide, where there is one |

---

## On the plugin's main screen

| Key | What it does |
|---|---|
| **OK** | Open the selected section |
| **← / →** | Move between sections |
| **RED** | Close the plugin |
| **MENU** | Saved servers — switch between subscriptions |
| **INFO** | Settings |
| **GREEN** | Downloads |

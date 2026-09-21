# Getting started — for complete beginners

This guide assumes nothing. If you have never connected to your receiver with a
computer, never installed a plugin, and do not know what an M3U link is, you are
in the right place. Follow it from top to bottom and you will end up watching a
channel with live translation.

Set aside about 20 minutes for the first time.

---

## Step 1 — Find your receiver's IP address

Your receiver has an address on your home network, four numbers separated by
dots, like `192.168.1.50`. You will need it in almost every step.

On the receiver, with the remote:

**Menu → Setup → System → Network → Device Setup**

Write down the number next to **IP address**.

If your menu looks different, look for anything called *Network*, *LAN*, or
*Network settings*. The address is always shown there.

> **Tip:** it is worth telling your home router to always give the receiver the
> same address, so this number never changes. In the router's settings this is
> usually called *DHCP reservation* or *static lease*.

---

## Step 2 — Connect to the receiver from your computer

Your receiver is a small Linux computer. To install a plugin you send files to
it and run one command. The tool for that is called **SSH**, and it is already
installed on Windows 10/11, macOS and Linux.

### Open a terminal

| Your computer | What to open |
|---|---|
| Windows 10 or 11 | Press `Windows key`, type **PowerShell**, press Enter |
| macOS | Press `Cmd + Space`, type **Terminal**, press Enter |
| Linux | Your usual terminal application |

### Connect

Type this, replacing `192.168.1.50` with your receiver's address, then press
Enter:

```bash
ssh root@192.168.1.50
```

The first time, it asks something like *"Are you sure you want to continue
connecting?"* — type `yes` and press Enter.

Then it asks for a password. Most images use one of these:

- no password at all (just press Enter)
- `root`
- `dreambox`
- a password you set yourself when you flashed the image

When it works you see a line ending in `#`, for example `root@dreambox:~#`.
That means you are now typing commands **on the receiver**, not on your
computer.

To leave later, type `exit` and press Enter.

> **It says "Connection refused" or nothing happens.** Some images ship with SSH
> turned off. On the receiver: **Menu → Setup → System → Network → Network
> Services**, and switch on **SSH** (sometimes called *Dropbear* or *OpenSSH*).

---

## Step 3 — Get a Gemini API key (only if you want translation)

Translation is done by Google's Gemini service. You need a key — a long line of
letters and numbers that identifies your account.

1. On your computer, open <https://aistudio.google.com/apikey>
2. Sign in with a Google account.
3. Click **Create API key**.
4. Copy the key. It starts with `AIza` and is about 39 characters long.

> **This key is like a password to your Google account's billing.** Never post
> it in a group, a screenshot, or a GitHub issue. If it leaks, delete it on the
> same page and make a new one.

**Cost:** Google charges for every minute of audio you translate. Start with
short sessions and watch your usage on the same website until you know what a
typical evening costs you.

You will put the key on the receiver in step 5.

---

## Step 4 — Install the plugin

Download the package on your computer from the
[Releases page](https://github.com/dreamboxone/piip/releases):

- `enigma2-plugin-extensions-piip_1.0_all.deb` — for DreamOS receivers
  (Dreambox One/Two, DM900, DM920…)
- `enigma2-plugin-extensions-piip_1.0_all.ipk` — for OE-Alliance images
  (OpenPLi, OpenATV, OpenViX, VTi, Zgemma and most others)

Not sure which one? Try the `.deb` first. If the receiver answers
`dpkg: command not found`, use the `.ipk`.

### Send the file to the receiver

In the terminal **on your computer** (not the one connected to the receiver —
open a second window, or type `exit` first), go to the folder where you
downloaded the file, then:

```bash
scp enigma2-plugin-extensions-piip_1.0_all.deb root@192.168.1.50:/tmp/
```

`scp` means *secure copy*. `/tmp/` is a temporary folder on the receiver.

> **On Windows**, if the file is in your Downloads folder, first type
> `cd $HOME\Downloads` and press Enter.

### Install it

Connect again with `ssh root@192.168.1.50`, then type:

```bash
dpkg -i /tmp/enigma2-plugin-extensions-piip_1.0_all.deb
```

or, for the `.ipk` file:

```bash
opkg install /tmp/enigma2-plugin-extensions-piip_1.0_all.ipk
```

You will see a few lines of text, then **the picture on your TV disappears for
a few seconds** while Enigma2 restarts. That is normal and expected. Your SSH
connection stays alive.

---

## Step 5 — Put your API key on the receiver

Still connected by SSH, type this as one line, replacing `YOUR_KEY` with the key
you copied in step 3:

```bash
echo 'YOUR_KEY' > /root/apikey.txt && chmod 600 /root/apikey.txt
```

`chmod 600` means *only the owner may read this file*.

To check it worked:

```bash
wc -c /root/apikey.txt
```

It should print a number around 40. If it prints `0`, the file is empty — try
again and make sure you kept the quotation marks.

> **Prefer not to use SSH for this?** You can also type the key into the plugin:
> **PIIP → INFO (Settings) → Translation → API key**. The file always wins over
> the typed value.

---

## Step 6 — Add your IPTV subscription

Open **Menu → Plugins → PIIP** on the receiver. The first screen asks what kind
of subscription you have. Your provider gave you one of these three:

### A. An M3U link

A long web address, usually containing `get.php?username=...&password=...`.

Choose **M3U Playlist**, then paste the address into the **URL** field.

Typing a long address with the remote is painful. Two easier ways:

- **Use the on-screen keyboard** — press OK on the field and type with the
  number keys, like an old mobile phone.
- **Put it in a file instead.** Over SSH:

  ```bash
  echo 'http://your-provider.tv/get.php?username=USER&password=PASS&type=m3u_plus' > /root/m3u.txt
  ```

  PIIP reads `/root/m3u.txt` automatically. You can put several playlists in it,
  one per line, and even give them names:

  ```
  Sport = http://another-provider.tv/playlist.m3u
  /media/hdd/my-local-list.m3u
  ```

### B. An Xtream Codes account

Your provider gave you a **host address**, a **username** and a **password**.

Choose **Xtream Codes** and fill in the three fields.

### C. A Stalker portal

Your provider gave you a **portal address** and registered a **MAC address** for
you (it looks like `00:1A:79:xx:xx:xx`).

Choose **Stalker Portal** and fill in both.

Press the **green** button to save.

---

## Step 7 — Check the receiver is ready

From the plugin's main screen, choose **Check receiver requirements**.

It looks for `ffmpeg`, for your API key, and for everything else it needs, and
tells you in plain words what is missing. Fix anything it complains about before
going further — it saves a lot of guessing later.

---

## Step 8 — Watch your first channel

1. **PIIP → Live TV**
2. Pick a group, then a channel, and press **OK**.
3. The screen is black for a few seconds while the channel opens. The panel at
   the bottom tells you what is happening (`buffering... 3s`).
4. The picture appears. Five seconds later the panel fades away on its own.
   Press any key to bring it back.

**No translation yet** — that is deliberate.

---

## Step 9 — Turn translation on

While the channel is playing, press the **red** button.

The panel shows `connecting to Gemini...`, then `translation buffering...`,
then `translating`. The first Persian speech arrives after about ten seconds.

Now adjust the two volumes with the arrow keys:

| Key | What it changes |
|---|---|
| `→` and `←` | Volume of the **translation** |
| `↑` and `↓` | Volume of the **original channel** |

A good starting point is translation at 100% and the original channel at 30%,
which is what PIIP uses by default: you still hear the original voices quietly
underneath, like a news interpreter.

Press **red** again to switch translation off.

---

## What next

- Every single setting, explained one by one:
  **[Options reference](options.md)**
- Every button on the remote while watching:
  **[Remote control keys](remote-keys.md)**
- Something not working? **[Troubleshooting](troubleshooting.md)**
- Want IPTV channels in your normal channel list, so you can zap to them with
  the remote like any satellite channel? That is the **Bouquets** menu — see
  [Options reference](options.md#bouquets).

---

## A note about the delay

Live translation is not instant, and it cannot be. The sound has to travel to
Google, be understood, be translated, be spoken, and travel back. PIIP holds the
picture back by about 12 seconds so that the translated speech lands on the
right scene.

That means **the picture you see is about 12 seconds behind live**. If you are
watching a football match, your neighbour without the plugin will cheer before
you do. This is the price of hearing the programme in your own language, and
every live translation system has it.

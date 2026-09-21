<div dir="rtl">

# نصب، به‌روزرسانی و حذف

اگر تا حالا با SSH کار نکرده‌اید، اول [شروع از صفر](getting-started.md) را
بخوانید — آنجا هر دستور توضیح داده شده به‌جای اینکه فرض شود می‌دانید.

---

## کدام بسته را لازم دارم؟

| ایمیج شما | بسته |
|---|---|
| DreamOS — دریم‌باکس One / Two، DM900، DM920 | `.deb` |
| OpenPLi، OpenATV، OpenViX، VTi، Egami، زگما و بیشتر بقیه | `.ipk` |
| مطمئن نیستید | اول `.deb`؛ اگر پیام `dpkg: command not found` گرفتید، `.ipk` |

هر دو بسته دقیقاً یک پلاگین را دارند و با معماری `all` علامت خورده‌اند؛ یعنی یک
فایل روی **arm64، armhf و mipsel** نصب می‌شود. بر اساس پردازندهٔ رسیور چیزی برای
انتخاب کردن وجود ندارد.

---

## نصب

**۱. فایل را روی رسیور کپی کنید** (این را روی کامپیوترتان بزنید):

</div>

```bash
scp enigma2-plugin-extensions-piip_1.0_all.deb root@RECEIVER_IP:/tmp/
```

<div dir="rtl">

**۲. نصبش کنید** (این را روی رسیور، با SSH یا Telnet):

</div>

```bash
dpkg -i /tmp/enigma2-plugin-extensions-piip_1.0_all.deb
```

<div dir="rtl">

یا

</div>

```bash
opkg install /tmp/enigma2-plugin-extensions-piip_1.0_all.ipk
```

<div dir="rtl">

**۳. تمام.** نصب‌کننده خودش انیگما۲ را ری‌استارت می‌کند و فایل بسته را از `/tmp`
پاک می‌کند. تصویر بعد از چند ثانیه برمی‌گردد.

سپس: **Menu ← Plugins ← PIIP**

### نصب‌کننده چه می‌گوید

بعد از نصب، یادآوری می‌کند چه چیزی هنوز کم است — کلید Gemini، فایل پلی‌لیست یا
`ffmpeg`. خواندن همان دو سه خط کلی وقت صرفه‌جویی می‌کند.

### چه چیزی کجا گذاشته می‌شود

| مسیر | چیست |
|---|---|
| `/usr/lib/enigma2/python/Plugins/Extensions/PIIP` | خود پلاگین |
| `/root/m3u.txt` | یک فایل پلی‌لیست خالی که برایتان ساخته می‌شود |
| `/etc/enigma2/piip_*.json` | تنظیمات و سرورهای ذخیره‌شدهٔ شما |
| `/etc/enigma2/userbouquet.piip_*.tv` | بوکه‌هایی که می‌سازید |
| `/etc/epgimport/piip.*` | فایل‌های جدول پخش برای EPGImport |
| `/tmp/piip_*.log` | لاگ‌ها — با هر ری‌استارت پاک می‌شوند |

---

## به‌روزرسانی

بستهٔ جدید را دقیقاً مثل بالا نصب کنید. نصب‌کننده اول نسخهٔ قبلی را پاک می‌کند.

**تنظیمات، سرورهای ذخیره‌شده، بوکه‌ها و کلید API شما دست‌نخورده می‌مانند**، چون
بیرون از پوشهٔ پلاگین ذخیره شده‌اند.

---

## حذف

</div>

```bash
dpkg -r enigma2-plugin-extensions-piip
```

<div dir="rtl">

یا

</div>

```bash
opkg remove enigma2-plugin-extensions-piip
```

<div dir="rtl">

این کار تنظیمات و بوکه‌ها را باقی می‌گذارد تا اگر دوباره نصب کردید همه‌چیز سر
جایش باشد.

### پاک کردن کامل، همراه با تنظیمات

</div>

```bash
rm -f /etc/enigma2/userbouquet.piip_*.tv /etc/enigma2/piip_*.json /etc/epgimport/piip.*
```

<div dir="rtl">

بعد رسیور را ری‌استارت کنید.

کلید API شما در `/root/apikey.txt` با نصب یا حذف هرگز دست نمی‌خورد. اگر می‌خواهید
پاک شود، خودتان پاکش کنید:

</div>

```bash
rm -f /root/apikey.txt
```

<div dir="rtl">

---

## نصب بدون کامپیوتر

بعضی ایمیج‌ها می‌توانند بسته را از خود رسیور نصب کنند:

**Menu ← Plugins ← (دکمهٔ آبی) ← Install local extension**

فایل را روی فلش بگذارید، به رسیور بزنید و از همان‌جا انتخابش کنید. عبارت دقیق
منو بین ایمیج‌ها فرق می‌کند.

---

## مشکلات رایج هنگام نصب

| چه می‌بینید | چه کنید |
|---|---|
| `dpkg: command not found` | ایمیج شما از opkg استفاده می‌کند. فایل `.ipk` را نصب کنید. |
| `opkg: command not found` | ایمیج شما از dpkg استفاده می‌کند. فایل `.deb` را نصب کنید. |
| هنگام کپی `Permission denied` | با کاربر `root` وصل نشده‌اید. به‌جای نام کاربری خودتان `root@ADDRESS` بنویسید. |
| `Connection refused` | SSH روی رسیور خاموش است: **Menu ← Setup ← System ← Network ← Network Services**. |
| پلاگین در منو ظاهر نمی‌شود | انیگما۲ ری‌استارت نشده. `killall -9 enigma2` بزنید یا رسیور را ری‌استارت کنید. |
| بعد از نصب هیچ‌چیز پخش نمی‌شود | `ffmpeg` نصب نیست. با `opkg install ffmpeg` یا `apt-get install ffmpeg` نصبش کنید. |

نشانه‌های بیشتر در [عیب‌یابی](troubleshooting.md).

</div>

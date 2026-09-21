<div dir="rtl">

# ساخت از روی سورس

برای **استفاده** از برنامه به این صفحه نیازی ندارید — بسته‌های آماده در
[صفحهٔ Releases](https://github.com/dreamboxone/piip/releases) هستند. این صفحه
برای کسی است که می‌خواهد خودش بسته بسازد یا پلاگین را تغییر دهد.

---

## چه چیزی لازم دارید

- پایتون ۳.۸ یا بالاتر، روی هر کامپیوتری: ویندوز، مک یا لینوکس.
- همین. نه `dpkg` لازم است، نه `opkg`، نه کامپایلر، نه ماشین لینوکسی.

بسته‌ها را مستقیم خودِ پایتون می‌نویسد، چون یک فایل `.deb` (و `.ipk` که همان
قالب را دارد) در واقع فقط یک آرشیو `ar` با سه عضو است.

---

## گرفتن سورس

</div>

```bash
git clone https://github.com/dreamboxone/piip.git
```

```bash
cd piip
```

<div dir="rtl">

---

## اول تست‌ها را اجرا کنید

</div>

```bash
python PIIP/tests/run_all.py
```

<div dir="rtl">

باید خلاصه‌ای ببینید که به چیزی شبیه
`1559 checks passed, 0 failed, 0 suites crashed` ختم می‌شود.

این تست‌ها روی کامپیوتر معمولی اجرا می‌شوند: به‌جای انیگما۲ یک جایگزین ساختگی
گذاشته شده، پس صفحه‌ها، اسکین‌ها، پلی‌لیست‌ها، منابع و بخش‌های ترجمه همگی بدون
رسیور آزمایش می‌شوند.

یکی از مجموعه‌ها، یک بازرسی ایستا برای **سازگاری با پایتون ۲.۷** است — رسیورهای
موجود هنوز پایتون ۲.۷ دارند و این کامپیوتر نمی‌تواند اجرایش کند، پس تک‌تک
ماژول‌ها تجزیه می‌شوند و دنبال دستور یا کتابخانه‌ای می‌گردد که آنجا وجود ندارد.
اگر پلاگین را تغییر دادید، این مجموعه را سبز نگه دارید.

> در ویندوز، اگر متن فارسی خروجی باعث خطای `UnicodeEncodeError` شد، اول
> `set PYTHONIOENCODING=utf-8` را بزنید (در PowerShell:
> `$env:PYTHONIOENCODING='utf-8'`).

---

## ساخت بسته‌ها

</div>

```bash
python packaging/build_deb.py
```

```bash
python packaging/build_ipk.py
```

<div dir="rtl">

هر دو داخل پوشهٔ `dist/` نوشته می‌شوند:

```
dist/enigma2-plugin-extensions-piip_1.0_all.deb
dist/enigma2-plugin-extensions-piip_1.0_all.ipk
```

هر کدام حدود ۱۵ مگابایت و شامل ۱۴۱ فایل است.

---

## بررسی چیزی که ساختید

</div>

```bash
python packaging/verify_deb.py dist/enigma2-plugin-extensions-piip_1.0_all.deb
```

<div dir="rtl">

این ابزار آرشیو را دوباره باز می‌کند و بررسی می‌کند که همهٔ فایل‌های سورس هست،
چیز اضافه‌ای اضافه نشده، فایل‌های استخراج‌شده بایت‌به‌بایت با سورس یکی‌اند و
آیکون یک PNG سالم است.

---

## تغییر شمارهٔ نسخه

نسخه فقط در یک جا تعریف شده:

</div>

```python
# packaging/build_deb.py
VERSION = '1.0'
```

<div dir="rtl">

فایل `build_ipk.py` همان را وارد می‌کند، پس هر دو بسته همیشه یک شماره دارند.

---

## ساختار بسته

| عضو | چه دارد |
|---|---|
| `debian-binary` | فقط متن `2.0` |
| `control.tar.gz` | توضیحات بسته و چهار اسکریپت نصب |
| `data.tar.gz` | خود پلاگین، زیر مسیر `usr/lib/enigma2/python/Plugins/Extensions/PIIP` |

اسکریپت‌های نصب:

| اسکریپت | کی اجرا می‌شود | چه می‌کند |
|---|---|---|
| `preinst` | قبل از باز شدن بسته | نسخهٔ قبلی پلاگین را پاک می‌کند |
| `postinst` | بعد از باز شدن بسته | می‌گوید چه چیزی کم است و انیگما۲ را ری‌استارت می‌کند |
| `prerm` | قبل از حذف | توضیح می‌دهد چطور تنظیمات و بوکه‌ها را پاک کنید |

اسکریپت `postinst` انیگما۲ را در پیش‌زمینه ری‌استارت می‌کند و به ترتیب
`systemctl`، بعد `/etc/init.d/enigma2`، بعد `init 4` / `init 3` و در آخر
`killall` را امتحان می‌کند. عمداً در پیش‌زمینه است: ری‌استارتی که در پس‌زمینه
بیفتد، همراه گروه پردازهٔ dpkg کشته می‌شود و اصلاً اجرا نمی‌شود.

### چرا یک بسته برای همهٔ رسیورها

پلاگین پایتون خالص است، پس بسته با `Architecture: all` علامت می‌خورد و همان یک
فایل روی arm64، armhf و mipsel نصب می‌شود. تفاوت `.deb` و `.ipk` فقط در بخش
توضیحات بسته است — `opkg` وابستگی‌ها را خودش حل می‌کند و `Depends:` می‌خواهد،
در حالی که `dpkg` روی DreamOS با `Recommends:` راضی است.

---

## ساختار پروژه

```
PIIP/                 خود پلاگین، دقیقاً همان‌طور که نصب می‌شود
  plugin.py           تنظیمات و نقطهٔ ورود انیگما۲
  main.py             اولین صفحهٔ برنامه
  screens/            همهٔ صفحه‌ها، از جمله player.py
  providers/          کلاینت‌های M3U، Xtream Codes و Stalker
  translate/          موتور ترجمه
    e2dub/            مسیر صدا: ضبط، رله، Gemini، میکس
  utils/              اسکین، زیرنویس، بوکه، تصاویر، لاگ
  tests/              مجموعهٔ تست (همراه بسته هم می‌رود تا روی رسیور اجرا شود)
  icons/              پس‌زمینه‌ها و تصاویر
packaging/            سازنده‌های بسته و بررسی‌کننده
docs/                 همین مستندات
```

---

## نصب چیزی که ساختید

</div>

```bash
scp dist/enigma2-plugin-extensions-piip_1.0_all.deb root@RECEIVER_IP:/tmp/
```

```bash
ssh root@RECEIVER_IP "dpkg -i /tmp/enigma2-plugin-extensions-piip_1.0_all.deb"
```

<div dir="rtl">

هنگام توسعه معمولاً سریع‌تر است که فقط یک فایل را کپی کنید و انیگما۲ را ری‌استارت
کنید:

</div>

```bash
scp PIIP/screens/player.py root@RECEIVER_IP:/usr/lib/enigma2/python/Plugins/Extensions/PIIP/screens/
```

```bash
ssh root@RECEIVER_IP "rm -f /usr/lib/enigma2/python/Plugins/Extensions/PIIP/screens/player.pyo; killall -9 enigma2"
```

<div dir="rtl">

حتماً فایل `.pyo` متناظر را پاک کنید، وگرنه رسیور همان نسخهٔ کامپایل‌شدهٔ قبلی را
اجرا می‌کند.

</div>

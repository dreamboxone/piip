# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 1.0 | ✅ |
| Older builds | ❌ — please upgrade |

Always install the newest release from the
[Releases page](https://github.com/dreamboxone/piip/releases).

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use GitHub's private reporting instead:
[Report a vulnerability](https://github.com/dreamboxone/piip/security/advisories/new).
Only the maintainer sees it, and we can fix it before it becomes public.

You can also write privately on Telegram: [t.me/routekernel1](https://t.me/routekernel1)

### What to include

- Your receiver model and image, and the plugin version.
- What an attacker could do, and what access they would need first.
- The steps to reproduce it.
- Logs, with any API key, subscription link or password removed.

### What to expect

- An acknowledgement within a few days.
- An assessment of whether it is a real issue, and how serious.
- A fix in a release, with credit to you if you want it.

## What counts as a vulnerability here

This plugin runs on a receiver inside your home network and talks to your IPTV
provider and to Google's Gemini service. Things worth reporting:

- Anything that exposes your **Gemini API key** — in a log, on screen, in the
  process list, or over the network.
- Anything that exposes your **IPTV username, password or portal MAC**.
- Anything that lets a device on your network, or a malicious stream, run
  commands on your receiver.
- A local port that should be bound to `127.0.0.1` but is reachable from the
  network.

## What is not a vulnerability

- **The cost of translation.** Audio goes to Gemini only while translation is
  on, and only with your own key, but Google does charge for it. That is by
  design and documented.
- **Your provider seeing your stream requests.** That is how IPTV works.
- **The receiver's own root password**, SSH being open, or the image's own
  security settings. Those belong to your image, not to this plugin.
- Anything that needs someone to already have root on your receiver.

## How your credentials are handled

- The Gemini key is read from `/root/apikey.txt`, `/etc/enigma2/piip_apikey.txt`,
  an environment variable, or the settings field. It is never printed in full on
  screen, in a log, or in the process list — the logs mask it.
- Subscription passwords are stored in the receiver's own settings files and
  masked in the diagnostic screens.
- The local stream server, the control port and the resolver all listen on
  `127.0.0.1` only. Nothing on your network can reach them.
- The plugin sends no telemetry of any kind.

---

<div dir="rtl">

# گزارش مشکل امنیتی

## نسخه‌های پشتیبانی‌شده

نسخهٔ **۱.۰** پشتیبانی می‌شود. همیشه آخرین نسخه را از
[صفحهٔ Releases](https://github.com/dreamboxone/piip/releases) نصب کنید.

## چطور گزارش کنم

**لطفاً برای مشکل امنیتی Issue عمومی باز نکنید.**

از گزارش خصوصی گیت‌هاب استفاده کنید:
[گزارش یک آسیب‌پذیری](https://github.com/dreamboxone/piip/security/advisories/new).
فقط نگه‌دارندهٔ پروژه آن را می‌بیند و می‌توانیم قبل از عمومی شدن، مشکل را درست
کنیم.

یا به‌صورت خصوصی در تلگرام: [t.me/routekernel1](https://t.me/routekernel1)

### چه چیزی بنویسید

- مدل رسیور و ایمیج، و نسخهٔ پلاگین.
- یک مهاجم چه کاری می‌تواند بکند و اول به چه دسترسی‌ای نیاز دارد.
- مرحله‌به‌مرحله چطور تکرارش کنیم.
- لاگ‌ها — با حذف کلید API، لینک اشتراک و رمزها.

### چه انتظاری داشته باشید

- ظرف چند روز پاسخ دریافت اولیه.
- بررسی اینکه واقعاً مشکل هست و چقدر جدی است.
- اصلاح در یک نسخهٔ جدید، و اگر بخواهید، تشکر با نام شما.

## چه چیزی مشکل امنیتی حساب می‌شود

- هر چیزی که **کلید Gemini** شما را فاش کند — در لاگ، روی صفحه، در فهرست
  پردازه‌ها یا روی شبکه.
- هر چیزی که **نام کاربری، رمز یا مک پورتال** اشتراک شما را فاش کند.
- هر چیزی که به دستگاهی در شبکهٔ شما، یا به یک استریم مخرب، اجازهٔ اجرای دستور
  روی رسیور بدهد.
- پورتی که باید فقط روی `127.0.0.1` باشد ولی از شبکه در دسترس است.

## چه چیزی مشکل امنیتی نیست

- **هزینهٔ ترجمه.** صدا فقط وقتی ترجمه روشن است و فقط با کلید خودتان به Gemini
  می‌رود، ولی گوگل بابتش هزینه می‌گیرد. این طراحی برنامه است و مستند شده.
- **دیدن درخواست‌های استریم توسط سرویس‌دهنده.** آی‌پی‌تی‌وی همین‌طور کار می‌کند.
- **رمز root رسیور**، باز بودن SSH، یا تنظیمات امنیتی خود ایمیج. این‌ها به ایمیج
  شما مربوط‌اند، نه به این پلاگین.
- هر چیزی که نیاز دارد مهاجم از قبل روی رسیور دسترسی root داشته باشد.

## اطلاعات محرمانهٔ شما چطور نگهداری می‌شود

- کلید Gemini از `/root/apikey.txt`، `/etc/enigma2/piip_apikey.txt`، متغیر
  محیطی یا فیلد تنظیمات خوانده می‌شود و هرگز به‌طور کامل روی صفحه، در لاگ یا در
  فهرست پردازه‌ها چاپ نمی‌شود — لاگ‌ها آن را ماسک می‌کنند.
- رمز اشتراک در فایل‌های تنظیمات خود رسیور ذخیره و در صفحه‌های تشخیصی پنهان
  می‌شود.
- سرور پخش محلی، پورت کنترل و resolver همگی فقط روی `127.0.0.1` گوش می‌دهند.
  هیچ دستگاهی در شبکه به آن‌ها دسترسی ندارد.
- برنامه هیچ اطلاعاتی برای هیچ‌کس نمی‌فرستد.

</div>

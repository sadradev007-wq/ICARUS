# Task Companion — همراه وظایف

**Task Companion** دستیار مدیریت و پیشبرد کارهای شخصی و پروژه‌ای ایکاروس است. این ابزار در Harness توسعه و آزموده می‌شود؛ اما مدل تعامل آن برای استفادهٔ دائمی در پوستهٔ اصلی ایکاروس طراحی شده است.

## مسئله‌ای که حل می‌کند

کاربر نباید برای به‌خاطر سپردن کارهای مهم، تشخیص اولویت یا انتخاب قدم بعدی، خودش بین پروژه‌ها و ابزارهای مختلف جابه‌جا شود. Task Companion باید کارها را از ورودی‌های مختلف دریافت کند، به اقدام‌های روشن تبدیل کند و همیشه مهم‌ترین اقدام‌های باز را در دسترس قرار دهد.

## دو سطح محصول

### ۱. ابزار Harness

مسیر: `Harness/Tools/Task Companion/`

مسئولیت‌ها:

- دریافت کار خام با زبان طبیعی و ثبت آن در صندوق ورودی؛
- تبدیل هدف‌های بزرگ به گام‌های کوچک و قابل انجام؛
- پیشنهاد اولویت، موعد، وابستگی و برآورد زمان؛
- تشخیص کار بعدی بر اساس اهمیت، فوریت، موعد و پیش‌نیازها؛
- نگهداری وضعیت‌ها: صندوق ورودی، بعدی، در حال انجام، منتظر، انجام‌شده و بایگانی؛
- پیوند دادن کار به پروژه، ابزار Idea Architect یا منبع بیرونی؛
- ثبت تصمیم‌ها و تاریخچهٔ تغییرات.

هستهٔ فعلی در `src/idea_architect/task_companion.py` شامل `TaskStore` برای ذخیره‌سازی محلی و `TaskAssistant` برای تهیهٔ برنامهٔ پیشنهادی با مدل System 2 است. پیشنهادها تا پیش از پذیرش صریح کاربر ذخیره نمی‌شوند. داده‌ها در JSON مستقل نگهداری می‌شوند و صف اجرای Idea Architect را دست‌کاری نمی‌کنند.\n\nفرم واقعی ثبت و فهرست کارها در `src/idea_architect/task_dashboard.py` پیاده‌سازی شده است. این رابط یک سرور محلی loopback-only با محافظ CSRF است و از طریق فرمان `icarus-tasks` اجرا می‌شود.

### ۲. پنل دائمی در پوستهٔ اصلی

در تمام صفحات اصلی نرم‌افزار، یک نوار کناری کشویی در **لبهٔ چپ پنجره** وجود دارد. این پنل جزئی از پوستهٔ سراسری است، نه یک ویجت مختص صفحه یا ابزار.

رفتار مورد انتظار:

- دکمهٔ ثابت برای باز و بسته‌کردن پنل در تمام صفحات؛
- حالت باز: فهرست اولویت‌دار کارها، عنوان، نشان اولویت، موعد و وضعیت؛
- حالت بسته: نوار باریک یا آیکون دسترسی سریع، بدون اشغال فضای محتوای اصلی؛
- حفظ وضعیت باز/بسته در جابه‌جایی صفحات؛
- در نمایشگر باریک، تبدیل به drawer روی محتوا با بستن از طریق Escape و کلیک بیرون؛
- دسترسی‌پذیری با صفحه‌کلید، focus واضح و برچسب مناسب برای screen reader.

پنل باید از هر صفحه، حتی هنگام استفاده از ابزارها، قابل دسترسی باشد. محتوای صفحهٔ اصلی نباید زیر پنل پنهان یا از عرض صفحه بیرون رانده شود.

## محتوای پنل

ترتیب پیش‌فرض:

1. **اکنون انجام بده** — یک اقدام پیشنهادی و دلیل انتخاب آن؛
2. **اولویت بحرانی و بالا** — کارهای فعال با بالاترین اهمیت؛
3. **موعدهای نزدیک** — کارهایی که موعدشان نزدیک است یا گذشته؛
4. **در انتظار** — کارهای مسدود یا منتظر پاسخ؛
5. **نمایش همهٔ کارها** — رفتن به فضای کامل Task Companion.

هر ردیف باید امکان بازکردن جزئیات، تغییر وضعیت و رفتن به پروژهٔ مرتبط را داشته باشد. تکمیل کار باید از پنل ممکن باشد، اما اجرای عملیات بیرونی یا حساس صرفاً با کلیک روی کار نباید خودکار انجام شود.

## رفتار هوشمند دستیار

دستیار می‌تواند پیشنهاد بدهد، اما نباید اختیار کاربر را تصاحب کند:

- اولویت و برنامه را پیشنهاد می‌دهد؛ کاربر می‌تواند اصلاح یا رد کند.
- کارهای بزرگ را به گام‌های کوچک با خروجی قابل مشاهده تقسیم می‌کند.
- وقتی اطلاعات کافی نیست، فقط سؤال ضروری را می‌پرسد.
- اگر کار مسدود است، علت و اقدام رفع مانع را نشان می‌دهد.
- پس از انجام یک کار، قدم بعدی را از میان کارهای آماده پیشنهاد می‌دهد.
- کارهای تکراری یا متناقض را شناسایی و برای ادغام پیشنهاد می‌کند؛ بدون حذف خودکار.
- برای تغییر موعد، بایگانی یا بازنویسی کارها، تاریخچه نگه می‌دارد.

## مدل دادهٔ پایه

هر کار حداقل این فیلدها را دارد:

| فیلد | کاربرد |
|---|---|
| `id` | شناسهٔ پایدار |
| `title` و `description` | اقدام و زمینه |
| `priority` | بحرانی، بالا، معمولی، پایین |
| `status` | صندوق ورودی، بعدی، در حال انجام، منتظر، انجام‌شده، بایگانی |
| `due_at` | موعد اختیاری با منطقهٔ زمانی |
| `project_id` و `parent_id` | اتصال به پروژه و کار والد |
| `source` | منشأ ایجاد کار |
| `tags` | دسته‌بندی |
| `created_at`, `updated_at`, `completed_at` | تاریخچهٔ زمانی |

## معماری و مرز مسئولیت

- **TaskStore:** منبع دادهٔ پایدار و مستقل کارها.
- **Task Assistant:** لایهٔ هوشمند برای فهم درخواست، خردکردن کار و پیشنهاد برنامه.
- **Priority Engine:** رتبه‌بندی قطعی و قابل توضیح بر اساس اولویت، موعد و آمادگی.
- **Task API:** رابط مشترک پنل چپ، داشبورد کامل و ابزارهای دیگر.
- **Global Task Drawer:** جزء ثابت پوستهٔ اصلی که فقط از Task API داده می‌گیرد.

صف اجرای Idea Architect همچنان منبع حقیقت اجرای وظایف فنی پروژه است. Task Companion می‌تواند یک کار را به پروژهٔ Idea Architect پیوند دهد، اما نباید وضعیت اجرای فنی را با وضعیت کار شخصی یکی کند.

## API خواندنی Task Companion (v1)

سرور محلی Task Companion علاوه بر فرم HTML، یک snapshot فقط‌خواندنی در مسیر `GET /api/v1/tasks` ارائه می‌کند؛ برای اجرای پیش‌فرض، نشانی آن `http://127.0.0.1:8766/api/v1/tasks` است.

- پاسخ شامل `schema: icarus.task-api.v1`، زمان تولید، کارهای فعال مرتب‌شده با همان منطق `TaskStore.list_tasks()`، رویدادهای اجرای در انتظار تأیید و شمارنده‌هاست.
- فقط فیلدهای عمومیِ تعریف‌شده در قرارداد منتشر می‌شوند؛ فیلدهای داخلی یا ناشناختهٔ فایل ذخیره‌سازی به پاسخ راه پیدا نمی‌کنند.
- endpoint هیچ تغییری در TaskStore نمی‌دهد و برای POST یا مسیرهای نوشتنی API وجود ندارد. پذیرش/رد پیشنهادها همچنان از فرم‌های CSRF-protected داشبورد انجام می‌شود.
- پاسخ با `Cache-Control: no-store` و `X-Content-Type-Options: nosniff` ارسال می‌شود. سرور فقط روی `127.0.0.1` گوش می‌دهد، مقدار Host را نیز دقیقاً برای همین میزبان بررسی می‌کند تا DNS rebinding نتواند درخواست را به API محلی هدایت کند و CORS را فعال نمی‌کند.
- قرارداد ماشین‌خوان در `Harness/Tools/Task Companion/schemas/task-api.v1.schema.json` قرار دارد.

پوستهٔ اصلی باید از همین قرارداد استفاده کند، نه اینکه نسخهٔ دیگری از مدل کارها بسازد. چون CORS عمداً فعال نیست، اتصال پوسته‌ای با origin جداگانه باید از same-origin proxy یا desktop bridge استفاده کند؛ این endpoint را به شبکهٔ محلی یا عمومی expose نکن.

## نقشهٔ پیاده‌سازی

1. **هستهٔ داده:** ذخیره‌سازی محلی، اولویت‌بندی، وضعیت‌ها و آزمون‌ها.
2. **دستیار برنامه‌ریز:** ورودی زبان طبیعی، خردکردن کار و پیشنهاد قدم بعدی با مدل قابل تعویض.
3. **API مشترک:** خواندن و تغییر کارها برای همهٔ صفحات.
4. **پوستهٔ سراسری:** پنل کشویی چپ با رفتار واکنش‌گرا و دسترس‌پذیر.
5. **اتصال‌ها:** پروژه‌ها، تقویم، یادآورها و ابزارهای Harness با مجوزهای روشن.
6. **حافظه و یادگیری:** استفاده از الگوهای انجام کار برای بهبود پیشنهادها، با امکان مشاهده و اصلاح توسط کاربر.

## اجرای فرم ثبت کار\n\nپس از نصب بسته از مسیر `Harness/Tools/Idea Architect/` با فرمان `pip install -e .`، اجرا کن:\n\n```bash\nicarus-tasks\n```\n\nسپس نشانی `http://127.0.0.1:8766/` را در مرورگر باز کن. مسیر ذخیره‌سازی پیش‌فرض `~/.local/share/icarus/tasks.json` است؛ با `--data` یا متغیر محیطی `ICARUS_TASKS_FILE` قابل تغییر است. سرور فقط روی loopback گوش می‌دهد و برای ثبت، عنوان کار الزامی است. فرم شامل توضیحات، اولویت، وضعیت اولیه، موعد، پروژه و برچسب‌هاست.\n\n## محدودیت نسخهٔ نخست

نسخهٔ فعلی ذخیره و مرتب‌سازی محلی کارها، تهیهٔ برنامهٔ پیشنهادی با مدل زبانی و یک API خواندنی نسخه‌دار روی loopback را فراهم می‌کند؛ افزودن پیشنهادها به فهرست نیازمند پذیرش صریح است. API شبکه‌ای از راه دور، پنل سراسری و اتصال تقویم هنوز وجود ندارند و نباید به‌عنوان قابلیت آماده معرفی شوند.


## دریافت نتیجهٔ Coding Harness با تأیید کاربر

اتصال میان Coding Harness و Task Companion از طریق رویدادهای مستقل انجام می‌شود؛ هارنس هرگز مستقیماً وضعیت کار را تغییر نمی‌دهد.

1. هنگام اجرای یک کار از طریق `icarus-harness run --task-store ... --task-id ...`، هارنس پس از پایان اجرا از کاربر می‌پرسد آیا نتیجه به‌عنوان پیشنهاد ثبت شود.
2. در صورت موافقت، یک فایل مستقل در کنار فایل اصلی ساخته می‌شود: `tasks.json.events/E-<id>.json`.
3. داشبورد Task Companion پیشنهادهای جدید را در بخش «بازخوردهای در انتظار تأیید» نمایش می‌دهد.
4. کاربر می‌تواند پیشنهاد را بپذیرد یا رد کند. پذیرش، وضعیت کار را تغییر می‌دهد؛ ردکردن فقط پیشنهاد را کنار می‌گذارد.
5. پیشنهاد اجرای کامل، وضعیت `completed` و اجرای متوقف‌شده در سقف گام‌ها، وضعیت `in_progress` را پیشنهاد می‌کند. اجرای ناموفق پیشنهاد تکمیل ایجاد نمی‌کند.
6. رویداد تکراری یا رویدادی که هدف آن دیگر فعال نیست، رد می‌شود.

هستهٔ API نیز این عملیات را ارائه می‌کند: `TaskStore.pending_execution_events()`، `TaskStore.apply_execution_event(event, user_approved=True)` و `TaskStore.dismiss_execution_event(event_id)`. رابط گرافیکی قبل از فراخوانی عملیات تغییر وضعیت، تأیید صریح را از طریق فرم محافظت‌شده با CSRF دریافت می‌کند.

این طراحی سه مفهوم را جدا نگه می‌دارد: نتیجهٔ اجرای هارنس، پیشنهاد تغییر وضعیت، و وضعیت نهایی تأییدشده توسط کاربر.


قرارداد رویداد در `Local LLM/Train Data/schemas/execution-event.schema.json` تعریف شده است. این فایل مستقل از schema اصلی `icarus.tasks.v1` است تا پیام اجرایی نتواند به‌جای وضعیت واقعی کار ثبت شود.


## نمونهٔ اولیهٔ پنل کشویی

داشبورد محلی اکنون یک نمونهٔ اولیه از پنل سمت چپ دارد. پنل با دارایی‌های مستقل در مسیر src/idea_architect/static/ ساخته شده، از همان origin سرو می‌شود و snapshot نسخه‌دار GET /api/v1/tasks را مصرف می‌کند. در دسکتاپ فضای محتوا را جابه‌جا می‌کند و در نمایشگر باریک به drawer شناور با بستن از Escape و backdrop تبدیل می‌شود. وضعیت باز/بسته در مرورگر حفظ می‌شود.

این نمونه عمداً فقط‌خواندنی است؛ ایجاد یا تغییر کار همچنان از فرم‌های صریح و محافظت‌شدهٔ داشبورد انجام می‌شود. تا زمان ساخته‌شدن runtime پوستهٔ اصلی، این قابلیت در همهٔ صفحات ابزارها حاضر نیست و نباید به‌عنوان Global Drawer کامل معرفی شود. آزمون‌های منطق JavaScript با pnpm test در پوشهٔ Harness/Tools/Idea Architect/ui/ اجرا می‌شوند.


### Idempotency across correlated runs

For schema `icarus.execution-event.v1`, `run_id` is optional for backward compatibility. When present, it must be a 32-character lowercase UUID hex value. TaskStore records handled run IDs for both accepted and dismissed suggestions; a second event with the same run_id is hidden from the pending inbox and cannot be applied, even if it has a different event_id. Legacy events without run_id continue to be protected by event_id.


### Resilient execution-event inbox

The pending-event reader treats each file as untrusted input. It skips handled event IDs from their filenames before opening the file, reads at most 16 KiB per event, uses no-follow file opens where supported, and validates the full `icarus.execution-event.v1` contract before exposing a suggestion. Malformed JSON, incomplete records, invalid field types, oversized files, and unreadable entries are logged and skipped individually; they do not prevent the dashboard or read-only task APIs from loading valid events. The adjacent `.events` path itself must be a real directory, not a symlink.

The Coding Harness resolves the selected TaskStore path before creating the adjacent event directory. This allows legitimate symlinked parent paths (for example, a user-selected path through a home-directory symlink) while retaining no-follow protection on the `.events` directory and its files. Credential redaction is applied before the 1,000-character summary limit, so redaction expansion cannot create an event that the TaskStore refuses to accept.


## API خواندنی Task Companion (v2)

برای نمایش جزئیات ارتباط اجرای Harness، endpoint سازگار با نسخهٔ قبلی در مسیر `GET /api/v2/tasks` ارائه می‌شود.

- قرارداد پاسخ `icarus.task-api.v2` است و همان snapshot کارهای فعال، شمارنده‌ها و پیشنهادهای در انتظار را برمی‌گرداند.
- رویدادهای جدید، در صورت وجود، فیلد `run_id` با الگوی ۳۲ رقم هگزادسیمال دارند. رویدادهای قدیمی بدون این فیلد همچنان در v2 معتبرند.
- endpoint نسخهٔ v1 و schema سخت‌گیرانهٔ آن بدون تغییر باقی می‌ماند؛ مصرف‌کنندگان قدیمی لازم نیست مهاجرت کنند.
- schema نسخهٔ جدید در `Harness/Tools/Task Companion/schemas/task-api.v2.schema.json` قرار دارد.
- پنل فعلی از v2 برای نمایش شناسهٔ اجرای هر پیشنهاد استفاده می‌کند. نمایش شناسه صرفاً برای ردیابی است و هیچ اختیاری برای پذیرش پیشنهاد یا تغییر وضعیت ایجاد نمی‌کند.


### Feedback edge-case behavior

Pending suggestions are shown only while their target task remains active. If a task is completed, archived, or removed from the active set by another path, its old suggestion is hidden; direct application still rejects stale feedback. The dashboard's drawer link reloads the current page before navigating to the feedback anchor, so feedback arriving after initial page load is rendered before the link is followed.

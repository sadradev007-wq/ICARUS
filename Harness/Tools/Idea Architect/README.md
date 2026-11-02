# معمار ایده (Idea Architect)

ابزار هارنس ایکاروس برای تبدیل ایده خام به برنامه پروژه، درخت وظایف و صف اجرای قابل اعتبارسنجی.

## وضعیت نسخه

**نسخه توسعه‌ای 0.6.0**

هسته برنامه‌ریزی بازگشتی، اجرای تأییدمحور، ثبت Skillهای بازبینی‌شده، sandbox لینوکسی، بازخورد System 2، بازبرنامه‌ریزی تأییدمحور و زمان‌بندی وابستگی‌ها پیاده‌سازی شده‌اند. مرحلهٔ ۹ از snapshotهای کامل صف، journal زنجیره‌ای، بازسازی audit، قفل بین‌فرایندی و آزمون بازیابی تشکیل شده است. مرحلهٔ ۱۰ نیز CLI عملیاتی، داشبورد محلی تعاملی و آزمون چرخهٔ کامل تأیید تا اجرا و بازبینی را دارد.

## معماری فعلی

1. **Idea Input:** دریافت هدف خام و ایجاد شناسه پروژه.
2. **Skill Discovery:** جست‌وجوی اختیاری GitHub و ثبت کاندیداها در قرنطینه.
3. **System 1:** تولید طرح سطح بالا با مدل لوکال یا آفلاین.
4. **System 2:** گسترش بازگشتی وظایف تا برگ‌های اجرایی.
5. **Validation:** اعتبارسنجی قرارداد ITP و کنترل ساختار.
6. **Execution Queue:** تولید صف وظایف اجرایی همراه با وابستگی‌ها.
7. **Approval Gate:** تأیید انسانی برای وظیفه و Handler مشخص.
8. **Execution Engine:** اجرای Handlerهای ثبت‌شده در allow-list.
9. **Result Evaluation:** ارزیابی خروجی با Evaluator میزبان یا System 2.
10. **Audit & Persistence:** ثبت رویدادها، تلاش‌ها و خروجی‌ها.
11. **Skill Approval:** اتصال Skill بررسی‌شده به Handler مورد اعتماد میزبان.
12. **Sandbox:** اجرای فرمان ثابت در bubblewrap با namespace شبکه جدا و محدودیت منابع.
13. **System 2 Feedback:** ارسال خروجی واقعی اجرا به System 2.
14. **Acceptance Review:** بررسی یک‌به‌یک معیارها و نیاز به تأیید مستقل برای تکمیل خودکار.
15. **Retry & Replanning:** تلاش مجدد محدود و پیشنهاد اصلاحی که پیش از اعمال نیازمند تأیید انسانی است.
16. **Dependency Scheduler:** تشخیص چرخه، ساخت batchهای توپولوژیک و جلوگیری از اجرای زودهنگام وظایف.

## پروتکل ITP-1.0

تمام خروجی‌های مدل باید یک JSON object معتبر باشند؛ متن توضیحی، Markdown fence یا محتوای اضافه پذیرفته نمی‌شود.

- `schemas/plan.schema.json`: قرارداد خروجی System 1.
- `schemas/expansion.schema.json`: قرارداد خروجی System 2.
- `protocol.py`: اعتبارسنجی زمان اجرا بدون وابستگی خارجی.
- هر برگ اجرایی باید `method`, `inputs`, `expected_outputs` و `acceptance_criteria` غیرخالی داشته باشد.
- وظایفی که تا سقف عمق اجرایی نشوند با `planning_blocked` علامت می‌خورند و وارد صف اجرا نمی‌شوند.

## اجرای وظایف و امنیت

ماژول `execution.py` شامل `HandlerRegistry` و `ExecutionEngine` است:

- فقط Handlerهایی اجرا می‌شوند که برنامه میزبان صراحتاً ثبت کرده باشد.
- `approve(...)` وظیفه را به یک Handler مشخص متصل می‌کند و تأیید انسانی را ثبت می‌کند.
- `run(...)` فقط وظیفه تأییدشده را اجرا می‌کند.
- نتیجه هر تلاش در فایل جداگانه ذخیره می‌شود. journal زنجیره‌ای منبع اصلی رویدادهاست و `audit_log.jsonl` نمای قابل‌بازسازی آن است.
- بدون Evaluator معتبر، وظیفه `awaiting_review` باقی می‌ماند و completed اعلام نمی‌شود.

**توجه:** Handler پایتونی معمولی در همان فرایند میزبان اجرا می‌شود و به‌تنهایی sandbox نیست. برای فرمان‌های بیرونیِ ثابت و مورد اعتماد از `BubblewrapCommandHandler` استفاده کنید.

## Skillها

`SkillRegistry` مخازن GitHub را در قرنطینه ثبت می‌کند.

- `approve_candidate(...)` رکورد Skill را پس از بررسی انسانی به یک `handler_id` مشخص متصل می‌کند.
- `get_approved_handler(...)` فقط Handler از پیش ثبت‌شده در allow-list میزبان را برمی‌گرداند.
- کد مخزن GitHub خودکار نصب، import یا اجرا نمی‌شود.
- توکن GitHub نباید در فایل‌های پروژه ذخیره شود.

تأیید Skill به معنی تأیید امنیتی خودکار کد نیست؛ بررسی منبع، مجوز، وابستگی‌ها و رفتار آن همچنان لازم است.

## Sandbox لینوکسی

`sandbox.py` آداپتر `BubblewrapCommandHandler` را ارائه می‌کند:

- فقط executable مطلق و آرگومان‌های ثابتِ پیکربندی‌شده توسط میزبان پذیرفته می‌شوند.
- متن مدل هرگز به shell command تبدیل نمی‌شود.
- از `bwrap --unshare-all` برای جداسازی namespace شبکه استفاده می‌شود.
- مسیرهای سیستمی فقط‌خواندنی هستند و workspace موقت محل نوشتن است.
- محدودیت زمان، CPU، حافظه، تعداد فرایندها، اندازه فایل و حجم ورودی/خروجی اعمال می‌شود.
- اگر Linux/POSIX یا bubblewrap در دسترس نباشد، اجرا fail-closed می‌شود.

روی Debian می‌توان bubblewrap را با این دستور نصب کرد:

```bash
sudo apt update && sudo apt install bubblewrap
```

این sandbox به تنظیمات کرنل و میزبان وابسته است و جایگزین VM یا sandbox سخت‌افزاری نیست. پیش از اجرای کد ناشناس باید روی دستگاه هدف آزمایش امنیتی شود.

## بازیابی پس از توقف ناگهانی (مرحلهٔ ۹)

- `protocol.write_json` از فایل موقت یکتا، `fsync` و جایگزینی اتمیک استفاده می‌کند.
- `event_journal.jsonl` یک journal افزایشیِ hash-chain است. هر تغییر وضعیت، snapshot کامل صف شامل تلاش‌ها و تصمیم‌های انسانی را پیش از جایگزینی فایل صف ثبت می‌کند؛ بنابراین بازیابی بر مبنای آخرین snapshot معتبر انجام می‌شود، نه replay عمومی eventها.
- در شروع `ExecutionEngine`، journal از نظر زنجیره و hash بررسی می‌شود؛ خرابی رکورد کامل باعث توقف fail-closed می‌شود. tail ناقص آخر نادیده گرفته و پیش از append بعدی حذف می‌شود.
- وظیفه‌ای که هنگام توقف در وضعیت `running` مانده باشد، به `awaiting_review` منتقل و تلاش آن `interrupted` علامت‌گذاری می‌شود؛ هیچ handler به‌طور خودکار دوباره اجرا نمی‌شود.
- قفل انحصاری سیستم‌عامل تمام تراکنش‌های صف و اجرای Handler را بین فرایندها سریال می‌کند. آزمون رقابت دو فرایند برای تأیید یک وظیفه نیز اضافه شده است؛ این طراحی اجرای موازی را فعال نمی‌کند.
- journal منبع اصلی audit است و `audit_log.jsonl` هنگام راه‌اندازی از آن بازسازی می‌شود.
- کلید idempotency برای retryهای یک revision ثابت است و با replan به scope جدید تغییر می‌کند. این کلید باید توسط Handler به سرویس خارجی منتقل و در آن سرویس رعایت شود؛ exactly-once عمومی برای side effect خارجی قابل‌تضمین نیست. وظایف interrupted همچنان نیازمند بررسی انسانی‌اند.


## بازخورد System 2 و ارزیابی

`System2FeedbackEvaluator` خروجی واقعی Handler و معیارهای پذیرش را به System 2 می‌فرستد. پاسخ باید برای هر معیار وضعیت `met`, `not_met` یا `unknown` و شواهد متنی داشته باشد.

**رأی مثبت مدل به‌تنهایی وظیفه را completed نمی‌کند.** برای تکمیل خودکار باید `deterministic_verifier` مورد اعتماد میزبان نیز نتیجه مثبت بدهد؛ در غیر این صورت وظیفه در `awaiting_review` باقی می‌ماند. گزارش مدل در مسیر feedback ذخیره می‌شود.

## Retry و بازبرنامه‌ریزی

- `ExecutionEngine.retry(...)` فقط برای وظیفه ناموفق قابل استفاده است و سقف تلاش مجدد دارد.
- هر تلاش نیازمند تأیید تازه است و خروجی تلاش‌های قبلی حفظ می‌شود.
- `System2Replanner.propose(...)` پیشنهاد اصلاح را جداگانه ذخیره می‌کند و صف زنده را تغییر نمی‌دهد.
- `approve_and_apply(...)` پیشنهاد را با تأیید انسانی اعمال می‌کند؛ اجرای دوباره همچنان به تأیید Handler نیاز دارد.

## زمان‌بندی وابستگی‌ها

`DependencyScheduler` گراف وابستگی را بررسی می‌کند، چرخه‌ها و ارجاع‌های نامعتبر را رد می‌کند و batchهای توپولوژیک را می‌سازد. `ProjectOrchestrator` وابستگی وظایف والد را به برگ‌های اجرایی منتقل می‌کند. `ExecutionEngine` نیز پیش از تأیید و اجرا دوباره آماده‌بودن پیش‌نیازها را کنترل می‌کند.

عملیات تغییر صف با قفل انحصاری سیستم‌عامل سریال می‌شوند؛ در نتیجه handlerها نیز هنگام اجرا قفل را نگه می‌دارند. آزمون چندپردازه‌ای در CI وجود دارد. این طراحی عمداً اجرای موازی را فعال نمی‌کند.

## خروجی گرافیکی پروژه

پس از ساخت هر پروژه، `visualization.py` سه خروجی مستقل تولید می‌کند:

- `visualization/project_graph.html`: صفحهٔ مستقل فارسی و راست‌به‌چپ، دارای SVG درون‌صفحه‌ای و کنترل بزرگ‌نمایی؛ بدون CDN و قابل بازشدن آفلاین.
- `visualization/project_graph.svg`: تصویر برداری مستقل برای مشاهده، اشتراک‌گذاری و استفاده در اسناد.
- `visualization/project_graph.mmd`: نمودار Mermaid برای نمایش در GitHub و ویرایش در ابزارهای سازگار.

خطوط پیوسته ساختار والد/فرزند را نشان می‌دهند و خطوط چین بنفش وابستگی میان وظایف را. رنگ گره‌ها وضعیت صف اجرا را نمایش می‌دهد. CLI پس از هر عملیات صف نمودار را بازتولید می‌کند. داشبورد محلی نیز SVG تازه را در کنار فرم‌های تأیید، اجرا، retry و بازبینی نمایش می‌دهد.

## ساختار

```text
Idea Architect/
├── README.md
├── pyproject.toml
├── schemas/
│   ├── plan.schema.json
│   └── expansion.schema.json
├── src/idea_architect/
│   ├── __init__.py
│   ├── protocol.py
│   ├── models.py
│   ├── planner.py
│   ├── orchestrator.py
│   ├── execution.py
│   ├── crash_recovery.py
│   ├── dashboard.py
│   ├── visualization.py
│   ├── sandbox.py
│   ├── skills.py
│   ├── feedback.py
│   ├── replanning.py
│   ├── scheduler.py
│   └── cli.py
└── tests/
    ├── test_protocol.py
    ├── test_execution.py
    ├── test_crash_recovery.py
    ├── test_dashboard.py
    ├── test_cli.py
    ├── test_visualization.py
    ├── test_sandbox.py
    ├── test_skills.py
    ├── test_feedback.py
    ├── test_replanning.py
    ├── test_scheduler.py
    └── test_orchestrator.py
```

## اجرا در حالت آزمایشی آفلاین

به Python 3.10 یا جدیدتر نیاز است:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
icarus-idea "ساخت یک دستیار هوش مصنوعی آفلاین" --demo --projects ./Projects
python -m unittest discover -s tests -v
```

در ویندوز فعال‌سازی محیط مجازی با `.venv\\Scripts\\activate` انجام می‌شود. حالت `--demo` برای بررسی جریان داده است و کیفیت برنامه‌ریزی واقعی LLM را شبیه‌سازی نمی‌کند.

## مدیریت صف و داشبورد محلی

پس از ساخت پروژه می‌توان صف را از CLI بررسی کرد:

```bash
icarus-idea --project-dir ./Projects/PROJECT_ID --status
```

برای اجرای وظایف، یک فایل پایتونی محلی و مورداعتماد بسازید که تابع `register_handlers(registry)` را تعریف کند. این فایل فقط وقتی با `--trusted-handler-module` صریحاً معرفی شود بارگذاری می‌شود؛ هرگز Skill دانلودشده یا کد تولیدشده توسط مدل را به این گزینه ندهید. نمونهٔ چرخه:

```bash
icarus-idea --project-dir ./Projects/PROJECT_ID --trusted-handler-module ./trusted_handlers.py --approve-task TASK_ID --handler-id my.handler --approved-by OPERATOR
icarus-idea --project-dir ./Projects/PROJECT_ID --trusted-handler-module ./trusted_handlers.py --run-task TASK_ID
icarus-idea --project-dir ./Projects/PROJECT_ID --review-task TASK_ID --decision accept --reviewed-by OPERATOR --reason "خروجی بررسی شد"
```

برای رابط گرافیکی محلی:

```bash
icarus-idea --project-dir ./Projects/PROJECT_ID --trusted-handler-module ./trusted_handlers.py --serve
```

سپس `http://127.0.0.1:8765/` را در مرورگر باز کنید. داشبورد فقط روی loopback گوش می‌دهد و فرم‌های POST آن توکن CSRF دارند. برای Handlerهای محلی فقط از کدی استفاده کنید که خودتان بررسی و اعتماد کرده‌اید.

## اتصال مدل لوکال

ابتدا Ollama و مدل‌های موردنظر را نصب و آماده کنید:

```bash
icarus-idea "ساخت دستیار فایل آفلاین" --system1-model MODEL_FAST --system2-model MODEL_REASONING --projects ./Projects
```

آدرس پیش‌فرض سرویس `http://127.0.0.1:11434` است و با `--ollama-url` قابل تغییر است. پس از آماده‌سازی وزن مدل‌ها، برنامه‌ریزی محلی به اینترنت وابسته نیست.

## نقشه راه ۱۰ مرحله‌ای

| مرحله | موضوع | وضعیت |
|---|---|---|
| ۱ | موتور اجرای تأییدمحور | انجام شد |
| ۲ | ممیزی، ذخیره خروجی و ارزیابی | انجام شد |
| ۳ | اتصال Skillهای بررسی‌شده | انجام شد؛ بدون نصب خودکار کد ثالث |
| ۴ | sandbox و محدودیت منابع | هسته پیاده‌سازی شد؛ آزمایش امنیتی روی دستگاه هدف باقی است |
| ۵ | بازگرداندن خروجی به System 2 | انجام شد |
| ۶ | ارزیابی معیارهای پذیرش | انجام شد؛ تکمیل خودکار نیازمند verifier میزبان است |
| ۷ | retry و بازبرنامه‌ریزی | انجام شد؛ با تأیید انسانی |
| ۸ | زمان‌بندی وابستگی‌ها | اجرای ترتیبی انجام شد؛ موازی‌سازی باقی است |
| ۹ | بازیابی پس از crash | snapshot کامل، journal hash-chain، بازسازی audit، قفل بین‌فرایندی و آزمون چندپردازه‌ای؛ side effect خارجی همچنان به idempotency خود Handler وابسته است |
| ۱۰ | رابط کاربری و آزمون end-to-end | CLI عملیاتی، داشبورد محلی تعاملی، نمودار زنده و آزمون چرخهٔ approve/run/review |

## محدودیت‌های فعلی

- اجرای CLI از طریق فایل `--trusted-handler-module` کد پایتون محلی را اجرا می‌کند؛ این فقط برای افزونهٔ میزبانِ بازبینی‌شده است، نه کد مدل یا Skill دانلودشده.
- داشبورد فقط روی `127.0.0.1` در دسترس است؛ برای دسترسی شبکه‌ای یا چندکاربره طراحی نشده است.
- اجرای موازی چند worker فعال نیست؛ قفل صف عمداً عملیات را سریال می‌کند.
- کلید idempotency تضمین exactly-once ایجاد نمی‌کند؛ Handler و سرویس خارجی باید آن را رعایت کنند.
- sandbox باید روی Debian 13 و دستگاه هدف آزمایش میدانی شود.
- CI روی Python 3.10 و 3.12 اجرا می‌شود.

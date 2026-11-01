# معمار ایده (Idea Architect)

ابزار مستقل هارنس ایکاروس برای تبدیل ایده خام به برنامه پروژه، درخت وظایف و صف اجرای قابل اعتبارسنجی.

## وضعیت نسخه

**نسخه توسعه‌ای 0.5.0 — برنامه‌ریزی بازگشتی، اجرای تأییدمحور، Skillهای بازبینی‌شده، sandbox لینوکسی، بازخورد System 2، بازبرنامه‌ریزی تأییدمحور و زمان‌بندی وابستگی‌ها پیاده‌سازی شده‌اند.**

این نسخه شامل مدل آزمایشی آفلاین، آداپتر Ollama، اعتبارسنجی قرارداد ITP، تجزیه بازگشتی وظایف، صف اجرا، موتور اجرای تأییدمحور، ثبت Skillهای بازبینی‌شده و آداپتر sandbox مبتنی بر bubblewrap است. حلقه بازبرنامه‌ریزی و retry خودکار هنوز در برنامه توسعه هستند.

## معماری

1. **Idea Input:** دریافت هدف خام و ایجاد شناسه پروژه.
2. **Skill Discovery:** جست‌وجوی اختیاری GitHub برای یافتن مهارت‌های مرتبط.
3. **System 1:** تولید طرح سطح بالا و وظایف اصلی؛ قابل اجرا با مدل محلی یا آفلاین.
4. **System 2:** گسترش بازگشتی هر وظیفه تا رسیدن به برگ اجرایی.
5. **Validation:** اعتبارسنجی قرارداد ITP و کنترل ساختار قبل از ذخیره.
6. **Execution Queue:** ساخت صف وظایف آماده بررسی.
7. **Approval Gate:** ثبت تأیید انسانی برای یک وظیفه و Handler مشخص.
8. **Execution Engine:** اجرای Handlerهای ثبت‌شده در allow-list؛ مدل اجازه تولید فرمان اجرایی یا کد قابل اجرا ندارد.
9. **Result Evaluation:** ارزیابی نتیجه توسط Evaluator مورد اعتماد میزبان؛ در نبود Evaluator، وظیفه در وضعیت awaiting_review می‌ماند.
10. **Audit & Persistence:** ثبت رویدادهای تأیید، شروع، پایان و شکست و ذخیره خروجی‌ها.\n11. **Skill Approval:** اتصال رکورد Skill تأییدشده به شناسه Handler از پیش ثبت‌شده در میزبان.\n12. **Sandbox:** اجرای فرمان ثابت و مورد اعتماد در bubblewrap با namespace شبکه جدا، فایل‌سیستم عمدتاً فقط‌خواندنی و workspace موقت.\n13. **System 2 Feedback:** ارسال خروجی واقعی اجرا و معیارهای پذیرش به مدل System 2 و ذخیره پاسخ ساختاریافته.\n14. **Acceptance Review:** تطبیق یک‌به‌یک معیارها، ثبت شواهد، و نیاز به تأیید مستقل میزبان پیش از تکمیل قطعی.\n15. **Retry & Replanning:** تلاش مجدد محدود با تأیید دوباره و پیشنهاد اصلاح System 2 که پیش از اعمال نیازمند تأیید انسانی است.\n16. **Dependency Scheduler:** ساخت batchهای توپولوژیک، تشخیص چرخه و جلوگیری از تأیید/اجرای وظیفه پیش از تکمیل پیش‌نیازها.

## پروتکل ITP-1.0

تمام خروجی‌های مدل باید یک JSON object معتبر باشند؛ متن توضیحی، Markdown fence یا محتوای اضافه پذیرفته نمی‌شود.

- `schemas/plan.schema.json`: قرارداد خروجی System 1.
- `schemas/expansion.schema.json`: قرارداد خروجی System 2.
- `protocol.py`: اعتبارسنجی زمان اجرا بدون وابستگی خارجی.
- هر برگ اجرایی باید `method`, `inputs`, `expected_outputs` و `acceptance_criteria` غیرخالی داشته باشد.
- وظایفی که تا سقف عمق اجرایی نشوند با `planning_blocked` علامت می‌خورند و وارد صف اجرا نمی‌شوند.

## موتور اجرا و امنیت

ماژول `src/idea_architect/execution.py` اجزای زیر را ارائه می‌کند:

- `HandlerRegistry`: فهرست مجاز Handlerهای پایتونی که برنامه میزبان صراحتاً ثبت کرده است.
- `ExecutionEngine.approve(...)`: تأیید یک وظیفه با ثبت هویت تأییدکننده و شناسه Handler.
- `ExecutionEngine.run(...)`: اجرای همان Handler پس از تأیید؛ بدون اجرای shell و بدون تبدیل متن مدل به کد.
- `ResultEvaluator`: رابط ارزیابی مورد اعتماد میزبان.
- `execution/audit_log.jsonl`: گزارش رویدادهای ممیزی.
- `execution/results/`: خروجی ساختاریافته هر وظیفه.\n- `feedback.py`: بازگرداندن خروجی اجرا به System 2 و اعتبارسنجی پاسخ بررسی.\n- `replanning.py`: ساخت پیشنهاد اصلاح وظیفه و اعمال آن فقط پس از تأیید انسانی.\n- `scheduler.py`: تحلیل گراف وابستگی، batchهای توپولوژیک و وضعیت آماده/منتظر/مسدود.\n- `execution/feedback/`: محل ذخیره گزارش بررسی System 2 (مسیر به سازنده evaluator داده می‌شود).\n\n### Skillها و محیط ایزوله\n\n- `SkillRegistry.approve_candidate(...)` یک مخزن قرنطینه‌شده را پس از ثبت بازبین و خلاصه/هش بررسی به یک `handler_id` مشخص متصل می‌کند. این کار کد مخزن را نصب یا import نمی‌کند.\n- `SkillRegistry.get_approved_handler(...)` فقط Handler ثبت‌شده در allow-list میزبان را برای Skill تأییدشده برمی‌گرداند.\n- `BubblewrapCommandHandler` در `sandbox.py` یک executable مطلق و آرگومان‌های ثابتِ پیکربندی‌شده توسط میزبان را اجرا می‌کند؛ متن مدل هرگز به shell command تبدیل نمی‌شود.\n- sandbox از `bwrap --unshare-all` استفاده می‌کند؛ شبکه جدا می‌شود، مسیرهای سیستمی فقط‌خواندنی هستند و فقط workspace موقت نوشتنی است. محدودیت زمان، CPU، حافظه، تعداد فرایندها، اندازه فایل و ورودی/خروجی اعمال می‌شوند.\n- اگر Linux/POSIX یا bubblewrap در دسترس نباشد، اجرا fail-closed می‌شود و به اجرای بدون sandbox سقوط نمی‌کند.\n- این یک sandbox لینوکسی وابسته به پیکربندی میزبان است؛ قبل از اجرای کد ناشناس باید روی توزیع هدف با تست نفوذ و بررسی mountها اعتبارسنجی شود. bubblewrap جایگزین VM یا sandbox سخت‌افزاری نیست.

نمونه استفاده در کد میزبان:

```python
from pathlib import Path
from idea_architect.execution import ExecutionEngine, HandlerRegistry

registry = HandlerRegistry()

def create_report(task, project_dir):
    # فقط منطق مورد اعتماد برنامه میزبان را اینجا قرار دهید.
    return {"report": "generated"}

registry.register("reports.create", create_report)
engine = ExecutionEngine(Path("./Projects/PROJECT_ID"), registry)

engine.approve("TASK-ID", "reports.create", approved_by="human")
result = engine.run("TASK-ID")
print(result["status"])  # awaiting_review یا completed/failed
```

**مهم:** این موتور sandbox سیستم‌عامل نیست. Handler ثبت‌شده با دسترسی‌های همان فرایند پایتون اجرا می‌شود. فقط Handlerهای مورد اعتماد را ثبت کنید؛ اجرای Skillهای ثالث تا زمان اضافه‌شدن sandbox و بررسی امنیتی غیرفعال است. اگر Evaluator تنظیم نشود، نتیجه خودکار completed اعلام نمی‌شود و برای بررسی انسانی باقی می‌ماند.

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
│   ├── skills.py
│   └── cli.py
└── tests/
    ├── test_protocol.py
    └── test_execution.py
```

## اجرا در حالت آزمایشی آفلاین

به Python 3.10 یا جدیدتر نیاز است. از همین پوشه:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
icarus-idea "ساخت یک دستیار هوش مصنوعی آفلاین" --demo --projects ./Projects
python -m unittest discover -s tests
```

در ویندوز فعال‌سازی محیط مجازی با `.venv\\Scripts\\activate` انجام می‌شود.

حالت `--demo` از مدل قطعی آزمایشی استفاده می‌کند و برای بررسی جریان داده است، نه تولید برنامه واقعی با کیفیت LLM.

## اتصال مدل لوکال

آداپتر `OllamaJsonModel` از API محلی Ollama استفاده می‌کند. ابتدا Ollama و دو مدل موردنظر را روی دستگاه نصب و آماده کنید؛ سپس:

```bash
icarus-idea "ساخت دستیار فایل آفلاین" --system1-model MODEL_FAST --system2-model MODEL_REASONING --projects ./Projects
```

آدرس پیش‌فرض سرویس `http://127.0.0.1:11434` است و با `--ollama-url` قابل تغییر است. پس از آماده‌سازی وزن مدل‌ها، برنامه‌ریزی محلی به اینترنت وابسته نیست.

## کشف مهارت‌های GitHub

`GitHubSkillDiscovery` جست‌وجوی مخازن را انجام می‌دهد و `SkillRegistry` کاندیداها را در `quarantine/` ثبت می‌کند. این مرحله به اینترنت نیاز دارد.

**هیچ مخزن کشف‌شده‌ای خودکار نصب یا اجرا نمی‌شود.** قبل از فعال‌سازی یک مهارت باید مجوز، منبع، کد، وابستگی‌ها و رفتار آن بررسی و در sandbox آزمایش شود. توکن GitHub نباید در فایل پروژه ذخیره شود.

## نقشه تکمیل تا نسخه 80 درصدی

1. هسته اجرای تأییدمحور و قرارداد وضعیت‌ها — انجام شد.
2. ثبت ممیزی، ذخیره خروجی و نقطه اتصال ارزیابی — انجام شد.
3. اتصال Skillهای تأییدشده به Handlerها.
4. sandbox واقعی و محدودسازی منابع/دسترسی‌ها.
5. بازگرداندن خروجی اجرا به System 2.
6. ارزیابی هوشمند معیارهای پذیرش.
7. اصلاح برنامه، retry و کنترل چرخه شکست.
8. مدیریت وابستگی‌ها و اجرای ترتیبی/موازی.
9. بازیابی امن پروژه پس از crash.
10. رابط کاربری، گزارش پیشرفت و آزمون یکپارچه end-to-end.

## محدودیت‌های فعلی

- CLI فعلی فقط برنامه‌ریزی و ساخت صف را اجرا می‌کند؛ موتور اجرا فعلاً از طریق API پایتون قابل استفاده است.
- Handlerهای خارجی و Skillهای GitHub هنوز به‌صورت خودکار نصب یا اجرا نمی‌شوند.
- sandbox سیستم‌عامل، مدیریت هم‌زمانی چند worker و بازیابی تراکنشی هنوز پیاده‌سازی نشده‌اند.
- تست‌ها به مخزن افزوده شده‌اند؛ اجرای آن‌ها در محیط CI یا دستگاه کاربر هنوز تأیید نشده است.

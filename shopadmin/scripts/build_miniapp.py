"""v2.18.0: makes ``app/assets/miniapp/`` (what «انتشار» sends to /app/ on the site host) from the
two ready packages:

    python scripts/build_miniapp.py <folder of asr-ertebatat-2-miniapp.zip, unpacked>
                                    <folder of phone-store-customer-miniapp.zip, unpacked>

* The shop page: as it is, except that Google Fonts (slow or blocked in Iran) becomes the
  bundled Vazirmatn; the Bale and Telegram scripts stay. Everything else of the package is kept
  (its sample products are only a fallback: the page reads the real catalog first).
* The customer form (/app/form/): only the form of the package, under the shop's own name; the
  package's page was also a demo (ZIP download, JSON preview, test buttons).
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "app" / "assets" / "miniapp"

GOOGLE = re.compile(r'\s*<link[^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*>')
FONT_FACES = "".join(
    f"@font-face{{font-family:'Vazirmatn';font-weight:{weight};font-display:swap;"
    f"src:url('{prefix}fonts/Vazirmatn-{name}.ttf') format('truetype')}}"
    for weight, name, prefix in ((400, "Regular", "__P__"), (500, "Medium", "__P__"),
                                 (600, "SemiBold", "__P__"), (700, "Bold", "__P__"),
                                 (800, "Bold", "__P__")))
SDK = ('    <script src="https://tapi.bale.ai/miniapp.js"></script>\n'
       '    <script src="https://telegram.org/js/telegram-web-app.js"></script>\n')
FORM_SCRIPT = """
    <script type="module">
      import { validateCustomerForm, parsePrefillParams } from './validators.js';

      const ALL_FIELDS = ['first_name', 'last_name', 'national_code', 'address'];
      // v2.18.1: the bot says which of the two private fields are still missing (?need=nc,addr),
      // never their values. What is on file is not shown here; the server ignores it if sent.
      const query = new URLSearchParams(window.location.search);
      const needed = (query.get('need') ?? 'nc,addr').split(',');
      const FIELDS = ALL_FIELDS.filter((f) => (f === 'national_code' ? needed.includes('nc')
        : f === 'address' ? needed.includes('addr') : true));
      const form = document.getElementById('customer_form');
      const button = document.getElementById('submit_btn');
      const hint = document.getElementById('submit_status_hint');
      const progress = document.getElementById('validation_progress');
      const shown = document.getElementById('national_code_normalized');
      const inputs = Object.fromEntries(FIELDS.map((f) => [f, document.getElementById(f)]));
      for (const field of ALL_FIELDS.filter((f) => !FIELDS.includes(f))) {
        const box = document.getElementById(field);
        box.required = false;
        box.closest('.field-group').hidden = true;
        box.closest('.field-group').style.display = 'none';
      }
      const touched = {};
      const digits = (n) => String(n).replace(/[0-9]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);

      function app() {
        const bale = window.Bale && window.Bale.WebApp;
        const telegram = window.Telegram && window.Telegram.WebApp;
        if (bale && bale.initData) return bale;
        if (telegram && telegram.initData) return telegram;
        return bale && typeof bale.sendData === 'function' && !telegram ? bale : telegram || null;
      }

      function check() {
        const values = Object.fromEntries(FIELDS.map((f) => [f, inputs[f].value]));
        const result = validateCustomerForm(values);
        result.valid = FIELDS.every((f) => result.results[f].valid);
        result.payload = result.valid
          ? { v: 1, type: 'customer',
              ...Object.fromEntries(FIELDS.map((f) => [f, result.results[f].normalized])) }
          : null;
        let good = 0;
        for (const field of FIELDS) {
          const res = result.results[field];
          good += res.valid ? 1 : 0;
          const visible = touched[field] || inputs[field].value.trim().length > 0;
          inputs[field].classList.toggle('is-valid', visible && res.valid);
          inputs[field].classList.toggle('is-invalid', visible && !res.valid);
          document.getElementById(`${field}_error`).textContent = visible && !res.valid ? res.error : '';
          document.getElementById(`${field}_valid`).textContent = visible && res.valid ? 'درست است' : '';
        }
        shown.textContent = '';
        progress.textContent = `${digits(good)} از ${digits(FIELDS.length)} مورد کامل شده`;
        button.disabled = !result.valid;
        hint.textContent = result.valid
          ? 'همه‌چیز درست است؛ دکمه را بزنید.'
          : 'برای فعال شدن دکمه، همهٔ موردهای بالا را درست پر کنید.';
        return result;
      }

      const prefill = parsePrefillParams(window.location.search);
      for (const field of FIELDS) {
        inputs[field].value = prefill[field] || '';
        inputs[field].addEventListener('input', () => { touched[field] = true; check(); });
        inputs[field].addEventListener('blur', () => { touched[field] = true; check(); });
      }
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        FIELDS.forEach((f) => { touched[f] = true; });
        const result = check();
        if (!result.valid) return;
        const target = app();
        if (target && typeof target.sendData === 'function') {
          target.sendData(JSON.stringify(result.payload));
          if (typeof target.close === 'function') {
            try { target.close(); } catch (_) { /* the window closes by itself */ }
          }
        } else {
          hint.textContent = 'این فرم فقط از داخل ربات فرستاده می‌شود؛ آن را از دکمهٔ ربات باز کنید.';
        }
      });
      const started = app();
      if (started && typeof started.ready === 'function') {
        try { started.ready(); } catch (_) { /* outside the messenger */ }
      }
      check();
    </script>
"""


def build_shop(source: Path) -> None:
    app = source / "app"
    target = OUT / "app"
    if target.exists():
        shutil.rmtree(target)
    (target / "assets").mkdir(parents=True)
    html = (app / "index.html").read_text(encoding="utf-8")
    html = GOOGLE.sub("", html)
    faces = FONT_FACES.replace("__P__", "./")
    # the package's own preview bar (plain browser only): its ZIP link has no file behind it
    bar = '[aria-label="نوار پیش‌نمایش سریع صفحات"]{display:none!important}'
    html = html.replace("</head>", f"    <style>{faces}{bar}</style>\n  </head>", 1)
    assert "fonts.googleapis" not in html and "fonts.gstatic" not in html
    assert "tapi.bale.ai/miniapp.js" in html and "telegram-web-app.js" in html
    (target / "index.html").write_text(html, encoding="utf-8", newline="\n")
    for path in app.rglob("*"):
        relative = path.relative_to(app)
        # the page itself is rewritten above; aistudio = notes of the tool that made the package
        if path.is_file() and relative.as_posix() != "index.html" and "aistudio" not in relative.parts:
            (target / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target / relative)


def build_form(source: Path) -> None:
    html = (source / "index.html").read_text(encoding="utf-8")
    head = html.split("</style>", 1)[0] + "</style>"
    head = re.sub(r"<title>.*?</title>", "<title>ثبت اطلاعات خریدار — عصر ارتباطات ۲</title>", head,
                  flags=re.S)
    head = head.replace("</style>", """
      .workspace-grid { display: block; max-width: 720px; margin-inline: auto; }
      .card-meta { white-space: nowrap; }
    </style>""")
    start = html.index('<section id="form-section"')
    form = html[start:html.index("</section>", start) + len("</section>")]
    assert 'id="customer_form"' in form
    body = f"""{head}
{SDK}  </head>
  <body>
    <main class="main-container">
      <section class="hero-intro">
        <div>
          <h1 class="hero-title">ثبت اطلاعات خریدار — عصر ارتباطات ۲</h1>
          <p class="hero-subtitle">برای ثبت خرید شما در حسابداری فروشگاه این موردها لازم است؛ فقط همان‌هایی را می‌بینید که هنوز نداریم.</p>
        </div>
      </section>
      <div class="workspace-grid">
        {form}
      </div>
    </main>{FORM_SCRIPT}  </body>
</html>
"""
    target = OUT / "app" / "form"
    target.mkdir(parents=True)
    (target / "index.html").write_text(body, encoding="utf-8", newline="\n")
    shutil.copyfile(source / "validators.js", target / "validators.js")


if __name__ == "__main__":
    build_shop(Path(sys.argv[1]))
    build_form(Path(sys.argv[2]))
    print("built", OUT)

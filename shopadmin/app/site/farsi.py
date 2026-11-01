"""v2.16.0 «فارسی‌سازی توضیحات»: clean and translate accessory texts — offline, no AI.

Two steps, both run on every PDF import (``pdf_import.prepare``) and on the
«فارسی‌سازی توضیحات» button of «سایت» › «کالاها»:

1. **Clean** (``clean_description`` / ``clean_specs``): codes and noise out of the
   description and the specs — SKU / EAN / barcode rows, product codes like
   ``GNMPB20KTCDBL``, barcode numbers (8–14 digits), repeated codes and the
   ``|`` fragments the PDF tables leave behind. Capacities and powers
   (``20000mAh``, ``PD20W``, ``T10000``) are never taken for codes.
2. **Translate** (``translate``): spec labels and common feature phrases through
   a built-in Persian dictionary (``BUILT_IN``) plus the manager's own words
   (kept in ``site_data.json`` → ``fa_words``; they win over the built-in ones).
   Numbers, units and model names stay English (``20W``, ``PD``, ``mAh``,
   ``USB-C``): «PD 20W Fast Charging» → «شارژ سریع PD 20W».

Whole texts are matched first, then the longest phrases inside a text. When
what is left of an English text is only technical tokens, the Persian goes
first and the technical part after it; otherwise phrases are replaced where
they stand. Running it twice changes nothing more.
"""
from __future__ import annotations

import re

#: label / phrase -> Persian. Keys are matched without regard to case or spacing.
BUILT_IN: dict[str, str] = {
    # ---- battery and capacity
    "Battery Capacity": "ظرفیت باتری", "Capacity": "ظرفیت", "Rated Capacity": "ظرفیت نامی",
    "Real Capacity": "ظرفیت واقعی", "Cell Capacity": "ظرفیت سلول",
    "Battery Type": "نوع باتری", "Battery": "باتری", "Cell Type": "نوع سلول", "Cell": "سلول",
    "Lithium Polymer Cell": "سلول لیتیوم پلیمر", "Lithium Polymer": "لیتیوم پلیمر",
    "Li-Polymer": "لیتیوم پلیمر", "Li-Po": "لیتیوم پلیمر", "Lithium-ion": "لیتیوم یون",
    "Lithium Ion": "لیتیوم یون", "Li-ion": "لیتیوم یون",
    "High Capacity": "ظرفیت بالا", "Large Capacity": "ظرفیت بالا",
    # ---- input / output / power
    "Input": "ورودی", "Output": "خروجی", "Total Output": "مجموع خروجی",
    "Max Output": "حداکثر خروجی", "Maximum Output": "حداکثر خروجی", "Inputs": "ورودی‌ها",
    "Outputs": "خروجی‌ها", "Dual Output": "خروجی دوگانه", "Multiple Outputs": "خروجی‌های متعدد",
    "Wireless Output": "خروجی بی‌سیم", "Power": "توان", "Rated Power": "توان نامی",
    "Max Power": "حداکثر توان", "Voltage": "ولتاژ", "Current": "جریان", "Energy": "انرژی",
    "Rated Energy": "انرژی نامی", "Efficiency": "بازدهی", "Conversion Rate": "بازدهی تبدیل",
    "Conversion Efficiency": "بازدهی تبدیل",
    # ---- charging
    "Fast Charging": "شارژ سریع", "Fast Charge": "شارژ سریع", "Quick Charging": "شارژ سریع",
    "Quick Charge": "شارژ سریع", "Super Fast Charging": "شارژ فوق سریع",
    "Wireless Charging": "شارژ بی‌سیم", "Wireless Charger": "شارژر بی‌سیم",
    "Wired Charging": "شارژ سیمی", "Charging": "شارژ", "Charger": "شارژر",
    "Charging Time": "زمان شارژ", "Recharge Time": "زمان شارژ دوباره",
    "Recharging Time": "زمان شارژ دوباره", "Full Charge Time": "زمان شارژ کامل",
    "Simultaneous Charging": "شارژ هم‌زمان", "Pass-through Charging": "شارژ هم‌زمان (عبوری)",
    "Two-way Fast Charging": "شارژ سریع دوطرفه", "Two-way Charging": "شارژ دوطرفه",
    "Bidirectional": "دوطرفه", "Solar Charging": "شارژ خورشیدی", "Solar Input": "ورودی خورشیدی",
    "Solar Panel": "پنل خورشیدی", "Solar": "خورشیدی", "Charging Cable": "کابل شارژ",
    "Charging Port": "درگاه شارژ", "Charging Ports": "درگاه‌های شارژ",
    # ---- cables and ports
    "Cable": "کابل", "Cables": "کابل‌ها", "Cable Length": "طول کابل",
    "Built-in Cable": "کابل داخلی", "Built-in Cables": "کابل‌های داخلی",
    "Integrated Cable": "کابل یکپارچه", "Integrated Type-C Cable": "کابل Type-C یکپارچه",
    "Integrated USB-C Cable": "کابل USB-C یکپارچه",
    "Integrated Lightning Cable": "کابل Lightning یکپارچه", "Detachable Cable": "کابل جداشدنی",
    "Port": "درگاه", "Ports": "درگاه‌ها", "Interface": "درگاه",
    # ---- display and lights
    "Display": "نمایشگر", "Digital Display": "نمایشگر دیجیتال", "Screen": "صفحه‌نمایش",
    "Smart Display": "نمایشگر هوشمند", "Power Indicator": "نشانگر شارژ",
    "Battery Indicator": "نشانگر باتری", "Indicator": "نشانگر", "Indicator Light": "چراغ نشانگر",
    "LED Flashlight": "چراغ قوه LED", "Flashlight": "چراغ قوه", "Torch": "چراغ قوه",
    "Light": "نور", "Steady Light": "نور ثابت", "Strobe Light": "نور چشمک‌زن",
    "Camping Light": "چراغ کمپینگ", "Emergency Light": "چراغ اضطراری",
    # ---- magnet / wireless
    "Magnetic Attraction": "اتصال مغناطیسی", "Magnetic": "مغناطیسی",
    "Magnetic Wireless": "بی‌سیم مغناطیسی", "Strong Magnet": "آهنربای قوی",
    "MagSafe Compatible": "سازگار با MagSafe", "Magsafe Compatible": "سازگار با MagSafe", "Compatible with MagSafe": "سازگار با MagSafe",
    "Compatible": "سازگار", "Compatibility": "سازگاری", "Wireless": "بی‌سیم", "Wired": "سیمی",
    # ---- body and design
    "Material": "جنس بدنه", "Body Material": "جنس بدنه", "Shell Material": "جنس بدنه",
    "Design": "طراحی", "Compact Design": "طراحی جمع‌وجور", "Slim Design": "طراحی باریک",
    "Ultra Slim": "بسیار باریک", "Ultra-thin": "بسیار نازک", "Slim": "باریک",
    "Compact": "جمع‌وجور", "Lightweight": "سبک", "Portable": "قابل حمل",
    "Portable Handle": "دستهٔ حمل", "Handle": "دسته", "Stand": "پایه",
    "Kickstand": "پایهٔ نگهدارنده", "Phone Holder": "نگهدارندهٔ گوشی",
    "Ring Holder": "حلقهٔ نگهدارنده", "Color": "رنگ", "Colour": "رنگ", "Colors": "رنگ‌ها",
    "Weight": "وزن", "Net Weight": "وزن خالص", "Dimensions": "ابعاد", "Dimension": "ابعاد",
    "Size": "اندازه", "Length": "طول", "Width": "عرض", "Height": "ارتفاع",
    "Thickness": "ضخامت", "Finish": "روکش", "Premium": "مرغوب",
    # ---- protection
    "Protection": "محافظت", "Multiple Protection": "محافظت چندگانه",
    "Multiple Protections": "محافظت چندگانه", "Multi-Protection": "محافظت چندگانه",
    "Smart Protection": "محافظت هوشمند", "Safety Protection": "محافظت ایمنی",
    "Overcharge Protection": "محافظت در برابر شارژ بیش از حد",
    "Over-charge Protection": "محافظت در برابر شارژ بیش از حد",
    "Over-discharge Protection": "محافظت در برابر تخلیهٔ بیش از حد",
    "Short Circuit Protection": "محافظت در برابر اتصال کوتاه",
    "Over Temperature Protection": "محافظت در برابر دمای بالا",
    "Overheat Protection": "محافظت در برابر داغ شدن",
    "Over Current Protection": "محافظت در برابر جریان زیاد",
    "Over Voltage Protection": "محافظت در برابر ولتاژ زیاد",
    "Waterproof": "ضدآب", "Water Resistant": "مقاوم در برابر آب", "Dustproof": "ضدگردوغبار",
    "Shockproof": "ضدضربه", "Fireproof": "نسوز", "Flame Retardant": "مقاوم در برابر شعله",
    "Fire Resistant": "مقاوم در برابر آتش", "Drop Protection": "محافظت در برابر ضربه",
    "Scratch Resistant": "ضدخش", "Anti-slip": "ضدلغزش", "Anti-fingerprint": "ضداثرانگشت",
    # ---- audio
    "Noise Cancelling": "حذف نویز", "Noise Cancellation": "حذف نویز",
    "Active Noise Cancellation": "حذف نویز فعال", "Active Noise Cancelling": "حذف نویز فعال",
    "Environmental Noise Cancellation": "حذف نویز محیط", "Bluetooth Version": "نسخهٔ بلوتوث",
    "Bluetooth": "بلوتوث", "Playtime": "زمان پخش", "Play Time": "زمان پخش",
    "Playback Time": "زمان پخش", "Music Time": "زمان پخش موسیقی", "Talk Time": "زمان مکالمه",
    "Call Time": "زمان مکالمه", "Standby Time": "زمان آماده‌به‌کار", "Standby": "آماده‌به‌کار",
    "Range": "برد", "Transmission Distance": "برد ارتباط", "Frequency": "فرکانس",
    "Frequency Response": "پاسخ فرکانسی", "Impedance": "امپدانس", "Sensitivity": "حساسیت",
    "Driver": "درایور", "Driver Size": "اندازهٔ درایور", "Speaker": "بلندگو",
    "Microphone": "میکروفون", "Mic": "میکروفون", "Touch Control": "کنترل لمسی",
    "Voice Assistant": "دستیار صوتی", "Stereo": "استریو", "Bass": "بیس",
    "Deep Bass": "بیس عمیق", "Hi-Fi Sound": "صدای Hi-Fi", "Sound": "صدا",
    "Earphones": "هندزفری", "Earbuds": "هندزفری", "Headphones": "هدفون", "Headset": "هدست",
    "Charging Case": "کیس شارژ", "Case": "قاب",
    # ---- general
    "Type": "نوع", "Model": "مدل", "Brand": "برند", "Warranty": "گارانتی",
    "Features": "ویژگی‌ها", "Feature": "ویژگی", "Specifications": "مشخصات",
    "Package Contents": "محتویات بسته", "Package Includes": "محتویات بسته",
    "In the Box": "محتویات بسته", "Certification": "گواهی‌نامه", "Certifications": "گواهی‌نامه‌ها",
    "Operating Temperature": "دمای کار", "Working Temperature": "دمای کار",
    "Temperature": "دما", "Origin": "ساخت", "Made in": "ساخت", "Smart": "هوشمند",
    "Smart Chip": "تراشهٔ هوشمند", "Chip": "تراشه", "Universal": "همه‌کاره",
    "Devices": "دستگاه", "Multiple Devices": "چند دستگاه", "Fast": "سریع", "High": "بالا",
    "Durable": "بادوام", "Original": "اصل", "Genuine": "اصل",
    "Charge": "شارژ", "Charge Multiple Devices": "شارژ چند دستگاه",
    "Flight Approved": "مجاز در پرواز", "Airline Approved": "مجاز در پرواز",
    "Powerbank": "پاوربانک", "Power Bank": "پاوربانک", "PowerBank": "پاوربانک",
    "Chipset": "تراشه", "Transmission": "برد ارتباط", "Working Time": "زمان کارکرد",
    "Working Time With Case": "زمان کارکرد با کیس", "Case Material": "جنس قاب",
    "Case Capacity": "ظرفیت کیس", "Charging Case Capacity": "ظرفیت کیس شارژ",
    "Port Input": "ورودی درگاه", "Port Output": "خروجی درگاه",
    "Ports Input": "ورودی درگاه‌های", "Ports Output": "خروجی درگاه‌های",
    "Cable Input": "ورودی کابل", "Cable Output": "خروجی کابل",
    "Build-In Cable": "کابل داخلی", "Built In Cable": "کابل داخلی",
    "Integrated Cables": "کابل‌های یکپارچه", "Input/Output": "ورودی/خروجی",
    "Solar Powered": "با انرژی خورشیدی", "Solar Charging Panel": "پنل شارژ خورشیدی",
    "Solar Power Input": "ورودی توان خورشیدی", "Solar Panel Size": "اندازهٔ پنل خورشیدی",
    "Light Modes": "حالت‌های نور", "Modes": "حالت‌ها", "Mode": "حالت",
    "Dual Flashlights": "دو چراغ قوه", "Flashlights": "چراغ قوه‌ها", "Dual": "دوگانه",
    "Cooling Chip": "تراشهٔ خنک‌کننده", "Cooling": "خنک‌کننده",
    "Pass-Through": "شارژ عبوری", "LED Power": "توان LED",
    "Built-in Safeguards": "محافظ‌های داخلی", "Built In Safeguards": "محافظ‌های داخلی",
    "Patented Design": "طراحی ثبت‌شده", "Digital": "دیجیتال",
    "Digital Battery Display": "نمایشگر دیجیتال باتری", "Multi": "چند",
    "Multi Mode Flashlight": "چراغ قوه چندحالته", "Multi-Mode Flashlight": "چراغ قوه چندحالته",
    "Multi-Mode": "چندحالته", "Retractable": "جمع‌شونده",
    "Retractable Type-C Cable": "کابل Type-C جمع‌شونده", "Device Charging": "شارژ دستگاه",
    "Display Panel": "صفحهٔ نمایشگر", "Detachable": "جداشدنی", "Wire": "سیم",
    "Two or more Outputs": "دو خروجی یا بیشتر", "Sharing Output": "خروجی اشتراکی",
    "Output & Input": "خروجی و ورودی", "Input & Output": "ورودی و خروجی",
    "Compact & Portable": "جمع‌وجور و قابل حمل", "Compact Portable": "جمع‌وجور و قابل حمل",
    # ---- Persian spelling from the PDFs (the joiner the PDF text loses)
    "میلیآمپر": "میلی‌آمپر", "میلی آمپر": "میلی‌آمپر", "پاوربانکهای": "پاوربانک‌های",
    "همظرفیت": "هم‌ظرفیت", "خروجیهای": "خروجی‌های", "ورودیهای": "ورودی‌های",
    "گواهی نامه": "گواهی‌نامه", "دستگاههای": "دستگاه‌های", "گوشیهای": "گوشی‌های",
    "دستگاهها": "دستگاه‌ها", "گجتهای": "گجت‌های", "بیشازحد": "بیش‌ازحد",
    "اضافهشارژ": "اضافه‌شارژ", "سریعتر": "سریع‌تر", "باقیمانده": "باقی‌مانده",
    "فستشارژ": "فست‌شارژ", "چندینباره": "چندین‌باره", "همزمان": "هم‌زمان",
}

#: English head words: «X Y Input» -> «ورودی X Y» (Persian puts the head first)
HEADS = {"input", "output", "capacity", "material", "type", "time", "length", "weight",
         "size", "version", "protection", "battery", "voltage", "current", "power",
         "temperature", "indicator", "display", "design", "color", "colour", "range"}
#: «USB-A Ports3» -> «3 درگاه USB-A» (a count glued to the word in the PDFs)
_PORT_COUNT = re.compile(r"\b((?:USB-[A-Z]|Type-C|Lightning|Micro-?USB)\d*)\s+Ports?\s*(\d+)\b",
                         re.IGNORECASE)
#: whole bullets the PDFs garble: «in 35 Minutes65%-0%», «Device Charging4»
_MINUTES = re.compile(r"^in (\d+) ?Minutes? ?(\d+)%(?:\s*-\s*(\d+)%)?$", re.IGNORECASE)
_DEVICES = re.compile(r"^(\d+)?\s*Devices? Charging\s*(\d+)?$", re.IGNORECASE)
#: spec labels that are codes, never shown
CODE_LABELS = {"sku", "ean", "upc", "gtin", "barcode", "bar code", "part number", "part no",
               "p/n", "pn", "item code", "model code", "article number", "product code",
               "کد", "کد کالا", "بارکد", "شناسه", "شناسه کالا", "کد محصول", "سریال"}
_UNIT = re.compile(r"^(?:[A-Z]{0,3}\d+(?:[.,]\d+)*(?:mah|mh|wh|w|v|a|ma|mm|cm|m|g|kg|hz|khz|db"
                   r"|h|hrs?|min|°c|%)?|\d+(?:[.,]\d+)*(?:mah|wh|w|v|a))$", re.IGNORECASE)
_BULLET_SPLIT = re.compile(r"\s*[•|]\s*")
_SPACES = re.compile(r"\s+")
_KNOWN_TECH = {"type-c", "usb", "magsafe", "lightning", "micro", "micro-usb", "bluetooth",
               "iphone", "ipad", "android", "qi", "qi2", "max", "min", "pro", "plus", "mini",
               "ultra", "lite", "&", "+", "/", "-", "(", ")", ",", "x"}
_PERSIAN = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")


# ---- cleaning --------------------------------------------------------------------------------
def is_code(token: str) -> bool:
    """A product / barcode code (never a capacity, a power or a model like T10000)."""
    t = token.strip("|,;:()[]{}.").strip()
    if not t:
        return False
    if re.fullmatch(r"\d{8,14}", t):                       # EAN / UPC / barcode
        return True
    if re.fullmatch(r"(?:SKU|EAN|UPC|GTIN|P/?N)[:#-]?(?=[A-Z-]*\d)[A-Z0-9-]{4,}", t, re.IGNORECASE):
        return True                                     # «SKU123456789», «EAN:6935…»
    if _UNIT.match(t):
        return False
    return bool(re.fullmatch(r"[A-Z0-9][A-Z0-9-]{7,}", t) and re.search(r"[A-Z]", t)
                and re.search(r"\d", t) and len(re.findall(r"[A-Z]", t)) >= 3)


def _clean_part(part: str, *, need_letters: bool = True) -> str:
    words = [w for w in part.split() if not is_code(w) and w.strip("|•") != ""]
    out = " ".join(words).lstrip(".'\"،,;:-| ").rstrip(" |•,;-")
    # a description bullet of nothing but numbers and punctuation (a barcode list)
    # -> drop; a spec value may be only a number («5.4»)
    if need_letters and not _PERSIAN.search(out) and not _LATIN.search(out):
        return ""
    return out


def _fix_names(text: str) -> str:
    """«Type•C» (a hyphen the PDF turned into a bullet) -> «Type-C»."""
    return re.sub(r"\b(Type|USB)\s*•\s*(C|A)\b", r"\1-\2", text or "", flags=re.IGNORECASE)


def clean_description(text: str) -> str:
    """Codes, barcodes, repeated parts and «|» fragments out; bullets joined with « • »."""
    parts, seen = [], set()
    pieces: list[str] = []
    for raw in re.split(r"\s*(\||•)\s*", _fix_names(text)):
        if raw in ("|", "•"):
            pieces.append(raw)
            continue
        if len(pieces) >= 2 and pieces[-1] == "•" and re.fullmatch(r"[A-Za-z]+", pieces[-2] or "") \
                and re.match(r"[A-Za-z]", raw or ""):
            pieces.pop()
            pieces[-1] = pieces[-1] + " " + raw
            continue
        pieces.append(raw)
    for raw in [p for p in pieces if p not in ("|", "•")]:
        part = _clean_part(raw)
        key = part.casefold()
        if part and key not in seen:
            seen.add(key)
            parts.append(part)
    return " • ".join(parts)


def clean_specs(specs: list) -> list[list[str]]:
    out, seen = [], set()
    for row in specs or []:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            continue
        key = _SPACES.sub(" ", _fix_names(str(row[0] or ""))).strip(" |:•")
        if key.casefold() in CODE_LABELS or is_code(key):
            continue
        values = [_clean_part(v, need_letters=False)
                  for v in _BULLET_SPLIT.split(str(row[1] or ""))]
        value = "، ".join(dict.fromkeys(v for v in values if v))
        if key and value and (key.casefold(), value.casefold()) not in seen:
            seen.add((key.casefold(), value.casefold()))
            out.append([key, value])
    return out


# ---- dictionary -----------------------------------------------------------------------------
def _norm(text: str) -> str:
    return _SPACES.sub(" ", text or "").strip().casefold()


def clean_words(words) -> list[list[str]]:
    """The manager's words: [[English or Persian, Persian], ...] (empty rows out)."""
    out, seen = [], set()
    for row in words if isinstance(words, list) else []:
        if isinstance(row, (list, tuple)) and len(row) == 2:
            src = _SPACES.sub(" ", str(row[0] or "")).strip()[:80]
            dst = _SPACES.sub(" ", str(row[1] or "")).strip()[:120]
            if src and dst and _norm(src) not in seen:
                seen.add(_norm(src))
                out.append([src, dst])
    return out


class Dictionary:
    def __init__(self, extra=None) -> None:
        self.words: dict[str, str] = {_norm(k): v for k, v in BUILT_IN.items()}
        for src, dst in clean_words(extra):
            self.words[_norm(src)] = dst
        keys = sorted(self.words, key=len, reverse=True)
        pattern = "|".join(r"\s+".join(re.escape(w) for w in k.split(" ")) for k in keys)
        # a phrase is a whole word run: no letter, digit, hyphen or slash glued to either
        # side («Type-C» and «Micro/Type» are names, not «نوع»)
        self._re = re.compile(r"(?<![\w/-])(?:" + pattern + r")(?![\w/-])", re.IGNORECASE)

    def translate(self, text: str) -> str:
        text = _SPACES.sub(" ", text or "").strip()
        if not text:
            return text
        text = _PORT_COUNT.sub(lambda m: f"{m.group(2)} درگاه {m.group(1)}", text)
        minutes = _MINUTES.match(text)
        if minutes:
            low = minutes.group(3) or "0"
            return f"شارژ {low}% تا {minutes.group(2)}% در {minutes.group(1)} دقیقه"
        devices = _DEVICES.match(text)
        if devices and (devices.group(1) or devices.group(2)):
            return f"شارژ {devices.group(1) or devices.group(2)} دستگاه"
        whole = self.words.get(_norm(text))
        if whole is not None:
            return whole
        found = list(self._re.finditer(text))
        if not found:
            return text
        persian, rest, pos = [], [], 0
        for m in found:
            rest.append(text[pos:m.start()])
            persian.append(self.words[_norm(m.group(0))])
            pos = m.end()
        rest.append(text[pos:])
        leftover = " ".join(" ".join(rest).split())
        if all(_is_tech(t) for t in leftover.split()):
            # «Type-C Port Input»: the head word (input, output, capacity…) comes first
            # in Persian; the technical part goes last
            if len(found) > 1 and _norm(found[-1].group(0)) in HEADS:
                persian = persian[-1:] + persian[:-1]
            return " ".join(persian + ([leftover] if leftover else []))
        # a sentence: each phrase in its place
        return self._re.sub(lambda m: self.words[_norm(m.group(0))], text)


def _is_tech(token: str) -> bool:
    """A token that stays English: numbers / units, capitals (PD, QC, LCD), known names."""
    t = token.strip("()[],:;")
    if "/" in t.strip("/"):             # «Type-C/Micro/Lightning»: every part
        return all(_is_tech(part) for part in t.split("/") if part)
    if _PERSIAN.search(t):              # Persian words make it a sentence
        return False
    if not t or t.casefold() in _KNOWN_TECH:
        return True
    if re.search(r"\d", t) or re.search(r"[A-Z]{2,}", t):
        return True
    return bool(re.fullmatch(r"[^\w]+", t))


# ---- one item --------------------------------------------------------------------------------
def farsi_item(item: dict, dictionary: Dictionary) -> dict:
    """The item with a clean, translated description and specs (a new dict)."""
    out = dict(item)
    description = clean_description(item.get("description") or "")
    out["description"] = " • ".join(dictionary.translate(p) for p in description.split(" • ")
                                    if p)[:600]
    specs = []
    for key, value in clean_specs(item.get("specs") or []):
        specs.append([dictionary.translate(key)[:40], dictionary.translate(value)[:160]])
    out["specs"] = specs
    return out


def changed(old: dict, new: dict) -> bool:
    return (old.get("description") or "") != (new.get("description") or "") or \
        [list(r) for r in old.get("specs") or []] != [list(r) for r in new.get("specs") or []]

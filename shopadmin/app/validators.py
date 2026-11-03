"""v2.18.0: the customer form's rules on the server (the same rules and messages as
``validators.js`` of the mini app form at /app/form/; its test cases are in tests/test_v2180_forms.py).

What a page or a chat sends is never trusted: the server checks it all again.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_TO_ENGLISH = {ord(c): str(i) for i, c in enumerate(_PERSIAN_DIGITS)}
_TO_ENGLISH.update({ord(c): str(i) for i, c in enumerate(_ARABIC_DIGITS)})
_ARABIC_TO_PERSIAN = {ord(a): p for a, p in zip(_ARABIC_DIGITS, _PERSIAN_DIGITS)}

_LETTERS = ("ء-بت-غف-قل-وپچژک"
            "گھی")
_MARKS = "َ-ٕ"
_NAME_RE = re.compile(f"^[{_LETTERS}{_MARKS}\\s‌]+$")
_HAS_LETTER_RE = re.compile(f"[{_LETTERS}]")
_ADDRESS_RE = re.compile(f"^[{_LETTERS}{_MARKS}‌0-9۰-۹\\s،.\\-/]+$")

MAX_NAME = 50
MIN_ADDRESS = 5
MAX_ADDRESS = 300


@dataclass(frozen=True)
class Check:
    valid: bool
    normalized: str
    error: str = ""
    kind: str | None = None


def normalize_digits(value) -> str:
    return "" if value is None else str(value).translate(_TO_ENGLISH)


def normalize_persian_letters(value) -> str:
    if value is None:
        return ""
    text = re.sub("[يى]", "ی", str(value)).replace("ك", "ک")
    text = re.sub(r"[\r\n\t]+", " ", text)
    return re.sub(" {2,}", " ", text).strip()


def normalize_address_text(value) -> str:
    return normalize_persian_letters(value).translate(_ARABIC_TO_PERSIAN)


def is_valid_iranian_national_code(value) -> bool:
    code = normalize_digits(str(value if value is not None else "").strip())
    if not re.fullmatch(r"[0-9]{10}", code) or len(set(code)) == 1:
        return False
    remainder = sum(int(code[i]) * (10 - i) for i in range(9)) % 11
    check = int(code[9])
    return check == remainder if remainder < 2 else check == 11 - remainder


def is_valid_foreign_national_id(value) -> bool:
    code = normalize_digits(str(value if value is not None else "").strip())
    return bool(re.fullmatch(r"[0-9]{11}", code)) and len(set(code)) > 1


def validate_persian_name(value, label: str = "نام") -> Check:
    normalized = normalize_persian_letters(value)
    if not normalized:
        return Check(False, "", f"وارد کردن {label} الزامی است.")
    if not _NAME_RE.match(normalized):
        return Check(False, normalized, f"{label} باید فقط شامل حروف فارسی باشد.")
    if len(re.sub("[\\s‌]", "", normalized)) < 2:
        return Check(False, normalized, f"{label} باید حداقل ۲ حرف فارسی داشته باشد.")
    if len(normalized) > MAX_NAME:
        return Check(False, normalized, f"{label} نمی‌تواند بیش از ۵۰ کاراکتر باشد.")
    return Check(True, normalized)


def validate_first_name(value) -> Check:
    return validate_persian_name(value, "نام")


def validate_last_name(value) -> Check:
    return validate_persian_name(value, "نام خانوادگی")


def validate_national_code(value) -> Check:
    normalized = normalize_digits(str(value if value is not None else "").strip())
    if not normalized:
        return Check(False, "", "وارد کردن کد ملی یا شناسه اتباع الزامی است.")
    if not re.fullmatch(r"[0-9]+", normalized):
        return Check(False, normalized, "کد ملی باید فقط شامل اعداد باشد.")
    if len(normalized) == 10:
        if is_valid_iranian_national_code(normalized):
            return Check(True, normalized, kind="iranian_10")
        return Check(False, normalized, "کد ملی ۱۰ رقمی معتبر نیست (رقم کنترل نادرست است).")
    if len(normalized) == 11:
        if is_valid_foreign_national_id(normalized):
            return Check(True, normalized, kind="foreign_11")
        return Check(False, normalized, "شناسه ۱۱ رقمی اتباع معتبر نیست.")
    return Check(False, normalized, "کد ملی باید ۱۰ رقم (ایرانی) یا ۱۱ رقم (شناسه اتباع) باشد.")


def validate_address(value) -> Check:
    normalized = normalize_address_text(value)
    if not normalized:
        return Check(False, "", "وارد کردن نشانی الزامی است.")
    if not _ADDRESS_RE.match(normalized):
        return Check(False, normalized,
                     "نشانی فقط می‌تواند شامل حروف فارسی، اعداد، فاصله و علائم (، . - /) باشد.")
    if not _HAS_LETTER_RE.search(normalized):
        return Check(False, normalized, "نشانی باید شامل حداقل یک کلمه با حروف فارسی باشد.")
    if len(normalized) < MIN_ADDRESS:
        return Check(False, normalized, "نشانی وارد شده بسیار کوتاه است (حداقل ۵ کاراکتر).")
    if len(normalized) > MAX_ADDRESS:
        return Check(False, normalized, "نشانی نمی‌تواند بیش از ۳۰۰ کاراکتر باشد.")
    return Check(True, normalized)


VALIDATORS = {"first_name": validate_first_name, "last_name": validate_last_name,
              "national_code": validate_national_code, "address": validate_address}


def validate_customer_form(fields: dict) -> dict:
    """{valid, results: {field: Check}, errors: {field: text}, payload}: as the form's own."""
    results = {name: check(fields.get(name, "")) for name, check in VALIDATORS.items()}
    valid = all(result.valid for result in results.values())
    payload = None
    if valid:
        payload = {"v": 1, "type": "customer",
                   **{name: result.normalized for name, result in results.items()}}
    return {"valid": valid, "results": results,
            "errors": {name: result.error for name, result in results.items()},
            "payload": payload}

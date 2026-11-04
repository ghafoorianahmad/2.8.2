/**
 * ماژول اعتبارسنجی فرم اطلاعات مشتری — مینی‌اپ تلگرام و بله
 * بدون وابستگی خارجی — قابل اجرا در مرورگر (ES Module / Window) و Node.js
 */

const PERSIAN_DIGITS = '۰۱۲۳۴۵۶۷۸۹';
const ARABIC_DIGITS = '٠١٢٣٤٥٦٧٨٩';

// حروف مجاز فارسی (شامل همزه، پ، چ، ژ، ک، گ، ی و نیم‌فاصله در ترکیب)
const PERSIAN_NAME_REGEX = /^[\u0621-\u0628\u062A-\u063A\u0641-\u0642\u0644-\u0648\u064E-\u0655\u067E\u0686\u0698\u06A9\u06AF\u06BE\u06CC\s\u200C]+$/;

// حروف فارسی برای بررسی وجود حداقل یک حرف فارسی در نشانی
const HAS_PERSIAN_LETTER_REGEX = /[\u0621-\u0628\u062A-\u063A\u0641-\u0642\u0644-\u0648\u067E\u0686\u0698\u06A9\u06AF\u06BE\u06CC]/;

// کاراکترهای مجاز نشانی: حروف فارسی، ارقام فارسی و انگلیسی، فاصله، نیم‌فاصله و فقط علائم ، . - /
const ADDRESS_ALLOWED_REGEX = /^[\u0621-\u0628\u062A-\u063A\u0641-\u0642\u0644-\u0648\u064E-\u0655\u067E\u0686\u0698\u06A9\u06AF\u06BE\u06CC\u200C0-9\u06F0-\u06F9\s،.\-/]+$/;

/**
 * تبدیل ارقام فارسی (۰-۹) و عربی (٠-٩) به ارقام انگلیسی (0-9)
 * @param {string} value
 * @returns {string}
 */
export function normalizeDigits(value) {
  if (value === null || value === undefined) return '';
  let result = String(value);
  for (let i = 0; i < 10; i++) {
    result = result
      .replaceAll(PERSIAN_DIGITS[i], String(i))
      .replaceAll(ARABIC_DIGITS[i], String(i));
  }
  return result;
}

/**
 * یکسان‌سازی حروف عربی رایج کیبوردها (ي، ى، ك) به معادل استاندارد فارسی (ی، ک)
 * و تمیزسازی فاصله‌های متوالی
 * @param {string} value
 * @returns {string}
 */
export function normalizePersianLetters(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/[\u064A\u0649]/g, '\u06CC') // ي و ى -> ی
    .replace(/\u0643/g, '\u06A9') // ك -> ک
    .replace(/[\r\n\t]+/g, ' ')
    .replace(/ {2,}/g, ' ')
    .trim();
}

/**
 * یکسان‌سازی ارقام عربی (٠-٩) به فارسی (۰-۹) برای متن نشانی در صورت استفاده از کیبورد عربی
 * (ارقام فارسی و انگلیسی عیناً حفظ می‌شوند)
 * @param {string} value
 * @returns {string}
 */
export function normalizeAddressText(value) {
  if (value === null || value === undefined) return '';
  let result = normalizePersianLetters(value);
  for (let i = 0; i < 10; i++) {
    result = result.replaceAll(ARABIC_DIGITS[i], PERSIAN_DIGITS[i]);
  }
  return result;
}

/**
 * بررسی صحت کد ملی ۱۰ رقمی ایران بر اساس الگوریتم رقم کنترل (Modulo 11)
 * @param {string} rawCode
 * @returns {boolean}
 */
export function isValidIranianNationalCode(rawCode) {
  const code = normalizeDigits(String(rawCode ?? '').trim());
  if (!/^\d{10}$/.test(code)) {
    return false;
  }
  // رد کدهای دارای ۱۰ رقم یکسان مانند 0000000000 یا 1111111111
  if (/^(\d)\1{9}$/.test(code)) {
    return false;
  }

  let sum = 0;
  for (let i = 0; i < 9; i++) {
    sum += Number(code[i]) * (10 - i);
  }

  const remainder = sum % 11;
  const checkDigit = Number(code[9]);

  if (remainder < 2) {
    return checkDigit === remainder;
  }
  return checkDigit === 11 - remainder;
}

/**
 * بررسی صحت شناسه ۱۱ رقمی اتباع خارجی
 * @param {string} rawCode
 * @returns {boolean}
 */
export function isValidForeignNationalId(rawCode) {
  const code = normalizeDigits(String(rawCode ?? '').trim());
  if (!/^\d{11}$/.test(code)) {
    return false;
  }
  // رد شناسه‌هایی که تمام ۱۱ رقم آن یکسان است
  if (/^(\d)\1{10}$/.test(code)) {
    return false;
  }
  return true;
}

/**
 * اعتبارسنجی نام یا نام خانوادگی (فقط حروف فارسی)
 * @param {string} value
 * @param {string} fieldLabel
 * @returns {{ valid: boolean, normalized: string, error: string }}
 */
export function validatePersianName(value, fieldLabel = 'نام') {
  const raw = String(value ?? '');
  const normalized = normalizePersianLetters(raw);

  if (!normalized) {
    return {
      valid: false,
      normalized: '',
      error: `وارد کردن ${fieldLabel} الزامی است.`,
    };
  }

  if (!PERSIAN_NAME_REGEX.test(normalized)) {
    return {
      valid: false,
      normalized,
      error: `${fieldLabel} باید فقط شامل حروف فارسی باشد.`,
    };
  }

  const lettersOnly = normalized.replace(/[\s\u200C]/g, '');
  if (lettersOnly.length < 2) {
    return {
      valid: false,
      normalized,
      error: `${fieldLabel} باید حداقل ۲ حرف فارسی داشته باشد.`,
    };
  }

  if (normalized.length > 50) {
    return {
      valid: false,
      normalized,
      error: `${fieldLabel} نمی‌تواند بیش از ۵۰ کاراکتر باشد.`,
    };
  }

  return {
    valid: true,
    normalized,
    error: '',
  };
}

/**
 * اعتبارسنجی نام کوچک
 * @param {string} value
 */
export function validateFirstName(value) {
  return validatePersianName(value, 'نام');
}

/**
 * اعتبارسنجی نام خانوادگی
 * @param {string} value
 */
export function validateLastName(value) {
  return validatePersianName(value, 'نام خانوادگی');
}

/**
 * اعتبارسنجی کد ملی (۱۰ رقمی ایران با رقم کنترل) یا شناسه اتباع (۱۱ رقمی)
 * همراه با تبدیل ارقام فارسی/عربی به انگلیسی
 * @param {string} value
 * @returns {{ valid: boolean, normalized: string, kind: 'iranian_10' | 'foreign_11' | null, error: string }}
 */
export function validateNationalCode(value) {
  const raw = String(value ?? '').trim();
  const normalized = normalizeDigits(raw);

  if (!normalized) {
    return {
      valid: false,
      normalized: '',
      kind: null,
      error: 'وارد کردن کد ملی یا شناسه اتباع الزامی است.',
    };
  }

  if (!/^\d+$/.test(normalized)) {
    return {
      valid: false,
      normalized,
      kind: null,
      error: 'کد ملی باید فقط شامل اعداد باشد.',
    };
  }

  if (normalized.length === 10) {
    if (isValidIranianNationalCode(normalized)) {
      return {
        valid: true,
        normalized,
        kind: 'iranian_10',
        error: '',
      };
    }
    return {
      valid: false,
      normalized,
      kind: null,
      error: 'کد ملی ۱۰ رقمی معتبر نیست (رقم کنترل نادرست است).',
    };
  }

  if (normalized.length === 11) {
    if (isValidForeignNationalId(normalized)) {
      return {
        valid: true,
        normalized,
        kind: 'foreign_11',
        error: '',
      };
    }
    return {
      valid: false,
      normalized,
      kind: null,
      error: 'شناسه ۱۱ رقمی اتباع معتبر نیست.',
    };
  }

  return {
    valid: false,
    normalized,
    kind: null,
    error: 'کد ملی باید ۱۰ رقم (ایرانی) یا ۱۱ رقم (شناسه اتباع) باشد.',
  };
}

/**
 * اعتبارسنجی نشانی پستی:
 * فقط حروف فارسی، ارقام (فارسی یا انگلیسی)، فاصله و علائم ، . - / مجاز است.
 * @param {string} value
 * @returns {{ valid: boolean, normalized: string, error: string }}
 */
export function validateAddress(value) {
  const raw = String(value ?? '');
  const normalized = normalizeAddressText(raw);

  if (!normalized) {
    return {
      valid: false,
      normalized: '',
      error: 'وارد کردن نشانی الزامی است.',
    };
  }

  if (!ADDRESS_ALLOWED_REGEX.test(normalized)) {
    return {
      valid: false,
      normalized,
      error: 'نشانی فقط می‌تواند شامل حروف فارسی، اعداد، فاصله و علائم (، . - /) باشد.',
    };
  }

  if (!HAS_PERSIAN_LETTER_REGEX.test(normalized)) {
    return {
      valid: false,
      normalized,
      error: 'نشانی باید شامل حداقل یک کلمه با حروف فارسی باشد.',
    };
  }

  if (normalized.length < 5) {
    return {
      valid: false,
      normalized,
      error: 'نشانی وارد شده بسیار کوتاه است (حداقل ۵ کاراکتر).',
    };
  }

  if (normalized.length > 300) {
    return {
      valid: false,
      normalized,
      error: 'نشانی نمی‌تواند بیش از ۳۰۰ کاراکتر باشد.',
    };
  }

  return {
    valid: true,
    normalized,
    error: '',
  };
}

/**
 * اعتبارسنجی یکپارچه کل فرم مشتری و ساخت پیلود نهایی
 * @param {{ first_name?: string, last_name?: string, national_code?: string, address?: string }} fields
 */
export function validateCustomerForm(fields = {}) {
  const fnResult = validateFirstName(fields.first_name ?? '');
  const lnResult = validateLastName(fields.last_name ?? '');
  const ncResult = validateNationalCode(fields.national_code ?? '');
  const addrResult = validateAddress(fields.address ?? '');

  const valid =
    fnResult.valid && lnResult.valid && ncResult.valid && addrResult.valid;

  const payload = valid
    ? {
        v: 1,
        type: 'customer',
        first_name: fnResult.normalized,
        last_name: lnResult.normalized,
        national_code: ncResult.normalized,
        address: addrResult.normalized,
      }
    : null;

  return {
    valid,
    results: {
      first_name: fnResult,
      last_name: lnResult,
      national_code: ncResult,
      address: addrResult,
    },
    errors: {
      first_name: fnResult.error,
      last_name: lnResult.error,
      national_code: ncResult.error,
      address: addrResult.error,
    },
    payload,
  };
}

/**
 * استخراج مقادیر پیش‌فرض از پارامترهای URL (fn, ln, nc, addr)
 * @param {string} searchString
 * @returns {{ first_name: string, last_name: string, national_code: string, address: string, hasAny: boolean }}
 */
export function parsePrefillParams(searchString = '') {
  const params = new URLSearchParams(searchString);
  const first_name = params.get('fn') ?? '';
  const last_name = params.get('ln') ?? '';
  // v2.18.1: never from a link: a value in a URL stays in the logs of the host
  const national_code = '';
  const address = '';

  const hasAny = params.has('fn') || params.has('ln');

  return {
    first_name,
    last_name,
    national_code,
    address,
    hasAny,
  };
}

// اتصال به شیء سراسری مرورگر در صورت نیاز
if (typeof window !== 'undefined') {
  window.CustomerValidators = {
    normalizeDigits,
    normalizePersianLetters,
    normalizeAddressText,
    isValidIranianNationalCode,
    isValidForeignNationalId,
    validateFirstName,
    validateLastName,
    validateNationalCode,
    validateAddress,
    validateCustomerForm,
    parsePrefillParams,
  };
}

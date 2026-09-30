/** Persian formatting helpers — Jalali dates via Intl, relative times by hand. */

const jalaliDate = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  year: "numeric",
  month: "long",
  day: "numeric",
});

const jalaliDateTime = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  year: "numeric",
  month: "long",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const jalaliTime = new Intl.DateTimeFormat("fa-IR", {
  hour: "2-digit",
  minute: "2-digit",
});

export function faDate(value: string | Date | null | undefined): string {
  if (!value) return "—";
  return jalaliDate.format(new Date(value));
}

export function faDateTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  return jalaliDateTime.format(new Date(value));
}

export function faTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  return jalaliTime.format(new Date(value));
}

/** «۲ دقیقه پیش» */
export function relativeTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.round((Date.now() - then) / 1000);

  if (seconds < 45) return "همین حالا";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${toFa(minutes)} دقیقه پیش`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${toFa(hours)} ساعت پیش`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${toFa(days)} روز پیش`;
  return faDate(value);
}

export function toFa(input: number | string): string {
  return String(input).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
}

export function fileSize(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${toFa(bytes)} بایت`;
  if (bytes < 1024 * 1024) return `${toFa((bytes / 1024).toFixed(0))} کیلوبایت`;
  return `${toFa((bytes / 1024 / 1024).toFixed(1))} مگابایت`;
}

export function duration(seconds: number | null | undefined): string {
  if (!seconds || seconds < 0) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m === 0) return `${toFa(s)} ثانیه`;
  return `${toFa(m)}:${String(s).padStart(2, "0").replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)])}`;
}

export const conversationStatusLabel: Record<string, string> = {
  active: "فعال",
  waiting_user: "در انتظار کاربر",
  skipped: "ردشده",
  closed: "بسته",
};

export const answerStateLabel: Record<string, string> = {
  unanswered: "بدون پاسخ",
  answered: "پاسخ داده شده",
};

export const readStateLabel: Record<string, string> = {
  unread: "خوانده‌نشده",
  read: "خوانده‌شده",
};

export const skipReasonLabel: Record<string, string> = {
  spam: "هرزنامه",
  wrong_message: "پیام نامرتبط",
  not_relevant: "مرتبط نیست",
  handled_elsewhere: "در جای دیگر پیگیری شده",
  other: "سایر",
};

export const auditActionLabel: Record<string, string> = {
  AGENT_LOGIN: "ورود به پنل",
  AGENT_LOGIN_FAILED: "ورود ناموفق",
  AGENT_LOGOUT: "خروج از پنل",
  AGENT_CREATED: "ایجاد پشتیبان",
  AGENT_UPDATED: "ویرایش پشتیبان",
  AGENT_DISABLED: "غیرفعال‌سازی پشتیبان",
  CONVERSATION_CLAIMED: "برداشت گفتگو",
  CONVERSATION_RELEASED: "رها کردن گفتگو",
  CONVERSATION_ASSIGNED: "تخصیص گفتگو",
  CONVERSATION_SKIPPED: "رد کردن گفتگو",
  CONVERSATION_CLOSED: "بستن گفتگو",
  CONVERSATION_REOPENED: "بازگشایی گفتگو",
  CONVERSATION_WAITING_USER: "انتظار برای کاربر",
  CONVERSATION_READ: "خواندن گفتگو",
  MESSAGE_SENT: "ارسال پیام",
  MESSAGE_FAILED: "خطای ارسال پیام",
  MESSAGE_RETRIED: "تلاش مجدد ارسال",
  NOTE_ADDED: "ثبت یادداشت",
  NOTE_DELETED: "حذف یادداشت",
  EITAA_ACCOUNT_CONNECTED: "اتصال اکانت ایتا",
  EITAA_ACCOUNT_DISCONNECTED: "قطع اکانت ایتا",
  EITAA_ACCOUNT_UPDATED: "به‌روزرسانی اکانت ایتا",
  EITAA_SYNC_FAILED: "خطای همگام‌سازی",
  PASSWORD_CHANGED: "تغییر گذرواژه",
  LOGIN_CHALLENGE_REQUESTED: "درخواست کد ایتا",
};

export const roleLabel: Record<string, string> = {
  owner: "مالک",
  admin: "مدیر",
  agent: "پشتیبان",
};

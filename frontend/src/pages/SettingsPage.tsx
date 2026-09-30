import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { KeyRound, Moon, ShieldCheck, Sun, UserRound } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../stores/auth";
import { useTheme } from "../stores/theme";
import { useToast } from "../stores/toast";
import { useCapabilities } from "../api/queries";
import { roleLabel, toFa } from "../lib/format";

export function SettingsPage() {
  const { user, refreshUser } = useAuth();
  const { theme, toggle } = useTheme();
  const { push } = useToast();
  const { data: capabilities } = useCapabilities();

  const [name, setName] = useState(user?.name ?? "");
  const [username, setUsername] = useState(user?.username ?? "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  const saveProfile = useMutation({
    mutationFn: () =>
      api("/api/v1/auth/me", {
        method: "PATCH",
        body: { name, username: username || null },
      }),
    onSuccess: async () => {
      push("success", "پروفایل ذخیره شد.");
      await refreshUser();
    },
    onError: (exc) => push("error", exc instanceof ApiError ? exc.message : "خطا"),
  });

  const changePassword = useMutation({
    mutationFn: () =>
      api("/api/v1/auth/change-password", {
        method: "POST",
        body: { current_password: currentPassword, new_password: newPassword },
      }),
    onSuccess: () => {
      push("success", "گذرواژه تغییر کرد — لطفاً دوباره وارد شوید.");
      setCurrentPassword("");
      setNewPassword("");
    },
    onError: (exc) => push("error", exc instanceof ApiError ? exc.message : "خطا"),
  });

  return (
    <div className="h-full overflow-y-auto p-5">
      <h1 className="mb-4 text-base font-extrabold">تنظیمات</h1>

      <div className="grid max-w-4xl grid-cols-1 gap-4 md:grid-cols-2">
        {/* profile */}
        <section className="card p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-bold">
            <UserRound className="size-4 text-brand-600" />
            پروفایل من
          </h2>
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              saveProfile.mutate();
            }}
          >
            <div>
              <label className="mb-1 block text-[11px] font-semibold">نام نمایشی</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-semibold">نام کاربری</label>
              <input
                className="input"
                dir="ltr"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="اختیاری"
              />
            </div>
            <p className="text-[10px] text-ink-faint">
              نقش شما: <b>{roleLabel[user?.role ?? ""] ?? user?.role}</b> · ایمیل:{" "}
              <span dir="ltr">{user?.email}</span>
            </p>
            <button className="btn btn-primary" disabled={saveProfile.isPending}>
              ذخیره پروفایل
            </button>
          </form>
        </section>

        {/* password */}
        <section className="card p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-bold">
            <KeyRound className="size-4 text-brand-600" />
            تغییر گذرواژه
          </h2>
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              changePassword.mutate();
            }}
          >
            <div>
              <label className="mb-1 block text-[11px] font-semibold">گذرواژه فعلی</label>
              <input
                className="input"
                dir="ltr"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-semibold">گذرواژه جدید</label>
              <input
                className="input"
                dir="ltr"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                minLength={8}
                required
              />
            </div>
            <button className="btn btn-primary" disabled={changePassword.isPending}>
              تغییر گذرواژه
            </button>
            <p className="text-[10px] text-ink-faint">
              پس از تغییر، همه نشست‌های دیگر باطل می‌شوند.
            </p>
          </form>
        </section>

        {/* appearance */}
        <section className="card p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-bold">
            {theme === "dark" ? <Moon className="size-4 text-brand-600" /> : <Sun className="size-4 text-brand-600" />}
            ظاهر پنل
          </h2>
          <button className="btn btn-ghost w-full" onClick={toggle}>
            {theme === "dark" ? "روشن کردن پنل (Light)" : "تاریک کردن پنل (Dark)"}
          </button>
        </section>

        {/* system info */}
        <section className="card p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-bold">
            <ShieldCheck className="size-4 text-brand-600" />
            مشخصات سیستم
          </h2>
          <dl className="space-y-2 text-xs">
            <div className="flex justify-between border-b border-line/60 pb-1.5">
              <dt className="text-ink-faint">بازه همگام‌سازی ایتا</dt>
              <dd className="font-bold">{toFa(capabilities?.sync_interval_seconds ?? "—")} ثانیه</dd>
            </div>
            <div className="flex justify-between border-b border-line/60 pb-1.5">
              <dt className="text-ink-faint">سقف حجم پیوست</dt>
              <dd className="font-bold">{toFa(capabilities?.max_upload_size_mb ?? "—")} مگابایت</dd>
            </div>
            <div className="flex justify-between border-b border-line/60 pb-1.5">
              <dt className="text-ink-faint">همگام‌سازی لحظه‌ای پنل</dt>
              <dd className="font-bold">WebSocket فعال</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-ink-faint">رمزنگاری نشست ایتا</dt>
              <dd className="font-bold">Fernet (سمت سرور)</dd>
            </div>
          </dl>
          <p className="mt-3 text-[10px] leading-5 text-ink-faint">
            پیام‌های ایتا به‌صورت polling دریافت می‌شوند (کتابخانه eitaa-cli جریان رویداد
            ندارد) و بلافاصله پس از ذخیره، از طریق WebSocket به پنل شما ارسال می‌شوند.
          </p>
        </section>
      </div>
    </div>
  );
}

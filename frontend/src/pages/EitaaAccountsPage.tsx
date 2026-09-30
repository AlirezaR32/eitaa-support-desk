import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Phone, Plus, RefreshCw, Trash2, Zap } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useEitaaAccounts, useRequestCode, useVerifyCode } from "../api/queries";
import type { EitaaAccount, LoginChallenge } from "../types";
import { useAuth } from "../stores/auth";
import { useToast } from "../stores/toast";
import { faDateTime, toFa } from "../lib/format";
import { Badge, EmptyState, ErrorState, SkeletonRows, StatusDot } from "../components/ui/bits";
import { Modal } from "../components/ui/Modal";

export function EitaaAccountsPage() {
  const { hasPermission } = useAuth();
  const { push } = useToast();
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error, refetch } = useEitaaAccounts();
  const [wizardOpen, setWizardOpen] = useState(false);
  const canManage = hasPermission("eitaa.account.manage");

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
      api(`/api/v1/eitaa/accounts/${id}`, { method: "PATCH", body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["eitaa-accounts"] }),
    onError: (exc) => push("error", exc instanceof ApiError ? exc.message : "خطا"),
  });

  const disconnect = useMutation({
    mutationFn: (id: number) => api(`/api/v1/eitaa/accounts/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      push("success", "اکانت قطع شد.");
      queryClient.invalidateQueries({ queryKey: ["eitaa-accounts"] });
    },
    onError: (exc) => push("error", exc instanceof ApiError ? exc.message : "خطا"),
  });

  const triggerSync = useMutation({
    mutationFn: (id: number) => api(`/api/v1/eitaa/accounts/${id}/sync`, { method: "POST" }),
    onSuccess: () => push("success", "همگام‌سازی در صف قرار گرفت."),
  });

  if (isLoading) return <SkeletonRows rows={5} height="h-20" />;
  if (isError) return <ErrorState message={(error as Error).message} onRetry={() => refetch()} />;

  const accounts = data ?? [];

  return (
    <div className="h-full overflow-y-auto p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-base font-extrabold">اکانت‌های ایتا</h1>
          <p className="text-xs text-ink-faint">
            اکانت‌های متصل برای دریافت و پاسخ به پیام‌های کاربران — {toFa(accounts.length)} اکانت
          </p>
        </div>
        {canManage && (
          <button className="btn btn-primary" onClick={() => setWizardOpen(true)}>
            <Plus className="size-4" />
            افزودن اکانت ایتا
          </button>
        )}
      </div>

      {accounts.length === 0 ? (
        <EmptyState
          icon={<Phone className="size-9" />}
          title="اکانتی متصل نیست"
          hint="با «افزودن اکانت ایتا» با شماره support خود وارد شوید (ورود با کد یک‌بارمصرف ایتا)."
        />
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {accounts.map((account: EitaaAccount) => (
            <AccountCard
              key={account.id}
              account={account}
              canManage={canManage}
              onToggleSync={(enabled) => patch.mutate({ id: account.id, body: { sync_enabled: enabled } })}
              onSyncNow={() => triggerSync.mutate(account.id)}
              onDisconnect={() => disconnect.mutate(account.id)}
            />
          ))}
        </div>
      )}

      <p className="mt-4 text-[10px] leading-5 text-ink-faint">
        نکته: کتابخانه ایتا هیچ جریان رویداد لحظه‌ای ندارد؛ پیام‌ها با فاصله چند ثانیه همگام‌سازی می‌شوند.
        وضعیت «متصل» یعنی نشست ذخیره‌شده معتبر است و رمزنگاری‌شده نگه داشته می‌شود.
      </p>

      {wizardOpen && <ConnectWizard onClose={() => setWizardOpen(false)} />}
    </div>
  );
}

function AccountCard({
  account,
  canManage,
  onToggleSync,
  onSyncNow,
  onDisconnect,
}: {
  account: EitaaAccount;
  canManage: boolean;
  onToggleSync: (enabled: boolean) => void;
  onSyncNow: () => void;
  onDisconnect: () => void;
}) {
  const connected = account.status === "connected";
  return (
    <div className="card flex flex-col p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-bold">{account.display_name ?? "اکانت ایتا"}</p>
          <p dir="ltr" className="text-[11px] text-ink-faint">
            {account.phone_number}
            {account.username ? ` · @${account.username}` : ""}
          </p>
        </div>
        <StatusDot ok={connected}>
          {connected ? "متصل" : account.status === "pending" ? "در انتظار" : "قطع"}
        </StatusDot>
      </div>

      <div className="mb-3 space-y-1 text-[10px] text-ink-faint">
        <p>آخرین همگام‌سازی: {faDateTime(account.last_sync_at)}</p>
        {account.last_error && <p className="text-red-400">{account.last_error}</p>}
      </div>

      <div className="mt-auto flex flex-wrap items-center gap-1.5">
        {connected && account.deep_link && (
          <a
            className="btn btn-ghost !py-1 text-[11px]"
            href={account.deep_link}
            target="_blank"
            rel="noreferrer"
          >
            <ExternalLink className="size-3.5" />
            باز کردن اکانت در ایتا
          </a>
        )}
        {canManage && (
          <>
            <button
              className="btn btn-ghost !py-1 text-[11px]"
              onClick={() => onToggleSync(!account.sync_enabled)}
            >
              <RefreshCw className="size-3.5" />
              {account.sync_enabled ? "توقف همگام‌سازی" : "فعال‌سازی همگام‌سازی"}
            </button>
            {connected && (
              <button className="btn btn-ghost !py-1 text-[11px]" onClick={onSyncNow}>
                <Zap className="size-3.5" />
                همگام‌سازی فوری
              </button>
            )}
            <button
              className="btn btn-ghost !py-1 text-[11px] !text-red-500"
              onClick={onDisconnect}
            >
              <Trash2 className="size-3.5" />
              قطع اکانت
            </button>
          </>
        )}
      </div>

      {!account.sync_enabled && (
        <p className="mt-2">
          <Badge tone="warning">همگام‌سازی غیرفعال است</Badge>
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ OTP wizard */
function ConnectWizard({ onClose }: { onClose: () => void }) {
  const { push } = useToast();
  const requestCode = useRequestCode();
  const verifyCode = useVerifyCode();
  const [step, setStep] = useState<"phone" | "code">("phone");
  const [phone, setPhone] = useState("");
  const [challenge, setChallenge] = useState<LoginChallenge | null>(null);
  const [otp, setOtp] = useState("");
  const [resendTimer, setResendTimer] = useState(0);

  const request = async () => {
    try {
      const result = await requestCode.mutateAsync(phone.trim());
      setChallenge(result);
      setStep("code");
      setResendTimer(result.timeout_seconds ?? 120);
      push(
        "info",
        `کد از طریق «${deliveryLabel(result.delivery)}» ارسال شد — ${result.code_length ?? 5} رقم.`,
      );
    } catch (exc) {
      push("error", exc instanceof ApiError ? exc.message : "درخواست کد ناموفق بود");
    }
  };

  const resend = async () => {
    if (!challenge) return;
    try {
      const result = await api<LoginChallenge>("/api/v1/eitaa/accounts/resend-code", {
        method: "POST",
        body: { challenge_id: challenge.challenge_id },
      });
      setChallenge(result);
      setResendTimer(result.timeout_seconds ?? 120);
      push("info", `کد مجدداً از طریق «${deliveryLabel(result.delivery)}» ارسال شد.`);
    } catch (exc) {
      push("error", exc instanceof ApiError ? exc.message : "ارسال مجدد ناموفق بود");
    }
  };

  const verify = async () => {
    if (!challenge) return;
    try {
      await verifyCode.mutateAsync({ challenge_id: challenge.challenge_id, otp_code: otp.trim() });
      push("success", "اکانت ایتا متصل شد! همگام‌سازی پیام‌ها آغاز می‌شود.");
      onClose();
    } catch (exc) {
      push("error", exc instanceof ApiError ? exc.message : "کد تأیید نشد");
    }
  };

  return (
    <Modal open onClose={onClose} title="اتصال اکانت ایتا">
      {step === "phone" ? (
        <div className="space-y-4">
          <p className="text-xs leading-6 text-ink-soft">
            شماره موبایلی که اکانت پشتیبانی ایتا با آن ساخته شده را وارد کنید. کد تأیید به همان شماره
            ارسال می‌شود؛ سرور ایتا روش ارسال (پیامک/تماس/اپ) را تعیین می‌کند.
          </p>
          <input
            className="input text-left"
            dir="ltr"
            placeholder="09121234567"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            autoFocus
            inputMode="tel"
          />
          <button
            className="btn btn-primary w-full"
            onClick={() => void request()}
            disabled={phone.trim().length < 8 || requestCode.isPending}
          >
            {requestCode.isPending ? "در حال درخواست کد…" : "دریافت کد تأیید"}
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-xs leading-6 text-ink-soft">
            کد ارسال‌شده به شماره <span dir="ltr">{challenge?.phone_number}</span> را وارد کنید.
            {resendTimer > 0 && (
              <span className="text-ink-faint">
                {" "}
                (ارسال مجدد پس از {toFa(resendTimer)} ثانیه)
              </span>
            )}
          </p>
          <input
            className="input text-center text-lg tracking-[0.5em]"
            dir="ltr"
            placeholder="—————"
            value={otp}
            onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
            maxLength={challenge?.code_length ?? 5}
            autoFocus
            inputMode="numeric"
          />
          <div className="flex gap-2">
            <button className="btn btn-ghost flex-1" onClick={() => setStep("phone")}>
              تغییر شماره
            </button>
            <button
              className="btn btn-ghost flex-1"
              onClick={() => void resend()}
              disabled={resendTimer > 0}
            >
              ارسال مجدد کد
            </button>
          </div>
          <button
            className="btn btn-primary w-full"
            onClick={() => void verify()}
            disabled={otp.trim().length < 3 || verifyCode.isPending}
          >
            {verifyCode.isPending ? "در حال تأیید…" : "تأیید و اتصال"}
          </button>
        </div>
      )}
      <ResendTimer seconds={resendTimer} onTick={setResendTimer} />
    </Modal>
  );
}

function ResendTimer({
  seconds,
  onTick,
}: {
  seconds: number;
  onTick: (value: number) => void;
}) {
  useEffect(() => {
    if (seconds <= 0) return;
    const timer = setTimeout(() => onTick(seconds - 1), 1000);
    return () => clearTimeout(timer);
  }, [seconds, onTick]);
  return null;
}

function deliveryLabel(delivery: string): string {
  const map: Record<string, string> = {
    sms: "پیامک",
    call: "تماس صوتی",
    "flash-call": "تماس ریز",
    app: "اپلیکیشن ایتا",
    unknown: "نامشخص",
  };
  return map[delivery] ?? delivery;
}

import { Activity, CheckCircle2, Clock, Hand, Inbox, MessageCircle, Timer, XCircle } from "lucide-react";
import { useDashboard } from "../api/queries";
import { useAuth } from "../stores/auth";
import { duration, toFa } from "../lib/format";
import { ErrorState, SkeletonRows } from "../components/ui/bits";

export function DashboardPage() {
  const { data, isLoading, isError, error, refetch } = useDashboard();
  const { user } = useAuth();

  if (isLoading)
    return (
      <div className="h-full overflow-y-auto p-5">
        <SkeletonRows rows={6} height="h-24" />
      </div>
    );
  if (isError || !data)
    return <ErrorState message={(error as Error).message} onRetry={() => refetch()} />;

  const cards = [
    { label: "خوانده‌نشده", value: data.unread, icon: Inbox, tone: "text-brand-600" },
    { label: "بدون پاسخ", value: data.unanswered, icon: Clock, tone: "text-amber-500" },
    { label: "پاسخ‌داده امروز", value: data.answered_today, icon: CheckCircle2, tone: "text-emerald-500" },
    { label: "در انتظار کاربر", value: data.waiting_user, icon: Timer, tone: "text-sky-500" },
    { label: "ردشده", value: data.skipped, icon: XCircle, tone: "text-ink-faint" },
    { label: "بسته", value: data.closed, icon: XCircle, tone: "text-ink-faint" },
    { label: "گفتگوهای من", value: data.my_conversations, icon: MessageCircle, tone: "text-brand-600" },
    { label: "بدون پشتیبان", value: data.unassigned, icon: Hand, tone: "text-amber-500" },
  ];

  return (
    <div className="h-full overflow-y-auto p-5">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="text-base font-extrabold">داشبورد</h1>
          <p className="text-xs text-ink-faint">
            آمار لحظه‌ای از داده‌های واقعی پایگاه داده — {user?.name ?? ""}
          </p>
        </div>
        <p className="text-[10px] text-ink-faint">به‌روزرسانی خودکار هر ۳۰ ثانیه</p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {cards.map((card) => (
          <div key={card.label} className="card p-4">
            <card.icon className={`mb-2 size-5 ${card.tone}`} />
            <p className="text-xl font-extrabold">{toFa(card.value)}</p>
            <p className="mt-0.5 text-[11px] text-ink-soft">{card.label}</p>
          </div>
        ))}
      </div>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="card p-4">
          <p className="mb-2 text-xs font-bold">شاخص‌های عملکرد</p>
          <dl className="space-y-2.5 text-xs">
            <StatRow
              label="میانگین اولین پاسخ"
              value={data.avg_first_response_seconds ? duration(data.avg_first_response_seconds) : "—"}
            />
            <StatRow
              label="میانگین زمان حل مسئله"
              value={data.avg_resolution_seconds ? duration(data.avg_resolution_seconds) : "—"}
            />
          </dl>
        </div>
        <div className="card p-4">
          <p className="mb-2 text-xs font-bold">نمای کلی</p>
          <dl className="space-y-2.5 text-xs">
            <StatRow label="کل گفتگوها" value={toFa(data.total_conversations)} />
            <StatRow label="پیام‌های امروز" value={toFa(data.messages_today)} />
            <StatRow
              label="پشتیبان‌های فعال (۲۴ساعت)"
              value={toFa(data.active_agents)}
            />
          </dl>
        </div>
      </div>

      <p className="mt-4 flex items-center gap-1.5 text-[10px] text-ink-faint">
        <Activity className="size-3.5" />
        آمار دقیق پس از هر رویداد (ارسال، همگام‌سازی، تغییر وضعیت) به‌روز می‌شود.
      </p>
    </div>
  );
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-line/60 pb-2">
      <dt className="text-ink-faint">{label}</dt>
      <dd className="font-bold">{value}</dd>
    </div>
  );
}

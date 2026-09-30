import { Bell, BellOff, CheckCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useMarkAllRead, useNotifications } from "../api/queries";
import type { Notification } from "../types";
import { relativeTime, toFa } from "../lib/format";
import { Badge, EmptyState, SkeletonRows } from "../components/ui/bits";

export function NotificationsPage() {
  const { data, isLoading } = useNotifications();
  const markAllRead = useMarkAllRead();
  const navigate = useNavigate();

  if (isLoading) return <SkeletonRows rows={6} height="h-16" />;

  const notifications: Notification[] = data?.items ?? [];
  const unreadCount = notifications.filter((notification) => !notification.is_read).length;

  return (
    <div className="h-full overflow-y-auto p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-base font-extrabold">اعلان‌ها</h1>
          <p className="text-xs text-ink-faint">
            {toFa(unreadCount)} اعلان خوانده‌نشده از {toFa(notifications.length)} مورد
          </p>
        </div>
        {unreadCount > 0 && (
          <button
            className="btn btn-ghost"
            onClick={() => markAllRead.mutate()}
            disabled={markAllRead.isPending}
          >
            <CheckCheck className="size-4" />
            علامت‌گذاری همه به‌عنوان خوانده‌شده
          </button>
        )}
      </div>

      {notifications.length === 0 ? (
        <EmptyState
          icon={<BellOff className="size-9" />}
          title="اعلانی نیست"
          hint="گفتگوهای بدون پاسخ بیش از ۱۰ دقیقه به‌صورت خودکار اعلان ایجاد می‌کنند."
        />
      ) : (
        <div className="space-y-2">
          {notifications.map((notification: Notification) => (
            <button
              key={notification.id}
              onClick={() => notification.conversation_id && navigate(`/inbox/all/${notification.conversation_id}`)}
              className={`card fade-in block w-full p-3.5 text-right transition-colors hover:border-brand-400 ${
                notification.is_read ? "opacity-70" : ""
              }`}
            >
              <div className="mb-1 flex items-center gap-2">
                {!notification.is_read && <Bell className="size-3.5 text-amber-500" />}
                <p className="text-xs font-bold">{notification.title}</p>
                <Badge tone={notification.is_read ? "neutral" : "warning"}>
                  {notification.is_read ? "خوانده‌شده" : "جدید"}
                </Badge>
                <span className="mr-auto text-[10px] text-ink-faint">
                  {relativeTime(notification.created_at)}
                </span>
              </div>
              <p className="text-[11px] leading-5 text-ink-soft">{notification.body}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

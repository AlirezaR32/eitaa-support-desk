import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Bell,
  BookOpenCheck,
  History,
  Inbox,
  Keyboard,
  LayoutDashboard,
  LogOut,
  MessageCircle,
  Moon,
  Phone,
  Settings,
  Sun,
  Users,
} from "lucide-react";
import { api } from "../../lib/api";
import { useAuth } from "../../stores/auth";
import { useTheme } from "../../stores/theme";
import { useRealtime } from "../../hooks/useRealtime";
import { roleLabel, toFa } from "../../lib/format";
import { Modal } from "../ui/Modal";

const NAV_ITEMS = [
  { to: "/inbox", label: "صندوق ورودی", icon: Inbox, permission: "conversation.view.account" },
  { to: "/dashboard", label: "داشبورد", icon: LayoutDashboard, permission: "dashboard.view.own" },
  { to: "/agents", label: "پشتیبان‌ها", icon: Users, permission: "agent.view" },
  { to: "/eitaa-accounts", label: "اکانت‌های ایتا", icon: Phone, permission: "eitaa.account.view" },
  { to: "/notifications", label: "اعلان‌ها", icon: Bell, permission: "notification.view" },
  { to: "/audit-logs", label: "لاگ فعالیت", icon: History, permission: "audit.view" },
  { to: "/settings", label: "تنظیمات", icon: Settings, permission: null },
];

export const SHORTCUTS = [
  { keys: "J / K", action: "گفتگوی بعدی / قبلی" },
  { keys: "Ctrl+K", action: "پرش به جستجو" },
  { keys: "R", action: "تمرکز روی پاسخ‌دهی" },
  { keys: "C", action: "برداشت (Claim) گفتگو" },
  { keys: "Esc", action: "بستن پنجره / لغو" },
  { keys: "?", action: "نمایش همین راهنما" },
];

export function AppLayout() {
  const { user, logout, hasPermission } = useAuth();
  const { theme, toggle } = useTheme();
  const location = useLocation();
  const [showShortcuts, setShowShortcuts] = useState(false);
  useRealtime(Boolean(user));

  const { data: unread } = useQuery({
    queryKey: ["unread-count"],
    queryFn: () => api<{ count: number }>("/api/v1/notifications/unread-count"),
    refetchInterval: 60_000,
  });

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      const typing =
        target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
      if (event.key === "?" && !typing) {
        setShowShortcuts(true);
      }
      if (event.key === "Escape") setShowShortcuts(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const logoutMutation = useMutation({ mutationFn: logout });

  return (
    <div className="flex h-full">
      {/* sidebar */}
      <aside className="hidden w-56 shrink-0 flex-col border-l border-line bg-surface md:flex">
        <div className="flex items-center gap-2 px-4 py-4">
          <div className="flex size-9 items-center justify-center rounded-xl bg-brand-600 text-white">
            <MessageCircle className="size-4.5" />
          </div>
          <div>
            <p className="text-sm font-extrabold">پشتیبانی ایتا</p>
            <p className="text-[10px] text-ink-faint">میزبان گفتگوهای کاربران</p>
          </div>
        </div>

        <nav className="mt-2 flex-1 space-y-0.5 px-2">
          {NAV_ITEMS.filter((item) => !item.permission || hasPermission(item.permission)).map(
            (item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-semibold transition-colors ${
                    isActive
                      ? "bg-brand-500/10 text-brand-700 dark:text-brand-300"
                      : "text-ink-soft hover:bg-black/5 hover:text-ink dark:hover:bg-white/5"
                  }`
                }
              >
                <item.icon className="size-4" />
                {item.label}
                {item.to === "/notifications" && (unread?.count ?? 0) > 0 && (
                  <span className="mr-auto rounded-full bg-red-500 px-1.5 text-[10px] font-bold text-white">
                    {toFa(unread?.count ?? 0)}
                  </span>
                )}
              </NavLink>
            ),
          )}
        </nav>

        <div className="border-t border-line p-3">
          <div className="mb-2 flex items-center gap-2 px-1">
            <div className="flex size-8 items-center justify-center rounded-full bg-brand-500/15 text-xs font-bold text-brand-700 dark:text-brand-300">
              {user?.name?.slice(0, 1)}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-bold">{user?.name}</p>
              <p className="text-[10px] text-ink-faint">{roleLabel[user?.role ?? ""] ?? user?.role}</p>
            </div>
          </div>
          <div className="flex gap-1.5">
            <button
              onClick={() => setShowShortcuts(true)}
              className="btn btn-ghost flex-1 !px-2 !py-1.5 text-[11px]"
              title="کلیدهای میان‌بر (?)"
            >
              <Keyboard className="size-3.5" />
            </button>
            <button
              onClick={toggle}
              className="btn btn-ghost flex-1 !px-2 !py-1.5 text-[11px]"
              title="حالت شب/روز"
            >
              {theme === "dark" ? <Sun className="size-3.5" /> : <Moon className="size-3.5" />}
            </button>
            <button
              onClick={() => logoutMutation.mutate()}
              className="btn btn-ghost flex-1 !px-2 !py-1.5 text-[11px]"
              title="خروج"
            >
              <LogOut className="size-3.5" />
            </button>
          </div>
        </div>
      </aside>

      {/* content */}
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden" key={location.pathname}>
        {/* mobile top bar */}
        <div className="flex items-center justify-between border-b border-line bg-surface px-3 py-2 md:hidden">
          <p className="text-xs font-bold">پشتیبانی ایتا</p>
          <div className="flex gap-1">
            {NAV_ITEMS.filter((item) => !item.permission || hasPermission(item.permission))
              .slice(0, 5)
              .map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `rounded-lg p-2 ${isActive ? "bg-brand-500/10 text-brand-700" : "text-ink-soft"}`
                  }
                >
                  <item.icon className="size-4" />
                </NavLink>
              ))}
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </div>
      </main>

      <Modal open={showShortcuts} onClose={() => setShowShortcuts(false)} title="کلیدهای میان‌بر">
        <ul className="space-y-2">
          {SHORTCUTS.map((shortcut) => (
            <li key={shortcut.keys} className="flex items-center justify-between text-xs">
              <span className="text-ink-soft">{shortcut.action}</span>
              <kbd className="rounded-md border border-line bg-black/5 px-2 py-0.5 font-mono text-[10px] dark:bg-white/10">
                {shortcut.keys}
              </kbd>
            </li>
          ))}
        </ul>
        <p className="mt-4 flex items-center gap-1.5 text-[11px] text-ink-faint">
          <BookOpenCheck className="size-3.5" />
          میان‌برها فقط در صفحه صندوق ورودی فعال هستند.
        </p>
      </Modal>
    </div>
  );
}

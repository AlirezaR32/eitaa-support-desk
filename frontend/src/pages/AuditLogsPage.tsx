import { useState } from "react";
import { History, Search } from "lucide-react";
import { useAuditLogs } from "../api/queries";
import type { AuditLog } from "../types";
import { auditActionLabel, faDateTime, toFa } from "../lib/format";
import { Badge, EmptyState, SkeletonRows } from "../components/ui/bits";
import { ChevronLeft, ChevronRight } from "lucide-react";

const ACTION_GROUPS = [
  "AGENT_LOGIN",
  "AGENT_CREATED",
  "CONVERSATION_CLAIMED",
  "CONVERSATION_ASSIGNED",
  "MESSAGE_SENT",
  "MESSAGE_FAILED",
  "CONVERSATION_SKIPPED",
  "CONVERSATION_CLOSED",
  "NOTE_ADDED",
  "EITAA_ACCOUNT_CONNECTED",
  "EITAA_ACCOUNT_DISCONNECTED",
];

export function AuditLogsPage() {
  const [action, setAction] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const { data, isLoading } = useAuditLogs({ action: action || undefined, q: q || undefined, page });

  return (
    <div className="h-full overflow-y-auto p-5">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <h1 className="flex items-center gap-2 text-base font-extrabold">
            <History className="size-4.5" />
            لاگ فعالیت
          </h1>
          <p className="text-xs text-ink-faint">
            تمام عملیات‌های مهم پشتیبان‌ها — بدون هیچ داده حساسی (توکن/کد/گذرواژه)
          </p>
        </div>
        <div className="relative">
          <Search className="absolute right-3 top-1/2 size-3.5 -translate-y-1/2 text-ink-faint" />
          <input
            className="input !w-56 !pr-9 text-xs"
            placeholder="جستجوی نام کاربر…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </div>
        <select
          className="input !w-auto text-xs"
          value={action}
          onChange={(e) => {
            setAction(e.target.value);
            setPage(1);
          }}
        >
          <option value="">همه رویدادها</option>
          {ACTION_GROUPS.map((value) => (
            <option key={value} value={value}>
              {auditActionLabel[value] ?? value}
            </option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <SkeletonRows rows={10} height="h-10" />
      ) : (data?.items ?? []).length === 0 ? (
        <EmptyState icon={<History className="size-9" />} title="رویدادی ثبت نشده است" />
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-right text-xs">
            <thead>
              <tr className="border-b border-line text-ink-faint">
                <th className="p-3 font-semibold">زمان</th>
                <th className="p-3 font-semibold">کاربر</th>
                <th className="p-3 font-semibold">رویداد</th>
                <th className="p-3 font-semibold">هدف</th>
                <th className="p-3 font-semibold">جزئیات</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items ?? []).map((log: AuditLog) => (
                <tr key={log.id} className="border-b border-line/60 last:border-0">
                  <td className="whitespace-nowrap p-3 text-ink-faint">
                    {faDateTime(log.created_at)}
                  </td>
                  <td className="p-3 font-semibold">{log.actor_name || "سیستم"}</td>
                  <td className="p-3">
                    <Badge tone="neutral">{auditActionLabel[log.action] ?? log.action}</Badge>
                  </td>
                  <td className="p-3 text-ink-soft" dir="ltr">
                    {log.target_type ? `${log.target_type}#${log.target_id ?? "-"}` : "—"}
                  </td>
                  <td className="max-w-64 truncate p-3 text-[10px] text-ink-faint" dir="ltr">
                    {log.meta ? JSON.stringify(log.meta) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.pages > 1 && (
        <div className="mt-3 flex items-center justify-center gap-3 text-xs">
          <button
            className="btn btn-ghost !py-1 text-[11px]"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
          >
            <ChevronRight className="size-3.5" />
            قبلی
          </button>
          <span className="text-ink-faint">
            صفحه {toFa(data.page)} از {toFa(data.pages)}
          </span>
          <button
            className="btn btn-ghost !py-1 text-[11px]"
            disabled={page >= data.pages}
            onClick={() => setPage((p) => p + 1)}
          >
            بعدی
            <ChevronLeft className="size-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}

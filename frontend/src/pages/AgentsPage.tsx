import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, ShieldCheck, UserRound } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { useAgents, useEitaaAccounts } from "../api/queries";
import type { Agent } from "../types";
import { useAuth } from "../stores/auth";
import { useToast } from "../stores/toast";
import { faDateTime, roleLabel, toFa } from "../lib/format";
import { Badge, EmptyState, ErrorState, SkeletonRows } from "../components/ui/bits";
import { Modal } from "../components/ui/Modal";

export function AgentsPage() {
  const { hasPermission, user } = useAuth();
  const { push } = useToast();
  const queryClient = useQueryClient();
  const { data, isLoading, isError, error, refetch } = useAgents();
  const { data: accounts } = useEitaaAccounts();
  const [editing, setEditing] = useState<Agent | "new" | null>(null);

  const canManage = hasPermission("agent.manage");

  const deactivate = useMutation({
    mutationFn: (agentId: number) => api(`/api/v1/agents/${agentId}`, { method: "DELETE" }),
    onSuccess: () => {
      push("success", "پشتیبان غیرفعال شد.");
      queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: (exc) => push("error", exc instanceof ApiError ? exc.message : "خطا"),
  });

  if (isLoading) return <SkeletonRows rows={8} />;
  if (isError) return <ErrorState message={(error as Error).message} onRetry={() => refetch()} />;

  const agents = data?.items ?? [];

  return (
    <div className="h-full overflow-y-auto p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-base font-extrabold">پشتیبان‌ها</h1>
          <p className="text-xs text-ink-faint">
            {toFa(agents.length)} کاربر پنل — وضعیت اتصال هر پشتیبان به اکانت‌های ایتا مشخص است.
          </p>
        </div>
        {canManage && (
          <button className="btn btn-primary" onClick={() => setEditing("new")}>
            <Plus className="size-4" />
            افزودن پشتیبان
          </button>
        )}
      </div>

      {agents.length === 0 ? (
        <EmptyState icon={<UserRound className="size-9" />} title="پشتیبانی ثبت نشده است" />
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-right text-xs">
            <thead>
              <tr className="border-b border-line text-ink-faint">
                <th className="p-3 font-semibold">نام</th>
                <th className="p-3 font-semibold">ایمیل</th>
                <th className="p-3 font-semibold">نقش</th>
                <th className="p-3 font-semibold">وضعیت</th>
                <th className="p-3 font-semibold">اکانت‌های ایتا</th>
                <th className="p-3 font-semibold">آخرین ورود</th>
                {canManage && <th className="p-3 font-semibold">عملیات</th>}
              </tr>
            </thead>
            <tbody>
              {agents.map((agent: Agent) => {
                const linked = (accounts ?? []).filter(
                  (account: { id: number; agent_ids: number[] }) =>
                    account.agent_ids.includes(agent.id),
                );
                return (
                  <tr key={agent.id} className="border-b border-line/60 last:border-0">
                    <td className="p-3 font-bold">
                      {agent.name}
                      {agent.id === user?.id && (
                        <span className="mr-1.5 text-[10px] text-ink-faint">(شما)</span>
                      )}
                    </td>
                    <td className="p-3" dir="ltr">
                      {agent.email}
                    </td>
                    <td className="p-3">
                      <Badge tone={agent.role === "owner" ? "brand" : agent.role === "admin" ? "info" : "neutral"}>
                        {roleLabel[agent.role] ?? agent.role}
                      </Badge>
                    </td>
                    <td className="p-3">
                      {agent.is_active ? (
                        <Badge tone="success">فعال</Badge>
                      ) : (
                        <Badge tone="danger">غیرفعال</Badge>
                      )}
                    </td>
                    <td className="p-3">
                      {linked.length === 0 ? (
                        <span className="text-ink-faint">—</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {linked.map((account) => (
                            <Badge key={account.id} tone={account.status === "connected" ? "success" : "neutral"}>
                              {account.display_name ?? account.phone_number}
                              {account.status === "connected" ? " ●" : " ○"}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="p-3 text-ink-faint">{faDateTime(agent.last_login_at)}</td>
                    {canManage && (
                      <td className="space-x-1 p-3 text-left" dir="ltr">
                        <button
                          className="btn btn-ghost !py-1 text-[11px]"
                          onClick={() => setEditing(agent)}
                        >
                          ویرایش
                        </button>
                        {agent.is_active && agent.id !== user?.id && (
                          <button
                            className="btn btn-ghost !py-1 text-[11px] !text-red-500"
                            onClick={() => deactivate.mutate(agent.id)}
                            disabled={deactivate.isPending}
                          >
                            غیرفعال‌سازی
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-3 flex items-center gap-1.5 text-[10px] text-ink-faint">
        <ShieldCheck className="size-3.5" />
        دسترسی‌ها از طریق نقش‌ها و مجوزها کنترل می‌شوند؛ گذرواژه‌ها با Argon2 ذخیره می‌شوند.
      </p>

      {editing !== null && (
        <AgentEditModal
          agent={editing === "new" ? null : editing}
          accounts={accounts ?? []}
          canCreateOwner={user?.role === "owner"}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

function AgentEditModal({
  agent,
  accounts,
  canCreateOwner,
  onClose,
}: {
  agent: Agent | null;
  accounts: { id: number; display_name: string | null; phone_number: string; status: string }[];
  canCreateOwner: boolean;
  onClose: () => void;
}) {
  const { push } = useToast();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    name: agent?.name ?? "",
    username: agent?.username ?? "",
    email: agent?.email ?? "",
    password: "",
    role: agent?.role ?? "agent",
    is_active: agent?.is_active ?? true,
    account_ids: agent?.eitaa_account_ids ?? [],
  });

  const save = useMutation({
    mutationFn: async () => {
      const payload: Record<string, unknown> = {
        name: form.name,
        username: form.username || null,
        email: form.email,
        role: form.role,
        is_active: form.is_active,
        eitaa_account_ids: form.account_ids,
      };
      if (form.password) payload.password = form.password;
      if (agent) {
        return api<Agent>(`/api/v1/agents/${agent.id}`, { method: "PATCH", body: payload });
      }
      return api<Agent>("/api/v1/agents", { method: "POST", body: payload });
    },
    onSuccess: () => {
      push("success", agent ? "پشتیبان به‌روزرسانی شد." : "پشتیبان ساخته شد.");
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      onClose();
    },
    onError: (exc) => push("error", exc instanceof ApiError ? exc.message : "خطا در ذخیره"),
  });

  return (
    <Modal open onClose={onClose} title={agent ? "ویرایش پشتیبان" : "افزودن پشتیبان جدید"}>
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <Field label="نام">
          <input
            className="input"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
          />
        </Field>
        <Field label="ایمیل">
          <input
            className="input"
            dir="ltr"
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            required
          />
        </Field>
        <Field label="گذرواژه" hint={agent ? "خالی بگذارید تا تغییر نکند" : "حداقل ۸ کاراکتر"}>
          <input
            className="input"
            dir="ltr"
            type="password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            minLength={agent ? undefined : 8}
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="نقش">
            <select
              className="input"
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value })}
            >
              <option value="agent">پشتیبان</option>
              <option value="admin">مدیر</option>
              {canCreateOwner && <option value="owner">مالک</option>}
            </select>
          </Field>
          <Field label="وضعیت">
            <select
              className="input"
              value={form.is_active ? "1" : "0"}
              onChange={(e) => setForm({ ...form, is_active: e.target.value === "1" })}
            >
              <option value="1">فعال</option>
              <option value="0">غیرفعال</option>
            </select>
          </Field>
        </div>
        <Field label="اکانت‌های ایتا" hint="پشتیبان فقط گفتگوهای این اکانت‌ها را می‌بیند">
          <div className="space-y-1.5">
            {accounts.length === 0 && (
              <p className="text-[11px] text-ink-faint">اکانتی متصل نیست — از صفحه «اکانت‌های ایتا» اضافه کنید.</p>
            )}
            {accounts.map((account) => (
              <label key={account.id} className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={form.account_ids.includes(account.id)}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      account_ids: event.target.checked
                        ? [...form.account_ids, account.id]
                        : form.account_ids.filter((id) => id !== account.id),
                    })
                  }
                />
                {account.display_name ?? account.phone_number}
                <span dir="ltr" className="text-[10px] text-ink-faint">
                  {account.phone_number}
                </span>
              </label>
            ))}
          </div>
        </Field>

        <div className="flex justify-end gap-2 pt-2">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            انصراف
          </button>
          <button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {save.isPending ? "در حال ذخیره…" : "ذخیره"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-semibold">{label}</label>
      {children}
      {hint && <p className="mt-1 text-[10px] text-ink-faint">{hint}</p>}
    </div>
  );
}

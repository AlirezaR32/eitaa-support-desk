import type { ReactNode } from "react";

/** Small status dot with label — connection indicators (§7). */
export function StatusDot({
  ok,
  children,
}: {
  ok: boolean | null;
  children?: ReactNode;
}) {
  const color =
    ok === null ? "bg-ink-faint" : ok ? "bg-emerald-500" : "bg-red-500";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium">
      <span className={`size-2 rounded-full ${color} ${ok ? "" : "ring-2 ring-red-500/20"}`} />
      {children}
    </span>
  );
}

const badgeStyles: Record<string, string> = {
  neutral: "bg-black/5 text-ink-soft dark:bg-white/10",
  success: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  warning: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  danger: "bg-red-500/10 text-red-600 dark:text-red-400",
  brand: "bg-brand-500/10 text-brand-700 dark:text-brand-300",
  info: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
};

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: keyof typeof badgeStyles;
  children: ReactNode;
}) {
  return <span className={`badge ${badgeStyles[tone]}`}>{children}</span>;
}

export function EmptyState({
  icon,
  title,
  hint,
}: {
  icon: ReactNode;
  title: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 p-10 text-center">
      <div className="text-ink-faint">{icon}</div>
      <p className="text-sm font-semibold">{title}</p>
      {hint && <p className="max-w-xs text-xs leading-5 text-ink-faint">{hint}</p>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
      <p className="text-sm font-semibold text-red-500">{message}</p>
      {onRetry && (
        <button className="btn btn-ghost" onClick={onRetry}>
          تلاش مجدد
        </button>
      )}
    </div>
  );
}

export function SkeletonRows({ rows = 6, height = "h-12" }: { rows?: number; height?: string }) {
  return (
    <div className="flex flex-col gap-2 p-3">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className={`skeleton w-full ${height}`} />
      ))}
    </div>
  );
}

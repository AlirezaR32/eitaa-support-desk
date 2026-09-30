import { useEffect, useMemo, useState } from "react";
import { Search, ChevronRight, ChevronLeft, Inbox, Filter } from "lucide-react";
import { useConversations } from "../../api/queries";
import type { ConversationFilters } from "../../api/queries";
import type { Conversation } from "../../types";
import { relativeTime, toFa } from "../../lib/format";
import { Badge, EmptyState, ErrorState, SkeletonRows } from "../ui/bits";

export const TABS = [
  { key: "all", label: "همه" },
  { key: "unread", label: "خوانده‌نشده" },
  { key: "read", label: "خوانده‌شده" },
  { key: "unanswered", label: "بدون پاسخ" },
  { key: "answered", label: "پاسخ داده شده" },
  { key: "mine", label: "اختصاص‌یافته به من" },
  { key: "unassigned", label: "بدون پشتیبان" },
  { key: "waiting", label: "در انتظار کاربر" },
  { key: "skipped", label: "ردشده" },
  { key: "closed", label: "بسته" },
] as const;

export function filtersFromTab(tab: string): ConversationFilters {
  switch (tab) {
    case "unread":
      return { read_state: "unread" };
    case "read":
      return { read_state: "read" };
    case "unanswered":
      return { answer_state: "unanswered", status: ["active", "waiting_user"] };
    case "answered":
      return { answer_state: "answered" };
    case "mine":
      return { assigned: "me" };
    case "unassigned":
      return { assigned: "unassigned" };
    case "waiting":
      return { status: ["waiting_user"] };
    case "skipped":
      return { status: ["skipped"] };
    case "closed":
      return { status: ["closed"] };
    default:
      return {};
  }
}

export function ConversationListPane({
  tab,
  search,
  onSearchChange,
  selectedId,
  onSelect,
  searchInputRef,
}: {
  tab: string;
  search: string;
  onSearchChange: (value: string) => void;
  selectedId: number | null;
  onSelect: (conversation: Conversation) => void;
  searchInputRef: React.RefObject<HTMLInputElement | null>;
}) {
  const [page, setPage] = useState(1);
  const [debouncedSearch, setDebouncedSearch] = useState(search);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1);
    }, 350);
    return () => clearTimeout(timer);
  }, [search]);

  const filters = useMemo(
    () => ({ ...filtersFromTab(tab), q: debouncedSearch || undefined, page, page_size: 25 }),
    [tab, debouncedSearch, page],
  );

  const { data, isLoading, isError, error, refetch } = useConversations(filters);

  const conversations = data?.items ?? [];

  return (
    <div className="flex h-full w-full flex-col border-l border-line bg-surface md:w-80 lg:w-96">
      {/* search */}
      <div className="space-y-2 border-b border-line p-3">
        <div className="relative">
          <Search className="absolute right-3 top-1/2 size-4 -translate-y-1/2 text-ink-faint" />
          <input
            ref={searchInputRef}
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="جستجو: نام، نام کاربری، متن پیام، شناسه…"
            className="input !pr-9 text-xs"
            aria-label="جستجوی گفتگوها"
          />
        </div>
        <p className="flex items-center gap-1 text-[10px] text-ink-faint">
          <Filter className="size-3" />
          فیلتر فعلی: {TABS.find((t) => t.key === tab)?.label ?? "همه"}
          {data ? ` — ${toFa(data.total)} گفتگو` : ""}
        </p>
      </div>

      {/* list */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading && <SkeletonRows rows={8} height="h-16" />}
        {isError && <ErrorState message={(error as Error).message} onRetry={() => refetch()} />}
        {!isLoading && !isError && conversations.length === 0 && (
          <EmptyState
            icon={<Inbox className="size-9" />}
            title="گفتگویی یافت نشد"
            hint="با تغییر فیلترها یا عبارت جستجو دوباره امتحان کنید."
          />
        )}
        {conversations.map((conversation: Conversation) => (
          <button
            key={conversation.id}
            onClick={() => onSelect(conversation)}
            className={`fade-in block w-full border-b border-line px-3 py-3 text-right transition-colors hover:bg-black/[0.03] dark:hover:bg-white/[0.03] ${
              selectedId === conversation.id ? "bg-brand-500/10" : ""
            }`}
          >
            <div className="mb-1 flex items-center gap-2">
              <span
                className={`truncate text-[13px] ${
                  conversation.read_state === "unread" ? "font-extrabold" : "font-semibold"
                }`}
              >
                {conversation.title}
              </span>
              {conversation.read_state === "unread" && (
                <span className="size-2 shrink-0 rounded-full bg-brand-500" title="خوانده‌نشده" />
              )}
              <span className="mr-auto shrink-0 text-[10px] text-ink-faint">
                {relativeTime(conversation.last_message_at)}
              </span>
            </div>
            <p className="mb-1.5 truncate text-[11px] text-ink-soft">
              {conversation.last_message_preview || "—"}
            </p>
            <div className="flex flex-wrap items-center gap-1">
              {conversation.answer_state === "unanswered" &&
                conversation.status !== "closed" &&
                conversation.status !== "skipped" && (
                  <Badge tone="warning">در انتظار پاسخ</Badge>
                )}
              {conversation.status === "waiting_user" && <Badge tone="info">انتظار کاربر</Badge>}
              {conversation.status === "skipped" && <Badge tone="neutral">ردشده</Badge>}
              {conversation.status === "closed" && <Badge tone="neutral">بسته</Badge>}
              {conversation.assigned_agent_id ? (
                <Badge tone="brand">{conversation.assigned_agent_name ?? "اختصاص‌یافته"}</Badge>
              ) : (
                <Badge tone="neutral">بدون پشتیبان</Badge>
              )}
              {conversation.username && (
                <span dir="ltr" className="text-[10px] text-ink-faint">
                  @{conversation.username}
                </span>
              )}
            </div>
          </button>
        ))}
      </div>

      {/* pagination */}
      {data && data.pages > 1 && (
        <div className="flex items-center justify-between border-t border-line p-2 text-xs">
          <button
            className="btn btn-ghost !py-1 text-[11px]"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
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

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ConversationListPane, TABS } from "../components/inbox/ConversationListPane";
import { ConversationPane } from "../components/conversation/ConversationPane";
import { useAuth } from "../stores/auth";
import { useConversations } from "../api/queries";

const VALID_TABS = new Set<string>(TABS.map((tab) => tab.key));

export function InboxPage() {
  const { filter, id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const tab = filter && VALID_TABS.has(filter) ? filter : "all";
  const conversationId = id ? Number(id) : null;

  const [search, setSearch] = useState("");
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const claimRef = useRef<HTMLButtonElement | null>(null);


  // keyboard shortcuts: j/k navigate, ctrl+k search, r composer, c claim
  const { data } = useConversations({ q: search || undefined, page: 1, page_size: 100 });
  const conversations = useMemo(() => data?.items ?? [], [data]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      const typing =
        target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
        return;
      }
      if (typing) return;

      if (event.key === "j" || event.key === "k") {
        event.preventDefault();
        if (conversations.length === 0) return;
        const currentIndex = conversations.findIndex((c) => c.id === conversationId);
        const delta = event.key === "j" ? 1 : -1;
        const nextIndex =
          currentIndex === -1
            ? 0
            : Math.min(conversations.length - 1, Math.max(0, currentIndex + delta));
        navigate(`/inbox/${tab}/${conversations[nextIndex].id}`);
      }
      if (event.key.toLowerCase() === "r") {
        event.preventDefault();
        composerRef.current?.focus();
      }
      if (event.key.toLowerCase() === "c") {
        claimRef.current?.click();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [conversations, conversationId, navigate, tab]);

  const canSeeInbox = user?.permissions?.some((permission) =>
    permission.startsWith("conversation.view"),
  );

  if (!canSeeInbox) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center">
        <div>
          <p className="text-sm font-bold">دسترسی به صندوق ورودی ندارید</p>
          <p className="mt-1 text-xs text-ink-faint">
            مدیر باید اکانت ایتایی به پروفایل شما متصل کند یا نقش شما را تغییر دهد.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full">
      <div className={`min-h-0 ${conversationId ? "hidden md:flex md:w-80 lg:w-96" : "flex w-full md:w-80 lg:w-96"}`}>
        <ConversationListPane
          tab={tab}
          search={search}
          onSearchChange={setSearch}
          selectedId={conversationId}
          onSelect={(conversation) => navigate(`/inbox/${tab}/${conversation.id}`)}
          searchInputRef={searchInputRef}
        />
      </div>

      {conversationId ? (
        <ConversationPane
          conversationId={conversationId}
          onBack={() => navigate(`/inbox/${tab}`)}
          onClaimedShortcut={claimRef}
        />
      ) : (
        <div className="hidden min-w-0 flex-1 items-center justify-center bg-canvas md:flex">
          <div className="text-center">
            <p className="text-sm font-bold text-ink-soft">یک گفتگو را انتخاب کنید</p>
            <p className="mt-1 text-xs text-ink-faint">
              با کلیدهای J و K بین گفتگوها جابه‌جا شوید · Ctrl+K جستجو · R پاسخ سریع
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

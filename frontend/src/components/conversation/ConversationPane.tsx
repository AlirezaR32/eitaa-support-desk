import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCheck,
  Clock,
  ExternalLink,
  Hand,
  MessageSquareOff,
  Phone,
  RotateCcw,
  SendHorizonal,
  UserRound,
  X,
} from "lucide-react";
import { api, ApiError } from "../../lib/api";
import {
  useAgents,
  useConversation,
  useMessages,
  useNotes,
  useRetryMessage,
  useSendMessage,
  useAddNote,
} from "../../api/queries";
import type { Agent, ConversationDetail, Message, Note } from "../../types";
import { useAuth } from "../../stores/auth";
import { useToast } from "../../stores/toast";
import {
  answerStateLabel,
  conversationStatusLabel,
  faDate,
  faDateTime,
  readStateLabel,
  relativeTime,
  toFa,
} from "../../lib/format";
import { Badge, EmptyState, ErrorState, SkeletonRows } from "../ui/bits";
import { Composer } from "./Composer";
import { MessageBubble, NoteBubble, NoteComposer } from "./MessageBubble";

interface TimelineItem {
  key: string;
  at: string;
  message?: Message;
  note?: Note;
}

export function ConversationPane({
  conversationId,
  onBack,
  onClaimedShortcut,
}: {
  conversationId: number;
  onBack: () => void;
  onClaimedShortcut?: React.RefObject<HTMLButtonElement | null>;
}) {
  const { user, hasPermission } = useAuth();
  const { push } = useToast();
  const queryClient = useQueryClient();

  const { data: conversation, isLoading, isError, error, refetch } = useConversation(conversationId);
  const { data: messagesData, isLoading: messagesLoading } = useMessages(conversationId);
  const { data: notes } = useNotes(conversationId);
  const { data: agents } = useAgents();
  const sendMessage = useSendMessage(conversationId);
  const retryMessage = useRetryMessage();
  const addNote = useAddNote(conversationId);

  const [replyTo, setReplyTo] = useState<Message | null>(null);
  const [showProfile, setShowProfile] = useState(true);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);

  const messages = useMemo(() => messagesData?.items ?? [], [messagesData]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, conversationId, notes?.length]);

  // mark as read when opened (server-side state change)
  useEffect(() => {
    if (conversation && conversation.read_state === "unread") {
      api(`/api/v1/conversations/${conversation.id}/read`, { method: "POST" })
        .then(() => queryClient.invalidateQueries({ queryKey: ["conversations"] }))
        .catch(() => undefined);
    }
  }, [conversation?.id, conversation?.read_state, queryClient, conversation]);

  const timeline = useMemo<TimelineItem[]>(() => {
    const items: TimelineItem[] = [
      ...messages.map((m: Message) => ({ key: `m-${m.id}`, at: m.created_at, message: m })),
      ...(notes ?? []).map((n: Note) => ({ key: `n-${n.id}`, at: n.created_at, note: n })),
    ];
    return items.sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());
  }, [messages, notes]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["conversations"] });
    queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
  };

  const act = useMutation({
    mutationFn: async ({ path, body }: { path: string; body?: unknown }) =>
      api(`/api/v1/conversations/${conversationId}/${path}`, { method: "POST", body }),
    onSuccess: () => {
      push("success", "انجام شد.");
      invalidate();
    },
    onError: (exc) => {
      push("error", exc instanceof ApiError ? exc.message : "خطا در انجام عملیات");
    },
  });

  const assign = useMutation({
    mutationFn: (agentId: number | null) =>
      api(`/api/v1/conversations/${conversationId}/assign`, {
        method: "POST",
        body: { agent_id: agentId },
      }),
    onSuccess: () => {
      push("success", "تخصیص updated.");
      invalidate();
    },
    onError: (exc) => push("error", exc instanceof ApiError ? exc.message : "خطا"),
  });

  if (isLoading) {
    return (
      <div className="flex min-w-0 flex-1 flex-col bg-canvas">
        <SkeletonRows rows={6} height="h-16" />
      </div>
    );
  }
  if (isError || !conversation) {
    return (
      <div className="flex min-w-0 flex-1 flex-col items-center justify-center bg-canvas">
        <ErrorState message={(error as Error)?.message ?? "گفتگو یافت نشد"} onRetry={() => refetch()} />
      </div>
    );
  }

  const detail = conversation as ConversationDetail;
  const isClosed = detail.status === "closed";
  const mineOrFree =
    detail.assigned_agent_id === null || detail.assigned_agent_id === user?.id;
  const canReply = hasPermission("message.send") && !isClosed && mineOrFree;
  const canTakeOver = hasPermission("conversation.assign") && !mineOrFree;

  return (
    <div className="flex min-w-0 flex-1 flex-1bg-canvas bg-canvas">
      {/* thread column */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* header */}
        <div className="flex items-center gap-2 border-b border-line bg-surface px-3 py-2.5">
          <button className="btn btn-ghost !p-1.5 md:hidden" onClick={onBack} aria-label="بازگشت">
            <ArrowRight className="size-4" />
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <p className="truncate text-sm font-extrabold">{detail.title}</p>
              <Badge tone={detail.answer_state === "unanswered" ? "warning" : "success"}>
                {answerStateLabel[detail.answer_state]}
              </Badge>
              <Badge tone="neutral">{conversationStatusLabel[detail.status]}</Badge>
            </div>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10px] text-ink-faint">
              <span>#{toFa(detail.id)}</span>
              {detail.username && (
                <span dir="ltr">
                  @{detail.username}
                </span>
              )}
              {detail.phone && <span dir="ltr">{detail.phone}</span>}
              <span>· {readStateLabel[detail.read_state]}</span>
            </p>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-1">
            {detail.deep_link && (
              <a
                className="btn btn-ghost !py-1 text-[11px]"
                href={detail.deep_link}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink className="size-3.5" />
                باز کردن در ایتا
              </a>
            )}
            {canTakeOver && (
              <button
                className="btn btn-primary !py-1 text-[11px]"
                onClick={() => assign.mutate(user!.id)}
                disabled={assign.isPending}
              >
                <Hand className="size-3.5" />
                برداشت گفتگو
              </button>
            )}
            {detail.assigned_agent_id === null && hasPermission("conversation.claim") && (
              <button
                className="btn btn-primary !py-1 text-[11px]"
                ref={onClaimedShortcut}
                onClick={() => act.mutate({ path: "claim" })}
                disabled={act.isPending}
              >
                <Hand className="size-3.5" />
                برداشت (Claim)
              </button>
            )}
            {detail.assigned_agent_id === user?.id && hasPermission("conversation.release") && (
              <button
                className="btn btn-ghost !py-1 text-[11px]"
                onClick={() => act.mutate({ path: "release" })}
                disabled={act.isPending}
              >
                رها کردن
              </button>
            )}
            {hasPermission("conversation.assign") && (
              <select
                className="input !w-auto !py-1 text-[11px]"
                value={detail.assigned_agent_id ?? ""}
                onChange={(event) =>
                  assign.mutate(event.target.value ? Number(event.target.value) : null)
                }
                aria-label="تخصیص به پشتیبان"
              >
                <option value="">— بدون پشتیبان —</option>
                {(agents?.items ?? [])
                  .filter((agent: Agent) => agent.is_active)
                  .map((agent: Agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name}
                    </option>
                  ))}
              </select>
            )}
            {detail.status === "active" && hasPermission("conversation.status.manage") && (
              <button
                className="btn btn-ghost !py-1 text-[11px]"
                onClick={() => act.mutate({ path: "waiting-user" })}
                title="در انتظار پاسخ کاربر"
              >
                <Clock className="size-3.5" />
                انتظار کاربر
              </button>
            )}
            {detail.status !== "closed" ? (
              <button
                className="btn btn-ghost !py-1 text-[11px]"
                onClick={() => act.mutate({ path: "close" })}
                disabled={act.isPending}
              >
                <X className="size-3.5" />
                بستن
              </button>
            ) : (
              <button
                className="btn btn-ghost !py-1 text-[11px]"
                onClick={() => act.mutate({ path: "reopen" })}
                disabled={act.isPending}
              >
                <RotateCcw className="size-3.5" />
                بازگشایی
              </button>
            )}
            {hasPermission("conversation.skip") && detail.status !== "skipped" && (
              <select
                className="input !w-auto !py-1 text-[11px]"
                value=""
                onChange={(event) => {
                  if (event.target.value) act.mutate({ path: "skip", body: { reason: event.target.value } });
                }}
                aria-label="رد کردن گفتگو"
              >
                <option value="">رد کردن…</option>
                <option value="spam">هرزنامه</option>
                <option value="wrong_message">پیام نامرتبط</option>
                <option value="not_relevant">مرتبط نیست</option>
                <option value="handled_elsewhere">در جای دیگر پیگیری شده</option>
                <option value="other">سایر</option>
              </select>
            )}
            <button
              className="btn btn-ghost !p-1.5 lg:hidden"
              onClick={() => setShowProfile((v) => !v)}
              aria-label="نمایش پروفایل"
            >
              <UserRound className="size-4" />
            </button>
          </div>
        </div>

        {/* timeline */}
        <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-4">
          {messagesLoading && <SkeletonRows rows={4} height="h-14" />}
          {!messagesLoading && timeline.length === 0 && (
            <EmptyState
              icon={<MessageSquareOff className="size-9" />}
              title="پیامی نیست"
              hint="اولین پیام این گفتگو پس از همگام‌سازی بعدی نمایش داده می‌شود."
            />
          )}
          {timeline.map((item) =>
            item.message ? (
              <MessageBubble
                key={item.key}
                message={item.message}
                onRetry={(message) => retryMessage.mutate(message.id)}
                onReply={setReplyTo}
              />
            ) : (
              <NoteBubble
                key={item.key}
                body={item.note!.body}
                author={item.note!.author_name}
                createdAt={item.note!.created_at}
              />
            ),
          )}
          <div ref={bottomRef} />
        </div>

        {/* notes + composer */}
        <div className="space-y-2 border-t border-line bg-surface">
          <div className="px-3 pt-2">
            <NoteComposer
              busy={addNote.isPending}
              onSubmit={async (body) => {
                try {
                  await addNote.mutateAsync(body);
                  push("success", "یادداشت ثبت شد (برای کاربر ارسال نمی‌شود).");
                } catch (exc) {
                  push("error", exc instanceof ApiError ? exc.message : "خطا در ثبت یادداشت");
                }
              }}
            />
          </div>
          <Composer
            disabled={!canReply}
            disabledReason={
              isClosed
                ? "این گفتگو بسته است — ابتدا بازگشایی کنید."
                : !mineOrFree
                  ? "این گفتگو به پشتیبان دیگری تخصیص دارد — ابتدا آن را بردارید."
                  : undefined
            }
            replyTo={replyTo}
            onCancelReply={() => setReplyTo(null)}
            sending={sendMessage.isPending}
            inputRef={composerRef}
            onSend={async (payload) => {
              try {
                const result = await sendMessage.mutateAsync({
                  text: payload.text,
                  replyTo: payload.replyTo,
                  file: payload.file,
                  asVoice: payload.asVoice,
                  durationSeconds: payload.durationSeconds,
                });
                if (result.send_status === "failed") {
                  push("error", `ارسال ناموفق: ${result.error_message ?? "خطای ایتا"}`);
                }
                setReplyTo(null);
              } catch (exc) {
                push("error", exc instanceof ApiError ? exc.message : "خطا در ارسال");
              }
            }}
          />
        </div>
      </div>

      {/* profile column */}
      {showProfile && (
        <aside className="hidden w-72 shrink-0 flex-col overflow-y-auto border-r border-line bg-surface p-4 lg:flex">
          <div className="mb-4 flex flex-col items-center text-center">
            <div className="flex size-14 items-center justify-center rounded-full bg-brand-500/15 text-lg font-extrabold text-brand-700 dark:text-brand-300">
              {detail.title.slice(0, 1)}
            </div>
            <p className="mt-2 text-sm font-bold">{detail.title}</p>
            <p className="text-[10px] text-ink-faint">
              {detail.peer_kind === "private" ? "گفتگوی خصوصی" : detail.peer_kind}
              {detail.eitaa_account_phone ? ` · اکانت ${detail.eitaa_account_phone}` : ""}
            </p>
          </div>

          <dl className="space-y-2 text-[11px]">
            <Row label="شناسه ایتا" value={detail.peer_id ? toFa(detail.peer_id) : "—"} ltr />
            <Row label="نام کاربری" value={detail.username ? `@${detail.username}` : "ندارد"} ltr />
            <Row label="شماره" value={detail.phone ?? "نامشخص"} ltr />
            <Row label="اولین پیام" value={faDate(detail.first_inbound_at)} />
            <Row label="آخرین پیام کاربر" value={relativeTime(detail.last_inbound_message_at)} />
            <Row
              label="اولین پاسخ پشتیبان"
              value={detail.first_agent_reply_at ? faDateTime(detail.first_agent_reply_at) : "هنوز پاسخی نبوده"}
            />
            <Row
              label="پشتیبان"
              value={detail.assigned_agent_name ?? (detail.assigned_agent_id ? `#${detail.assigned_agent_id}` : "بدون پشتیبان")}
            />
            <Row label="تعداد گفتگوهای این کاربر" value={toFa((detail.previous_conversations?.length ?? 0) + 1)} />
          </dl>

          {detail.deep_link && (
            <a
              className="btn btn-primary mt-4 w-full !py-2 text-xs"
              href={detail.deep_link}
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLink className="size-4" />
              باز کردن PV در ایتا
            </a>
          )}

          <div className="mt-5">
            <p className="mb-2 text-[11px] font-bold text-ink-soft">گفتگوهای قبلی این کاربر</p>
            {(detail.previous_conversations ?? []).length === 0 ? (
              <p className="text-[10px] text-ink-faint">گفتگوی دیگری ثبت نشده است.</p>
            ) : (
              <ul className="space-y-1.5">
                {detail.previous_conversations.map((previous) => (
                  <li key={previous.id}>
                    <a
                      href={`#/conversations/${previous.id}`}
                      className="flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-[11px] transition-colors hover:border-brand-400"
                      onClick={() => queryClient.invalidateQueries({ queryKey: ["conversation", previous.id] })}
                    >
                      <SendHorizonal className="size-3 text-ink-faint" />
                      <span className="flex-1 truncate">{previous.last_message_preview || "—"}</span>
                      <span className="text-[9px] text-ink-faint">{relativeTime(previous.last_message_at)}</span>
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="mt-auto pt-4">
            <p className="flex items-center gap-1.5 text-[10px] text-ink-faint">
              <CheckCheck className="size-3.5" />
              وضعیت خوانده‌شدن در پنل، سمت سرور مدیریت می‌شود.
            </p>
          </div>
        </aside>
      )}
    </div>
  );
}

function Row({ label, value, ltr }: { label: string; value: string; ltr?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-line/60 pb-1.5">
      <dt className="shrink-0 text-ink-faint">{label}</dt>
      <dd className={`truncate font-medium ${ltr ? "text-left" : ""}`} dir={ltr ? "ltr" : "auto"}>
        {value}
      </dd>
    </div>
  );
}

export { Phone };

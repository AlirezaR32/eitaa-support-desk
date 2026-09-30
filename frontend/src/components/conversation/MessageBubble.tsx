import { useState } from "react";
import {
  AlertTriangle,
  Download,
  ExternalLink,
  File as FileIcon,
  RotateCcw,
  StickyNote,
} from "lucide-react";
import type { Message } from "../../types";
import { apiUrl } from "../../lib/api";
import { faDateTime, fileSize, duration as formatDuration } from "../../lib/format";

export function MessageBubble({
  message,
  onRetry,
  onReply,
}: {
  message: Message;
  onRetry: (message: Message) => void;
  onReply: (message: Message) => void;
}) {
  const isOut = message.direction === "outbound";
  const failed = message.send_status === "failed";
  const pending = message.send_status === "pending";

  return (
    <div className={`group flex flex-col ${isOut ? "items-start" : "items-end"}`}>
      <div
        className={`fade-in max-w-[78%] rounded-2xl px-3.5 py-2.5 text-[13px] leading-6 shadow-sm ${
          isOut
            ? "rounded-tl-md bg-brand-600 text-white"
            : "rounded-tr-md bg-surface border border-line"
        } ${failed ? "!bg-red-500/90" : ""} ${pending ? "opacity-70" : ""}`}
        dir="auto"
      >
        {/* reply quote */}
        {message.reply_to_message_id && message.reply_preview && (
          <div
            className={`mb-2 rounded-lg border-r-2 px-2 py-1 text-[11px] ${
              isOut ? "border-white/50 bg-white/10 text-white/85" : "border-brand-400 bg-brand-500/5 text-ink-soft"
            }`}
          >
            <p className="line-clamp-2">در پاسخ به: {message.reply_preview}</p>
          </div>
        )}

        {/* media */}
        {message.attachment && message.attachment.kind === "photo" && (
          <img
            src={apiUrl(message.attachment.download_url ?? "")}
            alt={message.attachment.file_name ?? "تصویر"}
            loading="lazy"
            className="mb-1.5 max-h-64 rounded-xl object-cover"
          />
        )}
        {message.attachment && message.attachment.kind === "video" && (
          <video
            controls
            preload="metadata"
            className="mb-1.5 max-h-64 rounded-xl"
            src={apiUrl(message.attachment.download_url ?? "")}
          />
        )}
        {message.attachment && (message.attachment.kind === "voice" || message.attachment.kind === "audio") && (
          <div className="mb-1.5 flex items-center gap-2 rounded-xl bg-black/10 px-2.5 py-2">
            <audio
              controls
              preload="none"
              className="h-8 max-w-56"
              src={apiUrl(message.attachment.download_url ?? "")}
            />
            {message.attachment.duration_seconds ? (
              <span className={`text-[10px] ${isOut ? "text-white/80" : "text-ink-faint"}`}>
                {formatDuration(message.attachment.duration_seconds)}
              </span>
            ) : null}
          </div>
        )}
        {message.attachment && message.attachment.kind === "document" && (
          <a
            href={apiUrl(message.attachment.download_url ?? "")}
            target="_blank"
            rel="noreferrer"
            className={`mb-1.5 flex items-center gap-2 rounded-xl px-2.5 py-2 ${
              isOut ? "bg-white/10 hover:bg-white/20" : "bg-black/5 hover:bg-black/10"
            }`}
          >
            <FileIcon className="size-4 shrink-0" />
            <span className="min-w-0 flex-1 truncate text-[11px]" dir="ltr">
              {message.attachment.file_name ?? "فایل"}
            </span>
            <Download className="size-3.5 shrink-0" />
          </a>
        )}

        {message.text && <p className="whitespace-pre-wrap break-words">{message.text}</p>}

        {/* meta row */}
        <div
          className={`mt-1 flex items-center gap-1.5 text-[10px] ${
            isOut ? "text-white/70" : "text-ink-faint"
          }`}
        >
          <span>{faDateTime(message.sent_at ?? message.created_at)}</span>
          {isOut && message.source === "eitaa_app" && <span>· از خود ایتا</span>}
          {isOut && message.send_status === "sent" && <span title="ارسال شد">✓✓</span>}
          {pending && <span>در حال ارسال…</span>}
          {failed && (
            <span className="inline-flex items-center gap-1 font-bold">
              <AlertTriangle className="size-3" /> ارسال ناموفق
            </span>
          )}
        </div>
      </div>

      {/* hover actions */}
      <div className="mt-0.5 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        <button
          onClick={() => onReply(message)}
          className="text-[10px] text-ink-faint hover:text-ink"
          title="پاسخ به این پیام"
        >
          پاسخ
        </button>
        {failed && (
          <button
            onClick={() => onRetry(message)}
            className="inline-flex items-center gap-1 text-[10px] font-semibold text-red-500 hover:text-red-600"
          >
            <RotateCcw className="size-3" />
            تلاش مجدد
          </button>
        )}
        {message.error_message && (
          <span className="max-w-64 truncate text-[10px] text-red-400" title={message.error_message}>
            {message.error_message}
          </span>
        )}
        {message.attachment?.download_status === "failed" && (
          <span className="text-[10px] text-amber-500">دریافت رسانه ناموفق بود</span>
        )}
      </div>
    </div>
  );
}

export function NoteBubble({ body, author, createdAt }: { body: string; author: string | null; createdAt: string }) {
  return (
    <div className="fade-in mx-auto w-full max-w-[78%] rounded-xl border border-amber-400/40 bg-amber-400/10 px-3 py-2">
      <p className="mb-1 flex items-center gap-1.5 text-[11px] font-bold text-amber-600 dark:text-amber-400">
        <StickyNote className="size-3.5" />
        یادداشت داخلی {author ? `— ${author}` : ""}
      </p>
      <p className="whitespace-pre-wrap break-words text-[12px] leading-6 text-ink" dir="auto">
        {body}
      </p>
      <p className="mt-0.5 text-[10px] text-ink-faint">{faDateTime(createdAt)}</p>
    </div>
  );
}

export function NoteComposer({
  onSubmit,
  busy,
}: {
  onSubmit: (body: string) => Promise<void>;
  busy: boolean;
}) {
  const [body, setBody] = useState("");
  const [open, setOpen] = useState(false);

  if (!open) {
    return (
      <button className="btn btn-ghost !py-1 text-[11px]" onClick={() => setOpen(true)}>
        <StickyNote className="size-3.5" />
        یادداشت داخلی جدید
      </button>
    );
  }

  return (
    <form
      className="flex flex-col gap-2 rounded-xl border border-amber-400/50 bg-amber-400/10 p-2.5"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!body.trim()) return;
        await onSubmit(body.trim());
        setBody("");
        setOpen(false);
      }}
    >
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={3}
        className="input !border-amber-400/40 text-xs"
        placeholder="این یادداشت برای کاربر ارسال نمی‌شود…"
        dir="auto"
        autoFocus
      />
      <div className="flex justify-end gap-1.5">
        <button type="button" className="btn btn-ghost !py-1 text-[11px]" onClick={() => setOpen(false)}>
          انصراف
        </button>
        <button type="submit" className="btn btn-primary !py-1 text-[11px]" disabled={busy || !body.trim()}>
          ثبت یادداشت
        </button>
      </div>
    </form>
  );
}

export function AttachmentPreview({
  file,
  asVoice,
  onCancel,
}: {
  file: File;
  asVoice: boolean;
  onCancel: () => void;
}) {
  const [objectUrl] = useState(() => URL.createObjectURL(file));
  return (
    <div className="flex items-center gap-2 rounded-lg border border-line bg-black/5 p-2 dark:bg-white/5">
      {file.type.startsWith("image/") ? (
        <img src={objectUrl} alt={file.name} className="size-10 rounded object-cover" />
      ) : (
        <FileIcon className="size-8 text-ink-faint" />
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-[11px] font-semibold" dir="ltr">
          {file.name}
        </p>
        <p className="text-[10px] text-ink-faint">
          {asVoice ? "پیام صوتی · " : ""}
          {fileSize(file.size)}
        </p>
      </div>
      <a href={objectUrl} target="_blank" rel="noreferrer" className="text-ink-faint hover:text-ink" title="پیش‌نمایش">
        <ExternalLink className="size-3.5" />
      </a>
      <button onClick={onCancel} className="text-red-400 hover:text-red-500" title="حذف پیوست">
        ✕
      </button>
    </div>
  );
}

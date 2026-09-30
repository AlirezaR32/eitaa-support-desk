import { useEffect, useRef, useState } from "react";
import { Mic, Paperclip, Send, Square, Trash2, X } from "lucide-react";
import type { Message } from "../../types";
import { AttachmentPreview } from "./MessageBubble";
import { useCapabilities } from "../../api/queries";
import { useToast } from "../../stores/toast";

/** Message composer: text, attachments, voice recording, reply, retry (§16). */
export function Composer({
  disabled,
  disabledReason,
  replyTo,
  onCancelReply,
  onSend,
  sending,
  inputRef,
}: {
  disabled: boolean;
  disabledReason?: string;
  replyTo: Message | null;
  onCancelReply: () => void;
  onSend: (payload: {
    text: string;
    replyTo: number | null;
    file: File | null;
    asVoice: boolean;
    durationSeconds: number;
  }) => Promise<void>;
  sending: boolean;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [asVoice, setAsVoice] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordedSeconds, setRecordedSeconds] = useState(0);

  const { data: capabilities } = useCapabilities();
  const { push } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
    };
  }, []);

  const maxBytes = (capabilities?.max_upload_size_mb ?? 25) * 1024 * 1024;
  const allowed = capabilities?.allowed_extensions ?? [];

  const pickFile = (picked: File | null) => {
    if (!picked) return;
    if (picked.size > maxBytes) {
      push("error", `حجم فایل بیشتر از ${capabilities?.max_upload_size_mb ?? 25} مگابایت است.`);
      return;
    }
    const extension = picked.name.split(".").pop()?.toLowerCase() ?? "";
    if (allowed.length && !allowed.includes(extension)) {
      push("error", `فرمت .${extension} مجاز نیست.`);
      return;
    }
    setAsVoice(false);
    setFile(picked);
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      cancelledRef.current = false;
      chunksRef.current = [];
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        if (cancelledRef.current) return;
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        setRecordedSeconds(0);
        if (blob.size > 0) {
          setFile(new File([blob], `voice-${Date.now()}.webm`, { type: "audio/webm" }));
          setAsVoice(true);
        }
      };
      recorder.start();
      setRecording(true);
      setRecordedSeconds(0);
      timerRef.current = setInterval(() => setRecordedSeconds((s) => s + 1), 1000);
    } catch {
      push("error", "دسترسی به میکروفون ممکن نیست.");
    }
  };

  const stopRecording = (cancel = false) => {
    cancelledRef.current = cancel;
    if (timerRef.current) clearInterval(timerRef.current);
    recorderRef.current?.stop();
    setRecording(false);
  };

  const submit = async () => {
    if (disabled || sending) return;
    if (!text.trim() && !file) return;
    await onSend({
      text: text.trim(),
      replyTo: replyTo?.id ?? null,
      file,
      asVoice,
      durationSeconds: asVoice ? recordedSeconds || Math.round(file?.size ? 1 : 0) : 0,
    });
    setText("");
    setFile(null);
    setAsVoice(false);
  };

  return (
    <div className="border-t border-line bg-surface p-3">
      {/* reply banner */}
      {replyTo && (
        <div className="mb-2 flex items-center gap-2 rounded-lg border-r-2 border-brand-400 bg-brand-500/5 px-2.5 py-1.5">
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-bold text-brand-600 dark:text-brand-400">
              در پاسخ به {replyTo.direction === "inbound" ? "کاربر" : "پشتیبان"}
            </p>
            <p className="truncate text-[11px] text-ink-soft">{replyTo.text || "پیام پیوستی"}</p>
          </div>
          <button onClick={onCancelReply} className="text-ink-faint hover:text-ink" aria-label="لغو پاسخ">
            <X className="size-3.5" />
          </button>
        </div>
      )}

      {/* attachment preview */}
      {file && (
        <div className="mb-2">
          <AttachmentPreview
            file={file}
            asVoice={asVoice}
            onCancel={() => {
              setFile(null);
              setAsVoice(false);
            }}
          />
        </div>
      )}

      {/* disabled reason */}
      {disabled && disabledReason && (
        <p className="mb-2 rounded-lg bg-amber-500/10 px-2.5 py-1.5 text-[11px] text-amber-600 dark:text-amber-400">
          {disabledReason}
        </p>
      )}

      {/* recording bar */}
      {recording ? (
        <div className="flex items-center gap-3 rounded-xl border border-red-400/50 bg-red-500/10 px-3 py-2.5">
          <span className="size-2.5 animate-pulse rounded-full bg-red-500" />
          <span className="text-xs font-bold text-red-500">
            در حال ضبط… {Math.floor(recordedSeconds / 60)}:{String(recordedSeconds % 60).padStart(2, "0")}
          </span>
          <div className="mr-auto flex gap-1.5">
            <button onClick={() => stopRecording(true)} className="btn btn-ghost !py-1 text-[11px]">
              <Trash2 className="size-3.5" />
              حذف
            </button>
            <button onClick={() => stopRecording(false)} className="btn btn-primary !py-1 text-[11px]">
              <Square className="size-3" />
              پایان ضبط
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-end gap-2">
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            onChange={(e) => {
              pickFile(e.target.files?.[0] ?? null);
              e.target.value = "";
            }}
          />
          <button
            className="btn btn-ghost !rounded-xl !p-2.5"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || recording}
            title="پیوست فایل/تصویر"
            type="button"
          >
            <Paperclip className="size-4" />
          </button>
          <button
            className="btn btn-ghost !rounded-xl !p-2.5"
            onClick={startRecording}
            disabled={disabled || recording || file !== null}
            title="ضبط پیام صوتی"
            type="button"
          >
            <Mic className="size-4" />
          </button>
          <textarea
            ref={inputRef}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submit();
              }
            }}
            placeholder="پیام خود را بنویسید… (Enter برای ارسال، Shift+Enter خط جدید)"
            className="input max-h-36 min-h-11 flex-1 resize-y"
            dir="auto"
            disabled={disabled}
          />
          <button
            className="btn btn-primary !rounded-xl !p-2.5"
            onClick={() => void submit()}
            disabled={disabled || sending || (!text.trim() && !file)}
            title="ارسال"
            type="button"
          >
            <Send className="size-4 -scale-x-100" />
          </button>
        </div>
      )}
    </div>
  );
}

import { useEffect } from "react";
import type { ReactNode } from "react";
import { X } from "lucide-react";

/** Accessible modal dialog with backdrop + Esc handling. */
export function Modal({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`card fade-in max-h-[88vh] w-full overflow-y-auto p-5 shadow-2xl ${
          wide ? "max-w-2xl" : "max-w-md"
        }`}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-bold">{title}</h2>
          <button onClick={onClose} className="text-ink-faint hover:text-ink" aria-label="بستن">
            <X className="size-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

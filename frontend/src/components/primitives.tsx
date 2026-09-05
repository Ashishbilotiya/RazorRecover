// Shared presentational primitives. All pure / stateless. No data fetching.
// Importable from anywhere without circular-dep risk.

import { useEffect, useRef, type ReactNode } from "react";
import { getCaseStatusMeta, getActionStatusMeta } from "../badges";

// ---------------------------------------------------------------------------
// StatusBadge
// ---------------------------------------------------------------------------
interface StatusBadgeProps {
  status: string;
  kind?: "case" | "action";
  size?: "sm" | "md";
  className?: string;
}

export function StatusBadge({
  status,
  kind = "case",
  size = "md",
  className = "",
}: StatusBadgeProps) {
  const meta = kind === "action" ? getActionStatusMeta(status) : getCaseStatusMeta(status);
  const sizing =
    size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium ${meta.classes} ${sizing} ${className}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} aria-hidden />
      {meta.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// EmptyState
// ---------------------------------------------------------------------------
interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({
  title,
  description,
  action,
  className = "",
}: EmptyStateProps) {
  return (
    <div
      className={`flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center ${className}`}
    >
      <div
        aria-hidden
        className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-400"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          className="h-5 w-5"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M3 12h18M12 3v18"
          />
        </svg>
      </div>
      <p className="text-sm font-semibold text-slate-700">{title}</p>
      {description ? (
        <p className="mt-1 max-w-md text-sm text-slate-500">{description}</p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// LoadingState (skeleton)
// ---------------------------------------------------------------------------
interface SkeletonProps {
  className?: string;
}

export function Skeleton({ className = "" }: SkeletonProps) {
  return (
    <div
      className={`animate-pulse rounded-md bg-slate-200/70 ${className}`}
      aria-hidden
    />
  );
}

interface LoadingStateProps {
  rows?: number;
  variant?: "card" | "row";
  className?: string;
}

export function LoadingState({
  rows = 4,
  variant = "row",
  className = "",
}: LoadingStateProps) {
  if (variant === "card") {
    return (
      <div className={`grid gap-4 sm:grid-cols-2 xl:grid-cols-4 ${className}`}>
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full rounded-2xl" />
        ))}
      </div>
    );
  }
  return (
    <div className={`space-y-3 ${className}`}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-12 w-full rounded-lg" />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ErrorState
// ---------------------------------------------------------------------------
interface ErrorStateProps {
  message: string;
  title?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({
  message,
  title = "Couldn't load data",
  onRetry,
  className = "",
}: ErrorStateProps) {
  return (
    <div
      className={`rounded-2xl border border-rose-200 bg-rose-50 px-5 py-4 text-sm text-rose-800 ${className}`}
      role="alert"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-semibold">{title}</p>
          <p className="mt-0.5 text-rose-700">{message}</p>
        </div>
        {onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="shrink-0 rounded-md bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-700"
          >
            Retry
          </button>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StatCard
// ---------------------------------------------------------------------------
interface StatCardProps {
  label: string;
  value: string;
  hint?: string;
  accent?: "indigo" | "emerald" | "amber" | "blue";
  className?: string;
}

const ACCENT_RING: Record<NonNullable<StatCardProps["accent"]>, string> = {
  indigo: "before:bg-indigo-500",
  emerald: "before:bg-emerald-500",
  amber: "before:bg-amber-500",
  blue: "before:bg-blue-500",
};

export function StatCard({
  label,
  value,
  hint,
  accent = "indigo",
  className = "",
}: StatCardProps) {
  return (
    <div
      className={`relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-soft before:absolute before:left-0 before:top-0 before:h-full before:w-1 ${ACCENT_RING[accent]} ${className}`}
    >
      <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className="mt-2 text-3xl font-semibold tabular-nums text-slate-900">
        {value}
      </p>
      {hint ? <p className="mt-1 text-xs text-slate-500">{hint}</p> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section
// ---------------------------------------------------------------------------
interface SectionProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Section({
  title,
  subtitle,
  actions,
  children,
  className = "",
}: SectionProps) {
  return (
    <section
      className={`rounded-2xl border border-slate-200 bg-white shadow-soft ${className}`}
    >
      <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
          {subtitle ? (
            <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>
          ) : null}
        </div>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </header>
      <div className="p-5">{children}</div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Modal (centered confirm-style)
// ---------------------------------------------------------------------------
interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
}

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  size = "md",
}: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (open) {
      const previous = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = previous;
      };
    }
    return;
  }, [open]);

  if (!open) return null;

  const widthClass =
    size === "sm" ? "max-w-md" : size === "lg" ? "max-w-3xl" : "max-w-xl";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 px-4 animate-fadein"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`w-full ${widthClass} rounded-2xl bg-white shadow-2xl`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h3 className="text-base font-semibold text-slate-900">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="Close dialog"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-4 w-4"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 6l12 12M6 18L18 6"
              />
            </svg>
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer ? (
          <div className="border-t border-slate-100 bg-slate-50 px-5 py-3">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}

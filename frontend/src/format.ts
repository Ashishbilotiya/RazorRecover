// Money + time formatters. The single place that touches Intl.NumberFormat
// or Intl.DateTimeFormat. All other files import from here.

const INR_FORMAT = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

const INR_FORMAT_WITH_DECIMALS = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const INR_COMPACT = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  notation: "compact",
  maximumFractionDigits: 1,
});

const DATE_FORMAT = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const DATE_SHORT = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** Format an amount in RUPEES as a full INR string ("₹5,000"). */
export function formatINR(rupees: number): string {
  if (!Number.isFinite(rupees)) return "—";
  return INR_FORMAT.format(rupees);
}

/** Format an amount in RUPEES with 2 decimals ("₹5,000.00"). */
export function formatINRDecimal(rupees: number): string {
  if (!Number.isFinite(rupees)) return "—";
  return INR_FORMAT_WITH_DECIMALS.format(rupees);
}

/** Compact INR format ("₹1.2L", "₹4.3Cr"). Used for big metric cards. */
export function formatINRCompact(rupees: number): string {
  if (!Number.isFinite(rupees)) return "—";
  return INR_COMPACT.format(rupees);
}

/** Convert paise → rupees and format as INR. */
export function formatPaise(paise: number): string {
  if (!Number.isFinite(paise)) return "—";
  return formatINR(paise / 100);
}

/** Format a unit interval [0..1] as a percentage string ("73.4%"). */
export function formatPercent(unitInterval: number): string {
  if (!Number.isFinite(unitInterval)) return "—";
  const pct = unitInterval * 100;
  if (pct >= 100) return "100%";
  if (pct <= 0) return "0%";
  return `${pct.toFixed(1)}%`;
}

/** Format an ISO timestamp as a short date ("24 Aug, 14:32"). */
export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return DATE_FORMAT.format(d);
}

/** Format an ISO timestamp as a short date without year ("24 Aug, 14:32"). */
export function formatTimestampShort(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return DATE_SHORT.format(d);
}

/** Render a relative time ("just now", "5m ago", "2h ago", "3d ago"). */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const now = Date.now();
  const diffMs = now - d.getTime();
  const abs = Math.abs(diffMs);
  const future = diffMs < 0;
  const min = 60_000;
  const hr = 60 * min;
  const day = 24 * hr;
  let label: string;
  if (abs < 30_000) label = "just now";
  else if (abs < hr) label = `${Math.round(abs / min)}m`;
  else if (abs < day) label = `${Math.round(abs / hr)}h`;
  else if (abs < 30 * day) label = `${Math.round(abs / day)}d`;
  else label = DATE_SHORT.format(d);
  return future ? `in ${label}` : `${label} ago`;
}

/** Short id helper ("8f2c1a…"). */
export function shortId(id: string, headLen = 8): string {
  if (!id) return "";
  return id.length > headLen ? `${id.slice(0, headLen)}…` : id;
}

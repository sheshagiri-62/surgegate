// Pure seat-map logic (no React, no fetch) so it can be unit-tested.

export type SeatStatus = "available" | "held" | "sold";

export interface Seat {
  id: string;
  label: string;
  section: string;
  row: string;
  number: number;
  zone: string;
  price_paise: number;
  status: SeatStatus;
}

export interface SeatMap {
  event: {
    id: string;
    name: string;
    venue: string;
    starts_at: string;
    sale_starts_at: string;
    per_buyer_limit: number;
  };
  generated_at: string;
  seats: Seat[];
}

export interface Row {
  row: string;
  seats: Seat[];
}
export interface Section {
  section: string;
  rows: Row[];
}

const natural = new Intl.Collator("en", { numeric: true, sensitivity: "base" });

/** Group seats by section, then row, in natural order ("2" before "10"); seats by number. */
export function groupSeats(seats: Seat[]): Section[] {
  const sections = new Map<string, Map<string, Seat[]>>();
  for (const s of seats) {
    const rows = sections.get(s.section) ?? new Map<string, Seat[]>();
    rows.set(s.row, [...(rows.get(s.row) ?? []), s]);
    sections.set(s.section, rows);
  }
  return [...sections.entries()]
    .sort(([a], [b]) => natural.compare(a, b))
    .map(([section, rows]) => ({
      section,
      rows: [...rows.entries()]
        .sort(([a], [b]) => natural.compare(a, b))
        .map(([row, list]) => ({ row, seats: [...list].sort((x, y) => x.number - y.number) })),
    }));
}

/** Zones with their price, most expensive first (for the legend and colours). */
export function zones(seats: Seat[]): { zone: string; price_paise: number }[] {
  const byZone = new Map<string, number>();
  for (const s of seats) byZone.set(s.zone, s.price_paise);
  return [...byZone.entries()]
    .map(([zone, price_paise]) => ({ zone, price_paise }))
    .sort((a, b) => b.price_paise - a.price_paise);
}

/**
 * Toggle a seat in the selection. Only available seats can be picked, and never more than
 * `limit` (the server enforces the real limit; this just stops obviously invalid requests).
 */
export function toggleSeat(selected: string[], seat: Seat, limit: number): string[] {
  if (selected.includes(seat.id)) return selected.filter((id) => id !== seat.id);
  if (seat.status !== "available" || selected.length >= limit) return selected;
  return [...selected, seat.id];
}

/** Drop selected seats that someone else took meanwhile (seat map refreshed). */
export function pruneSelection(selected: string[], seats: Seat[]): string[] {
  const available = new Set(seats.filter((s) => s.status === "available").map((s) => s.id));
  return selected.filter((id) => available.has(id));
}

export function total(selected: string[], seats: Seat[]): number {
  const price = new Map(seats.map((s) => [s.id, s.price_paise]));
  return selected.reduce((sum, id) => sum + (price.get(id) ?? 0), 0);
}

export function formatInr(paise: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: paise % 100 === 0 ? 0 : 2,
  }).format(paise / 100);
}

/** "2d 03:04:05" / "04:05" countdown text; "" once the time has passed. */
export function countdown(targetIso: string, nowMs: number): string {
  const ms = Date.parse(targetIso) - nowMs;
  if (ms <= 0) return "";
  const s = Math.floor(ms / 1000);
  const d = Math.floor(s / 86400);
  const hh = String(Math.floor((s % 86400) / 3600)).padStart(2, "0");
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  if (d > 0) return `${d}d ${hh}:${mm}:${ss}`;
  return hh === "00" ? `${mm}:${ss}` : `${hh}:${mm}:${ss}`;
}

"use client";

import { formatInr, groupSeats, zones, type Seat } from "@/lib/seatmap";

const ZONE_COLOURS = [
  "bg-amber-400 hover:bg-amber-300 text-amber-950",
  "bg-sky-400 hover:bg-sky-300 text-sky-950",
  "bg-emerald-400 hover:bg-emerald-300 text-emerald-950",
];

export default function SeatPicker({
  seats,
  selected,
  onToggle,
}: {
  seats: Seat[];
  selected: string[];
  onToggle: (seat: Seat) => void;
}) {
  const legend = zones(seats);
  const colour = new Map(legend.map((z, i) => [z.zone, ZONE_COLOURS[i % ZONE_COLOURS.length]]));
  return (
    <div className="space-y-4">
      <ul className="flex flex-wrap gap-4 text-sm" aria-label="Price zones">
        {legend.map((z) => (
          <li key={z.zone} className="flex items-center gap-2">
            <span className={`inline-block h-4 w-4 rounded ${colour.get(z.zone)}`} />
            <span className="capitalize">{z.zone}</span> {formatInr(z.price_paise)}
          </li>
        ))}
        <li className="flex items-center gap-2">
          <span className="inline-block h-4 w-4 rounded bg-slate-300 dark:bg-slate-700" /> Taken
        </li>
        <li className="flex items-center gap-2">
          <span className="inline-block h-4 w-4 rounded bg-indigo-600" /> Your pick
        </li>
      </ul>
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <div className="mb-4 rounded bg-slate-200 py-1 text-center text-xs uppercase tracking-widest text-slate-600 dark:bg-slate-800 dark:text-slate-400">
          Stage
        </div>
        {groupSeats(seats).map((section) => (
          <div key={section.section} className="mb-4">
            <div className="mb-1 text-xs font-semibold text-slate-500">Section {section.section}</div>
            {section.rows.map((row) => (
              <div key={row.row} className="mb-1 flex items-center gap-1">
                <span className="w-8 shrink-0 text-right text-xs text-slate-500">{row.row}</span>
                {row.seats.map((seat) => {
                  const mine = selected.includes(seat.id);
                  const taken = seat.status !== "available";
                  const cls = mine
                    ? "bg-indigo-600 text-white"
                    : taken
                      ? "cursor-not-allowed bg-slate-300 text-slate-500 dark:bg-slate-700"
                      : colour.get(seat.zone);
                  return (
                    <button
                      key={seat.id}
                      type="button"
                      disabled={taken && !mine}
                      onClick={() => onToggle(seat)}
                      aria-pressed={mine}
                      aria-label={`Seat ${seat.label}, ${seat.zone}, ${formatInr(seat.price_paise)}${taken ? ", taken" : ""}`}
                      title={`${seat.label} · ${formatInr(seat.price_paise)}`}
                      className={`h-7 w-7 rounded text-[10px] font-medium transition-colors ${cls}`}
                    >
                      {seat.number}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

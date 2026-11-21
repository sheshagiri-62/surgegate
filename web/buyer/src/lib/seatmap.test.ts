import {
  countdown,
  formatInr,
  groupSeats,
  pruneSelection,
  toggleSeat,
  total,
  zones,
  type Seat,
} from "./seatmap";

const seat = (id: string, section: string, row: string, number: number, over: Partial<Seat> = {}): Seat => ({
  id,
  label: `${section}-${row}-${number}`,
  section,
  row,
  number,
  zone: "gold",
  price_paise: 150000,
  status: "available",
  ...over,
});

describe("groupSeats", () => {
  it("orders sections and rows naturally and seats by number", () => {
    const g = groupSeats([seat("1", "B", "1", 1), seat("2", "A", "10", 2), seat("3", "A", "2", 3), seat("4", "A", "2", 1)]);
    expect(g.map((s) => s.section)).toEqual(["A", "B"]);
    expect(g[0].rows.map((r) => r.row)).toEqual(["2", "10"]); // not "10" before "2"
    expect(g[0].rows[0].seats.map((s) => s.number)).toEqual([1, 3]);
  });
});

describe("toggleSeat", () => {
  const free = seat("a", "A", "1", 1);
  it("adds and removes an available seat", () => {
    expect(toggleSeat([], free, 4)).toEqual(["a"]);
    expect(toggleSeat(["a"], free, 4)).toEqual([]);
  });
  it("never picks a taken seat", () => {
    expect(toggleSeat([], { ...free, status: "held" }, 4)).toEqual([]);
  });
  it("stops at the per-buyer limit", () => {
    expect(toggleSeat(["x", "y"], free, 2)).toEqual(["x", "y"]);
  });
});

describe("pruneSelection", () => {
  it("drops seats that someone else took meanwhile", () => {
    const seats = [seat("a", "A", "1", 1), seat("b", "A", "1", 2, { status: "held" })];
    expect(pruneSelection(["a", "b", "gone"], seats)).toEqual(["a"]);
  });
});

describe("money and zones", () => {
  it("totals paise and formats rupees", () => {
    const seats = [seat("a", "A", "1", 1), seat("b", "A", "1", 2, { price_paise: 75050 })];
    expect(total(["a", "b"], seats)).toBe(225050);
    expect(formatInr(150000)).toBe("₹1,500");
    expect(formatInr(75050)).toBe("₹750.50");
  });
  it("lists zones most expensive first", () => {
    const z = zones([seat("a", "A", "1", 1, { zone: "silver", price_paise: 900 }), seat("b", "A", "1", 2)]);
    expect(z.map((x) => x.zone)).toEqual(["gold", "silver"]);
  });
});

describe("countdown", () => {
  const now = Date.parse("2026-11-21T10:00:00Z");
  it("formats days, hours, minutes and seconds", () => {
    expect(countdown("2026-11-23T13:04:05Z", now)).toBe("2d 03:04:05");
    expect(countdown("2026-11-21T10:09:30Z", now)).toBe("09:30");
  });
  it("is empty once the time has passed", () => {
    expect(countdown("2026-11-21T09:59:59Z", now)).toBe("");
  });
});

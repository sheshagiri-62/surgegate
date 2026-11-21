import { view, waitText, type Position, type Serving } from "./queue";

const serving = (over: Partial<Serving> = {}): Serving => ({
  event_id: "e",
  status: "open",
  serving_up_to: 100,
  admission_rate: 125,
  sale_starts_at: "2026-11-21T12:00:00Z",
  ...over,
});
const NOON = Date.parse("2026-11-21T12:00:00Z");

describe("view", () => {
  it("counts down before the sale while the place has no number", () => {
    const v = view({ status: "pre-queue" }, serving({ status: "pre-queue" }), NOON - 90_000);
    expect(v).toEqual({ phase: "before-sale", startsInMs: 90_000 });
  });

  it("waits for a number after the start (shuffle / sequencer)", () => {
    expect(view({ status: "joining" }, serving(), NOON + 1000).phase).toBe("placing");
  });

  it("shows position, people ahead and the wait from the shared counter", () => {
    const p: Position = { status: "queued", position: 600, serving_up_to: 0, queue_token: "t" };
    expect(view(p, serving({ serving_up_to: 100 }), NOON)).toEqual({
      phase: "in-line",
      position: 600,
      ahead: 499,
      etaSeconds: 4 * 60, // 500 people / 125 per minute
      paused: false,
    });
  });

  it("no estimate while paused", () => {
    const p: Position = { status: "queued", position: 600 };
    const v = view(p, serving({ status: "paused", admission_rate: 0 }), NOON);
    expect(v).toMatchObject({ phase: "in-line", paused: true, etaSeconds: null });
  });

  it("is your turn as soon as the counter reaches your number", () => {
    const p: Position = { status: "queued", position: 100 };
    expect(view(p, serving({ serving_up_to: 100 }), NOON)).toEqual({ phase: "your-turn", position: 100 });
  });

  it("never goes backwards if the cached counter is older than the position answer", () => {
    const p: Position = { status: "admitted", position: 50, serving_up_to: 60 };
    expect(view(p, serving({ serving_up_to: 40 }), NOON).phase).toBe("your-turn");
  });
});

describe("waitText", () => {
  it("formats the estimate", () => {
    expect(waitText(null)).toBe("");
    expect(waitText(60)).toBe("less than a minute");
    expect(waitText(240)).toBe("about 4 minutes");
    expect(waitText(3 * 3600 + 600)).toBe("about 3 h 10 min");
  });
});

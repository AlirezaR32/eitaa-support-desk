import { describe, expect, it } from "vitest";
import { duration, relativeTime, toFa } from "./format";

describe("toFa", () => {
  it("converts latin digits to persian digits", () => {
    expect(toFa(123)).toBe("۱۲۳");
  });
});

describe("relativeTime", () => {
  it("returns just-now for fresh timestamps", () => {
    expect(relativeTime(new Date())).toBe("همین حالا");
  });
  it("returns dash for empty", () => {
    expect(relativeTime(null)).toBe("—");
  });
});

describe("duration", () => {
  it("formats seconds", () => {
    expect(duration(45)).toContain("ثانیه");
  });
  it("formats minutes", () => {
    expect(duration(125)).toContain("۲:");
  });
});

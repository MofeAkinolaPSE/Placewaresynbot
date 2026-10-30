import { describe, expect, it } from "vitest";
import { isVoided, withoutVoided } from "./voided";

describe("voided records", () => {
  it("knows a voided document by its status, in any case", () => {
    for (const status of ["VOID", "Void", "voided", "cancelled", "CANCELLED"]) expect(isVoided({ status })).toBe(true);
    for (const status of ["POSTED", "PAID", "OPEN", "finance_approved", "REVERSED", "ACTIVE", "inactive", undefined]) expect(isVoided({ status })).toBe(false);
  });

  it("lets the server's flag win - a journal reversed on a later date stays", () => {
    expect(isVoided({ status: "REVERSED", voided: true })).toBe(true);
    expect(isVoided({ status: "REVERSED", voided: false })).toBe(false);
    expect(isVoided({ status: "POSTED", voided: true })).toBe(true); // the same-day reversal journal itself
  });

  it("takes voided rows out of an export", () => {
    const rows = [{ n: 1, status: "POSTED" }, { n: 2, status: "VOID" }, { n: 3, voided: true }, { n: 4, Status: "Void" }, { n: 5 }];
    expect(withoutVoided(rows).map((r) => r.n)).toEqual([1, 5]);
    expect(withoutVoided(undefined)).toEqual([]);
  });
});

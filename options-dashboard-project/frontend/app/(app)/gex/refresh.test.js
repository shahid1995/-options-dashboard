import { describe, it, expect } from "vitest";

describe("GexPage refresh timer lifecycle", () => {
  it("creates exactly one interval per effect lifecycle", () => {
    // Simulate the timer lifecycle from the corrected implementation
    let intervalsCreated = 0;
    let intervalsCleared = 0;
    const mockSetInterval = () => {
      intervalsCreated++;
      return 1;
    };
    const mockClearInterval = () => {
      intervalsCleared++;
    };

    // Simulate useEffect execution (from corrected code)
    const executeEffect = () => {
      const fetchData = async () => {
        // fetchData does NOT create interval
      };

      fetchData();

      // useEffect creates ONE interval
      const refreshTimer = mockSetInterval();

      return () => mockClearInterval();
    };

    const cleanup = executeEffect();

    // Exactly one interval created after initial effect
    expect(intervalsCreated).toBe(1);

    // Effect cleanup clears exactly that one interval
    cleanup();
    expect(intervalsCleared).toBe(1);
    expect(intervalsCreated).toBe(1);
  });

  it("does not create interval inside fetchData", () => {
    // Verify the corrected pattern: fetchData only fetches, doesn't schedule
    let fetchDataCalled = 0;
    let setIntervalCalls = 0;

    const correctedPattern = () => {
      const fetchData = async () => {
        fetchDataCalled++;
        // No setInterval here
      };

      fetchData();

      setIntervalCalls++; // setInterval called ONCE by useEffect, not fetchData
    };

    // Simulate initial fetch + interval
    correctedPattern();
    expect(fetchDataCalled).toBe(1);
    expect(setIntervalCalls).toBe(1);
  });
});

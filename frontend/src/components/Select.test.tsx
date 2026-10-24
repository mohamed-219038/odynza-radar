import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { Select } from "./Select";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("Select", () => {
  it("reads native <option> children and shows the chosen one", () => {
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    act(() =>
      root.render(
        <Select aria-label="Score" value={4} onChange={() => undefined}>
          {[5, 4].map((n) => (
            <option key={n} value={n}>
              {n} · score
            </option>
          ))}
          <option>pricing</option>
        </Select>,
      ),
    );
    expect(host.querySelector(".rs__single-value")?.textContent).toBe("4 · score");
    expect(host.querySelector("select")).toBeNull();
    act(() => root.unmount());
    host.remove();
  });
});

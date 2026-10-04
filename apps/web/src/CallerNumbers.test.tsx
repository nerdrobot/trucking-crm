import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "@testing-library/react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { CallerNumbers, formatPhone } from "./CallerNumbers";
afterEach(cleanup);
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute("open", "");
};
const owned = {
  selected: "+14155550100",
  numbers: [
    { phone_number: "+14155550100", status: "active", label: "Softphone" },
    { phone_number: "+13215550111", status: "active", label: "" },
    { phone_number: "+13215550199", status: "purchase_pending", label: "" },
  ],
};
const available = [
  {
    phone_number: "+13214041064",
    locality: "Titusville",
    state: "FL",
    upfront_cost: "1.00000",
    monthly_cost: "1.00000",
  },
];
function mockApi(order = vi.fn().mockResolvedValue({ status: "pending" })) {
  return vi.fn().mockImplementation(async (path: string, method?: string) => {
    if (path === "/numbers") return owned;
    if (path.startsWith("/numbers/available")) return available;
    if (path === "/numbers/order") return order(path, method);
    return { selected: "+13215550111" };
  });
}
describe("caller numbers", () => {
  it("formats US numbers", () => {
    expect(formatPhone("+13214041064")).toBe("+1 (321) 404-1064");
    expect(formatPhone("+447700900123")).toBe("+447700900123");
  });
  it("shows the number in use and switches to another active number", async () => {
    const api = mockApi();
    render(<CallerNumbers api={api} demo={false} />);
    expect(await screen.findByText("In use")).toBeVisible();
    expect(screen.getByText("purchase pending")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Use this number" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/numbers/select", "POST", {
        phone_number: "+13215550111",
      }),
    );
  });
  it("searches Florida by default and confirms the price before buying", async () => {
    const api = mockApi();
    render(<CallerNumbers api={api} demo={false} />);
    await screen.findByText("In use");
    fireEvent.change(screen.getByLabelText("Area code"), {
      target: { value: "32a1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Search/ }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/numbers/available?state=FL&area_code=321",
      ),
    );
    expect(
      await screen.findByText(/\$1\.00 now \+ \$1\.00\/month/),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Buy/ }));
    expect(
      screen.getByText(/charges \$1\.00 now and \$1\.00 per month/),
    ).toBeVisible();
    expect(api).not.toHaveBeenCalledWith(
      "/numbers/order",
      "POST",
      expect.anything(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Buy number" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/numbers/order", "POST", {
        phone_number: "+13214041064",
      }),
    );
    expect(
      await screen.findByText(/Ordered \+1 \(321\) 404-1064/),
    ).toBeVisible();
    // The ordered number is not on the account yet, so the notice stays put.
    expect(screen.queryByText(/is active/)).toBeNull();
  });
  it("keeps the dialog open and shows why an order failed", async () => {
    const api = mockApi(
      vi.fn().mockRejectedValue(new Error("Order outcome unknown")),
    );
    render(<CallerNumbers api={api} demo={false} />);
    await screen.findByText("In use");
    fireEvent.click(screen.getByRole("button", { name: /Search/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Buy/ }));
    fireEvent.click(screen.getByRole("button", { name: "Buy number" }));
    expect(
      await screen.findAllByText("Order outcome unknown"),
    ).not.toHaveLength(0);
    expect(screen.getByRole("dialog")).toBeVisible();
  });
  it("explains that demo purchases are simulated", async () => {
    render(<CallerNumbers api={mockApi()} demo />);
    await screen.findByText("In use");
    fireEvent.click(screen.getByRole("button", { name: /Search/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Buy/ }));
    expect(screen.getByText(/nothing is charged/)).toBeVisible();
  });
  it("re-checks pending numbers until Telnyx activates them", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let status = "purchase_pending";
    const api = vi.fn().mockImplementation(async () => ({
      selected: "+14155550100",
      numbers: [
        { phone_number: "+14155550100", status: "active", label: "" },
        { phone_number: "+13862457453", status, label: "" },
      ],
    }));
    render(<CallerNumbers api={api} demo={false} />);
    expect(await screen.findByText("purchase pending")).toBeVisible();
    status = "active";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(
      await screen.findByRole("button", { name: "Use this number" }),
    ).toBeVisible();
    const calls = api.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(api.mock.calls.length).toBe(calls);
    vi.useRealTimers();
  });
});

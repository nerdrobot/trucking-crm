import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MyLeads, LogCallForm, dayBounds } from "./Queue";
import { type Lead, type QueueData } from "./api";
afterEach(cleanup);
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute("open", "");
};
const lead: Lead = {
  id: "lead",
  name: "Alex Carrier",
  phone: "+13125550123",
  email: "",
  kind: "owner_operator",
  status: "active",
  stage: "contacted",
  follow_up_at: "2020-01-01T14:00:00+00:00",
  last_outcome: "no_answer",
  last_activity_at: new Date().toISOString(),
  agent_id: "agent",
  timezone: "UTC",
  consent_sms: true,
  consent_voice: true,
  consent_note: "Form consent",
  created_at: "2026-10-01T10:00:00Z",
};
const queue: QueueData = {
  items: [lead],
  counts: { today: 1, untouched: 3, followups: 1, in_progress: 2, closed: 0 },
  summary: {
    assigned_today: 2,
    called_today: 1,
    calls_today: 4,
    untouched: 3,
    follow_ups_due: 1,
  },
};
function mockApi() {
  return vi.fn().mockImplementation(async (path: string) => {
    if (path.startsWith("/queue")) return queue;
    if (path === "/leads/lead")
      return {
        lead,
        jobs: [],
        enrollment: null,
        activities: [
          {
            id: "a1",
            channel: "call",
            direction: "outbound",
            text: "Call logged: No answer",
            status: "no_answer",
            created_at: "2026-10-01T10:00:00Z",
          },
        ],
      };
    return {};
  });
}
describe("my leads queue", () => {
  it("shows today's numbers, tab counts and overdue follow-ups", async () => {
    const api = mockApi();
    render(<MyLeads api={api} onOpen={vi.fn()} />);
    expect(await screen.findByText("Alex Carrier")).toBeVisible();
    expect(screen.getByText(/called today \(4 calls\)/)).toBeVisible();
    expect(screen.getByRole("tab", { name: /Untouched/ })).toHaveTextContent(
      "Untouched3",
    );
    expect(screen.getByText("No answer")).toBeVisible();
    expect(document.querySelector(".follow-up.overdue")).not.toBeNull();
    expect(api.mock.calls[0][0]).toMatch(
      /^\/queue\?tab=today&since=.+&until=.+/,
    );
    fireEvent.click(screen.getByRole("tab", { name: /Follow ups/ }));
    await waitFor(() =>
      expect(api.mock.calls.at(-1)?.[0]).toMatch(/^\/queue\?tab=followups/),
    );
  });
  it("expands a row to show the lead's history in place", async () => {
    render(<MyLeads api={mockApi()} onOpen={vi.fn()} />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: /Alex Carrier/,
        expanded: false,
      }),
    );
    expect(await screen.findByText("Call logged: No answer")).toBeVisible();
  });
  it("logs a call from the queue and reloads it", async () => {
    const api = mockApi();
    render(<MyLeads api={api} onOpen={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Log call/ }));
    fireEvent.click(screen.getByLabelText("Interested"));
    fireEvent.change(screen.getByLabelText("Note"), {
      target: { value: "Pre-approved" },
    });
    fireEvent.submit(screen.getByRole("dialog").querySelector("form")!);
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/leads/lead/log-call", "POST", {
        outcome: "interested",
        note: "Pre-approved",
      }),
    );
  });
});
describe("log call form", () => {
  it("requires a time for call backs and hides it for closing outcomes", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<LogCallForm lead={lead} onSubmit={onSubmit} onClose={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("Call back"));
    expect(screen.getByLabelText("Call back at")).toBeRequired();
    fireEvent.change(screen.getByLabelText("Call back at"), {
      target: { value: "2030-01-02T09:30" },
    });
    fireEvent.submit(document.querySelector("form")!);
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        outcome: "call_back",
        follow_up_at: new Date("2030-01-02T09:30").toISOString(),
      }),
    );
    fireEvent.click(screen.getByLabelText("Wrong number"));
    expect(screen.getByText(/closes the lead/)).toBeVisible();
    expect(screen.queryByLabelText("Next follow-up")).toBeNull();
  });
  it("keeps the dialog content and shows server errors", async () => {
    const onClose = vi.fn();
    render(
      <LogCallForm
        lead={lead}
        onSubmit={vi.fn().mockRejectedValue(new Error("Lead opted out"))}
        onClose={onClose}
      />,
    );
    fireEvent.submit(document.querySelector("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Lead opted out",
    );
    expect(onClose).not.toHaveBeenCalled();
  });
  it("uses the agent's local day for today", () => {
    const { since, until } = dayBounds(new Date(2026, 9, 3, 15, 30));
    expect(new Date(since).getHours()).toBe(0);
    expect(new Date(until).getTime() - new Date(since).getTime()).toBe(
      86400000,
    );
  });
});

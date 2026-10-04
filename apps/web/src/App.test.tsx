import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import App from "./App";
import { request } from "./api";
vi.mock("./api", async () => ({
  ...(await vi.importActual("./api")),
  request: vi.fn(),
}));
afterEach(cleanup);
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute("open", "");
};
const lead = {
  id: "lead1",
  name: "Alex Carrier",
  phone: "+13125550123",
  email: "",
  kind: "owner_operator",
  status: "new",
  agent_id: "admin",
  timezone: "UTC",
  consent_sms: false,
  consent_voice: false,
  consent_note: "",
  created_at: "2026-09-21T10:00:00Z",
};
beforeEach(() => {
  vi.mocked(request).mockImplementation(async (path) => {
    if (path === "/me")
      return {
        user: { id: "admin", name: "Pilot Admin", role: "admin" },
        mode: "demo",
        sms_ready: true,
        voice_ready: true,
      };
    if (path === "/agents") return [{ id: "admin", name: "Pilot Admin" }];
    if (path.startsWith("/leads?")) return { items: [lead], total: 1 };
    if (path === "/dashboard")
      return {
        total_leads: 1,
        active_followups: 0,
        due_today: 0,
        needs_attention: 0,
        sent_today: 0,
        paused: 0,
      };
    if (path === "/sequences") return [];
    if (path === "/settings")
      return {
        automation_enabled: true,
        daily_sms_limit: 10,
        daily_call_limit: 2,
        contact_start_hour: 0,
        contact_end_hour: 24,
        mode: "demo",
      };
    if (path === "/leads/import") return { created: 1, errors: [] };
    if (path === "/leads/lead1")
      return { lead, activities: [], jobs: [], enrollment: null };
    return {};
  });
});
async function login() {
  render(<App />);
  fireEvent.change(screen.getByLabelText("Personal access key"), {
    target: { value: "session-key" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Open workspace" }));
  await screen.findByText("Good to see you, Pilot.");
  await screen.findByRole("button", { name: "Open Alex Carrier" });
}
describe("workspace navigation", () => {
  it("loads real API metrics, navigates leads and signs out", async () => {
    await login();
    expect(screen.getByText("DEMO · NO REAL SENDS")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Open Alex Carrier" }));
    await screen.findByText("Contact permissions");
    fireEvent.click(screen.getByRole("button", { name: "Edit lead" }));
    expect(screen.getByLabelText(/Phone/)).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Contact name"), {
      target: { value: "Alex Updated" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(request).toHaveBeenCalledWith(
        "/leads/lead1",
        "session-key",
        "PATCH",
        expect.not.objectContaining({ phone: expect.anything() }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "All leads" }));
    fireEvent.click(screen.getByRole("button", { name: "Sequences" }));
    expect(await screen.findByText("No sequences yet")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Automation" }));
    expect(await screen.findByText("Workspace readiness")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(
      screen.getByRole("button", { name: "Open workspace" }),
    ).toBeVisible();
    expect(screen.getByLabelText("Personal access key")).toHaveValue("");
  });
  it("imports CSV and shows row results", async () => {
    await login();
    fireEvent.click(screen.getByRole("button", { name: "Import CSV" }));
    fireEvent.change(screen.getByLabelText("CSV contents"), {
      target: { value: "name,phone\nTaylor,+15555550123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import leads" }));
    expect(await screen.findByText("1 leads imported.")).toBeVisible();
    expect(request).toHaveBeenCalledWith(
      "/leads/import",
      "session-key",
      "POST",
      { csv: "name,phone\nTaylor,+15555550123" },
    );
  });
  it("reports an invalid access key without entering the workspace", async () => {
    vi.mocked(request).mockRejectedValue(new Error("Invalid credentials"));
    render(<App />);
    fireEvent.change(screen.getByLabelText("Personal access key"), {
      target: { value: "bad-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open workspace" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid credentials",
    );
    expect(screen.queryByText("DEMO · NO REAL SENDS")).not.toBeInTheDocument();
  });
});
it("assigns new leads to the current agent and hides administrator controls", async () => {
  const previous = vi.mocked(request).getMockImplementation()!;
  vi.mocked(request).mockImplementation(async (path, ...rest) => {
    if (path === "/me")
      return {
        user: { id: "agent", name: "Taylor Agent", role: "agent" },
        mode: "demo",
        sms_ready: true,
        voice_ready: true,
      };
    if (path === "/agents")
      return [
        { id: "admin", name: "Pilot Admin" },
        { id: "agent", name: "Taylor Agent" },
      ];
    return previous(path, ...rest);
  });
  render(<App />);
  fireEvent.change(screen.getByLabelText("Personal access key"), {
    target: { value: "agent-key" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Open workspace" }));
  // Agents land on their call queue; the full lead list is one click away.
  await screen.findByRole("heading", { name: "My leads" });
  fireEvent.click(screen.getByRole("button", { name: "Leads" }));
  await screen.findByRole("button", { name: "Open Alex Carrier" });
  expect(
    screen.queryByRole("button", { name: "Automation" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Add lead" }));
  expect(screen.getByLabelText("Assigned dispatcher")).toHaveValue("agent");
  expect(
    screen.queryByRole("option", { name: "Pilot Admin" }),
  ).not.toBeInTheDocument();
});

import { describe, it, expect, vi, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  cleanup,
  waitFor,
} from "@testing-library/react";
import { LeadForm } from "./LeadForm";
afterEach(cleanup);
describe("Lead consent workflow", () => {
  const agents = [{ id: "agent-1", name: "Alex Agent" }];
  function fill() {
    fireEvent.change(screen.getByLabelText("Contact name"), {
      target: { value: "Jamie Carrier" },
    });
    fireEvent.change(screen.getByLabelText(/Phone/), {
      target: { value: "+13125550123" },
    });
  }
  it("requires explicit consent evidence before enabling outreach", async () => {
    const save = vi.fn();
    render(<LeadForm agents={agents} onSave={save} onClose={() => {}} />);
    fill();
    fireEvent.click(screen.getByLabelText("Lead has agreed to SMS follow-ups"));
    fireEvent.click(screen.getByRole("button", { name: "Add lead" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Record where and when",
    );
    expect(save).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Consent record"), {
      target: { value: "Website form 2026-09-21, SMS permission" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add lead" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Jamie Carrier",
          consent_sms: true,
          consent_voice: false,
          agent_id: "agent-1",
        }),
      ),
    );
  });
  it("preserves data and displays backend validation errors", async () => {
    const save = vi.fn().mockRejectedValue(new Error("Lead already exists"));
    render(<LeadForm agents={agents} onSave={save} onClose={() => {}} />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Add lead" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Lead already exists",
    );
    expect(screen.getByLabelText("Contact name")).toHaveValue("Jamie Carrier");
  });
  it("rejects a domestic phone number before any request", async () => {
    const save = vi.fn();
    render(<LeadForm agents={agents} onSave={save} onClose={() => {}} />);
    fill();
    fireEvent.change(screen.getByLabelText(/Phone/), {
      target: { value: "3125550123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add lead" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "international phone",
    );
    expect(save).not.toHaveBeenCalled();
  });
});

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Channels, type ChannelView } from "./Channels";
afterEach(cleanup);
const view: ChannelView = {
  sms_enabled: false,
  voice_enabled: true,
  messaging_profile_id: "",
  connection_id: "voice",
  assistant_id: "ai-1",
  sms_ready: false,
  voice_ready: true,
  messaging_profiles: [{ id: "profile-1", name: "Pilot texts" }],
  voice_apps: [{ id: "voice", name: "Pilot calls" }],
  assistants: [{ id: "ai-1", name: "Lead follow-up" }],
};
describe("channel settings", () => {
  it("shows current choices and saves switches with selected resources", async () => {
    const onSaved = vi.fn();
    const api = vi
      .fn()
      .mockImplementation(async (_path: string, method?: string) =>
        method === "PUT"
          ? { ...view, sms_enabled: true, sms_ready: true }
          : view,
      );
    render(<Channels api={api} onSaved={onSaved} />);
    const texts = await screen.findByLabelText(/Text messages/);
    expect(texts).not.toBeChecked();
    expect(screen.getByLabelText("Messaging profile")).toBeDisabled();
    expect(screen.getByLabelText("Voice app")).toHaveValue("voice");
    fireEvent.click(texts);
    fireEvent.change(screen.getByLabelText("Messaging profile"), {
      target: { value: "profile-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save channels" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/channels", "PUT", {
        sms_enabled: true,
        voice_enabled: true,
        messaging_profile_id: "profile-1",
        connection_id: "voice",
        assistant_id: "ai-1",
        email_enabled: false,
        email_from: "",
        email_from_name: "",
      }),
    );
    expect(await screen.findByText("Channels saved.")).toBeVisible();
    expect(onSaved).toHaveBeenCalled();
  });
  it("keeps an unlisted current value visible and reports save errors", async () => {
    const api = vi
      .fn()
      .mockImplementation(async (_p: string, method?: string) => {
        if (method === "PUT")
          throw new Error("Choose a voice app before turning calls on");
        return { ...view, connection_id: "env-app" };
      });
    render(<Channels api={api} onSaved={vi.fn()} />);
    expect(await screen.findByText("env-app (current)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save channels" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Choose a voice app",
    );
  });
});

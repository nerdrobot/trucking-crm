import { afterEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { DialerProvider, useDialer } from "./Dialer";
import { type Lead, type Session } from "./api";
afterEach(cleanup);
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute("open", "");
};

// A stand-in for the Telnyx SDK: records the client so tests can push call events.
const sdk = vi.hoisted(() => ({
  client: null as null | {
    options: { login_token: string };
    handlers: Record<string, (payload: unknown) => void>;
  },
}));
vi.mock("@telnyx/webrtc", () => ({
  TelnyxRTC: class {
    handlers: Record<string, (payload: unknown) => void> = {};
    remoteElement = "";
    options: { login_token: string };
    constructor(options: { login_token: string }) {
      this.options = options;
      sdk.client = this;
    }
    on(event: string, handler: (payload: unknown) => void) {
      this.handlers[event] = handler;
    }
    async connect() {
      this.handlers["telnyx.ready"]?.({});
    }
    async disconnect() {}
  },
}));

const lead: Lead = {
  id: "lead",
  name: "Alex Carrier",
  company: "Garden State Haulers LLC",
  phone: "+13125550123",
  email: "",
  kind: "fleet",
  status: "active",
  agent_id: "admin",
  timezone: "UTC",
  consent_sms: true,
  consent_voice: true,
  consent_note: "Form consent",
  created_at: "2026-10-01T10:00:00Z",
};
const session = (mode: "demo" | "live", browser_ready = true): Session => ({
  user: { id: "admin", name: "Admin", role: "admin" },
  mode,
  sms_ready: false,
  voice_ready: false,
  browser_ready,
});
function CallButton() {
  const dialer = useDialer();
  if (!dialer) return <p>No dialer</p>;
  return (
    <button disabled={!dialer.ready} onClick={() => dialer.callLead(lead)}>
      Call in browser
    </button>
  );
}
function setup(mode: "demo" | "live", browser_ready = true) {
  const api = vi.fn(async (path: string) =>
    path === "/webrtc/token" ? { login_token: "jwt" } : {},
  );
  const onChanged = vi.fn();
  render(
    <DialerProvider
      api={api as never}
      session={session(mode, browser_ready)}
      onChanged={onChanged}
    >
      <CallButton />
    </DialerProvider>,
  );
  return { api, onChanged };
}
const rtcCall = (state: string) => ({
  id: "call-1",
  state,
  direction: "inbound",
  options: { remoteCallerNumber: "+13125550123" },
  answer: vi.fn(async () => {}),
  hangup: vi.fn(async () => {}),
  toggleAudioMute: vi.fn(),
  dtmf: vi.fn(),
});
const notify = (call: ReturnType<typeof rtcCall>) =>
  act(() =>
    sdk.client!.handlers["telnyx.notification"]({ type: "callUpdate", call }),
  );

describe("browser dialer", () => {
  it("hides the dialer when browser calling is not configured", () => {
    setup("live", false);
    expect(screen.getByText("No dialer")).toBeVisible();
  });

  it("simulates the call in demo mode and asks for an outcome", async () => {
    const { api } = setup("demo");
    fireEvent.click(screen.getByRole("button", { name: "Call in browser" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/leads/lead/connect", "POST", {
        via: "browser",
      }),
    );
    expect(await screen.findByText("Log this call")).toBeVisible();
    expect(api).not.toHaveBeenCalledWith("/webrtc/token");
  });

  it("signs in, answers its own call leg, and logs the call after hang-up", async () => {
    const { api, onChanged } = setup("live");
    const button = await screen.findByRole("button", {
      name: "Call in browser",
    });
    await waitFor(() => expect(button).toBeEnabled());
    expect(sdk.client!.options.login_token).toBe("jwt");
    fireEvent.click(button);
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/leads/lead/connect", "POST", {
        via: "browser",
      }),
    );
    const ringing = rtcCall("ringing");
    notify(ringing);
    expect(ringing.answer).toHaveBeenCalled();
    const active = rtcCall("active");
    notify(active);
    expect(screen.getByText("Garden State Haulers LLC")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Mute" }));
    expect(active.toggleAudioMute).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Unmute" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Keypad" }));
    fireEvent.click(screen.getByRole("button", { name: "5" }));
    expect(active.dtmf).toHaveBeenCalledWith("5");
    notify(rtcCall("hangup"));
    expect(await screen.findByText("Log this call")).toBeVisible();
    expect(onChanged).toHaveBeenCalled();
  });

  it("lets the dispatcher answer or decline an unexpected incoming call", async () => {
    setup("live");
    await waitFor(() =>
      expect(sdk.client?.handlers["telnyx.notification"]).toBeTruthy(),
    );
    const ringing = rtcCall("ringing");
    notify(ringing);
    expect(ringing.answer).not.toHaveBeenCalled();
    expect(screen.getByText("Incoming call")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(ringing.hangup).toHaveBeenCalled();
  });
});

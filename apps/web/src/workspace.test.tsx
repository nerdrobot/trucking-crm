import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { LeadDetail } from "./LeadDetail";
import { Sequences } from "./Sequences";
import { Settings } from "./Settings";
import { type Detail, type Session } from "./api";
afterEach(cleanup);
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute("open", "");
};
const session: Session = {
  user: { id: "agent", name: "Agent", role: "admin" },
  mode: "demo",
  sms_ready: true,
  voice_ready: true,
};
const sequences = [
  {
    id: "seq",
    name: "First contact",
    steps: [
      { channel: "sms" as const, message: "Hi {{name}}", delay_minutes: 0 },
    ],
    created_at: "2026-09-21T10:00:00Z",
  },
];
const detail: Detail = {
  lead: {
    id: "lead",
    name: "Alex Carrier",
    phone: "+13125550123",
    email: "",
    kind: "owner_operator",
    status: "active",
    agent_id: "agent",
    timezone: "UTC",
    consent_sms: true,
    consent_voice: true,
    consent_note: "Form consent",
    created_at: "2026-09-21T10:00:00Z",
  },
  activities: [
    {
      id: "activity",
      channel: "sms",
      direction: "inbound",
      text: "Hello",
      status: "received",
      created_at: "2026-09-21T10:00:00Z",
    },
  ],
  jobs: [
    {
      id: "job",
      channel: "sms",
      message: "Follow up",
      due_at: "2026-09-22T10:00:00Z",
      status: "pending",
    },
  ],
  enrollment: { id: "enrollment", status: "active", sequence_id: "seq" },
};
function showDetail(
  action = vi.fn().mockResolvedValue(undefined),
  data = detail,
  send = vi.fn().mockResolvedValue(undefined),
  active = session,
) {
  render(
    <LeadDetail
      detail={data}
      sequences={sequences}
      agents={[session.user]}
      session={active}
      onBack={vi.fn()}
      onEdit={vi.fn()}
      action={action}
      send={send}
    />,
  );
  return action;
}
describe("lead outreach controls", () => {
  it("requires confirmation and submits the selected sequence", async () => {
    const action = showDetail();
    fireEvent.click(screen.getByRole("button", { name: "Schedule follow-up" }));
    fireEvent.submit(screen.getByRole("dialog").querySelector("form")!);
    await waitFor(() =>
      expect(action).toHaveBeenCalledWith("enroll", { sequence_id: "seq" }),
    );
  });
  it("sends typed messages and reports errors without closing the compose dialog", async () => {
    const action = showDetail(
      vi.fn().mockRejectedValue(new Error("Daily budget reached")),
    );
    fireEvent.click(screen.getByRole("button", { name: "Send SMS" }));
    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "Hi Alex" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Daily budget reached",
    );
    expect(action).toHaveBeenCalledWith("message", { text: "Hi Alex" });
  });
  it("explains demo call behavior before starting", async () => {
    const action = showDetail();
    fireEvent.click(screen.getByRole("button", { name: "AI call" }));
    expect(screen.getByText(/No real number will be contacted/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Start call" }));
    await waitFor(() => expect(action).toHaveBeenCalledWith("call", {}));
  });
  it("records demo replies through the backend", async () => {
    const action = showDetail();
    fireEvent.click(screen.getByRole("button", { name: "Simulate reply" }));
    fireEvent.change(screen.getByLabelText("Lead reply"), {
      target: { value: "STOP" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Record demo reply" }));
    await waitFor(() =>
      expect(action).toHaveBeenCalledWith("demo-reply", { text: "STOP" }),
    );
  });
  it("disables communication for opted-out leads", () => {
    showDetail(undefined, {
      ...detail,
      lead: { ...detail.lead, status: "opted_out" },
    });
    expect(screen.getByRole("button", { name: "Send SMS" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "AI call" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Schedule follow-up" }),
    ).toBeDisabled();
  });
  it("resumes a paused lead", async () => {
    const action = showDetail(undefined, {
      ...detail,
      lead: { ...detail.lead, status: "paused" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    await waitFor(() =>
      expect(action).toHaveBeenCalledWith("resume", undefined),
    );
  });
  it("confirms completion", async () => {
    const action = showDetail();
    fireEvent.click(screen.getByRole("button", { name: "Complete" }));
    fireEvent.click(screen.getByRole("button", { name: "Complete lead" }));
    await waitFor(() => expect(action).toHaveBeenCalledWith("complete", {}));
  });
});
describe("automation administration", () => {
  it("creates a new sequence version and leaves the original intact", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<Sequences sequences={sequences} onSave={onSave} admin />);
    fireEvent.click(
      screen.getByRole("button", { name: "Create updated version" }),
    );
    fireEvent.change(screen.getByLabelText("Sequence name"), {
      target: { value: "New version" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save sequence" }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        name: "New version",
        steps: sequences[0].steps,
      }),
    );
    expect(sequences[0].name).toBe("First contact");
  });
  it("hides sequence authoring for agents", () => {
    render(<Sequences sequences={sequences} onSave={vi.fn()} admin={false} />);
    expect(
      screen.queryByRole("button", { name: "New sequence" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Create updated version" }),
    ).not.toBeInTheDocument();
  });
  it("saves bounded settings and processes due steps", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const run = vi.fn().mockResolvedValue({});
    render(
      <Settings
        settings={{
          automation_enabled: true,
          daily_sms_limit: 10,
          daily_call_limit: 2,
          contact_start_hour: 9,
          contact_end_hour: 18,
          mode: "demo",
        }}
        session={session}
        onSave={save}
        onRun={run}
      />,
    );
    fireEvent.change(screen.getByLabelText("Daily SMS limit"), {
      target: { value: "5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(
        expect.objectContaining({ daily_sms_limit: 5 }),
      ),
    );
    await screen.findByText("Settings saved.");
    fireEvent.click(screen.getByRole("button", { name: "Run due follow-ups" }));
    await waitFor(() => expect(run).toHaveBeenCalled());
  });
});
it("builds a multi-channel sequence and retains input after a server failure", async () => {
  const save = vi.fn().mockRejectedValue(new Error("Could not save sequence"));
  render(<Sequences sequences={[]} onSave={save} admin />);
  fireEvent.click(screen.getByRole("button", { name: "New sequence" }));
  fireEvent.change(screen.getByLabelText("Sequence name"), {
    target: { value: "Carrier introduction" },
  });
  fireEvent.change(screen.getByLabelText("Message"), {
    target: { value: "Hello {{name}}" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Add step" }));
  fireEvent.change(screen.getAllByLabelText("Channel")[1], {
    target: { value: "voice" },
  });
  fireEvent.change(
    screen.getAllByLabelText("Wait after previous step (minutes)")[1],
    { target: { value: "60" } },
  );
  fireEvent.change(screen.getByLabelText("Call context"), {
    target: { value: "Ask about preferred viewing time" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save sequence" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not save sequence",
  );
  expect(save).toHaveBeenCalledWith({
    name: "Carrier introduction",
    steps: [
      { channel: "sms", delay_minutes: 0, message: "Hello {{name}}" },
      {
        channel: "voice",
        delay_minutes: 60,
        message: "Ask about preferred viewing time",
      },
    ],
  });
  fireEvent.click(screen.getByRole("button", { name: "Remove step 2" }));
  expect(screen.queryByLabelText("Call context")).not.toBeInTheDocument();
});
describe("lead pipeline, tasks and agent-first calls", () => {
  it("changes the pipeline stage through the lead endpoint", async () => {
    const send = vi.fn().mockResolvedValue(undefined);
    showDetail(undefined, detail, send);
    fireEvent.change(screen.getByLabelText("Pipeline stage"), {
      target: { value: "interested" },
    });
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith("/leads/lead", "PATCH", {
        stage: "interested",
      }),
    );
  });
  it("adds a task with an optional due time and completes open tasks", async () => {
    const send = vi.fn().mockResolvedValue(undefined);
    const action = showDetail(
      undefined,
      {
        ...detail,
        tasks: [
          {
            id: "task",
            lead_id: "lead",
            title: "Call back at 3pm",
            due_at: "2020-01-01T10:00:00+00:00",
            status: "open",
            source: "call_outcome",
            created_at: "2020-01-01T10:00:00+00:00",
          },
        ],
      },
      send,
    );
    expect(screen.getByText("Overdue")).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: "Complete task: Call back at 3pm" }),
    );
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith("/tasks/task", "PATCH", {
        status: "done",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Add task/ }));
    fireEvent.change(screen.getByLabelText("Task"), {
      target: { value: "Send rate sheet" },
    });
    fireEvent.submit(screen.getByRole("dialog").querySelector("form")!);
    await waitFor(() =>
      expect(action).toHaveBeenCalledWith("tasks", {
        title: "Send rate sheet",
      }),
    );
  });
  it("offers agent-first calling only when the agent's phone is configured", async () => {
    const action = showDetail();
    expect(
      screen.getByRole("button", { name: /Call me first/ }),
    ).toBeDisabled();
    cleanup();
    const ready = showDetail(undefined, detail, undefined, {
      ...session,
      bridge_ready: true,
    });
    fireEvent.click(screen.getByRole("button", { name: /Call me first/ }));
    expect(screen.getByText(/No real call is placed/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Call my phone" }));
    await waitFor(() => expect(ready).toHaveBeenCalledWith("connect", {}));
    expect(action).not.toHaveBeenCalled();
  });
});
describe("email", () => {
  it("sends an email only when the lead and channel allow it", async () => {
    const action = showDetail();
    expect(screen.getByRole("button", { name: /Send email/ })).toBeDisabled();
    cleanup();
    const ready = showDetail(
      undefined,
      {
        ...detail,
        lead: {
          ...detail.lead,
          email: "alex@example.com",
          consent_email: true,
        },
      },
      undefined,
      { ...session, email_ready: true },
    );
    fireEvent.click(screen.getByRole("button", { name: /Send email/ }));
    fireEvent.change(screen.getByLabelText("Subject"), {
      target: { value: "Homes near you" },
    });
    fireEvent.change(screen.getByLabelText("Email message"), {
      target: { value: "Three loads this week" },
    });
    fireEvent.submit(screen.getByRole("dialog").querySelector("form")!);
    await waitFor(() =>
      expect(ready).toHaveBeenCalledWith("email", {
        subject: "Homes near you",
        text: "Three loads this week",
      }),
    );
    expect(action).not.toHaveBeenCalled();
  });
});

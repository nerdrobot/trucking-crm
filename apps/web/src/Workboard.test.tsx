import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Tasks } from "./Workboard";
import { type Task } from "./api";
afterEach(cleanup);
const task: Task = {
  id: "task",
  lead_id: "lead",
  title: "Reply to text: Can you call me?",
  due_at: "2999-01-01T10:00:00+00:00",
  status: "open",
  source: "reply",
  created_at: "2026-10-01T10:00:00+00:00",
  lead_name: "Alex Carrier",
};
describe("tasks page", () => {
  it("lists open tasks, completes them and opens the lead", async () => {
    const api = vi
      .fn()
      .mockImplementation(async (path: string) =>
        path.startsWith("/tasks?") ? [task] : {},
      );
    const onOpen = vi.fn();
    render(<Tasks api={api} onOpen={onOpen} />);
    expect(await screen.findByText(task.title)).toBeVisible();
    expect(screen.getByText(/Text reply/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Alex Carrier" }));
    expect(onOpen).toHaveBeenCalledWith("lead");
    fireEvent.click(
      screen.getByRole("button", { name: `Complete task: ${task.title}` }),
    );
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/tasks/task", "PATCH", {
        status: "done",
      }),
    );
    fireEvent.change(screen.getByLabelText("Filter tasks"), {
      target: { value: "done" },
    });
    await waitFor(() => expect(api).toHaveBeenCalledWith("/tasks?status=done"));
  });
  it("shows an empty state and tolerates a malformed response", async () => {
    render(<Tasks api={vi.fn().mockResolvedValue({})} onOpen={vi.fn()} />);
    expect(await screen.findByText("All caught up")).toBeVisible();
  });
});

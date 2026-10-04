import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Templates } from "./Templates";
afterEach(cleanup);
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute("open", "");
};
const template = {
  id: "t1",
  name: "Dispatch intro",
  channel: "email" as const,
  subject: "Just listed",
  body: "Hi {{first_name}}",
  updated_at: "2026-10-03T10:00:00Z",
};
describe("templates page", () => {
  it("opens a template and lets admins delete it", async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    render(
      <Templates
        templates={[template]}
        admin
        onSave={vi.fn()}
        onDelete={onDelete}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit template" }));
    fireEvent.click(screen.getByRole("button", { name: /Delete/ }));
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith("t1"));
  });
  it("hides editing for agents", () => {
    render(
      <Templates
        templates={[template]}
        admin={false}
        onSave={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /New template/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit template" })).toBeNull();
  });
});

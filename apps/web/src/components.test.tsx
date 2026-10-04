import { it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { Modal, Loading, Empty, Notice } from "./components";
afterEach(cleanup);
it("opens a modal and provides explicit and Escape dismissal", () => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  const close = vi.fn();
  render(
    <Modal title="Edit contact" onClose={close}>
      <p>Contact form</p>
    </Modal>,
  );
  expect(screen.getByRole("dialog")).toHaveAttribute("open");
  fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
  expect(close).toHaveBeenCalledOnce();
  fireEvent(
    screen.getByRole("dialog"),
    new Event("cancel", { bubbles: false }),
  );
  expect(close).toHaveBeenCalledTimes(2);
});
it("distinguishes loading, empty and error states", () => {
  render(
    <>
      <Loading />
      <Empty title="No leads">Add a contact</Empty>
      <Notice error>Service unavailable</Notice>
    </>,
  );
  expect(screen.getByText(/Loading your workspace/)).toBeVisible();
  expect(screen.getByRole("heading", { name: "No leads" })).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent("Service unavailable");
});

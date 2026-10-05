import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ClipComments from "./ClipComments";
import { api } from "../../services/api";

vi.mock("../../services/api", () => ({
  api: { get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
vi.mock("../../contexts/AuthContext", () => ({
  useAuth: () => ({ user: { user_id: 7 } }),
}));
const comment = {
  id: 12,
  user_id: 7,
  author: "Diver",
  body: "Great dive!",
  created_at: "2026-10-05T10:00:00Z",
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
beforeEach(() => {
  vi.resetAllMocks();
});
it.each([false, true])(
  "keeps a successful post when an older initial read resolves (snapshot includes post: %s)",
  async (includesPost) => {
    const read = deferred<{
      data: { items: (typeof comment)[]; next_before: null };
    }>();
    vi.mocked(api.get).mockReturnValueOnce(read.promise);
    vi.mocked(api.post).mockResolvedValueOnce({ data: comment });
    const onCountChange = vi.fn();
    render(<ClipComments id={1} onCountChange={onCountChange} />);
    fireEvent.change(screen.getByLabelText("Join the discussion"), {
      target: { value: comment.body },
    });
    fireEvent.click(screen.getByRole("button", { name: "Post comment" }));
    expect(await screen.findByText(comment.body)).toBeInTheDocument();
    await act(async () =>
      read.resolve({
        data: { items: includesPost ? [comment] : [], next_before: null },
      }),
    );
    expect(screen.getAllByText(comment.body)).toHaveLength(1);
    expect(onCountChange).toHaveBeenCalledTimes(1);
    expect(onCountChange).toHaveBeenCalledWith(1);
    expect(screen.getByLabelText("Join the discussion")).toHaveValue("");
  },
);
it("does not resurrect a deleted comment from a delayed pagination snapshot", async () => {
  const read = deferred<{
    data: { items: (typeof comment)[]; next_before: null };
  }>();
  vi.mocked(api.get)
    .mockResolvedValueOnce({ data: { items: [comment], next_before: 12 } })
    .mockReturnValueOnce(read.promise);
  vi.mocked(api.delete).mockResolvedValueOnce({});
  const onCountChange = vi.fn();
  render(<ClipComments id={1} onCountChange={onCountChange} />);
  await screen.findByText(comment.body);
  fireEvent.click(screen.getByRole("button", { name: "Older comments" }));
  await act(async () =>
    fireEvent.click(
      screen.getByRole("button", { name: "Delete comment by Diver" }),
    ),
  );
  expect(screen.queryByText(comment.body)).not.toBeInTheDocument();
  await act(async () =>
    read.resolve({ data: { items: [comment], next_before: null } }),
  );
  expect(screen.queryByText(comment.body)).not.toBeInTheDocument();
  expect(onCountChange).toHaveBeenCalledTimes(1);
  expect(onCountChange).toHaveBeenCalledWith(-1);
});

it("likes a comment and posts a reply inside its thread", async () => {
  vi.mocked(api.get)
    .mockResolvedValueOnce({ data: { items: [{ ...comment, liked: false, like_count: 0, reply_count: 0 }], next_before: null } })
    .mockResolvedValueOnce({ data: { items: [], next_before: null } });
  vi.mocked(api.put).mockResolvedValueOnce({ data: { ...comment, liked: true, like_count: 1, reply_count: 0 } });
  vi.mocked(api.post).mockResolvedValueOnce({ data: { ...comment, id: 13, body: "Thanks!", parent_id: 12 } });
  const onCountChange = vi.fn();
  render(<ClipComments id={1} onCountChange={onCountChange} />);
  await screen.findByText(comment.body);
  fireEvent.click(screen.getByRole("button", { name: "Like comment by Diver" }));
  await screen.findByRole("button", { name: "Like comment by Diver", pressed: true });
  expect(api.put).toHaveBeenCalledWith('/api/v1/dives/1/comments/12/like', { liked: true });
  fireEvent.click(screen.getByRole("button", { name: "Reply" }));
  await act(async () => {});
  fireEvent.change(screen.getByLabelText("Reply to Diver"), { target: { value: "Thanks!" } });
  fireEvent.click(screen.getByRole("button", { name: "Post reply to Diver" }));
  expect(await screen.findByText("Thanks!")).toBeInTheDocument();
  expect(api.post).toHaveBeenCalledWith('/api/v1/dives/1/comments', { body: "Thanks!", parent_id: 12 });
  expect(onCountChange).toHaveBeenCalledWith(1);
});

it("preserves a failed reply draft for retry", async () => {
  vi.mocked(api.get).mockResolvedValue({ data: { items: [comment], next_before: null } });
  vi.mocked(api.post).mockRejectedValueOnce(new Error('offline'));
  render(<ClipComments id={1} onCountChange={vi.fn()} />);
  await screen.findByText(comment.body);
  fireEvent.click(screen.getByRole("button", { name: "Reply" }));
  await act(async () => {});
  fireEvent.change(screen.getByLabelText("Reply to Diver"), { target: { value: "My reply" } });
  fireEvent.click(screen.getByRole("button", { name: "Post reply to Diver" }));
  await screen.findByRole('alert');
  expect(screen.getByLabelText("Reply to Diver")).toHaveValue("My reply");
});

it("preserves a newer reply count when a delayed root like completes", async () => {
  const root = { ...comment, reply_count: 1, liked: false, like_count: 0 };
  const reply = { ...comment, id: 13, author: "Reply author", body: "Thanks!", parent_id: root.id };
  const reaction = deferred<{ data: typeof root }>();
  vi.mocked(api.get)
    .mockResolvedValueOnce({ data: { items: [root], next_before: null } })
    .mockResolvedValueOnce({ data: { items: [reply], next_before: null } });
  vi.mocked(api.put).mockReturnValueOnce(reaction.promise);
  vi.mocked(api.delete).mockResolvedValue({});
  const onCountChange = vi.fn();
  render(<ClipComments id={1} onCountChange={onCountChange} />);
  fireEvent.click(await screen.findByRole("button", { name: "View replies (1)" }));
  await screen.findByText(reply.body);
  fireEvent.click(screen.getByRole("button", { name: "Like comment by Diver" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete comment by Reply author" }));
  await act(async () => {});
  expect(screen.queryByText(reply.body)).not.toBeInTheDocument();
  await act(async () => reaction.resolve({ data: { ...root, liked: true, like_count: 1 } }));
  expect(screen.queryByRole("button", { name: "Hide replies" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Delete comment by Diver" }));
  await act(async () => {});
  expect(onCountChange.mock.calls).toEqual([[-1], [-1]]);
});

it("opens and loads replies only after a pending like finishes", async () => {
  const root = { ...comment, reply_count: 1, liked: false, like_count: 0 };
  const reply = { ...comment, id: 13, author: "Reply author", body: "Existing reply", parent_id: root.id };
  const reaction = deferred<{ data: typeof root }>();
  vi.mocked(api.get)
    .mockResolvedValueOnce({ data: { items: [root], next_before: null } })
    .mockResolvedValueOnce({ data: { items: [reply], next_before: null } });
  vi.mocked(api.put).mockReturnValueOnce(reaction.promise);
  render(<ClipComments id={1} onCountChange={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Like comment by Diver" }));
  const replyButton = screen.getByRole("button", { name: "Reply" });
  const toggle = screen.getByRole("button", { name: "View replies (1)" });
  expect(replyButton).toBeDisabled();
  expect(toggle).toBeDisabled();
  fireEvent.click(replyButton);
  fireEvent.click(toggle);
  expect(api.get).toHaveBeenCalledTimes(1);
  expect(replyButton).toHaveAttribute("aria-expanded", "false");
  await act(async () => reaction.resolve({ data: { ...root, liked: true, like_count: 1 } }));
  expect(replyButton).toBeEnabled();
  fireEvent.click(replyButton);
  expect(await screen.findByText(reply.body)).toBeInTheDocument();
  expect(api.get).toHaveBeenLastCalledWith('/api/v1/dives/1/comments', { params: { parent_id: root.id, before: undefined } });
});

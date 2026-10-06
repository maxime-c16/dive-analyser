import { createRef } from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import ImmersiveControls from "./ImmersiveControls";
class Pointer extends MouseEvent {
  isPrimary = true;
  pointerId = 1;
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("PointerEvent", Pointer);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
function setup(
  rate = 0.5,
  drag: {
    dragEnabled?: boolean;
    onDragUpdate?: (dy: number) => void;
    onDragEnd?: (result: { dy: number; velocity: number; cancelled: boolean }) => void;
  } = {},
) {
  const video = document.createElement("video");
  video.playbackRate = rate;
  const videoRef = createRef<HTMLVideoElement>();
  Object.assign(videoRef, { current: video });
  const onLike = vi.fn(),
    onNavigate = vi.fn();
  const play = vi.spyOn(video, "play"),
    pause = vi.spyOn(video, "pause");
  const view = render(
    <ImmersiveControls
      videoRef={videoRef}
      playbackRate={rate}
      onLike={onLike}
      onNavigate={onNavigate}
      dragEnabled={drag.dragEnabled}
      onDragUpdate={drag.onDragUpdate}
      onDragEnd={drag.onDragEnd}
    />,
  );
  const surface = screen.getByRole("button", { name: "Play video" });
  const down = (x = 100, y = 100) =>
    fireEvent.pointerDown(surface, { clientX: x, clientY: y, button: 0 });
  const move = (x = 100, y = 100) =>
    fireEvent.pointerMove(surface, { clientX: x, clientY: y });
  const up = (x = 100, y = 100) =>
    fireEvent.pointerUp(surface, { clientX: x, clientY: y });
  return { ...view, video, surface, onLike, onNavigate, play, pause, down, move, up };
}
it("single tap plays after the double-tap window; double tap likes without changing playback", () => {
  const t = setup();
  t.down();
  t.up();
  act(() => vi.advanceTimersByTime(270));
  expect(t.play).toHaveBeenCalledOnce();
  t.play.mockClear();
  t.down();
  t.up();
  t.down();
  t.up();
  act(() => vi.advanceTimersByTime(270));
  expect(t.onLike).toHaveBeenCalledOnce();
  expect(t.play).not.toHaveBeenCalled();
});
it("hold restores the selected speed on release, cancel and unmount without toggling playback", () => {
  const t = setup(0.75);
  t.down();
  act(() => vi.advanceTimersByTime(350));
  expect(t.video.playbackRate).toBe(2);
  t.up();
  expect(t.video.playbackRate).toBe(0.75);
  t.down();
  act(() => vi.advanceTimersByTime(350));
  fireEvent.pointerCancel(t.surface);
  expect(t.video.playbackRate).toBe(0.75);
  t.down();
  act(() => vi.advanceTimersByTime(350));
  t.unmount();
  expect(t.video.playbackRate).toBe(0.75);
  act(() => vi.advanceTimersByTime(300));
  expect(t.play).not.toHaveBeenCalled();
  expect(t.onLike).not.toHaveBeenCalled();
});
it("vertical swipes navigate once and horizontal drags do not pause", () => {
  const t = setup();
  t.down(100, 300);
  fireEvent.pointerMove(t.surface, { clientX: 100, clientY: 120 });
  t.up(100, 120);
  expect(t.onNavigate).toHaveBeenLastCalledWith(1);
  t.down(100, 100);
  t.up(100, 300);
  expect(t.onNavigate).toHaveBeenLastCalledWith(-1);
  t.down(100, 100);
  fireEvent.pointerMove(t.surface, { clientX: 300, clientY: 100 });
  t.up(300, 100);
  act(() => vi.advanceTimersByTime(300));
  expect(t.onNavigate).toHaveBeenCalledTimes(2);
  expect(t.play).not.toHaveBeenCalled();
});
it("keyboard activation plays and rejected autoplay remains actionable", async () => {
  const t = setup();
  t.play.mockRejectedValueOnce(new Error("NotAllowedError"));
  await act(async () => fireEvent.click(t.surface, { detail: 0 }));
  expect(t.play).toHaveBeenCalledOnce();
  expect(
    screen.getByRole("button", { name: "Play video" }),
  ).toBeInTheDocument();
});
it("a vertical drag reports finger travel and suppresses swipe navigation", () => {
  const onDragUpdate = vi.fn();
  const onDragEnd = vi.fn();
  const t = setup(0.5, { dragEnabled: true, onDragUpdate, onDragEnd });
  t.down(100, 300);
  t.move(100, 250);
  t.move(100, 200);
  expect(onDragUpdate).toHaveBeenLastCalledWith(-100);
  expect(onDragUpdate.mock.calls.length).toBeGreaterThan(1);
  t.up(100, 200);
  expect(onDragEnd).toHaveBeenCalledTimes(1);
  const result = onDragEnd.mock.calls[0][0];
  expect(result.dy).toBe(-100);
  expect(result.cancelled).toBe(false);
  expect(t.onNavigate).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(300));
  expect(t.play).not.toHaveBeenCalled();
  expect(t.onLike).not.toHaveBeenCalled();
});
it("horizontal drift never engages the pager", () => {
  const onDragUpdate = vi.fn();
  const onDragEnd = vi.fn();
  const t = setup(0.5, { dragEnabled: true, onDragUpdate, onDragEnd });
  t.down(100, 100);
  fireEvent.pointerMove(t.surface, { clientX: 300, clientY: 110 });
  t.up(300, 110);
  expect(onDragUpdate).not.toHaveBeenCalled();
  expect(onDragEnd).not.toHaveBeenCalled();
  expect(t.onNavigate).not.toHaveBeenCalled();
});
it("cancelling mid-drag reports a cancelled end for spring-back", () => {
  const onDragUpdate = vi.fn();
  const onDragEnd = vi.fn();
  const t = setup(0.5, { dragEnabled: true, onDragUpdate, onDragEnd });
  t.down(100, 300);
  t.move(100, 200);
  expect(onDragUpdate).toHaveBeenCalled();
  fireEvent.pointerCancel(t.surface);
  expect(onDragEnd).toHaveBeenCalledTimes(1);
  expect(onDragEnd.mock.calls[0][0]).toMatchObject({ dy: -100, velocity: 0, cancelled: true });
  expect(t.onNavigate).not.toHaveBeenCalled();
});
it("taps still toggle playback while drag mode is enabled", () => {
  const onDragUpdate = vi.fn();
  const onDragEnd = vi.fn();
  const t = setup(0.5, { dragEnabled: true, onDragUpdate, onDragEnd });
  t.down();
  t.up();
  act(() => vi.advanceTimersByTime(270));
  expect(t.play).toHaveBeenCalledOnce();
  expect(onDragUpdate).not.toHaveBeenCalled();
  expect(onDragEnd).not.toHaveBeenCalled();
});

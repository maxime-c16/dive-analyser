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
function setup(rate = 0.5) {
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
    />,
  );
  const surface = screen.getByRole("button", { name: "Play video" });
  const down = (x = 100, y = 100) =>
    fireEvent.pointerDown(surface, { clientX: x, clientY: y, button: 0 });
  const up = (x = 100, y = 100) =>
    fireEvent.pointerUp(surface, { clientX: x, clientY: y });
  return { ...view, video, surface, onLike, onNavigate, play, pause, down, up };
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

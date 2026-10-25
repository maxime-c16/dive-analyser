import { createRef } from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import ImmersiveControls from "./ImmersiveControls";
class Pointer extends MouseEvent {
  isPrimary: boolean;
  pointerId: number;
  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.isPrimary = init.isPrimary ?? true;
    this.pointerId = init.pointerId ?? 1;
  }
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
    onPinchStart?: () => void;
    onPinchUpdate?: (ratio: number) => void;
    onPinchEnd?: (cancelled: boolean) => void;
  } = {},
  hud: {
    onHudPauseChange?: (paused: boolean) => void;
    onHudPressChange?: (pressing: boolean) => void;
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
      onPinchStart={drag.onPinchStart}
      onPinchUpdate={drag.onPinchUpdate}
      onPinchEnd={drag.onPinchEnd}
      onHudPauseChange={hud.onHudPauseChange}
      onHudPressChange={hud.onHudPressChange}
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

// Two fingers: finger 1 is the primary pointer, finger 2 a secondary one.
const finger = (id: number, x: number, y: number) => ({
  pointerId: id,
  isPrimary: id === 1,
  clientX: x,
  clientY: y,
  button: 0,
});
it("a pinch reports live span ratios and ends once, without tap, like or drag side effects", () => {
  const onDragEnd = vi.fn();
  const onPinchStart = vi.fn();
  const onPinchUpdate = vi.fn();
  const onPinchEnd = vi.fn();
  const t = setup(0.5, {
    dragEnabled: true,
    onDragEnd,
    onPinchStart,
    onPinchUpdate,
    onPinchEnd,
  });
  fireEvent.pointerDown(t.surface, finger(1, 100, 300));
  fireEvent.pointerDown(t.surface, finger(2, 300, 300));
  expect(onPinchStart).toHaveBeenCalledOnce();
  fireEvent.pointerMove(t.surface, finger(2, 250, 300));
  expect(onPinchUpdate).toHaveBeenLastCalledWith(0.75);
  fireEvent.pointerMove(t.surface, finger(2, 400, 300));
  expect(onPinchUpdate).toHaveBeenLastCalledWith(1.5);
  expect(onPinchEnd).not.toHaveBeenCalled();
  fireEvent.pointerUp(t.surface, finger(2, 400, 300));
  expect(onPinchEnd).toHaveBeenCalledOnce();
  expect(onPinchEnd).toHaveBeenCalledWith(false);
  fireEvent.pointerUp(t.surface, finger(1, 100, 300));
  expect(onPinchEnd).toHaveBeenCalledOnce();
  expect(onPinchStart).toHaveBeenCalledOnce();
  act(() => vi.advanceTimersByTime(400));
  expect(t.play).not.toHaveBeenCalled();
  expect(t.onLike).not.toHaveBeenCalled();
  expect(t.onNavigate).not.toHaveBeenCalled();
  expect(onDragEnd).not.toHaveBeenCalled();
});
it("a cancelled pinch ends as cancelled", () => {
  const onPinchEnd = vi.fn();
  const t = setup(0.5, { onPinchEnd });
  fireEvent.pointerDown(t.surface, finger(1, 100, 300));
  fireEvent.pointerDown(t.surface, finger(2, 300, 300));
  fireEvent.pointerCancel(t.surface, finger(2, 300, 300));
  expect(onPinchEnd).toHaveBeenCalledOnce();
  expect(onPinchEnd).toHaveBeenCalledWith(true);
});
it("a second finger landing mid-drag cancels the feed drag instead of paging", () => {
  const onDragUpdate = vi.fn();
  const onDragEnd = vi.fn();
  const t = setup(0.5, { dragEnabled: true, onDragUpdate, onDragEnd });
  fireEvent.pointerDown(t.surface, finger(1, 100, 300));
  fireEvent.pointerMove(t.surface, finger(1, 100, 200));
  expect(onDragUpdate).toHaveBeenCalled();
  fireEvent.pointerDown(t.surface, finger(2, 300, 200));
  expect(onDragEnd).toHaveBeenCalledOnce();
  expect(onDragEnd.mock.calls[0][0]).toMatchObject({ cancelled: true });
  onDragUpdate.mockClear();
  fireEvent.pointerMove(t.surface, finger(1, 100, 100));
  expect(onDragUpdate).not.toHaveBeenCalled();
  fireEvent.pointerUp(t.surface, finger(2, 300, 200));
  fireEvent.pointerUp(t.surface, finger(1, 100, 100));
  expect(onDragEnd).toHaveBeenCalledOnce();
  expect(t.onNavigate).not.toHaveBeenCalled();
});
it("a normal one-finger tap still works after a pinch ended", () => {
  const t = setup();
  fireEvent.pointerDown(t.surface, finger(1, 100, 300));
  fireEvent.pointerDown(t.surface, finger(2, 300, 300));
  fireEvent.pointerUp(t.surface, finger(2, 300, 300));
  fireEvent.pointerUp(t.surface, finger(1, 100, 300));
  t.down();
  t.up();
  act(() => vi.advanceTimersByTime(270));
  expect(t.play).toHaveBeenCalledOnce();
});

// ---- Auto-hiding HUD signals ----

it("announces the element's initial paused state once, then every real change", () => {
  const onHudPauseChange = vi.fn();
  const t = setup(0.5, {}, { onHudPauseChange });
  // jsdom media elements start paused: the parent holds its HUD up right
  // away, which also covers autoplay-blocked and still-loading elements.
  expect(onHudPauseChange).toHaveBeenCalledTimes(1);
  expect(onHudPauseChange).toHaveBeenCalledWith(true);
  // Playback starts while the element is paused=false: announced once.
  Object.defineProperty(t.video, "paused", {
    configurable: true,
    get: () => false,
  });
  fireEvent.play(t.video);
  expect(onHudPauseChange).toHaveBeenLastCalledWith(false);
  // Repeated events with an unchanged state stay silent.
  fireEvent.play(t.video);
  expect(onHudPauseChange).toHaveBeenCalledTimes(2);
  // Pausing again flips the announcement back.
  Object.defineProperty(t.video, "paused", {
    configurable: true,
    get: () => true,
  });
  fireEvent.pause(t.video);
  expect(onHudPauseChange).toHaveBeenLastCalledWith(true);
  expect(onHudPauseChange).toHaveBeenCalledTimes(3);
});

it("a sustained press announces itself once and releases on pointer up", () => {
  const onHudPressChange = vi.fn();
  const t = setup(0.5, {}, { onHudPressChange });
  expect(onHudPressChange).not.toHaveBeenCalled();
  t.down();
  act(() => vi.advanceTimersByTime(350));
  expect(onHudPressChange).toHaveBeenCalledTimes(1);
  expect(onHudPressChange).toHaveBeenLastCalledWith(true);
  t.up();
  expect(onHudPressChange).toHaveBeenCalledTimes(2);
  expect(onHudPressChange).toHaveBeenLastCalledWith(false);
  // A subsequent tap that never reaches the hold threshold stays silent.
  t.down();
  t.up();
  expect(onHudPressChange).toHaveBeenCalledTimes(2);
});

it("movement, cancellation and unmount during a hold release the press", () => {
  const onHudPressChange = vi.fn();
  const t = setup(0.5, {}, { onHudPressChange });
  t.down();
  act(() => vi.advanceTimersByTime(350));
  // More than 12px of travel cancels the hold: the press ends too.
  fireEvent.pointerMove(t.surface, { clientX: 100, clientY: 130 });
  expect(onHudPressChange).toHaveBeenLastCalledWith(false);
  // A cancelled finger releases the press as well.
  t.down();
  act(() => vi.advanceTimersByTime(350));
  fireEvent.pointerCancel(t.surface);
  expect(onHudPressChange).toHaveBeenLastCalledWith(false);
  // Unmounting mid-press must not strand the parent in a dismissed HUD.
  const calls = onHudPressChange.mock.calls.length;
  t.down();
  act(() => vi.advanceTimersByTime(350));
  t.unmount();
  expect(onHudPressChange).toHaveBeenCalledTimes(calls + 2);
  expect(onHudPressChange).toHaveBeenLastCalledWith(false);
});

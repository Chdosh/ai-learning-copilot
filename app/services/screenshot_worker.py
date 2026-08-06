from __future__ import annotations

import ctypes
import math
import sys
import time
from datetime import datetime
from pathlib import Path


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _selection_to_physical(
    start: tuple[int, int],
    end: tuple[int, int],
    canvas_size: tuple[int, int],
    bounds: dict[str, int],
) -> tuple[int, int, int, int]:
    canvas_width = max(1, int(canvas_size[0]))
    canvas_height = max(1, int(canvas_size[1]))
    scale_x = int(bounds["width"]) / canvas_width
    scale_y = int(bounds["height"]) / canvas_height

    logical_x1 = max(0, min(canvas_width, min(start[0], end[0])))
    logical_y1 = max(0, min(canvas_height, min(start[1], end[1])))
    logical_x2 = max(0, min(canvas_width, max(start[0], end[0])))
    logical_y2 = max(0, min(canvas_height, max(start[1], end[1])))

    physical_x1 = math.floor(logical_x1 * scale_x)
    physical_y1 = math.floor(logical_y1 * scale_y)
    physical_x2 = math.ceil(logical_x2 * scale_x)
    physical_y2 = math.ceil(logical_y2 * scale_y)
    return (
        int(bounds["left"]) + physical_x1,
        int(bounds["top"]) + physical_y1,
        physical_x2 - physical_x1,
        physical_y2 - physical_y1,
    )


def _wait_for_overlay_removal() -> None:
    if sys.platform == "win32":
        try:
            if ctypes.windll.dwmapi.DwmFlush() == 0:
                return
        except Exception:
            pass
    time.sleep(0.03)


def select_region(bounds: dict[str, int]) -> tuple[int, int, int, int] | None:
    import tkinter as tk

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.38)
    root.configure(cursor="crosshair", bg="black")
    width = int(bounds["width"])
    height = int(bounds["height"])
    left = int(bounds["left"])
    top = int(bounds["top"])
    root.geometry(f"{width}x{height}{left:+d}{top:+d}")

    canvas = tk.Canvas(root, highlightthickness=0, bg="black")
    canvas.pack(fill="both", expand=True)
    state = {
        "start_x": 0,
        "start_y": 0,
        "dragging": False,
        "rect_id": None,
        "size_id": None,
        "result": None,
        "pending_drag": None,
        "drag_update_scheduled": False,
        "cancelling": False,
    }

    def update_selection(x: int, y: int) -> None:
        x1 = min(int(state["start_x"]), x)
        y1 = min(int(state["start_y"]), y)
        x2 = max(int(state["start_x"]), x)
        y2 = max(int(state["start_y"]), y)
        canvas_width = canvas.winfo_width()
        canvas_height = canvas.winfo_height()
        canvas.coords(state["rect_id"], x1, y1, x2, y2)

        selection_width = max(0, x2 - x1)
        selection_height = max(0, y2 - y1)
        label_x = min(x1 + 8, max(8, canvas_width - 130))
        label_y = y2 + 16 if y2 + 28 < canvas_height else max(16, y1 - 14)
        canvas.coords(state["size_id"], label_x, label_y)
        canvas.itemconfigure(
            state["size_id"], text=f"{selection_width} × {selection_height}"
        )
    def flush_drag_update() -> None:
        state["drag_update_scheduled"] = False
        pending_drag = state["pending_drag"]
        if state["dragging"] and pending_drag is not None:
            update_selection(*pending_drag)

    def on_press(event) -> None:
        state["start_x"] = event.x
        state["start_y"] = event.y
        state["dragging"] = True
        state["rect_id"] = canvas.create_rectangle(
            event.x,
            event.y,
            event.x,
            event.y,
            outline="#1689ff",
            width=2,
        )
        state["size_id"] = canvas.create_text(
            event.x + 8,
            event.y + 16,
            anchor="w",
            fill="white",
            font=("Segoe UI", 10, "bold"),
        )
        update_selection(event.x, event.y)

    def on_drag(event) -> None:
        if state["dragging"] and state["rect_id"]:
            state["pending_drag"] = (event.x, event.y)
            if not state["drag_update_scheduled"]:
                state["drag_update_scheduled"] = True
                root.after(16, flush_drag_update)

    def on_release(event) -> None:
        if not state["dragging"]:
            return
        state["dragging"] = False
        region = _selection_to_physical(
            (int(state["start_x"]), int(state["start_y"])),
            (event.x, event.y),
            (canvas.winfo_width(), canvas.winfo_height()),
            bounds,
        )
        if region[2] >= 8 and region[3] >= 8:
            state["result"] = region
        root.destroy()

    def on_cancel_press(_event):
        state["cancelling"] = True
        state["dragging"] = False
        canvas.grab_set()
        return "break"

    def on_cancel_release(_event):
        if not state["cancelling"]:
            return "break"
        state["cancelling"] = False
        try:
            canvas.grab_release()
        except tk.TclError:
            pass
        root.after_idle(root.destroy)
        return "break"

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    canvas.bind("<ButtonPress-3>", on_cancel_press)
    canvas.bind("<ButtonRelease-3>", on_cancel_release)
    root.bind("<Escape>", lambda _event: root.destroy())
    root.update_idletasks()
    root.after(0, root.focus_force)
    root.mainloop()
    return state["result"]


def run(screenshots_dir: str | Path) -> str | None:
    import mss
    from mss.tools import to_png

    _enable_dpi_awareness()
    with mss.MSS() as screen_capture:
        bounds = {
            key: int(value)
            for key, value in screen_capture.monitors[0].items()
            if key in {"left", "top", "width", "height"}
        }

    region = select_region(bounds)
    if region is None:
        return None

    target_dir = Path(screenshots_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output_path = target_dir / f"capture-{timestamp}.png"
    left, top, width, height = region
    _wait_for_overlay_removal()
    with mss.MSS() as screen_capture:
        shot = screen_capture.grab(
            {"left": left, "top": top, "width": width, "height": height}
        )
        to_png(shot.rgb, shot.size, output=str(output_path))
    return str(output_path)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("缺少截图保存目录。", file=sys.stderr)
        return 2
    try:
        output_path = run(args[0])
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if output_path:
        print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

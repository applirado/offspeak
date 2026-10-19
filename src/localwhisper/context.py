import threading

from localwhisper import winapi


def selected_text(timeout: float = 0.5) -> str:
    """Read the focused control's selection through UI Automation, without sending keystrokes."""
    result: list[str] = []

    def worker():
        try:
            import uiautomation as auto

            with auto.UIAutomationInitializerInThread():
                control = auto.GetFocusedControl()
                pattern = control.GetPattern(auto.PatternId.TextPattern) if control else None
                if pattern:
                    ranges = pattern.GetSelection()
                    result.append("".join(r.GetText(-1) for r in ranges))
        except Exception:
            pass

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    return result[0] if result else ""


def matches_app(app: dict, activation_apps: list[str]) -> bool:
    name = (app.get("name") or "").lower()
    if not name:
        return False
    for entry in activation_apps:
        e = entry.lower().removesuffix(".exe")
        # entries may be exe names or packaged-app ids like "vendor.app_hash!appid"
        if e == name or e.endswith(f"!{name}") or (len(name) >= 4 and name in e):
            return True
    return False


def gather(mode, app: dict) -> dict:
    ctx: dict = {}
    if mode.context_from_active_app and app:
        ctx["application"] = {"name": app.get("name", ""), "title": app.get("title", "")}
    if mode.context_from_selection:
        ctx["selection"] = selected_text()
    if mode.context_from_clipboard:
        ctx["clipboard"] = winapi.get_clipboard_text() or ""
    return ctx

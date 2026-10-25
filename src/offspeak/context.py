import threading


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
    """Context for the language model. The clipboard is never read: OffSpeak only uses it to paste."""
    ctx: dict = {}
    if mode.context_from_active_app and app:
        ctx["application"] = {"name": app.get("name", ""), "title": app.get("title", "")}
    if mode.language_model and mode.context_from_selection:  # only the language model reads the selection
        ctx["selection"] = selected_text()
    return ctx

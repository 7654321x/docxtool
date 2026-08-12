"""Standalone login and registration window shown before WPS services start."""

from __future__ import annotations

import sqlite3
import tkinter as tk

from docxtool.wps_server.validation import (
    WpsValidationError,
    validate_password,
    validate_username,
)

from .account_runtime import account_from_response, device_payload
from .public_api import PublicApiError


WINDOW_WIDTH = 420
HERO_HEIGHT = 118
CONTENT_TOP = 136
CONTENT_BOTTOM_PADDING = 34
HERO_BG = "#EDF4F2"
HERO_ACCENT = "#DCEBE8"
PANEL_BG = "#FFFFFF"
BRAND_DARK = "#222827"
BRAND_GREEN = "#32786C"
BRAND_GREEN_ACTIVE = "#255F56"
TEXT_PRIMARY = "#202525"
TEXT_MUTED = "#7B8381"
FIELD_BG = "#FAFBFB"
FIELD_BORDER = "#E1E5E4"
FIELD_FOCUS = "#86AAA3"
BUTTON_BG = "#2D3231"
BUTTON_ACTIVE = "#202423"
ERROR_RED = "#D92D20"


def window_geometry(
    width: int,
    requested_height: int,
    screen_width: int,
    screen_height: int,
) -> str:
    """Return centered geometry that never clips the requested client area."""
    height = max(1, int(requested_height))
    left = max(0, (int(screen_width) - int(width)) // 2)
    top = max(0, (int(screen_height) - height) // 2)
    return f"{int(width)}x{height}+{left}+{top}"


def required_window_height(
    content_top: int,
    requested_content_height: int,
    bottom_padding: int,
) -> int:
    """Return enough client height for the currently visible form."""
    return max(1, int(content_top) + int(requested_content_height) + int(bottom_padding))


def password_mask(visible: bool) -> str:
    """Return the Tk entry mask for the requested password visibility."""
    return "" if visible else "*"


def _rounded_rectangle(canvas: tk.Canvas, coordinates, *, radius: int, **options):
    left, top, right, bottom = coordinates
    points = (
        left + radius,
        top,
        right - radius,
        top,
        right,
        top,
        right,
        top + radius,
        right,
        bottom - radius,
        right,
        bottom,
        right - radius,
        bottom,
        left + radius,
        bottom,
        left,
        bottom,
        left,
        bottom - radius,
        left,
        top + radius,
        left,
        top,
        left + radius,
        top,
    )
    return canvas.create_polygon(points, smooth=True, **options)


def submit_account(
    *,
    mode: str,
    username: str,
    password: str,
    confirmation: str,
    api,
    account_store,
    device_key: str,
) -> dict:
    """Validate one form submission, authenticate it, and save the account."""
    validated_username, _ = validate_username(username)
    validated_password = validate_password(password)
    payload = {
        "username": validated_username,
        "password": validated_password,
        "device": device_payload(device_key),
    }
    if mode == "register":
        if confirmation != validated_password:
            raise ValueError("两次输入的密码不一致")
        response = api.register(payload)
    elif mode == "login":
        response = api.login(payload)
    else:
        raise ValueError("WPS_LOGIN_MODE_INVALID")
    account = account_from_response(
        response,
        origin=api.origin,
        username=validated_username,
        password=validated_password,
        device_key=device_key,
    )
    account_store.save_account(account)
    return account


def show_login_register_window(*, api, account_store) -> dict:
    root = tk.Tk()
    root.withdraw()
    root.title("DocxTool WPS")
    root.resizable(False, False)
    root.configure(bg=HERO_BG)
    result = {}
    mode = tk.StringVar(value="login")
    username = tk.StringVar()
    password = tk.StringVar()
    confirmation = tk.StringVar()
    status = tk.StringVar(value="请输入账号和密码")
    device_key = account_store.new_device_key()
    submitting = False

    background = tk.Canvas(
        root,
        bg=HERO_BG,
        highlightthickness=0,
        borderwidth=0,
    )
    background.place(x=0, y=0, relwidth=1, relheight=1)

    brand = tk.Frame(root, bg=HERO_BG)
    brand.place(x=30, y=26)
    mark = tk.Canvas(
        brand,
        width=38,
        height=38,
        bg=HERO_BG,
        highlightthickness=0,
    )
    _rounded_rectangle(
        mark,
        (1, 1, 37, 37),
        radius=10,
        fill=BRAND_DARK,
        outline=BRAND_DARK,
    )
    mark.create_text(
        19,
        19,
        text="D",
        fill="#FFFFFF",
        font=("Microsoft YaHei", 16, "bold"),
    )
    mark.pack(side="left", padx=(0, 11))
    brand_text = tk.Frame(brand, bg=HERO_BG)
    brand_text.pack(side="left")
    tk.Label(
        brand_text,
        text="DocxTool",
        bg=HERO_BG,
        fg=TEXT_PRIMARY,
        font=("Microsoft YaHei", 14, "bold"),
    ).pack(anchor="w")
    tk.Label(
        brand_text,
        text="WPS WORKSPACE",
        bg=HERO_BG,
        fg=TEXT_MUTED,
        font=("Microsoft YaHei", 7),
    ).pack(anchor="w", pady=(3, 0))

    content = tk.Frame(root, bg=PANEL_BG, width=360)
    content.place(x=30, y=CONTENT_TOP, width=360)
    view_title = tk.StringVar(value="账号登录")
    view_hint = tk.StringVar(value="欢迎回来，继续进入你的工作台。")
    tk.Label(
        content,
        textvariable=view_title,
        bg=PANEL_BG,
        fg=TEXT_PRIMARY,
        font=("Microsoft YaHei", 17, "bold"),
    ).pack(anchor="w")
    tk.Label(
        content,
        textvariable=view_hint,
        bg=PANEL_BG,
        fg=TEXT_MUTED,
        font=("Microsoft YaHei", 9),
    ).pack(anchor="w", pady=(6, 22))

    fields = tk.Frame(content, bg=PANEL_BG)
    fields.pack(fill="x")

    def field(
        label: str,
        variable: tk.StringVar,
        *,
        password_field: bool = False,
    ):
        block = tk.Frame(fields, bg=PANEL_BG)
        tk.Label(
            block,
            text=label,
            bg=PANEL_BG,
            fg="#5E6664",
            font=("Microsoft YaHei", 9),
        ).pack(anchor="w", pady=(0, 6))
        shell = tk.Canvas(
            block,
            height=48,
            bg=PANEL_BG,
            highlightthickness=0,
            borderwidth=0,
        )
        shell.pack(fill="x")
        entry = tk.Entry(
            shell,
            textvariable=variable,
            show=password_mask(False) if password_field else "",
            relief="flat",
            borderwidth=0,
            bg=FIELD_BG,
            fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            font=("Microsoft YaHei", 10),
        )

        def draw_border(color: str) -> None:
            shell.delete("field")
            _rounded_rectangle(
                shell,
                (1, 1, max(2, shell.winfo_width() - 1), 47),
                radius=10,
                fill=FIELD_BG,
                outline=color,
                width=1,
                tags="field",
            )
            shell.tag_lower("field")

        entry_width_offset = -62 if password_field else -26
        entry.place(x=13, y=7, relwidth=1, width=entry_width_offset, height=34)
        shell.bind("<Configure>", lambda _event: draw_border(FIELD_BORDER))
        entry.bind("<FocusIn>", lambda _event: draw_border(FIELD_FOCUS))
        entry.bind("<FocusOut>", lambda _event: draw_border(FIELD_BORDER))

        if password_field:
            password_visible = False
            eye = tk.Canvas(
                shell,
                width=34,
                height=34,
                bg=FIELD_BG,
                highlightthickness=0,
                borderwidth=0,
                cursor="hand2",
            )

            def draw_eye() -> None:
                eye.delete("all")
                color = BRAND_GREEN if password_visible else "#8B9391"
                eye.create_oval(
                    5,
                    10,
                    29,
                    24,
                    outline=color,
                    width=1,
                )
                eye.create_oval(14, 14, 20, 20, fill=color, outline=color)
                if password_visible:
                    eye.create_line(7, 7, 27, 27, fill=color, width=2)

            def toggle_password(_event=None) -> None:
                nonlocal password_visible
                password_visible = not password_visible
                entry.configure(show=password_mask(password_visible))
                draw_eye()
                entry.focus_set()

            eye.place(relx=1, x=-47, y=7, width=34, height=34)
            eye.bind("<Button-1>", toggle_password)
            draw_eye()
        return block, entry

    username_block, username_entry = field("账号", username)
    password_block, _password_entry = field(
        "密码", password, password_field=True
    )
    confirmation_block, _confirmation_entry = field(
        "确认密码", confirmation, password_field=True
    )
    username_block.pack(fill="x")
    password_block.pack(fill="x", pady=(16, 0))

    status_label = tk.Label(
        content,
        textvariable=status,
        bg=PANEL_BG,
        fg=TEXT_MUTED,
        justify="left",
        anchor="w",
        wraplength=360,
        font=("Microsoft YaHei", 8),
        height=2,
    )
    status_label.pack(fill="x", pady=(13, 0))

    submit = tk.Canvas(
        content,
        height=50,
        highlightthickness=0,
        borderwidth=0,
        bg=PANEL_BG,
        cursor="hand2",
        takefocus=True,
    )
    submit.pack(fill="x", pady=(16, 0))
    submit_state = {"enabled": True, "text": "登录", "active": False}

    def draw_submit() -> None:
        submit.delete("all")
        if submit_state["enabled"]:
            color = BUTTON_ACTIVE if submit_state["active"] else BUTTON_BG
            text_color = "#FFFFFF"
        else:
            color = "#666D6B"
            text_color = "#D8DCDB"
        _rounded_rectangle(
            submit,
            (0, 0, max(1, submit.winfo_width()), 50),
            radius=10,
            fill=color,
            outline=color,
        )
        submit.create_text(
            max(1, submit.winfo_width()) // 2,
            25,
            text=submit_state["text"],
            fill=text_color,
            font=("Microsoft YaHei", 10, "bold"),
        )

    def set_submit(*, text: str, enabled=None) -> None:
        submit_state["text"] = text
        if enabled is not None:
            submit_state["enabled"] = enabled
            submit.configure(cursor="hand2" if enabled else "arrow")
        draw_submit()

    def activate_submit(_event=None) -> None:
        if submit_state["enabled"]:
            submit_form()

    submit.bind("<Configure>", lambda _event: draw_submit())
    submit.bind("<Button-1>", activate_submit)
    submit.bind("<Return>", activate_submit)
    submit.bind("<space>", activate_submit)
    submit.bind(
        "<Enter>",
        lambda _event: (
            submit_state.update(active=True),
            draw_submit(),
        ),
    )
    submit.bind(
        "<Leave>",
        lambda _event: (
            submit_state.update(active=False),
            draw_submit(),
        ),
    )

    switch_prompt = tk.StringVar(value="还没有账号？")
    switch_text = tk.StringVar(value="注册账号")
    switch_row = tk.Frame(content, bg=PANEL_BG)
    switch_row.pack(pady=(18, 0))
    tk.Label(
        switch_row,
        textvariable=switch_prompt,
        bg=PANEL_BG,
        fg=TEXT_MUTED,
        font=("Microsoft YaHei", 9),
    ).pack(side="left")
    switch = tk.Button(
        switch_row,
        textvariable=switch_text,
        command=lambda: switch_mode(),
        relief="flat",
        borderwidth=0,
        bg=PANEL_BG,
        activebackground=PANEL_BG,
        fg=BRAND_GREEN,
        activeforeground=BRAND_GREEN_ACTIVE,
        cursor="hand2",
        font=("Microsoft YaHei", 9),
        padx=2,
        pady=0,
    )
    switch.pack(side="left")

    def set_status(message: str, *, error: bool = False) -> None:
        status.set(message)
        status_label.configure(fg=ERROR_RED if error else TEXT_MUTED)

    def fit_window() -> None:
        root.update_idletasks()
        requested_height = required_window_height(
            CONTENT_TOP,
            content.winfo_reqheight(),
            CONTENT_BOTTOM_PADDING,
        )
        root.geometry(
            window_geometry(
                WINDOW_WIDTH,
                requested_height,
                root.winfo_screenwidth(),
                root.winfo_screenheight(),
            )
        )
        background.delete("all")
        background.create_rectangle(
            0,
            0,
            WINDOW_WIDTH,
            requested_height,
            fill=HERO_BG,
            outline=HERO_BG,
        )
        background.create_polygon(
            250,
            0,
            WINDOW_WIDTH,
            0,
            WINDOW_WIDTH,
            HERO_HEIGHT - 14,
            342,
            HERO_HEIGHT - 40,
            fill=HERO_ACCENT,
            outline=HERO_ACCENT,
        )
        _rounded_rectangle(
            background,
            (0, HERO_HEIGHT - 20, WINDOW_WIDTH, requested_height + 30),
            radius=30,
            fill=PANEL_BG,
            outline=PANEL_BG,
        )

    def refresh_mode() -> None:
        if mode.get() == "register":
            confirmation_block.pack(fill="x", pady=(16, 0))
            view_title.set("注册账号")
            view_hint.set("创建账号后将自动登录。")
            set_submit(text="注册并登录")
            switch_prompt.set("已有账号？")
            switch_text.set("返回登录")
            set_status("账号和密码至少 5 位，必须同时包含字母和数字")
        else:
            confirmation_block.pack_forget()
            view_title.set("账号登录")
            view_hint.set("欢迎回来，继续进入你的工作台。")
            set_submit(text="登录")
            switch_prompt.set("还没有账号？")
            switch_text.set("注册账号")
            set_status("请输入账号和密码")
        root.after_idle(fit_window)

    def switch_mode() -> None:
        if submitting:
            return
        mode.set("register" if mode.get() == "login" else "login")
        refresh_mode()
        username_entry.focus_set()

    def submit_form() -> None:
        nonlocal submitting
        if submitting:
            return
        submitting = True
        current_mode = mode.get()
        idle_text = "注册并登录" if current_mode == "register" else "登录"
        set_submit(
            enabled=False,
            text="注册中..." if current_mode == "register" else "登录中...",
        )
        set_status("正在连接账号服务...")
        root.update_idletasks()
        completed = False
        try:
            account = submit_account(
                mode=current_mode,
                username=username.get(),
                password=password.get(),
                confirmation=confirmation.get(),
                api=api,
                account_store=account_store,
                device_key=device_key,
            )
            result.update(account)
            completed = True
            root.destroy()
        except PublicApiError as exc:
            set_status(exc.message, error=True)
        except (WpsValidationError, ValueError, OSError, sqlite3.Error) as exc:
            set_status(str(exc), error=True)
        finally:
            if not completed:
                submitting = False
                set_submit(enabled=True, text=idle_text)
                fit_window()

    refresh_mode()
    fit_window()
    root.bind("<Return>", lambda _event: submit_form())
    username_entry.focus_set()
    root.deiconify()
    root.mainloop()
    return result

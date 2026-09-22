"""Minimal tkinter interface for the offline MiniDict dictionary."""

from __future__ import annotations

import tkinter as tk
import os
import sys
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from dictionary import Dictionary, DictionaryEntry, DictionaryError
from macos_hotkey import GlobalHotKey, HotKeyError
from macos_hotkey import activate_application, hide_application


class MiniDictApp:
    """A search field and a scrollable result area backed by Dictionary."""

    def __init__(self, root: tk.Tk, dictionary: Dictionary | None = None) -> None:
        self.root = root
        self.dictionary = dictionary if dictionary is not None else Dictionary()
        self.hotkey: GlobalHotKey | None = None
        self._pending_show: str | None = None
        self._closing = False
        self._hotkey_read_fd: int | None = None
        self._hotkey_write_fd: int | None = None

        root.title("MiniDict")
        root.geometry("520x480")
        root.minsize(360, 280)
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)

        content = ttk.Frame(root, padding=16)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(3, weight=1)

        ttk.Label(content, text="输入英文单词，按 Enter 查询").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self.search_entry = ttk.Entry(content)
        self.search_entry.grid(row=1, column=0, sticky="ew")
        ttk.Separator(content).grid(row=2, column=0, sticky="ew", pady=12)

        self.results = ScrolledText(
            content,
            wrap=tk.WORD,
            width=1,
            height=1,
            font="TkTextFont",
            relief=tk.FLAT,
            padx=8,
            pady=8,
            state=tk.DISABLED,
        )
        self.results.grid(row=3, column=0, sticky="nsew")

        footer = ttk.Frame(content)
        footer.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        self.shortcut_hint = ttk.Label(footer, text="Esc 隐藏 · ⌘Q 退出")
        self.shortcut_hint.grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="退出 MiniDict", command=self.quit).grid(
            row=0, column=1, sticky="e"
        )

        root.bind("<Return>", self.search)
        root.bind("<Escape>", self.hide)
        root.protocol("WM_DELETE_WINDOW", self.hide)
        self.search_entry.bind("<Control-a>", self.select_all)
        if root.tk.call("tk", "windowingsystem") == "aqua":
            self.search_entry.bind("<Command-a>", self.select_all)
            root.bind("<Command-q>", self.quit)
            # Route the macOS application menu's Quit through our cleanup too.
            root.createcommand("tk::mac::Quit", self.quit)

        root.after_idle(self.search_entry.focus_force)

    def start_hotkey(self) -> None:
        """Register once; leave a usable visible window if setup fails."""
        try:
            if sys.platform == "darwin":
                import AppKit  # Check the activation dependency before hiding.
                self._hotkey_read_fd, self._hotkey_write_fd = os.pipe()
                os.set_blocking(self._hotkey_read_fd, False)
                os.set_blocking(self._hotkey_write_fd, False)
                self.root.createfilehandler(
                    self._hotkey_read_fd, tk.READABLE, self._hotkey_ready
                )
            self.hotkey = GlobalHotKey(self.request_show)
        except (HotKeyError, ImportError, OSError) as error:
            self._close_hotkey_pipe()
            self.shortcut_hint.configure(text="快捷键不可用 · ⌘Q 退出")
            self.show_text(
                f"全局快捷键未启用：{error}\n\n"
                "请检查快捷键占用及 requirements.txt 中的依赖。"
                "窗口仍可查词；Esc 会最小化窗口，方便从 Dock 恢复。"
            )
            return

        shortcut = self.hotkey.shortcut.label
        self.shortcut_hint.configure(text=f"{shortcut} 呼出 · Esc 隐藏")
        if self.hotkey.failures:
            self.show_text(
                f"默认快捷键注册失败，已改用 {shortcut}。\n\n"
                + "\n".join(self.hotkey.failures)
            )

    def request_show(self) -> None:
        """Wake Tcl without entering Tk from a native callback (even on main)."""
        if not self._closing and self._hotkey_write_fd is not None:
            try:
                os.write(self._hotkey_write_fd, b"\0")
            except BlockingIOError:
                pass  # A pending notification already guarantees a wakeup.

    def _hotkey_ready(self, descriptor: int, mask: int) -> None:
        os.read(descriptor, 4096)
        if not self._closing and self._pending_show is None:
            self._pending_show = self.root.after_idle(self.show)

    def _close_hotkey_pipe(self) -> None:
        if self._hotkey_read_fd is not None:
            self.root.deletefilehandler(self._hotkey_read_fd)
            os.close(self._hotkey_read_fd)
            self._hotkey_read_fd = None
        if self._hotkey_write_fd is not None:
            os.close(self._hotkey_write_fd)
            self._hotkey_write_fd = None

    def show(self) -> None:
        self._pending_show = None
        if self._closing:
            return
        self.root.deiconify()
        if sys.platform == "darwin":
            activate_application()
        self.root.lift()
        self.search_entry.focus_force()
        self.select_all()

    def hide(self, event: tk.Event | None = None) -> str:
        if self._pending_show is not None:
            self.root.after_cancel(self._pending_show)
            self._pending_show = None
        if self.hotkey is None:
            self.root.iconify()
        else:
            self.root.withdraw()
            if sys.platform == "darwin":
                hide_application()
        return "break"

    def select_all(self, event: tk.Event | None = None) -> str:
        self.search_entry.selection_range(0, tk.END)
        self.search_entry.icursor(tk.END)
        return "break"

    def search(self, event: tk.Event | None = None) -> str:
        """Replace the previous result with the requested entry or a message."""
        word = self.search_entry.get().strip()
        self.search_entry.delete(0, tk.END)
        self.search_entry.insert(0, word)

        if not word:
            self.show_text("请输入英文单词。")
        else:
            try:
                entry = self.dictionary.lookup(word)
            except (DictionaryError, OSError) as error:
                self.show_text(f"无法读取词典数据库，请检查数据库文件。\n\n{error}")
            else:
                if entry is None:
                    self.show_text(f"未找到该单词：{word}")
                else:
                    self.show_entry(entry)

        self.search_entry.focus_set()
        return "break"

    def show_entry(self, entry: DictionaryEntry) -> None:
        sections = [entry.word]
        if entry.phonetic:
            sections[0] += f"\n/{entry.phonetic}/"
        if entry.translation:
            sections.append(f"中文\n{entry.translation}")
        if entry.definition:
            sections.append(f"English\n{entry.definition}")

        metadata = []
        if entry.tag:
            metadata.append(entry.tag.upper())
        if entry.collins is not None:
            metadata.append(f"Collins {entry.collins}")
        if metadata:
            sections.append("    ".join(metadata))
        self.show_text("\n\n".join(sections))

    def show_text(self, text: str) -> None:
        self.results.configure(state=tk.NORMAL)
        self.results.delete("1.0", tk.END)
        self.results.insert("1.0", text)
        self.results.yview_moveto(0)
        self.results.configure(state=tk.DISABLED)

    def quit(self, event: tk.Event | None = None) -> str:
        if self._closing:
            return "break"
        self._closing = True
        if self._pending_show is not None:
            self.root.after_cancel(self._pending_show)
            self._pending_show = None
        if self.hotkey is not None:
            self.hotkey.close()
            self.hotkey = None
        self._close_hotkey_pipe()
        self.root.destroy()
        return "break"


def main() -> None:
    root = tk.Tk()
    app = MiniDictApp(root)
    app.start_hotkey()
    try:
        root.mainloop()
    finally:
        app.quit()


if __name__ == "__main__":
    main()

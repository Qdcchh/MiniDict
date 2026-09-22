"""Minimal tkinter interface for the offline MiniDict dictionary."""

from __future__ import annotations

import logging
import os
import sys
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from associator import Associator, NullAssociator
from dictionary import (
    Dictionary,
    DictionaryCandidate,
    DictionaryEntry,
    DictionaryError,
    contains_cjk,
)
from macos_hotkey import (
    GlobalHotKey,
    HotKeyError,
    MenuBarIcon,
    activate_application,
    hide_application,
    read_pasteboard_word,
    restore_dock_activation_policy,
    set_accessory_activation_policy,
)


def _first_sense(translation: str | None, width: int = 44) -> str:
    """First line of a translation, trimmed, for the candidate list."""
    line = translation.splitlines()[0] if translation else ""
    return line if len(line) <= width else line[:width] + "…"


class MiniDictApp:
    """A search field and a scrollable result area backed by Dictionary."""

    def __init__(
        self,
        root: tk.Tk,
        dictionary: Dictionary | None = None,
        associator: Associator | None = None,
    ) -> None:
        self.root = root
        self.dictionary = dictionary if dictionary is not None else Dictionary()
        # The seat reserved for a small local model; see associator.py.
        self.associator = associator if associator is not None else NullAssociator()
        self._candidate_query: str | None = None
        self.hotkey: GlobalHotKey | None = None
        self.menubar_icon: MenuBarIcon | None = None
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

        ttk.Label(content, text="输入英文或中文词语，按 Enter 查询").grid(
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
        self.results.tag_configure("link", underline=True, foreground="#1B4F9C")
        self.results.tag_bind("link", "<Enter>", self._hand_cursor)
        self.results.tag_bind("link", "<Leave>", self._text_cursor)

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
        """Install the global hotkey, menu bar icon, and Dock-less policy.

        Every failure degrades to an app that stays reachable: the icon
        covers for a dead hotkey, and the Dock comes back when both fail.
        """
        appkit_ready = False
        if sys.platform == "darwin":
            try:
                import AppKit  # The icon, the policy, and the pipe need PyObjC.

                set_accessory_activation_policy()
                self._hotkey_read_fd, self._hotkey_write_fd = os.pipe()
                os.set_blocking(self._hotkey_read_fd, False)
                os.set_blocking(self._hotkey_write_fd, False)
                self.root.createfilehandler(
                    self._hotkey_read_fd, tk.READABLE, self._hotkey_ready
                )
                appkit_ready = True
            except (ImportError, OSError) as error:
                self._close_hotkey_pipe()
                self.shortcut_hint.configure(text="快捷键与图标不可用 · ⌘Q 退出")
                self.show_text(
                    f"macOS 集成未启用（{error}），请检查 requirements.txt。\n\n"
                    "窗口仍可查词；Esc 会最小化窗口，方便恢复。"
                )
                return

        hotkey_error: Exception | None = None
        try:
            self.hotkey = GlobalHotKey(self.request_show)
        except (HotKeyError, OSError) as error:
            hotkey_error = error

        icon_error: Exception | None = None
        if appkit_ready:
            try:
                self.menubar_icon = MenuBarIcon(
                    self.request_show, self.request_quit
                )
            except Exception as error:
                # The icon is optional; a broken status bar must not break start.
                icon_error = error
                self._close_menubar_icon()

        if self.hotkey is not None:
            shortcut = self.hotkey.shortcut.label
            self.shortcut_hint.configure(
                text=f"{shortcut} 呼出并查剪贴板 · Esc 隐藏"
            )
            if self.hotkey.failures:
                self.show_text(
                    f"默认快捷键注册失败，已改用 {shortcut}。\n\n"
                    + "\n".join(self.hotkey.failures)
                )
            if icon_error is not None:
                logging.warning("MiniDict 菜单栏图标不可用：%s", icon_error)
        elif self.menubar_icon is not None:
            self.shortcut_hint.configure(text="右上角图标呼出 · Esc 隐藏")
            self.show_text(
                f"全局快捷键注册失败（{hotkey_error}）。\n\n"
                "请用右上角的「译」图标呼出 MiniDict。"
            )
        else:
            notes = ["MiniDict 的呼出方式都不可用："]
            if hotkey_error is not None:
                notes.append(f"快捷键：{hotkey_error}")
            if icon_error is not None:
                notes.append(f"菜单栏图标：{icon_error}")
            if appkit_ready:
                # The Dock icon left with the accessory policy; bring it back
                # before the window can hide, or MiniDict becomes unreachable.
                restore_dock_activation_policy()
                notes.append("\n已恢复 Dock 图标，最小化后从 Dock 恢复。")
            else:
                notes.append("\n最小化后从任务栏恢复。")
            self.shortcut_hint.configure(text="快捷键与图标不可用 · ⌘Q 退出")
            self.show_text("\n".join(notes))

    def request_show(self) -> None:
        """Wake Tcl without entering Tk from a native callback (even on main)."""
        if not self._closing and self._hotkey_write_fd is not None:
            try:
                os.write(self._hotkey_write_fd, b"s")
            except BlockingIOError:
                pass  # A pending notification already guarantees a wakeup.

    def request_quit(self) -> None:
        """Ask the Tcl loop to exit; safe from AppKit menu callbacks."""
        if not self._closing and self._hotkey_write_fd is not None:
            try:
                os.write(self._hotkey_write_fd, b"x")
            except BlockingIOError:
                pass

    def _hotkey_ready(self, descriptor: int, mask: int) -> None:
        data = os.read(descriptor, 4096)
        if self._closing:
            return
        if b"x" in data:
            self.root.after_idle(self.quit)
        elif data and self._pending_show is None:
            self._pending_show = self.root.after_idle(self.show)

    def _close_menubar_icon(self) -> None:
        if self.menubar_icon is not None:
            self.menubar_icon.close()
            self.menubar_icon = None

    def _close_hotkey_pipe(self) -> None:
        if self._hotkey_read_fd is not None:
            self.root.deletefilehandler(self._hotkey_read_fd)
            os.close(self._hotkey_read_fd)
            self._hotkey_read_fd = None
        if self._hotkey_write_fd is not None:
            os.close(self._hotkey_write_fd)
            self._hotkey_write_fd = None

    def show(self) -> None:
        """Summon the window; look up clipboard text when it is a single line."""
        self._pending_show = None
        if self._closing:
            return
        self.root.deiconify()
        word = None
        if sys.platform == "darwin":
            activate_application()
            word = read_pasteboard_word()
        self.root.lift()
        if word is None:
            self.search_entry.focus_force()
            self.select_all()
            return
        self.search_entry.delete(0, tk.END)
        self.search_entry.insert(0, word)
        self.search()
        self.select_all()
        self.search_entry.focus_force()

    def hide(self, event: tk.Event | None = None) -> str:
        if self._pending_show is not None:
            self.root.after_cancel(self._pending_show)
            self._pending_show = None
        # With no hotkey and no menu bar icon there is nothing to summon the
        # window back: keep it in the Dock instead of withdrawing it.
        if self.hotkey is None and self.menubar_icon is None:
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
            self.show_text("请输入查询词。")
        elif contains_cjk(word):
            self.show_chinese_results(word)
        else:
            self._candidate_query = None
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

    def show_chinese_results(self, chinese: str) -> None:
        """List English words for a Chinese query; click a word for its entry."""
        self._candidate_query = chinese
        try:
            candidates = self.dictionary.lookup_by_chinese(chinese)
        except (DictionaryError, OSError) as error:
            self.show_text(f"无法读取词典数据库，请检查数据库文件。\n\n{error}")
            return
        self._render_candidates(chinese, candidates, self._associated_entries(chinese, candidates))

    def _associated_entries(
        self, chinese: str, candidates: list[DictionaryCandidate]
    ) -> list[DictionaryEntry]:
        """Entries suggested by the associator; the small-model seam."""
        seen = {candidate.word for candidate in candidates}
        try:
            words = self.associator.associate(chinese)
        except Exception:
            # The associator is an optional plug-in; it must never break lookup.
            logging.exception("MiniDict associator failed")
            return []
        entries = []
        for word in words:
            if contains_cjk(word) or word in seen:
                continue
            try:
                entry = self.dictionary.lookup(word)
            except DictionaryError:
                continue
            if entry is not None:
                seen.add(entry.word)
                entries.append(entry)
        return entries

    def _render_candidates(
        self,
        chinese: str,
        candidates: list[DictionaryCandidate],
        associated: list[DictionaryEntry],
    ) -> None:
        """Draw the clickable candidate list and the association section."""
        results = self.results
        results.configure(state=tk.NORMAL)
        results.delete("1.0", tk.END)
        if candidates:
            results.insert(
                "end", f"「{chinese}」的英文候选（点击单词查看词条）\n\n"
            )
        for index, candidate in enumerate(candidates):
            tag = f"candidate-{index}"
            results.insert("end", candidate.word, ("link", tag))
            results.insert(
                "end", "\n    " + _first_sense(candidate.translation) + "\n\n"
            )
            results.tag_bind(
                tag, "<Button-1>",
                lambda event, word=candidate.word: self.open_candidate(word),
            )
        if associated:
            results.insert("end", "联想词（点击查看）\n\n")
            for index, entry in enumerate(associated):
                tag = f"associated-{index}"
                results.insert("end", entry.word, ("link", tag))
                results.insert(
                    "end", "\n    " + _first_sense(entry.translation) + "\n\n"
                )
                results.tag_bind(
                    tag, "<Button-1>",
                    lambda event, word=entry.word: self.open_candidate(word),
                )
        if not candidates and not associated:
            results.insert("end", f"未找到与「{chinese}」相关的英文单词。")
        results.yview_moveto(0)
        results.configure(state=tk.DISABLED)

    def open_candidate(self, word: str) -> None:
        """Open one candidate entry, keeping a link back to the list."""
        back_to = self._candidate_query
        self.search_entry.delete(0, tk.END)
        self.search_entry.insert(0, word)
        self.search()
        if back_to and not contains_cjk(word):
            results = self.results
            results.configure(state=tk.NORMAL)
            results.insert(
                "1.0", f"← 返回「{back_to}」的候选列表\n\n", ("link", "back")
            )
            results.tag_bind(
                "back", "<Button-1>",
                lambda event: self.reopen_candidates(back_to),
            )
            results.configure(state=tk.DISABLED)

    def reopen_candidates(self, chinese: str) -> None:
        """Show the candidate list for *chinese* again after following a word."""
        self.search_entry.delete(0, tk.END)
        self.search_entry.insert(0, chinese)
        self.show_chinese_results(chinese)

    def show_text(self, text: str) -> None:
        self.results.configure(state=tk.NORMAL)
        self.results.delete("1.0", tk.END)
        self.results.insert("1.0", text)
        self.results.yview_moveto(0)
        self.results.configure(state=tk.DISABLED)

    def _hand_cursor(self, event: tk.Event) -> None:
        self.results.configure(cursor="hand2")

    def _text_cursor(self, event: tk.Event) -> None:
        self.results.configure(cursor="xterm")

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
        self._close_menubar_icon()
        self._close_hotkey_pipe()
        self.root.destroy()
        return "break"


def main() -> None:
    root = tk.Tk()
    app = MiniDictApp(root)
    app.start_hotkey()
    if sys.platform == "darwin":
        try:
            activate_application()  # Accessory apps launch behind other windows.
        except ImportError:
            pass
    try:
        root.mainloop()
    finally:
        app.quit()


if __name__ == "__main__":
    main()

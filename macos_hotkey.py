"""macOS integration: hotkey registration, activation, menu bar icon, and
pasteboard access; nothing is monitored or polled.

Carbon's C event APIs are declared with ctypes because PyObjC does not expose
InstallEventHandler. AppKit activation uses the maintained PyObjC bridge.
Create and close GlobalHotKey on the main thread running Tk's event loop.
The callback must not call Tk: notify a Tcl file handler through a pipe instead.
Menu actions take the same detour: they only write to the pipe.
"""

from __future__ import annotations

import ctypes as ct
from dataclasses import dataclass
import logging
import sys
import threading
from collections.abc import Callable


@dataclass(frozen=True)
class Shortcut:
    key_code: int
    modifiers: int
    label: str


# Carbon virtual key codes and modifier masks (Events.h). Change shortcuts here.
KEY_D = 2
OPTION = 1 << 11
CONTROL = 1 << 12
SHORTCUTS = (
    Shortcut(KEY_D, OPTION, "⌥D"),
    Shortcut(KEY_D, CONTROL | OPTION, "⌃⌥D"),
)


class HotKeyError(RuntimeError):
    """The system could not register a usable global shortcut."""


class _EventTypeSpec(ct.Structure):
    _fields_ = [("event_class", ct.c_uint32), ("event_kind", ct.c_uint32)]


class _EventHotKeyID(ct.Structure):
    _fields_ = [("signature", ct.c_uint32), ("id", ct.c_uint32)]


_HANDLER = ct.CFUNCTYPE(ct.c_int32, ct.c_void_p, ct.c_void_p, ct.c_void_p)
_SIGNATURE = int.from_bytes(b"MDic", "big")
_NOT_HANDLED = -9874


class GlobalHotKey:
    """Own one exclusive Carbon hotkey and its main-thread event handler."""

    def __init__(
        self, on_press: Callable[[], None], shortcuts: tuple[Shortcut, ...] = SHORTCUTS
    ) -> None:
        if sys.platform != "darwin":
            raise HotKeyError("全局快捷键仅支持 macOS。")
        self._check_thread()
        self._on_press = on_press
        self._hotkey = ct.c_void_p()
        self._handler = ct.c_void_p()
        # Keep the Python callback alive until RemoveEventHandler has completed.
        self._callback = _HANDLER(self._handle_event)
        self.failures: list[str] = []
        self._carbon = ct.CDLL(
            "/System/Library/Frameworks/Carbon.framework/Carbon"
        )
        self._declare_functions()
        event_type = _EventTypeSpec(int.from_bytes(b"keyb", "big"), 5)
        target = self._carbon.GetEventDispatcherTarget()
        status = self._carbon.InstallEventHandler(
            target, self._callback, 1, ct.byref(event_type), None,
            ct.byref(self._handler),
        )
        if status:
            raise HotKeyError(f"无法安装快捷键事件处理器（OSStatus {status}）。")

        for shortcut in shortcuts:
            status = self._carbon.RegisterEventHotKey(
                shortcut.key_code, shortcut.modifiers,
                _EventHotKeyID(_SIGNATURE, 1), target,
                1,  # kEventHotKeyExclusive: don't share an occupied shortcut.
                ct.byref(self._hotkey),
            )
            if status == 0:
                self.shortcut = shortcut
                return
            self.failures.append(f"{shortcut.label}: OSStatus {status}")

        self.close()
        raise HotKeyError("无法注册全局快捷键：" + "; ".join(self.failures))

    def _declare_functions(self) -> None:
        signatures = {
            "GetEventDispatcherTarget": (ct.c_void_p, []),
            "InstallEventHandler": (ct.c_int32, [
                ct.c_void_p, _HANDLER, ct.c_ulong,
                ct.POINTER(_EventTypeSpec), ct.c_void_p, ct.POINTER(ct.c_void_p),
            ]),
            "RegisterEventHotKey": (ct.c_int32, [
                ct.c_uint32, ct.c_uint32, _EventHotKeyID,
                ct.c_void_p, ct.c_uint32, ct.POINTER(ct.c_void_p),
            ]),
            "GetEventParameter": (ct.c_int32, [
                ct.c_void_p, ct.c_uint32, ct.c_uint32, ct.POINTER(ct.c_uint32),
                ct.c_ulong, ct.POINTER(ct.c_ulong), ct.c_void_p,
            ]),
            "UnregisterEventHotKey": (ct.c_int32, [ct.c_void_p]),
            "RemoveEventHandler": (ct.c_int32, [ct.c_void_p]),
        }
        for name, (result_type, argument_types) in signatures.items():
            function = getattr(self._carbon, name)
            function.restype = result_type
            function.argtypes = argument_types

    @staticmethod
    def _check_thread() -> None:
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("macOS hotkey operations must run on the main thread")

    def _handle_event(self, handler: int, event: int, user_data: int) -> int:
        hotkey_id = _EventHotKeyID()
        status = self._carbon.GetEventParameter(
            event, int.from_bytes(b"----", "big"), int.from_bytes(b"hkid", "big"),
            None, ct.sizeof(hotkey_id), None, ct.byref(hotkey_id),
        )
        if status or (hotkey_id.signature, hotkey_id.id) != (_SIGNATURE, 1):
            return _NOT_HANDLED
        try:
            self._check_thread()
            self._on_press()
        except Exception:
            # Exceptions must never escape a C callback boundary.
            logging.exception("MiniDict hotkey callback failed")
        return 0

    def close(self) -> None:
        """Release the shortcut before releasing its event handler; idempotent."""
        self._check_thread()
        for attribute, function_name in (
            ("_hotkey", "UnregisterEventHotKey"),
            ("_handler", "RemoveEventHandler"),
        ):
            reference = getattr(self, attribute)
            if reference.value:
                status = getattr(self._carbon, function_name)(reference)
                if status:
                    logging.error("%s failed: OSStatus %s", function_name, status)
                else:
                    reference.value = None


def activate_application() -> None:
    from AppKit import NSApplication, NSApplicationActivateIgnoringOtherApps
    from AppKit import NSRunningApplication

    NSApplication.sharedApplication().unhideWithoutActivation()
    NSRunningApplication.currentApplication().activateWithOptions_(
        NSApplicationActivateIgnoringOtherApps
    )


def hide_application() -> None:
    from AppKit import NSApplication

    NSApplication.sharedApplication().hide_(None)


def set_accessory_activation_policy() -> None:
    """Drop the Dock icon; the menu bar item keeps MiniDict reachable."""
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyAccessory
    )


def restore_dock_activation_policy() -> None:
    """Undo the accessory policy when every summon channel died."""
    from AppKit import NSApplication, NSApplicationActivationPolicyRegular

    NSApplication.sharedApplication().setActivationPolicy_(
        NSApplicationActivationPolicyRegular
    )


_STATUS_TARGET_CLASS = None


def _status_target_class():
    """Define the NSObject target lazily; PyObjC exists only on macOS."""
    global _STATUS_TARGET_CLASS
    if _STATUS_TARGET_CLASS is None:
        from Foundation import NSObject

        class MiniDictStatusTarget(NSObject):
            """Menu actions call plain callables; Tk is reached via the pipe."""

            def show_(self, sender: object) -> None:
                self._on_show()

            def quit_(self, sender: object) -> None:
                self._on_quit()

        _STATUS_TARGET_CLASS = MiniDictStatusTarget
    return _STATUS_TARGET_CLASS


class MenuBarIcon:
    """The menu bar item that keeps a Dock-less MiniDict resident and reachable."""

    def __init__(
        self, on_show: Callable[[], None], on_quit: Callable[[], None]
    ) -> None:
        from AppKit import (
            NSMenu,
            NSMenuItem,
            NSStatusBar,
            NSVariableStatusItemLength,
        )

        # Trailing underscores become colons: show_ answers the "show:" action.
        self._target = _status_target_class().alloc().init()
        self._target._on_show = on_show
        self._target._on_quit = on_quit

        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        show_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "查词 MiniDict", "show:", ""
        )
        show_item.setTarget_(self._target)
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "退出 MiniDict", "quit:", ""
        )
        quit_item.setTarget_(self._target)
        menu.addItem_(show_item)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(quit_item)

        self._item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self._item.button().setTitle_("译")
        self._item.setMenu_(menu)

    def close(self) -> None:
        """Remove the icon; idempotent."""
        if getattr(self, "_item", None) is not None:
            from AppKit import NSStatusBar

            NSStatusBar.systemStatusBar().removeStatusItem_(self._item)
            self._item = None


def read_pasteboard_word() -> str | None:
    """Return clipboard text worth auto-searching, or ``None``.

    ECDICT stores words up to 64 characters, so longer text is ignored, and
    only single-line text can be looked up. Best effort: an unreadable
    pasteboard simply means there is nothing to search.
    """
    try:
        from AppKit import NSPasteboard, NSPasteboardTypeString

        text = NSPasteboard.generalPasteboard().stringForType_(
            NSPasteboardTypeString
        )
    except Exception:
        # Pasteboard failures must never break summoning the window.
        return None
    if not text:
        return None
    text = text.strip()
    if not text or len(text.splitlines()) != 1 or len(text) > 64:
        return None
    return text

"""Inline keyboards."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from compressor.engine import PRESETS, PresetId


def preset_keyboard(prefix: str = "run") -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("Light", callback_data=f"{prefix}:light"),
            InlineKeyboardButton("Medium", callback_data=f"{prefix}:medium"),
        ],
        [
            InlineKeyboardButton("Strong", callback_data=f"{prefix}:strong"),
            InlineKeyboardButton("Ultra", callback_data=f"{prefix}:ultra"),
        ],
        [
            InlineKeyboardButton("8 MB", callback_data=f"{prefix}:tg8"),
            InlineKeyboardButton("2 MB", callback_data=f"{prefix}:tg2"),
        ],
    ]
    if prefix == "run":
        rows.append([InlineKeyboardButton("Cancel", callback_data="run:cancel")])
    return InlineKeyboardMarkup(rows)


def settings_keyboard(ask_each: bool, current: PresetId) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                _mark("Light", current == "light"), callback_data="set:light"
            ),
            InlineKeyboardButton(
                _mark("Medium", current == "medium"), callback_data="set:medium"
            ),
        ],
        [
            InlineKeyboardButton(
                _mark("Strong", current == "strong"), callback_data="set:strong"
            ),
            InlineKeyboardButton(
                _mark("Ultra", current == "ultra"), callback_data="set:ultra"
            ),
        ],
        [
            InlineKeyboardButton(
                _mark("8 MB", current == "tg8"), callback_data="set:tg8"
            ),
            InlineKeyboardButton(
                _mark("2 MB", current == "tg2"), callback_data="set:tg2"
            ),
        ],
        [
            InlineKeyboardButton(
                "Ask each time: on" if ask_each else "Ask each time: off",
                callback_data="set:toggle_ask",
            )
        ],
    ]
    return InlineKeyboardMarkup(rows)


def _mark(label: str, active: bool) -> str:
    return f"· {label} ·" if active else label


def preset_labels() -> str:
    return ", ".join(p.label for p in PRESETS.values())

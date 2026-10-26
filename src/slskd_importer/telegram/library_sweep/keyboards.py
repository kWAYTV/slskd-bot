"""Inline keyboards for sweep review decisions and Keep-mine reasons."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

SWEEP_CHOICES = {"m": "keep_mine", "n": "take_new", "b": "keep_both"}
SWEEP_REASONS = {
    "d": "distorted",
    "m": "muffled",
    "v": "other_version",
    "o": "other",
}


def build_sweep_review_keyboard(review_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Keep mine", callback_data=f"swp:{review_id}:m"),
                InlineKeyboardButton("Take new", callback_data=f"swp:{review_id}:n"),
                InlineKeyboardButton("Keep both", callback_data=f"swp:{review_id}:b"),
            ]
        ]
    )


def build_sweep_reason_keyboard(review_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Distorted", callback_data=f"swr:{review_id}:d"),
                InlineKeyboardButton("Muffled", callback_data=f"swr:{review_id}:m"),
            ],
            [
                InlineKeyboardButton("Other version", callback_data=f"swr:{review_id}:v"),
                InlineKeyboardButton("Other", callback_data=f"swr:{review_id}:o"),
            ],
        ]
    )

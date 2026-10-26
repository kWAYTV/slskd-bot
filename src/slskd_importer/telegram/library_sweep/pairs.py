"""Send yours/proposal audio pairs for pending sweep reviews."""

from __future__ import annotations

import asyncio
import logging
import os

from telegram import Bot
from telegram.constants import ParseMode

from slskd_importer.records.sweep_models import Review
from slskd_importer.telegram.library_sweep.keyboards import build_sweep_review_keyboard
from slskd_importer.telegram.ui.markdown import escape_md

logger = logging.getLogger(__name__)

SWEEP_PAIRS_PER_MESSAGE = 10
SWEEP_SEND_PAUSE_SECS = 1.0


def _pair_caption(review: Review, which: str) -> str:
    if which == "yours":
        desc = review.current_desc
        length = review.current_len
        sound = review.current_sound
        label = "Yours"
    else:
        desc = review.proposal_desc
        length = review.proposal_len
        sound = review.proposal_sound
        label = "Proposal"
    bits = [f"*{escape_md(label)}*", f"`{escape_md(review.stem)}`"]
    if desc:
        bits.append(escape_md(desc))
    if length:
        bits.append(f"{length:.0f}s")
    if which == "proposal" and review.reason:
        bits.append(escape_md(review.reason))
    if sound:
        bits.append(escape_md(sound))
    return "\n".join(bits)


async def send_sweep_pairs(bot: Bot, chat_id: int, reviews: list[Review], *, mark_offered) -> int:
    """Send up to SWEEP_PAIRS_PER_MESSAGE undecided pairs. Returns how many were sent."""
    sent = 0
    for review in reviews:
        if sent >= SWEEP_PAIRS_PER_MESSAGE:
            break
        if review.decision is not None:
            continue
        try:
            yours_name = os.path.basename(review.current_path)
            stem = os.path.splitext(yours_name)[0]
            proposal_name = f"{stem}.{review.proposal_ext}"
            with open(review.current_path, "rb") as yours:
                await bot.send_audio(
                    chat_id=chat_id,
                    audio=yours,
                    filename=yours_name,
                    caption=_pair_caption(review, "yours"),
                    parse_mode=ParseMode.MARKDOWN,
                )
            await asyncio.sleep(SWEEP_SEND_PAUSE_SECS)
            with open(review.proposal_path, "rb") as proposal:
                await bot.send_audio(
                    chat_id=chat_id,
                    audio=proposal,
                    filename=proposal_name,
                    caption=_pair_caption(review, "proposal"),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=build_sweep_review_keyboard(review.id),
                )
            mark_offered(review.id)
            sent += 1
            await asyncio.sleep(SWEEP_SEND_PAUSE_SECS)
        except Exception:
            logger.exception("Failed to send sweep pair %s (%s)", review.id, review.stem)
    return sent

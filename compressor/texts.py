"""User-facing copy. Plain language, no emoji chrome."""

from __future__ import annotations

from compressor.config import Config
from compressor.engine import (
    PRESETS,
    CompressResult,
    Probe,
    Preset,
    format_duration,
    human_size,
    progress_bar,
)
from compressor.store import GlobalStats, UserRecord


def start_text(first_name: str, cfg: Config) -> str:
    name = first_name or "there"
    return (
        f"Hi {name}. Send or forward a video and I will compress it.\n\n"
        "Works with videos, video notes, GIFs, and video files sent as documents.\n\n"
        f"<b>Limits</b>\n"
        f"• Download up to <b>{cfg.download_limit_mb} MB</b>\n"
        f"• Upload up to <b>{cfg.upload_limit_mb} MB</b>\n\n"
        "Use /settings to pick a default preset, or choose one each time.\n"
        "/help lists every command."
    )


def help_text(cfg: Config) -> str:
    lines = [
        "<b>Commands</b>",
        "/start — what this bot does",
        "/help — this list",
        "/settings — default preset and ask-each-time",
        "/stats — your totals",
        "/queue — current job",
        "/cancel — stop the running encode",
        "/privacy — what is stored",
        "",
        "<b>Presets</b>",
    ]
    for preset in PRESETS.values():
        extra = (
            f"target {preset.target_mb:g} MB"
            if preset.target_mb
            else f"CRF {preset.crf}"
        )
        lines.append(f"• <b>{preset.label}</b> — {preset.blurb} ({extra})")
    lines.extend(
        [
            "",
            "<b>How it works</b>",
            "Send or forward a video. Pick a preset (or use your default). "
            "The bot downloads, encodes to H.264 + AAC MP4 with faststart, "
            "and sends the smaller file back.",
            "",
            f"This instance accepts videos up to {cfg.download_limit_mb} MB.",
        ]
    )
    return "\n".join(lines)


def privacy_text() -> str:
    return (
        "<b>Privacy</b>\n"
        "Videos are written to a temporary folder, encoded, uploaded, then deleted. "
        "Nothing is kept after the job finishes.\n\n"
        "The bot stores your Telegram user id, chosen preset, and anonymous totals "
        "(how many videos, bytes in/out). No video content is archived.\n\n"
        "The operator can ban abuse. There is no advertising and no third-party analytics."
    )


def settings_text(user: UserRecord) -> str:
    preset = PRESETS[user.preset]
    mode = "Ask every time" if user.ask_each else f"Auto — {preset.label}"
    return (
        "<b>Settings</b>\n\n"
        f"Default preset: <b>{preset.label}</b>\n"
        f"{preset.blurb}\n"
        f"Mode: {mode}\n\n"
        "Choose a default below. Toggle whether I ask on every video."
    )


def stats_text(user: UserRecord, global_stats: GlobalStats | None = None) -> str:
    saved = human_size(user.bytes_saved)
    body = (
        "<b>Your stats</b>\n\n"
        f"Videos: <code>{user.videos}</code>\n"
        f"In: {human_size(user.bytes_in)}\n"
        f"Out: {human_size(user.bytes_out)}\n"
        f"Saved: {saved}\n"
        f"Default: {PRESETS[user.preset].label}"
    )
    if global_stats:
        body += (
            "\n\n<b>This instance</b>\n"
            f"Users: {global_stats.users}\n"
            f"Videos: {global_stats.videos}\n"
            f"Saved: {human_size(max(0, global_stats.bytes_in - global_stats.bytes_out))}"
        )
    return body


def pick_preset_text(filename: str, size: int, probe: Probe | None = None) -> str:
    bits = [f"<b>{filename}</b>", human_size(size)]
    if probe and probe.width and probe.height:
        bits.append(f"{probe.display_width}×{probe.display_height}")
    if probe and probe.duration:
        bits.append(format_duration(probe.duration))
    return "Choose a preset for this video.\n" + " · ".join(bits)


def progress_text(stage: str, fraction: float | None = None, extra: str = "") -> str:
    lines = [stage]
    if fraction is not None:
        lines.append(f"<code>{progress_bar(fraction)}</code>")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def result_caption(
    result: CompressResult,
    preset: Preset,
    probe: Probe,
) -> str:
    if result.skipped_larger:
        return (
            "Already compact — the encode was not smaller than the original "
            f"({human_size(result.original_size)}). Sent nothing new."
        )
    saved_pct = result.ratio * 100
    lines = [
        f"<b>{preset.label}</b> · {human_size(result.original_size)} → "
        f"{human_size(result.compressed_size)} ({saved_pct:.0f}% smaller)",
        f"{format_duration(result.elapsed)} encode",
    ]
    if probe.duration:
        lines.append(f"{format_duration(probe.duration)} · {probe.display_width}×{probe.display_height}")
    return "\n".join(lines)


def too_large_download(size: int, limit_mb: int) -> str:
    return f"This file is {human_size(size)}, over the {limit_mb} MB download limit."


def too_large_upload(size: int, limit_mb: int) -> str:
    return (
        f"Compressed file is still {human_size(size)}, over the {limit_mb} MB upload limit. "
        "Try Ultra or the 2 MB target."
    )


def admin_stats(stats: GlobalStats, active: int) -> str:
    return (
        "<b>Admin</b>\n\n"
        f"Users: {stats.users}\n"
        f"Videos: {stats.videos}\n"
        f"In: {human_size(stats.bytes_in)}\n"
        f"Out: {human_size(stats.bytes_out)}\n"
        f"Saved: {human_size(max(0, stats.bytes_in - stats.bytes_out))}\n"
        f"Active jobs: {active}"
    )

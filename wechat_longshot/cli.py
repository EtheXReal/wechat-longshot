"""Command line entry point: ``wechat-longshot``."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from .types import Rect

app = typer.Typer(
    add_completion=False,
    help="Capture a whole WeChat (macOS) conversation as one long screenshot and a PDF.",
)

_TIME_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d")


def _default_out() -> Path:
    return Path(f"./wechat-longshot-{datetime.now():%Y%m%d-%H%M%S}.pdf")


def _parse_start(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise typer.BadParameter(
        f"cannot read {value!r} as a date/time; try '2026-09-01 10:00' or '2026-09-01T10:00'"
    )


def _parse_region(value: str) -> Rect:
    parts = [p.strip() for p in value.replace(" ", ",").split(",") if p.strip()]
    if len(parts) != 4:
        raise typer.BadParameter(f"--region wants X,Y,W,H (four numbers), got {value!r}")
    try:
        x, y, w, h = (int(p) for p in parts)
    except ValueError:
        raise typer.BadParameter(f"--region wants four integers, got {value!r}") from None
    if w <= 0 or h <= 0:
        raise typer.BadParameter("--region width and height must be positive")
    return Rect(x, y, w, h)


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import PackageNotFoundError, version

        try:
            typer.echo(f"wechat-longshot {version('wechat-longshot')}")
        except PackageNotFoundError:
            typer.echo("wechat-longshot (development)")
        raise typer.Exit()


@app.command()
def main(
    from_: Annotated[
        str | None,
        typer.Option(
            "--from",
            metavar="DATETIME",
            help="Start at the first message on/after this time, e.g. '2026-09-01 10:00'.",
        ),
    ] = None,
    from_current: Annotated[
        bool,
        typer.Option("--from-current", help="Start from whatever is on screen now (default)."),
    ] = False,
    out: Annotated[
        Path | None,
        typer.Option("-o", "--out", help="Output PDF path."),
    ] = None,
    page_mode: Annotated[
        str,
        typer.Option("--page-mode", help="'long' for one tall page, 'a4' for A4 pages."),
    ] = "long",
    region: Annotated[
        str | None,
        typer.Option("--region", metavar="X,Y,W,H", help="Message area override, in image pixels."),
    ] = None,
    step: Annotated[
        float,
        typer.Option("--step", help="Scroll step as a fraction of the region height."),
    ] = 0.6,
    max_pages: Annotated[
        int,
        typer.Option("--max-pages", help="Safety limit on the number of scroll steps."),
    ] = 500,
    keep_png: Annotated[
        bool,
        typer.Option("--keep-png", help="Also keep the stitched PNG next to the PDF."),
    ] = False,
    debug_dir: Annotated[
        Path | None,
        typer.Option("--debug-dir", help="Write every captured frame here for debugging."),
    ] = None,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Capture the currently open WeChat conversation."""
    if from_ and from_current:
        raise typer.BadParameter("--from and --from-current are mutually exclusive")
    if page_mode not in ("long", "a4"):
        raise typer.BadParameter("--page-mode must be 'long' or 'a4'")
    if not 0 < step <= 1:
        raise typer.BadParameter("--step must be in (0, 1]")
    if max_pages <= 0:
        raise typer.BadParameter("--max-pages must be positive")

    start = _parse_start(from_) if from_ else None

    # imported lazily so `--help` and `--version` work without the capture stack
    import logging

    from . import pipeline
    from .errors import WeChatLongshotError

    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    opts = pipeline.Options(
        start=start,
        out=out or _default_out(),
        page_mode=page_mode,
        region=_parse_region(region) if region else None,
        step_fraction=step,
        max_pages=max_pages,
        keep_png=keep_png,
        debug_dir=debug_dir,
    )

    try:
        result = pipeline.run(opts)
    except WeChatLongshotError as exc:  # clean message instead of a traceback
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None

    typer.echo(str(result))


if __name__ == "__main__":
    app()

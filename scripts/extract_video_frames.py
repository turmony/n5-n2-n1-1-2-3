# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "av>=15,<17",
#   "pillow>=11,<13",
# ]
# ///
"""Extract multiple video frames with targeted seeks and build a contact sheet.

This is the shared frame-screening tool for video grammar cards. Run it with
``uv run`` so the inline dependencies are resolved without relying on a system
Python installation.
"""

from __future__ import annotations

import argparse
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Capture:
    requested_seconds: float
    actual_seconds: float
    image: Any
    path: Path


def parse_times(values: Sequence[str]) -> list[float]:
    """Parse space- or comma-separated timestamps into sorted unique seconds."""
    times: set[float] = set()
    for value in values:
        for item in value.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                seconds = float(item)
            except ValueError as exc:
                raise argparse.ArgumentTypeError(f"无效时间点：{item!r}") from exc
            if not math.isfinite(seconds) or seconds < 0:
                raise argparse.ArgumentTypeError(f"时间点必须是非负有限数值：{item!r}")
            times.add(seconds)
    if not times:
        raise argparse.ArgumentTypeError("至少需要一个时间点")
    return sorted(times)


def validate_lesson(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise argparse.ArgumentTypeError("课程序号只能包含字母、数字、下划线和连字符")
    return value


def frame_filename(seconds: float) -> str:
    return f"t{seconds:06.2f}.png"


def output_paths(output_root: Path, lesson: str) -> tuple[Path, Path]:
    return output_root / f"f{lesson}", output_root / f"f{lesson}-contact.png"


def extract_frames(
    video: Path, times: Sequence[float], output_dir: Path
) -> list[Capture]:
    """Seek to each timestamp and save the first decodable frame at/after it."""
    import av

    output_dir.mkdir(parents=True, exist_ok=True)
    captures: list[Capture] = []
    with av.open(str(video)) as container:
        if not container.streams.video:
            raise ValueError(f"视频中没有可用的视频流：{video}")
        stream = container.streams.video[0]
        if stream.time_base is None:
            raise ValueError(f"视频流没有可用的时间基准：{video}")
        for requested_seconds in times:
            container.seek(
                int(requested_seconds / stream.time_base),
                stream=stream,
                backward=True,
                any_frame=False,
            )
            capture = None
            for frame in container.decode(stream):
                if frame.pts is None or frame.time_base is None:
                    continue
                actual_seconds = float(frame.pts * frame.time_base)
                if actual_seconds < requested_seconds:
                    continue
                image = frame.to_image()
                path = output_dir / frame_filename(requested_seconds)
                image.save(path)
                capture = Capture(requested_seconds, actual_seconds, image.copy(), path)
                captures.append(capture)
                break
            if capture is None:
                raise ValueError(f"时间点超出视频可解码范围：{requested_seconds:g}s")
    return captures


def build_contact_sheet(
    captures: Sequence[Capture],
    output: Path,
    *,
    columns: int = 4,
    thumb_width: int = 480,
) -> None:
    from PIL import Image, ImageDraw

    if columns < 1:
        raise ValueError("联系表列数必须大于零")
    if thumb_width < 80:
        raise ValueError("缩略图宽度不能小于80像素")
    if not captures:
        raise ValueError("没有可用于联系表的截图")

    first_width, first_height = captures[0].image.size
    thumb_height = max(1, round(thumb_width * first_height / first_width))
    label_height = 28
    rows = math.ceil(len(captures) / columns)
    sheet = Image.new(
        "RGB",
        (columns * thumb_width, rows * (thumb_height + label_height)),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    for index, capture in enumerate(captures):
        image = capture.image.copy()
        image.thumbnail((thumb_width, thumb_height))
        x = (index % columns) * thumb_width
        y = (index // columns) * (thumb_height + label_height)
        sheet.paste(image, (x, y))
        draw.text(
            (x + 6, y + thumb_height + 5),
            f"requested {capture.requested_seconds:g}s | frame {capture.actual_seconds:.2f}s",
            fill="black",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"必须是整数：{value!r}") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("数值必须大于零")
    return parsed


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="一次解码视频并截取多个时间点；默认在五帧以上时生成联系表。"
    )
    result.add_argument("--video", type=Path, required=True, help="本地视频文件")
    result.add_argument(
        "--lesson", type=validate_lesson, required=True, help="用于输出命名的课程序号"
    )
    result.add_argument(
        "--times",
        nargs="+",
        required=True,
        metavar="SECONDS",
        help="时间点；可用空格或逗号分隔，例如：1 15 30 或 1,15,30",
    )
    result.add_argument(
        "--output-root",
        type=Path,
        default=Path(".firecrawl"),
        help="输出根目录；默认 .firecrawl",
    )
    result.add_argument(
        "--columns", type=positive_int, default=4, help="联系表列数；默认4"
    )
    result.add_argument(
        "--thumb-width",
        type=positive_int,
        default=480,
        help="联系表缩略图宽度；默认480",
    )
    result.add_argument(
        "--contact-sheet",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="强制生成或禁用联系表；未指定时五帧以上自动生成",
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        times = parse_times(args.times)
    except argparse.ArgumentTypeError as exc:
        parser().error(str(exc))
    if not args.video.is_file():
        parser().error(f"视频文件不存在：{args.video}")

    output_dir, contact_path = output_paths(args.output_root, args.lesson)
    try:
        captures = extract_frames(args.video, times, output_dir)
        make_contact = args.contact_sheet is True or (
            args.contact_sheet is None and len(captures) > 4
        )
        if make_contact:
            build_contact_sheet(
                captures,
                contact_path,
                columns=args.columns,
                thumb_width=args.thumb_width,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        parser().exit(1, f"错误：{exc}\n")

    for capture in captures:
        print(
            f"{capture.path} | requested={capture.requested_seconds:g}s "
            f"actual={capture.actual_seconds:.2f}s size={capture.image.size[0]}x{capture.image.size[1]}"
        )
    if make_contact:
        print(f"{contact_path} | contact-sheet={len(captures)} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

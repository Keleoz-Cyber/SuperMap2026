"""像素分析：非背景像素统计 + 相邻步骤像素差（排除左上面板掩码）。

用法：python analyze_pixels.py <evidence_dir> <step1,step2,...>
输出 JSON 到 stdout 并写 <evidence_dir>/pixel-stats.json。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

# 面板区域（左上控件+状态区，44% 宽、约 60% 高，另加余量）
PANEL = (0, 0, 680, 560)


def load_masked(path: Path, size: tuple[int, int]):
    img = Image.open(path).convert("RGB").resize(size)
    px = img.load()
    w, h = img.size
    points = []
    for y in range(h):
        for x in range(w):
            if PANEL[0] <= x <= PANEL[2] and PANEL[1] <= y <= PANEL[3]:
                continue
            points.append(px[x, y])
    return points


def non_background_count(points, thresh: int = 12) -> int:
    return sum(1 for r, g, b in points if r > thresh or g > thresh or b > thresh)


def diff_count(a, b, thresh: int = 10) -> int:
    return sum(
        1
        for (r1, g1, b1), (r2, g2, b2) in zip(a, b)
        if abs(r1 - r2) > thresh or abs(g1 - g2) > thresh or abs(b1 - b2) > thresh
    )


def main() -> None:
    out_dir = Path(sys.argv[1])
    steps = sys.argv[2].split(",")
    size = (1440, 900)
    stats = {"dir": str(out_dir), "panel_mask": PANEL, "steps": {}}
    images = {s: load_masked(out_dir / f"{s}.png", size) for s in steps}
    for s, pts in images.items():
        stats["steps"][s] = {"non_background_pixels": non_background_count(pts), "total_pixels": len(pts)}
    stats["diffs"] = {}
    for prev, cur in zip(steps, steps[1:]):
        stats["diffs"][f"{prev}->{cur}"] = diff_count(images[prev], images[cur])
    (out_dir / "pixel-stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

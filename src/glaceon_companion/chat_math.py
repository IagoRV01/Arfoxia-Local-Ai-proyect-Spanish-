"""Bounded, local math rendering for the desktop transcript (no TeX process)."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
import math
import re
import threading
import uuid

from PIL import Image, ImageDraw

from .markdown_regions import protect_code, restore_code


MAX_FORMULA_CHARS = 1200
MAX_FORMULAS = 64
MAX_PIXELS = 2_000_000
_lock = threading.Lock()
_delimiters = re.compile(
    r"(?<!\\)\$\$(.+?)(?<!\\)\$\$"
    r"|(?<!\\)\\\[(.+?)(?<!\\)\\\]"
    r"|(?<!\\)\\\(([^\n]+?)(?<!\\)\\\)"
    r"|(?<![\\$])\$(?![\s$])([^\n$]+?)(?<![\\\s])\$(?![\d$])",
    re.DOTALL,
)


@dataclass(frozen=True)
class MathImage:
    source: str
    png: bytes
    width: float
    height: float


def _math_parts(expression: str):
    """Split top-level boxed results, keeping each part's math baseline."""
    start = index = depth = 0
    while index < len(expression):
        if depth == 0 and expression.startswith(r"\boxed{", index):
            if index > start:
                yield expression[start:index], False
            end = index + 7
            nesting = 1
            while end < len(expression) and nesting:
                if expression[end] == "{" and expression[end - 1] != "\\":
                    nesting += 1
                elif expression[end] == "}" and expression[end - 1] != "\\":
                    nesting -= 1
                end += 1
            if nesting:
                raise ValueError("Unclosed box")
            yield expression[index + 7:end - 1], True
            start = index = end
            continue
        if expression[index] == "{" and (index == 0 or expression[index - 1] != "\\"):
            depth += 1
        elif expression[index] == "}" and (index == 0 or expression[index - 1] != "\\"):
            depth -= 1
        index += 1
    if start < len(expression):
        yield expression[start:], False


def _raster(expression: str, point_size: int, nesting: int = 0):
    # Imports are lazy: non-mathematical chats don't pay the renderer startup cost.
    from matplotlib.font_manager import FontProperties
    from matplotlib.mathtext import MathTextParser
    import numpy as np

    if nesting > 8:
        raise ValueError("Too many nested boxes")
    pieces = []
    color = (237, 250, 255, 255)
    for part, boxed in _math_parts(expression):
        if not part.strip():
            continue
        if boxed:
            tile, descent = _raster(part, point_size, nesting + 1)
            padded = Image.new("RGBA", (tile.width + 16, tile.height + 12))
            padded.alpha_composite(tile, (8, 6))
            ImageDraw.Draw(padded).rectangle((1, 1, padded.width - 2, padded.height - 2), outline=color, width=2)
            tile, descent = padded, descent + 6
        else:
            prop = FontProperties(size=point_size, math_fontfamily="dejavusans")
            formula = "$" + part + "$"
            bounds = MathTextParser("path").parse(formula, dpi=192, prop=prop)
            if bounds.width > 6000 or bounds.height > 1500 or bounds.width * bounds.height > MAX_PIXELS:
                raise ValueError("Formula too large")
            parsed = MathTextParser("agg").parse(formula, dpi=192, prop=prop)
            alpha = Image.fromarray(np.asarray(parsed.image).copy())
            tile = Image.new("RGBA", alpha.size, color)
            tile.putalpha(alpha)
            descent = math.ceil(parsed.depth)
        pieces.append((tile, descent))
    if not pieces:
        raise ValueError("Empty formula")
    ascent = max(tile.height - descent for tile, descent in pieces)
    descent = max(depth for _, depth in pieces)
    width = sum(tile.width for tile, _ in pieces)
    height = ascent + descent
    if width > 6000 or height > 1500 or width * height > MAX_PIXELS:
        raise ValueError("Formula too large")
    output = Image.new("RGBA", (width + 4, height + 4))
    x = 2
    for tile, depth in pieces:
        output.alpha_composite(tile, (x, 2 + ascent - (tile.height - depth)))
        x += tile.width
    return output, descent + 2


@lru_cache(maxsize=128)
def render_math(expression: str, display: bool = False) -> tuple[bytes, float, float] | None:
    """Render a supported expression, or leave unsupported input readable."""
    if not expression.strip() or len(expression) > MAX_FORMULA_CHARS:
        return None
    # Keep parser recursion and expensive layout bounded, even on model output.
    if expression.count("{") > 80 or expression.count("\\") > 160:
        return None
    try:
        with _lock:
            output, _ = _raster(" ".join(expression.splitlines()), 12 if display else 11)
            buffer = BytesIO()
            output.save(buffer, format="PNG")
            return buffer.getvalue(), output.width / 2, output.height / 2
    except (ValueError, RuntimeError, RecursionError, OverflowError):
        return None


def prepare_math_markdown(source: str) -> tuple[str, dict[str, MathImage]]:
    """Mask rendered formulas before Markdown consumes their escapes/tables."""
    if not any(marker in source for marker in ("$", r"\(", r"\[")):
        return source, {}
    masked, code = protect_code(source)
    images: dict[str, MathImage] = {}
    nonce = uuid.uuid4().hex
    attempts = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal attempts
        if attempts >= MAX_FORMULAS:
            return match.group()
        attempts += 1
        expression = next(group for group in match.groups() if group is not None)
        # Escaped Markdown labels/parentheses are not automatically mathematics.
        if (match.group(2) or match.group(3)) and (
            "://" in expression or not re.search(r"[\\^_=+*/\d-]|^[a-zA-Z]{1,2}$", expression)
        ):
            return match.group()
        # Avoid pairing currency amounts such as '$20 and $30'.
        if match.group(4) and re.match(r"^\d[\d.,]*\s+[A-Za-zÁÉÍÓÚáéíóú]", expression):
            return match.group()
        rendered = render_math(expression, bool(match.group(1) or match.group(2)))
        if rendered is None:
            # Protect rejected LaTeX from Markdown's backslash/underscore rules.
            key = f"ARFOXIAUNRENDERED{nonce}X{attempts}END"
            code[key] = re.sub(r"([\\`*_{}\[\]()#$|])", r"\\\1", match.group())
            return key
        key = f"ARFOXIAMATH{nonce}X{attempts}END"
        images[key] = MathImage(match.group(), *rendered)
        return key

    masked = _delimiters.sub(replace, masked)
    return restore_code(masked, code), images

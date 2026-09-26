from io import BytesIO

from PIL import Image
import pytest

from glaceon_companion.chat_math import MAX_FORMULAS, prepare_math_markdown, render_math


SCREENSHOT_MARKDOWN = r"""# Cálculo paso a paso con números

**Expresión:** $\sqrt{2\;\cdot\;\sqrt{2^2}\;\cdot\;\sqrt{2}\;\cdot\;\sqrt{4}}$

**Paso 1 – Simplificar cada raíz interior:**

| Término | Valor |
| --- | --- |
| $\sqrt{2^2} = \sqrt{4}$ | 2 |
| $\sqrt{2}$ | ≈ **1.4142** |
| $\sqrt{4}$ | 2 |

**Paso 2 – Multiplicar todo lo de dentro:**

$$2\;\cdot\;2\;\cdot\;1.4142\;\cdot\;2 = 11.3137$$

**Paso 3 – Aplicar la raíz exterior:**

$$\sqrt{11.3137}\approx\boxed{3.3636}$$

---

**Comprobación rápida:** $2^{7/4} = 2^{(4+3)/4}$
"""


def test_all_screenshot_formulas_render():
    markdown, images = prepare_math_markdown(SCREENSHOT_MARKDOWN)
    assert len(images) == 7
    assert r"\sqrt" not in markdown
    assert "| Término | Valor |" in markdown
    for key, formula in images.items():
        assert key in markdown
        image = Image.open(BytesIO(formula.png))
        assert image.format == "PNG"
        assert image.mode == "RGBA"
        assert image.getbbox()
        assert formula.width == image.width / 2
        assert formula.height == image.height / 2


@pytest.mark.parametrize("source", [
    r"$x^2$", r"$$\frac{1}{2}$$", r"\(\sqrt[3]{8}\)",
    r"\[\sum_{i=1}^{n}i\]", "$$\n\\frac{a}{b}\n$$",
    r"$\boxed{\frac{1}{\sqrt{2}}}+x$",
    r"$x=\boxed{1}+\boxed{2}$", r"$\boxed{\boxed{2}}$",
    r"$\text{Resultado}\;\approx 3.36$",
])
def test_delimiters_and_common_notation(source):
    _, images = prepare_math_markdown(source)
    assert len(images) == 1
    assert next(iter(images.values())).source == source


@pytest.mark.parametrize("source", [
    r"`$\sqrt{2}$`", "```latex\n$$x^2$$\n```", "    $x^2$\n",
    "> ```latex\n> $x^2$\n> ```", "```\n$x^2$",
    r"Cuesta $20 y $30; ahorra $5.", r"Cuesta \$20 y \$30.",
    r"Sin cerrar $x^2", "no formulas", "$$$$", "$ $",
    r"\[abrir\]\(https://example.com\)",
])
def test_code_currency_and_unclosed_input_are_unchanged(source):
    assert prepare_math_markdown(source) == (source, {})


@pytest.mark.parametrize("formula", [
    r"\unknown{a}", r"\input{C:/Windows/win.ini}", r"\includegraphics{https://example.com/a.png}",
    r"\boxed{a", "x" * 1201, "{" * 81, r"\hspace{999999999}",
])
def test_unsupported_and_excessive_input_falls_back(formula):
    assert render_math(formula) is None


def test_message_formula_budget():
    _, images = prepare_math_markdown(" $x^2$ " * (MAX_FORMULAS + 10))
    assert len(images) == MAX_FORMULAS


def test_repeated_math_uses_cache():
    render_math.cache_clear()
    render_math("x+1")
    render_math("x+1")
    assert render_math.cache_info().hits == 1

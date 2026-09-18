import pytest

from glaceon_companion.browser_routing import extract_explicit_https_urls, filter_untrusted_https_urls
from glaceon_companion.markdown_regions import protect_code, restore_code
from glaceon_companion.ollama_client import clean_model_text


def test_model_cleanup_preserves_markdown_indentation_and_hard_breaks():
    source = '    import "https://cdn.example/a";\n    // next line  '
    assert clean_model_text(source) == source
    assert filter_untrusted_https_urls(clean_model_text(source), ()) == source
    assert clean_model_text("texto  \notro  ") == "texto  \notro  "


@pytest.mark.parametrize("code", [
    '```html\n<script type="module">\nimport * as THREE from "https://cdn.example/three.js";\n</script>\n```',
    '````md\n```js\nhttps://cdn.example/a\n```\n````',
    '~~~js\nconst url = "https://cdn.example/a";\n~~~',
    '```js\nconst url = "https://cdn.example/a";',
    '    import "https://cdn.example/a";\n    // <tag>&literal',
    '> ```js\n> import "https://cdn.example/a";\n> ```',
    '`https://cdn.example/a`',
    '``https://cdn.example/a ` nested``',
    '- example `https://cdn.example/a`',
    '```js\r\nconst url="https://cdn.example/a";\r\n```',
    'before\u2028text\n\n```js\nhttps://cdn.example/a\n```',
])
def test_literal_code_survives_source_filter_exactly(code):
    assert filter_untrusted_https_urls(code, ()) == code
    masked, replacements = protect_code(code)
    assert "https://cdn.example" not in masked
    assert restore_code(masked, replacements) == code


def test_only_code_is_exempt_not_prose_links():
    text = '`https://cdn.example/a` and [inventado](https://fake.example/a)\n\n```js\nhttps://cdn.example/a\n```\n\nhttps://fake.example/b'
    filtered = filter_untrusted_https_urls(text, ())
    assert '`https://cdn.example/a`' in filtered
    assert '```js\nhttps://cdn.example/a\n```' in filtered
    assert "https://fake.example" not in filtered


@pytest.mark.parametrize("text", [
    r'\`https://fake.example/a\`',
    '`unclosed https://fake.example/a',
    '`not code\n\nhttps://fake.example/a`',
])
def test_escaped_or_unmatched_backticks_do_not_bypass_filter(text):
    assert "https://fake.example" not in filter_untrusted_https_urls(text, ())


@pytest.mark.parametrize("text", [
    'https://example.com/A_(B)',
    '[artículo](https://example.com/A_(B))',
    '[artículo](<https://example.com/A_(B)>)',
    'Fuente (https://example.com/A_(B)).',
])
def test_balanced_parentheses_in_verified_url_are_preserved(text):
    url = "https://example.com/A_(B)"
    filtered = filter_untrusted_https_urls(text, (url,))
    assert url in filtered
    assert "omitido" not in filtered
    assert url in extract_explicit_https_urls(text)

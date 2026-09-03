---
source: Official Docs (ReadTheDocs)
library: nh3
package: nh3
topic: HTML Sanitization API
fetched: 2026-09-03T10:30:00Z
official_docs: https://nh3.readthedocs.io/en/latest/
---

# nh3 - HTML Sanitization API

## Main Functions

### `clean(html, **options)`

Sanitizes an HTML fragment according to the given options.

**Parameters:**
- `html` (str): Input HTML fragment
- All options from `Cleaner()` class (see below)

**Returns:** Sanitized HTML fragment (str)

**Example:**
```python
import nh3
result = nh3.clean("<script>alert('xss')</script><b>safe</b>")
# Returns: '<b>safe</b>'
```

### `clean_text(html, tags=None)` / `escape(html, tags=None)`

HTML-escapes an arbitrary string. Stricter than Python's `html.escape()`.

**Parameters:**
- `html` (str): Input string
- `tags` (set[str], optional): Tags to preserve with no attributes

**Example:**
```python
nh3.escape('Robert"); abuse();//')
# Returns: 'Robert&quot;);&#32;abuse();&#47;&#47;'

nh3.escape('<span>hello <mention>moto</mention>!</span>', tags={'mention'})
# Returns: 'hello <mention>moto</mention>!'
```

### `is_html(html)`

Determines if a string contains HTML.

**Example:**
```python
nh3.is_html("plain text")  # False
nh3.is_html("<p>html!</p>")  # True
```

## Cleaner Class

Create reusable sanitizer instances:

```python
cleaner = nh3.Cleaner(
    tags={"b", "i", "p"},
    attributes={"a": {"href", "title"}},
    link_rel="noopener noreferrer nofollow"
)
result = cleaner.clean("<b>bold</b> <a href='...'>link</a>")
```

## Constants

### `ALLOWED_TAGS`
Default set of allowed tags. Use to customize:
```python
tags = nh3.ALLOWED_TAGS - {"b"}
nh3.clean("<b><i>text</i></b>", tags=tags)
# Returns: '<i>text</i>'
```

### `ALLOWED_ATTRIBUTES`
Default mapping of tags to allowed attributes:
```python
from copy import deepcopy
attributes = deepcopy(nh3.ALLOWED_ATTRIBUTES)
attributes["img"].add("data-invert")
```

### `ALLOWED_URL_SCHEMES`
Default set of permitted URL schemes:
```python
url_schemes = nh3.ALLOWED_URL_SCHEMES - {'tel'}
```
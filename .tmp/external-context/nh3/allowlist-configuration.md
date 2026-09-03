---
source: Official Docs (ReadTheDocs)
library: nh3
package: nh3
topic: Allowlist Configuration
fetched: 2026-09-03T10:30:00Z
official_docs: https://nh3.readthedocs.io/en/latest/
---

# nh3 - Allowlist Configuration

## 1. Allow Specific Tags

**Allow tags: p, br, strong, em, u, ul, ol, li, h3, h4, a, code, pre, blockquote**

```python
import nh3

allowed_tags = {"p", "br", "strong", "em", "u", "ul", "ol", "li", "h3", "h4", "a", "code", "pre", "blockquote"}

# Using clean() function
result = nh3.clean(
    "<p>Paragraph</p><script>alert('xss')</script>",
    tags=allowed_tags
)
# Returns: '<p>Paragraph</p>'

# Using Cleaner class
cleaner = nh3.Cleaner(tags=allowed_tags)
result = cleaner.clean("<h3>Title</h3><iframe>bad</iframe>")
# Returns: '<h3>Title</h3>'
```

## 2. Allow Attributes on Specific Tags

**Allow attributes on `<a>` only: href, title**

```python
# Method 1: Using attributes parameter
result = nh3.clean(
    '<a href="https://example.com" title="Link" class="btn">Click</a>',
    tags={"a"},
    attributes={"a": {"href", "title"}}
)
# Returns: '<a href="https://example.com" title="Link" rel="noopener noreferrer">Click</a>'

# Method 2: Using Cleaner class
cleaner = nh3.Cleaner(
    tags={"a", "p"},
    attributes={"a": {"href", "title"}}
)
result = cleaner.clean('<a href="..." title="..." class="x">Link</a>')
# Returns: '<a href="..." title="..." rel="noopener noreferrer">Link</a>'
```

## 3. Force rel="nofollow noopener noreferrer" and target="_blank" on Links

```python
# Method 1: Using link_rel parameter (default behavior)
result = nh3.clean(
    '<a href="https://example.com">Link</a>',
    tags={"a"},
    attributes={"a": {"href"}},
    link_rel="nofollow noopener noreferrer"
)
# Returns: '<a href="https://example.com" rel="nofollow noopener noreferrer">Link</a>'

# Method 2: To also add target="_blank"
# Note: target must be explicitly allowed in attributes
result = nh3.clean(
    '<a href="https://example.com">Link</a>',
    tags={"a"},
    attributes={"a": {"href", "target"}},
    link_rel="nofollow noopener noreferrer",
    set_tag_attribute_values={"a": {"target": "_blank"}}
)
# Returns: '<a href="https://example.com" target="_blank" rel="nofollow noopener noreferrer">Link</a>'

# Method 3: Using attribute_filter for more control
def add_link_attributes(tag, attr, value):
    if tag == "a":
        if attr == "target":
            return "_blank"
        elif attr == "rel":
            return "nofollow noopener noreferrer"
    return value

result = nh3.clean(
    '<a href="https://example.com">Link</a>',
    tags={"a"},
    attributes={"a": {"href", "target", "rel"}},
    attribute_filter=add_link_attributes
)
```

## 4. Restrict URL Schemes to http, https, mailto

```python
# Method 1: Using url_schemes parameter
allowed_schemes = {"http", "https", "mailto"}
result = nh3.clean(
    '<a href="javascript:alert(1)">Bad</a> <a href="https://example.com">Good</a>',
    tags={"a"},
    attributes={"a": {"href"}},
    url_schemes=allowed_schemes
)
# Returns: '<a rel="noopener noreferrer">Bad</a> <a href="https://example.com" rel="noopener noreferrer">Good</a>'

# Method 2: Using Cleaner class
cleaner = nh3.Cleaner(
    tags={"a"},
    attributes={"a": {"href"}},
    url_schemes={"http", "https", "mailto"}
)
result = cleaner.clean('<a href="data:text/html,<script>alert(1)</script>">XSS</a>')
# Returns: '<a rel="noopener noreferrer">XSS</a>'
```

## 5. Strip Dangerous Elements and Attributes

**Automatically strips:**
- `<script>`, `<style>`, `<iframe>` tags
- `on*` event handlers (onclick, onerror, etc.)
- `javascript:` URLs
- `data:` URLs (unless explicitly allowed)

```python
# Default behavior - these are stripped automatically
result = nh3.clean('''
    <script>alert('xss')</script>
    <style>body{background:url('javascript:alert(1)')}</style>
    <img src="x" onerror="alert(1)">
    <a href="javascript:alert(1)">Click</a>
    <iframe src="https://evil.com"></iframe>
''')
# Returns: '<img src="x"> <a rel="noopener noreferrer">Click</a>'

# To explicitly deny data: URLs (they're denied by default)
result = nh3.clean(
    '<a href="data:text/html,<script>alert(1)</script>">XSS</a>',
    url_schemes={"http", "https", "mailto"}  # data: not in allowed schemes
)
# Returns: '<a rel="noopener noreferrer">XSS</a>'
```

## 6. Advanced Configuration Examples

### Combine all requirements:
```python
import nh3

# Configuration matching all user requirements
cleaner = nh3.Cleaner(
    tags={"p", "br", "strong", "em", "u", "ul", "ol", "li", "h3", "h4", "a", "code", "pre", "blockquote"},
    attributes={
        "*": set(),  # No attributes on any tag by default
        "a": {"href", "title", "target"}  # Only these attributes on <a>
    },
    link_rel="nofollow noopener noreferrer",
    url_schemes={"http", "https", "mailto"},
    set_tag_attribute_values={"a": {"target": "_blank"}}
)

# Test the configuration
html = '''
<p>Paragraph with <strong>bold</strong> and <em>italic</em></p>
<a href="https://example.com" title="Example">Link</a>
<script>alert('xss')</script>
<a href="javascript:alert(1)">Bad Link</a>
<iframe src="https://evil.com"></iframe>
'''

result = cleaner.clean(html)
# Returns: '<p>Paragraph with <strong>bold</strong> and <em>italic</em></p>\n<a href="https://example.com" title="Example" target="_blank" rel="nofollow noopener noreferrer">Link</a>'
```

### Using Default Constants with Customization:
```python
from copy import deepcopy

# Start with defaults and customize
tags = nh3.ALLOWED_TAGS & {"p", "br", "strong", "em", "u", "ul", "ol", "li", "h3", "h4", "a", "code", "pre", "blockquote"}
attributes = deepcopy(nh3.ALLOWED_ATTRIBUTES)
# Remove all attributes except for <a>
for tag in attributes:
    if tag != "a":
        attributes[tag] = set()
attributes["a"] = {"href", "title"}

result = nh3.clean(html, tags=tags, attributes=attributes)
```
---
source: Official Docs (ReadTheDocs)
library: nh3
package: nh3
topic: Installation and Basic Usage
fetched: 2026-09-03T10:30:00Z
official_docs: https://nh3.readthedocs.io/en/latest/
---

# nh3 - Installation and Basic Usage

## Installation

```bash
pip install nh3
```

## Basic Usage

The `clean()` function sanitizes HTML fragments:

```python
import nh3

# Basic sanitization
nh3.clean("<unknown>hi")
# Returns: 'hi'

# Removes dangerous attributes
nh3.clean("<b><img src='' onerror='alert(\\'hax\\')'>XSS?</b>")
# Returns: '<b><img src="">XSS?</b>'

# Allow only specific tags
nh3.clean("<b><a href='https://example.com'>Hello</a></b>", tags={"b"})
# Returns: '<b>Hello</b>'
```

## Performance vs bleach

Benchmark on MacBook Air (M2, 2022):
- **bleach.clean(html)**: 2.85 ms ± 22.8 µs per loop
- **nh3.clean(html)**: 138 µs ± 860 ns per loop

**Result**: nh3 is approximately **20 times faster** than bleach.

## Default Behavior

By default, nh3:
- Allows a comprehensive set of safe HTML tags (see `ALLOWED_TAGS`)
- Allows standard attributes on appropriate tags (see `ALLOWED_ATTRIBUTES`)
- Allows common URL schemes like http, https, mailto (see `ALLOWED_URL_SCHEMES`)
- Strips dangerous elements like `<script>`, `<style>`, event handlers
- Adds `rel="noopener noreferrer"` to links by default
- Removes `javascript:` and `data:` URLs from href/src attributes
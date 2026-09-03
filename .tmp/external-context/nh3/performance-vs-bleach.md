---
source: Official Docs (ReadTheDocs) + PyPI
library: nh3
package: nh3
topic: Performance Characteristics vs bleach
fetched: 2026-09-03T10:30:00Z
official_docs: https://nh3.readthedocs.io/en/latest/
---

# nh3 - Performance Characteristics vs bleach

## Performance Benchmark

**Test Environment:** MacBook Air (M2, 2022)
- Python 3.11.0
- Test HTML: Full Google homepage HTML

**Results:**
- **bleach.clean(html)**: 2.85 ms ± 22.8 µs per loop (mean ± std. dev. of 7 runs, 100 loops each)
- **nh3.clean(html)**: 138 µs ± 860 ns per loop (mean ± std. dev. of 7 runs, 10,000 loops each)

**Performance Improvement:** nh3 is approximately **20 times faster** than bleach.

## Why nh3 is Faster

1. **Rust Implementation**: nh3 is a Python binding to the [ammonia](https://github.com/rust-ammonia/ammonia) Rust crate, which provides native-speed HTML sanitization.

2. **Efficient Parsing**: Uses Rust's optimized HTML parsing and DOM manipulation libraries.

3. **Minimal Overhead**: The Python binding has minimal overhead, passing data directly to the Rust implementation.

## Comparison Table

| Feature | nh3 | bleach |
|---------|-----|--------|
| **Performance** | ~138 µs | ~2.85 ms |
| **Speed Ratio** | 20x faster | Baseline |
| **Implementation** | Rust (ammonia) | Python |
| **Maintenance** | Actively maintained | Deprecated |
| **Security** | Modern, secure | Legacy |
| **Features** | Full HTML5 support | Limited |
| **Customization** | Extensive | Basic |

## Memory Usage

nh3 also has better memory characteristics:
- Lower memory footprint due to Rust's efficient memory management
- No Python object overhead for DOM nodes
- Faster garbage collection

## Recommendation

For new projects, **nh3 is strongly recommended** over bleach due to:
1. **20x better performance**
2. **Active maintenance** (bleach is deprecated)
3. **Better security** through modern Rust implementation
4. **More features** and configuration options
5. **Future-proof** with ongoing development

## Migration from bleach

```python
# bleach
import bleach
clean_html = bleach.clean(html, tags=["p", "a", "b"], attributes={"a": ["href"]})

# nh3 equivalent
import nh3
clean_html = nh3.clean(html, tags={"p", "a", "b"}, attributes={"a": {"href"}})
```

Note: nh3 uses sets for tags and attributes instead of lists, and attribute values are sets instead of lists.
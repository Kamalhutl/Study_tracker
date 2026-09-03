# Requirements Pinning

This project pins several dependencies to exact versions to prevent breaking changes that have occurred in the past.

## Why pinned?

- **mypy**: Version 1.20.2 produced `Error constructing plugin instance of NewSemanalDjangoPlugin`, forcing a rollback to 1.11.2. We now pin to 2.3.1 (the current working version).
- **django-stubs**: Version 5.1.0 silently pulled in Django 6.1.1, requiring a force-reinstall of Django 5.2.17. We now pin to 6.1.0.
- **Django**: Pinned to 5.2.17 to ensure compatibility with the stubs and the codebase.
- **nh3**: Pinned to 0.3.7 as it is used for HTML sanitization.

Do not run `mypy --install-types` blindly; it may update these versions. If you need to update a package, update the pin here and verify everything still works.
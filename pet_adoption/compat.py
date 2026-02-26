import sys
from typing import Any


def patch_django_template_context_copy() -> None:
    """
    Django 5.0.x uses copy(super()) in BaseContext.__copy__().
    On Python 3.14 this can return a non-assignable super object.
    """
    if sys.version_info < (3, 14):
        return

    try:
        from django.template.context import BaseContext
    except Exception:
        return

    if getattr(BaseContext.__copy__, "__name__", "") == "_patched_basecontext_copy":
        return

    def _patched_basecontext_copy(self: Any):
        duplicate = object.__new__(self.__class__)
        duplicate.__dict__ = self.__dict__.copy()
        duplicate.dicts = self.dicts[:]
        return duplicate

    BaseContext.__copy__ = _patched_basecontext_copy

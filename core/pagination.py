"""Pagination: page-number with a cursor-ish consistent response shape."""

from typing import Any

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class CursorAwarePageNumberPagination(PageNumberPagination):
    """PageNumberPagination with ``page_size`` query param.

    Response shape: {"count", "next", "previous", "results"} — every list
    endpoint in the app keeps this shape, so later steps (jobs, exams)
    can rely on it.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data: Any) -> Response:
        assert self.page is not None
        return Response(
            {
                "count": self.page.paginator.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )

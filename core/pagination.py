"""Pagination classes used across the API."""

from rest_framework import pagination


class StandardPagination(pagination.PageNumberPagination):
    """Page-number pagination for small, bounded collections (members, cards)."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class CursorTransactionPagination(pagination.CursorPagination):
    """
    Cursor pagination for the (unbounded, append-only) transaction ledger.

    Offset pagination degrades linearly on large ledgers (`OFFSET n` walks n
    rows) and breaks when new rows arrive between pages; a cursor on
    `(created_at, id)` stays O(log n) and stable.
    """

    page_size = 50
    ordering = "-created_at"
    page_size_query_param = "page_size"
    max_page_size = 200

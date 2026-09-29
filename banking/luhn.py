"""Luhn-algorithm helpers for demo card numbers."""

import secrets


def luhn_checksum_valid(number: str) -> bool:
    digits = [int(d) for d in number]
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    total = sum(odd_digits)
    for d in even_digits:
        total += sum(divmod(d * 2, 10))
    return total % 10 == 0


def generate_luhn_number(prefix: str, length: int = 16) -> str:
    """Generate a Luhn-valid number with the given prefix (demo PAN)."""
    body = prefix
    while len(body) < length - 1:
        body += str(secrets.randbelow(10))
    payload = [int(d) for d in body]
    # Append a check digit that makes the whole number Luhn-valid. In the
    # final number the body's odd positions (from the right) become even
    # positions — those are the digits that get doubled.
    doubled = sum(sum(divmod(d * 2, 10)) for d in payload[-1::-2])
    single = sum(payload[-2::-2])
    check_digit = (10 - (doubled + single) % 10) % 10
    return body + str(check_digit)

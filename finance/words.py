"""Rupee amounts in words, Indian style (thousand, lakh, crore), as printed on bills."""

from decimal import ROUND_HALF_UP, Decimal

ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
        "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _below_hundred(n):
    if n < 20:
        return ONES[n]
    return f"{TENS[n // 10]} {ONES[n % 10]}".strip()


def _below_thousand(n):
    hundreds, rest = divmod(n, 100)
    parts = [f"{ONES[hundreds]} Hundred"] if hundreds else []
    if rest:
        parts.append(_below_hundred(rest))
    return " ".join(parts)


def number_in_words(n):
    """5574 -> 'Five Thousand Five Hundred Seventy Four'; 1234567 -> 'Twelve Lakh Thirty Four Thousand ...'."""
    if n == 0:
        return "Zero"
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(f"{number_in_words(crore)} Crore")
    if lakh:
        parts.append(f"{_below_hundred(lakh)} Lakh")
    if thousand:
        parts.append(f"{_below_hundred(thousand)} Thousand")
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def rupees_in_words(amount):
    """Decimal('5574.00') -> 'Five Thousand Five Hundred Seventy Four Rupees Only' (paise added when present)."""
    amount = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rupees, paise = divmod(int(abs(amount) * 100), 100)
    words = f"{number_in_words(rupees)} Rupees"
    if paise:
        words += f" and {_below_hundred(paise)} Paise"
    return f"{words} Only"

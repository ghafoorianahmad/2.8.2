"""Number -> Persian words (grand total on the invoice cards)."""
import pytest

from app.cards.numwords import amount_in_words, number_to_words_fa


@pytest.mark.parametrize("n,words", [
    (0, "صفر"),
    (1, "یک"),
    (10, "ده"),
    (11, "یازده"),
    (19, "نوزده"),
    (20, "بیست"),
    (21, "بیست و یک"),
    (99, "نود و نه"),
    (100, "صد"),
    (101, "صد و یک"),
    (115, "صد و پانزده"),
    (200, "دویست"),
    (999, "نهصد و نود و نه"),
    (1000, "هزار"),
    (1001, "هزار و یک"),
    (2000, "دو هزار"),
    (12_345, "دوازده هزار و سیصد و چهل و پنج"),
    (450_000, "چهارصد و پنجاه هزار"),
    (1_000_000, "یک میلیون"),
    (525_000_000, "پانصد و بیست و پنج میلیون"),
    (81_250_000, "هشتاد و یک میلیون و دویست و پنجاه هزار"),
    (118_900_000, "صد و هجده میلیون و نهصد هزار"),
    (1_000_000_000, "یک میلیارد"),
    (1_234_567_891, "یک میلیارد و دویست و سی و چهار میلیون و پانصد و شصت و هفت هزار و هشتصد و نود و یک"),
    (2_500_000_000_000, "دو هزار و پانصد میلیارد"),
])
def test_number_to_words(n, words):
    assert number_to_words_fa(n) == words


def test_inputs_are_normalised():
    assert number_to_words_fa("525000000") == "پانصد و بیست و پنج میلیون"
    assert number_to_words_fa(1500.4) == "هزار و پانصد"      # decimals are rounded
    assert number_to_words_fa(None) == ""
    assert number_to_words_fa("abc") == ""
    assert number_to_words_fa(-5) == ""


def test_amount_in_words_adds_the_currency():
    assert amount_in_words(525_000_000) == "پانصد و بیست و پنج میلیون ریال"
    assert amount_in_words(None) == ""

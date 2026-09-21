# -*- coding: utf-8 -*-
"""Content filtering shared by live, VOD and series screens."""

import re

from .compat import native

_ADULT = re.compile(
    r'(^|[\s|._+\-/])(adult|xxx|porn|porno|erotic|18\+|18plus|playboy)'
    r'([\s|._+\-/]|$)', re.I)


def is_adult(item):
    text = ' '.join(native(getattr(item, key, '') or '')
                    for key in ('name', 'group', 'plot'))
    return bool(_ADULT.search(text))


def allowed(items, show_adult=False):
    values = list(items or [])
    if show_adult:
        return values
    return [item for item in values if not is_adult(item)]

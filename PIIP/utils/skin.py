# -*- coding: utf-8 -*-
#
# PIIP — IPTV player with live Persian audio translation
# Copyright (c) 2026 Routekernel. All rights reserved.
#
# Telegram : https://t.me/routekernel1
# YouTube  : https://youtube.com/@routekernel
# Project  : https://github.com/dreamboxone/piip
#
# Licensed under the PIIP End User Licence Agreement; see LICENSE.
# Unauthorised reverse engineering or removal of this notice is prohibited.
#
"""One place for the look of every screen.

Enigma2 colours are #TTRRGGBB where the first byte is TRANSPARENCY: 00 is
opaque and ff is invisible. Getting that backwards paints over the video
layer, which is why it is spelled out here rather than left to each skin.

Screens are written for 1920x1080 and scaled down for 1280x720 boxes, so
positions are declared once and converted.
"""

from .compat import native

# ------------------------------------------------------------- palette

ACCENT = '#00d4ff'          # cyan, used for titles and rules
ACCENT_WARM = '#c8a020'     # amber, for the settings chip
TEXT = '#ffffff'
TEXT_DIM = '#a8b2c0'
TEXT_FAINT = '#6b7688'

PANEL = '#d0181e28'         # translucent dark blue-grey dialog ground
HEADER = '#0d1b2a'          # solid header/footer bar
SCRIM = '#90000000'         # dim sheet over a full-screen background
TRANSPARENT = '#ff000000'   # fully see-through: video shows underneath
OPAQUE = '#000000'          # the ground that hides the video layer
OPAQUE_INNER = '#00000000'  # the dark middle of an outlined chip
LIST_SCRIM = '#95000000'    # a list screen's sheet over its wallpaper
HINT_PILL = '#20ffffff'     # the pale key-hint tab in a footer
HINT_TEXT = '#101010'       # and the near-black it is written in

LIST_BG = '#181e28'
LIST_FG = '#dde4ee'
LIST_FG_SEL = '#ffffff'
LIST_BG_SEL = '#1e5799'

ZAP_GROUND = '#d0000000'
ZAP_HEADER = '#1a2533'
ZAP_LIST_BG = '#101010'
ZAP_LIST_FG = '#d0d0d0'
ZAP_LIST_BG_SEL = '#2a3f5f'

BTN_RED = '#ff0000'
BTN_DELETE = '#7a1a1a'      # the reference's DELETE chip
BTN_IMPORT = '#1a7a1a'      # and its IMPORT chip
BTN_GREEN = '#1a7a3a'
BTN_GREY = '#555555'
BTN_BLUE = '#1e5799'
BTN_PURPLE = '#31186c'
BTN_TEAL = '#278f80'

HD_SCALE = 1280.0 / 1920.0
NL = chr(10)


def xml_escape(text):
    """Attribute text has to be escaped: a raw < or > breaks the parser."""
    return (native(text)
            .replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def scale(value):
    return int(round(value * HD_SCALE))


def px(*values):
    """Scale a run of numbers for the 720p skin."""
    return [scale(v) for v in values]


# ------------------------------------------------------------ fragments

def chip(text, x, y, colour, width=260, height=56, font=24, fg=TEXT,
         z=2, wide=True, outline=False):
    """A rounded button pill, the way the reference plugin draws them.

    Two shapes, both taken from the reference: the carousel outlines its
    chips - a coloured ring round a dark middle with the text in the same
    colour - while a list screen fills them solid and puts white text on
    top. The text never names the key, so it can never disagree with the
    colour it is sitting on.
    """
    if not wide:
        x, y, width, height, font = (scale(x), scale(y), scale(width),
                                     scale(height), max(14, scale(font)))
    inner_w, inner_h = width - 6, height - 6
    radius = height // 2
    parts = ['<eLabel backgroundColor="%s" cornerRadius="%d" size="%d,%d" '
             'position="%d,%d" zPosition="%d"/>'
             % (colour, radius, width, height, x, y, z)]
    if outline:
        parts.append('<eLabel backgroundColor="%s" cornerRadius="%d" '
                     'size="%d,%d" position="%d,%d" zPosition="%d"/>'
                     % (OPAQUE_INNER, radius, inner_w, inner_h,
                        x + 3, y + 3, z + 1))
    parts.append(
        '<eLabel text="%s" position="%d,%d" size="%d,%d" font="Regular;%d" '
        'halign="center" valign="center" foregroundColor="%s" '
        'transparent="1" zPosition="%d"/>'
        % (xml_escape(text), x + 3, y + 4, inner_w, inner_h, font,
           colour if outline else fg, z + 2))
    return '\n  '.join(parts)


def pill(text, x, y, width=340, height=50, font=24, wide=True):
    """The pale key-hint tab the reference puts at the end of the footer.

    It is painted, not transparent: the reference marks it transparent and
    then writes black on it, which on a dark ground leaves nothing to read.
    """
    if not wide:
        x, y, width, height, font = (scale(x), scale(y), scale(width),
                                     scale(height), max(13, scale(font)))
    return ('<eLabel text="%s" position="%d,%d" size="%d,%d" '
            'backgroundColor="%s" cornerRadius="%d" font="Regular;%d" '
            'halign="center" valign="center" foregroundColor="%s" '
            'transparent="0" zPosition="4"/>'
            % (xml_escape(text), x, y, width, height, HINT_PILL, height // 3,
               font, HINT_TEXT))


def list_screen(name, title, subtitle='', buttons=(), header_widget=None,
                info=(), progress=None, item_height=60, wide=None, hint='',
                backdrop='bg_list.png', layout='center', artwork=False,
                logo_widget=None, detail_logo_widget=None, hint_x=1540,
                hint_width=340, extra=(), rows=None):
    """The standard browsing screen, laid out as the reference lays it out.

    `header_widget`, `info` and `progress` name the widgets the screen will
    create. Enigma2 raises SkinError for any widget missing from the skin
    AND for any widget in the skin the screen never creates, so the caller
    has to declare exactly what it builds - `bg` and `list` come free.
    """
    if wide is None:
        width = desktop_width()
        W, H = ((2560, 1440) if width >= 2560 else
                ((1920, 1080) if width >= 1920 else (1280, 720)))
    else:
        W, H = ((1920, 1080) if wide else (1280, 720))
    factor = W / 1920.0
    q = lambda value: int(round(value * factor))
    wide = W >= 1920

    parts = [
        '<widget name="bg" position="0,0" size="%d,%d" zPosition="0" '
        'scale="stretch" alphatest="on"/>' % (W, H),
        '<eLabel position="0,0" size="%d,%d" backgroundColor="%s" '
        'zPosition="-1"/>' % (W, H, LIST_SCRIM),
        '<eLabel text="%s" position="%d,%d" size="%d,%d" font="Regular;%d" '
        'halign="left" valign="center" foregroundColor="%s" '
        'transparent="1" zPosition="1"/>'
        % (xml_escape(title), q(40), q(15), q(1400), q(40), q(32), ACCENT),
    ]

    # One right-hand slot. A widget when the screen fills it in, otherwise
    # the fixed subtitle - never both, which is what was overlapping.
    right = ('<widget name="%s" ' % header_widget if header_widget
             else '<eLabel text="%s" ' % xml_escape(subtitle))
    if header_widget or subtitle:
        parts.append(
            right + 'position="%d,%d" size="%d,%d" font="Regular;%d" '
            'halign="right" valign="center" foregroundColor="%s" '
            'transparent="1" zPosition="1"/>'
            % (q(1440), q(15), q(440), q(40), q(28),
               TEXT if header_widget else TEXT_FAINT))

    parts.append('<eLabel position="0,%d" size="%d,3" backgroundColor="%s"/>'
                 % (q(65), W, ACCENT))

    if logo_widget:
        # HybridIPTV draws its emblem in a 1150x450 box at centre,80 scaled
        # to fit, i.e. a 450px square in the middle. The widget is that
        # square so LoadPixmap keeps the artwork's aspect on every image.
        parts.append(
            '<widget name="%s" position="%d,%d" size="%d,%d" '
            'alphatest="blend" transparent="1" scale="stretch" '
            'zPosition="3"/>'
            % (logo_widget, (W - q(450)) // 2, q(80), q(450), q(450)))
    if detail_logo_widget:
        parts.append(
            '<widget name="%s" position="%d,%d" size="%d,%d" '
            'alphatest="blend" transparent="1" scale="stretch" '
            'zPosition="3"/>'
            % (detail_logo_widget, q(770), q(90), q(300), q(300)))

    # Hybrid uses three recurring list shapes: a centred browser, a full
    # width manager and a left browser with artwork/EPG information at right.
    if layout == 'full':
        list_x, list_y, list_w, list_h = q(40), q(80), q(1840), q(880)
    elif layout == 'split':
        list_x, list_y, list_w, list_h = q(10), q(75), q(700), q(900)
    elif layout == 'browser':
        list_x, list_y, list_w, list_h = q(460), q(75), q(1000), q(900)
    elif layout == 'lower':
        list_x, list_y, list_w, list_h = q(460), q(550), q(1000), q(280)
    elif layout == 'sources':
        # IPTVOrgBrowserScreen: six 70px rows under the emblem, no status
        # line - its messages go to the header corner.
        list_x, list_y, list_w, list_h = q(460), q(550), q(1000), q(420)
    elif layout == 'setup':
        list_x, list_y, list_w, list_h = q(460), q(500), q(1000), q(300)
    elif layout == 'cover':
        list_x, list_y, list_w, list_h = q(40), q(500), q(1840), q(460)
    elif layout == 'summary':
        # A short action list with a multi-line summary underneath.  The
        # generic browser height left only one 34px line for the summary and
        # placed it behind the footer rule.
        list_x, list_y, list_w, list_h = q(410), q(130), q(1100), q(400)
    else:
        list_x, list_y, list_w, list_h = q(410), q(130), q(1100), q(720)
    if rows:
        # Exactly as tall as its rows, as the reference's setup menus are,
        # so the pane behind it does not hang below the last field.
        list_h = q(item_height) * int(rows)
    if layout in ('lower', 'setup', 'sources'):
        parts.append(list_panel(list_x, list_y, list_w, list_h))
    parts.append(
        '<widget name="list" position="%d,%d" size="%d,%d" '
        'scrollbarMode="showOnDemand" %s itemHeight="%d" transparent="1" '
        'zPosition="4"/>'
        % (list_x, list_y, list_w, list_h, list_attrs(),
           max(26, q(item_height))))

    info_x = q(750) if layout == 'split' else list_x
    info_w = q(1150) if layout == 'split' else list_w
    if layout == 'cover':
        info_x, info_w, y = q(460), q(1400), q(105)
    elif layout == 'summary':
        info_x, info_w, y = list_x, list_w, q(560)
    else:
        y = q(570) if layout == 'split' else list_y + list_h + q(6)
    line_h = q(34)
    if progress:
        bar_h = q(14)
        parts.append(
            '<widget name="%s" position="%d,%d" size="%d,%d" borderWidth="1" '
            'borderColor="%s" foregroundColor="%s" backgroundColor="%s" '
            'zPosition="2"/>'
            % (progress, info_x, y, info_w, bar_h, TEXT_FAINT, ACCENT,
               LIST_BG))
        y += bar_h + q(6)
    for index, widget in enumerate(info):
        colour = TEXT_DIM if index < len(info) - 1 else TEXT_FAINT
        if layout == 'summary' and index == 0:
            this_h = q(240)
        else:
            this_h = (q(180) if layout == 'split' and
                      len(info) > 1 and index == 0 else line_h)
        parts.append(
            '<widget name="%s" position="%d,%d" size="%d,%d" '
            'font="Regular;%d" foregroundColor="%s" transparent="1" '
            'zPosition="2"/>'
            % (widget, info_x, y, info_w, this_h, q(24), colour))
        y += this_h

    if artwork:
        if layout == 'cover':
            poster_pos = (q(40), q(80), q(400), q(400))
            art_pos = (q(1040), q(80), q(820), q(400))
            rating_pos = (q(460), q(70), q(500), q(35))
        else:
            poster_pos = (q(750), q(80), q(280), q(450))
            art_pos = (q(1050), q(80), q(830), q(450))
            rating_pos = (q(750), q(930), q(1150), q(35))
        parts.extend([
            '<widget name="poster" position="%d,%d" size="%d,%d" '
            'alphatest="blend" transparent="1" scale="stretch" zPosition="3"/>' % poster_pos,
            '<widget name="art" position="%d,%d" size="%d,%d" '
            'alphatest="blend" transparent="1" scale="stretch" zPosition="2"/>' % art_pos,
            '<widget name="rating" position="%d,%d" size="%d,%d" font="Regular;%d" '
            'foregroundColor="#f5c518" transparent="1" zPosition="4"/>' %
            (rating_pos + (q(24),)),
        ])

    parts.append('<eLabel position="0,%d" size="%d,2" backgroundColor="%s"/>'
                 % (q(980), W, BTN_BLUE))
    for index, (label, colour) in enumerate(buttons):
        parts.append(chip(label, q(40 + index * 280), q(1006), colour,
                          width=q(260), height=q(56), wide=True, font=q(24)))
    if hint:
        parts.append(pill(hint, q(hint_x), q(1010), width=q(hint_width),
                          height=q(50), font=q(24), wide=True))
    parts.extend(extra)

    return ('<screen name="%s" position="center,center" size="%d,%d" '
            'backgroundColor="%s">\n  %s\n</screen>' %
            (name, W, H, OPAQUE, (NL + '  ').join(parts)))


def list_panel(x, y, width, height):
    """The dark pane HybridIPTV puts behind a list over its wallpaper.

    DreamOS draws it as a vertical gradient; images without ePixmap
    gradients get a flat translucent sheet instead of an unknown attribute.
    """
    if supports_gradient():
        return ('<ePixmap position="%d,%d" size="%d,%d" zPosition="1" '
                'gradient="#00000000,#FF000000,verticalCentered"/>'
                % (x, y, width, height))
    return ('<eLabel position="%d,%d" size="%d,%d" zPosition="1" '
            'backgroundColor="#60000000"/>' % (x, y, width, height))


def supports_gradient():
    try:
        from enigma import ePixmap
        return hasattr(ePixmap, 'GRADIENT_VERTICAL_CENTERED')
    except Exception:
        return False


_MULTICONTENT = []


def _multicontent():
    """What this image's list-template syntax accepts.

    A TemplatedMultiContent template is evaluated as one expression, so a
    single argument the image does not know makes the whole list render
    empty while the rest of the screen looks fine. Older images have no
    MultiContentTemplateColor, and their pixmap entry takes no scale_flags.
    """
    if _MULTICONTENT:
        return _MULTICONTENT[0]
    result = _probe_multicontent()
    _MULTICONTENT.append(result)
    try:
        from .uisafe import note
        note('skin', 'list templates: colour=%s scaling=%s'
             % ('yes' if result[0] else 'no', result[1] or 'none'))
    except Exception:
        pass
    return result


def _probe_multicontent():
    color = False
    scale = ''
    try:
        __import__('Components.MultiContent')
        import sys as _sys
        MultiContent = _sys.modules['Components.MultiContent']
    except Exception:
        return color, scale
    color = hasattr(MultiContent, 'MultiContentTemplateColor')
    entry = getattr(MultiContent, 'MultiContentEntryPixmapAlphaTest', None)
    names = ()
    if entry is not None:
        try:
            import inspect
            spec = getattr(inspect, 'getfullargspec', None) or inspect.getargspec
            names = tuple(spec(entry).args or ())
        except Exception:
            names = ()
    try:
        import enigma
    except Exception:
        return color, scale
    if 'scale_flags' in names and hasattr(enigma, 'SCALE_STRETCH'):
        scale = ', scale_flags=__import__("enigma").SCALE_STRETCH'
    elif 'flags' in names and hasattr(enigma, 'BT_SCALE'):
        # What the same images used before scale_flags existed.
        scale = ', flags=__import__("enigma").BT_SCALE'
    return color, scale


def template_color(colour):
    """`color=...` for a template entry, or nothing where it is unknown."""
    return (', color=MultiContentTemplateColor("%s")' % colour
            if _multicontent()[0] else '')


def template_scale():
    """The argument that stretches a template pixmap into its box."""
    return _multicontent()[1]


def skin_factor():
    """Scale from the 1920 design grid to this desktop (720p/1080p/UHD)."""
    width = desktop_width()
    return (2560 if width >= 2560 else
            (1920 if width >= 1920 else 1280)) / 1920.0


def header(title, subtitle='', width=1920, height=80, wide=True):
    """A solid title bar with the accent rule under it."""
    if not wide:
        width, height = scale(width), scale(height)
    rule_y = height - 2
    title_font = 36 if wide else max(18, scale(36))
    sub_font = 26 if wide else max(14, scale(26))
    pad = 30 if wide else scale(30)
    parts = [
        '<eLabel position="0,0" size="%d,%d" backgroundColor="%s" '
        'transparent="0"/>' % (width, height, HEADER),
        '<eLabel position="0,%d" size="%d,3" backgroundColor="%s"/>'
        % (rule_y, width, ACCENT),
        '<eLabel text="%s" position="%d,%d" size="%d,%d" font="Regular;%d" '
        'halign="left" valign="center" foregroundColor="%s" transparent="1" '
        'zPosition="2"/>'
        % (xml_escape(title), pad, height // 8, width // 2, int(height * 0.7),
           title_font, ACCENT),
    ]
    if subtitle:
        parts.append(
            '<eLabel text="%s" position="%d,%d" size="%d,%d" '
            'font="Regular;%d" halign="right" valign="center" '
            'foregroundColor="%s" transparent="1" zPosition="2"/>'
            % (xml_escape(subtitle), width // 2, height // 8,
               width // 2 - pad, int(height * 0.7), sub_font, TEXT_FAINT))
    return '\n  '.join(parts)


def list_attrs(zap=False):
    """The colour attributes every list widget shares."""
    if zap:
        return ('backgroundColor="%s" foregroundColor="%s" '
                'foregroundColorSelected="%s" backgroundColorSelected="%s"'
                % (ZAP_LIST_BG, ZAP_LIST_FG, LIST_FG_SEL, ZAP_LIST_BG_SEL))
    return ('backgroundColor="%s" foregroundColor="%s" '
            'foregroundColorSelected="%s" backgroundColorSelected="%s"'
            % (LIST_BG, LIST_FG, LIST_FG_SEL, LIST_BG_SEL))


def dialog(name, body, width=1400, height=760, wide=True,
           ground=PANEL, flags='wfNoBorder'):
    """A centred panel dialog."""
    if not wide:
        width, height = scale(width), scale(height)
    return (
        '<screen name="%s" position="center,center" size="%d,%d" '
        'backgroundColor="%s" flags="%s">\n  %s\n</screen>'
        % (name, width, height, ground, flags, body)
    )


def fullscreen(name, body, wide=True, ground=TRANSPARENT,
               position='0,0', flags='wfNoBorder'):
    """A screen covering the whole picture.

    wfNoBorder makes the window an overlay on the video layer, which is
    what the player wants and what a menu must not have: without a
    border the ground is never painted and the channel shows through.
    """
    w, h = (1920, 1080) if wide else (1280, 720)
    return (
        '<screen name="%s" position="%s" size="%d,%d" backgroundColor="%s"%s>'
        '\n  %s\n</screen>'
        % (name, position, w, h, ground,
           ' flags="%s"' % flags if flags else '', body)
    )


def is_wide():
    """True on a 1080p desktop, False on 720p."""
    try:
        from enigma import getDesktop
        return getDesktop(0).size().width() >= 1920
    except Exception:
        return True


def desktop_width():
    try:
        from enigma import getDesktop
        return getDesktop(0).size().width()
    except Exception:
        return 1920

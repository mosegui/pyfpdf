#!/usr/bin/env python
# -*- coding: latin-1 -*-
# ****************************************************************************
# * Software: FPDF for python                                                *
# * Version:  1.7.1                                                          *
# * Date:     2010-09-10                                                     *
# * Last update: 2012-08-16                                                  *
# * License:  LGPL v3.0                                                      *
# *                                                                          *
# * Original Author (PHP):  Olivier PLATHEY 2004-12-31                       *
# * Ported to Python 2.4 by Max (maxpat78@yahoo.it) on 2006-05               *
# * Maintainer:  Mariano Reingart (reingart@gmail.com) et al since 2008 est. *
# * NOTE: 'I' and 'D' destinations are disabled, and simply print to STDOUT  *
# ****************************************************************************

from __future__ import division, with_statement

from enum import Enum

from datetime import datetime
import math
import errno
import os, sys, zlib, re, tempfile, struct

from contextlib import contextmanager

from .ttfonts import TTFontFile
from .fonts import fpdf_charwidths
from .php import substr, UTF8ToUTF16BE, UTF8StringToArray
from .py3k import PY3K, pickle, urlopen, BytesIO, Image, basestring, unicode, exception, b, hashpath

from .helpers import get_page_dimensions, load_cache, CatchAllError, check_page, get_op_from_draw_style, load_resource
from .pdf_settings import PDFSettings
from .pdf_elements import Line, Rectangle, Figure


# Global variables
FPDF_VERSION = '1.7.2'
FPDF_FONT_DIR = os.path.join(os.path.dirname(__file__), 'font')
FPDF_CACHE_MODE = 0  # 0 - in same folder, 1 - none, 2 - hash
FPDF_CACHE_DIR = None
SYSTEM_TTFONTS = None


def set_global(var, val):
    globals()[var] = val


class DocumentState(Enum):
    UNSTARTED = 0
    OPEN_IDLE = 1
    WRITING_PAGE = 2
    TERMINATED = 3


class FontSettings:
    def __init__(self, font_family, font_style, underlined, font_size, line_width, draw_color, fill_color, text_color, color_flag, font_stretching):
        self.font_family = font_family
        self.font_style = font_style
        self.underlined = underlined
        self.font_size = font_size
        self.line_width = line_width
        self.draw_color = draw_color
        self.fill_color = fill_color
        self.text_color = text_color
        self.color_flag = color_flag
        self.font_stretching = font_stretching

        if self.underlined:
            self.font_style += 'U'


def get_font_ttf_filepath(font_name):
    if os.path.exists(font_name):
        return font_name
    elif FPDF_FONT_DIR and os.path.exists(os.path.join(FPDF_FONT_DIR, font_name)):
        return os.path.join(FPDF_FONT_DIR, font_name)
    elif SYSTEM_TTFONTS and os.path.exists(os.path.join(SYSTEM_TTFONTS, font_name)):
        return os.path.join(SYSTEM_TTFONTS, font_name)
    else:
        raise RuntimeError(f"TTF Font file not found: {font_name}")


def get_unifilename(ttf_file_path):
    if FPDF_CACHE_MODE == 0:
        return os.path.splitext(ttf_file_path)[0] + '.pkl'
    elif FPDF_CACHE_MODE == 2:
        return os.path.join(FPDF_CACHE_DIR, hashpath(ttf_file_path) + ".pkl")
    else:
        return None


class FPDF:
    pdf_version = "1.4"

    core_fonts = {
        'courier': 'Courier', 'courierB': 'Courier-Bold',
        'courierI': 'Courier-Oblique', 'courierBI': 'Courier-BoldOblique',
        'helvetica': 'Helvetica', 'helveticaB': 'Helvetica-Bold',
        'helveticaI': 'Helvetica-Oblique',
        'helveticaBI': 'Helvetica-BoldOblique',
        'times': 'Times-Roman', 'timesB': 'Times-Bold',
        'timesI': 'Times-Italic', 'timesBI': 'Times-BoldItalic',
        'symbol': 'Symbol', 'zapfdingbats': 'ZapfDingbats'
    }

    in_footer = False  # flag set when processing footer
    str_alias_nb_pages = "{nb}"

    def __init__(self, orientation='P', unit='mm', format='A4'):
        # Some checks
        self._dochecks()
        # Initialization of properties
        self.offsets = {}  # array of object offsets
        self.current_page = 0  # current page number
        self.n = 2  # current object number
        self.buffer = ''  # buffer holding in-memory PDF
        self.pages = {}  # array containing pages and metadata
        self.state = DocumentState.UNSTARTED  # current document state
        self.fonts = {}  # array of used fonts
        self.font_files = {}  # array of font files
        self.diffs = {}  # array of encoding differences
        self.images = {}  # array of used images
        self.page_links = {}  # array of links in pages
        self.links = {}  # array of internal links

        self.lasth = 0  # height of last cell printed

        self.settings = PDFSettings(orientation=orientation, unit=unit, format=format)

    def close(self):
        """Terminate document"""
        if self.state == DocumentState.TERMINATED:
            return

        if self.current_page == 0:
            self.add_page()

        self.add_footer()
        self._endpage()
        self._enddoc()

    def get_font_settings(self):
        return FontSettings(self.settings.font_family,
                            self.settings.font_style,
                            self.settings.underline,
                            self.settings.font_size_pt,
                            self.settings.line_width,
                            self.settings.draw_color,
                            self.settings.fill_color,
                            self.settings.text_color,
                            self.settings.color_flag,
                            self.settings.font_stretching)

    def set_font_settings(self, font_settings: FontSettings):

        # Restore line width
        self.settings.line_width = font_settings.line_width
        self._out(f"{self.settings.line_width * self.settings.scale:.2f} w")

        # Restore font
        if font_settings.font_family:
            self.set_font(font_settings.font_family, font_settings.font_style, font_settings.font_size)

        # Restore colors
        self.settings.draw_color = font_settings.draw_color
        if self.settings.draw_color != '0 G':
            self._out(self.settings.draw_color)

        self.settings.fill_color = font_settings.fill_color
        if self.settings.fill_color != '0 g':
            self._out(self.settings.fill_color)

        self.settings.text_color = font_settings.text_color
        self.settings.color_flag = font_settings.color_flag

        self.set_stretching(font_settings.font_stretching)

    def add_page(self, orientation='', format='', same=False):
        """Start a new page, if same page format will be same as previous"""

        # TODO: I do not linke this design of the function modifying the sole current font settings, having to
        #  save them beforehand and setting them later (twice). Headers and footers should be their own classes
        #  with their own settings

        if self.state == DocumentState.UNSTARTED:
            self.state = DocumentState.OPEN_IDLE

        current_font_settings = self.get_font_settings()

        if self.current_page > 0:
            self.add_footer()
            self._endpage()

        self._beginpage(orientation, format, same)   # Start new page
        self._out('2 J')                             # Set line cap style to square

        self.set_font_settings(current_font_settings)
        self.header()
        self.set_font_settings(current_font_settings)

    def header(self):
        """Header to be implemented in your own inherited class"""
        pass

    def add_footer(self):
        self.in_footer = True
        self.footer()
        self.in_footer = False

    def footer(self):
        """Footer to be implemented in your own inherited class"""
        pass

    def set_draw_color(self, red=0, green=0, blue=0):
        """
        Set color for all stroking operations

        Note: The 'RG' vs 'rg' versions of the color setting string refer to
        the difference between stroking and non-stroking colors. See:
        https://stackoverflow.com/questions/27959391/what-is-pdf-stroking-non-stroking-and-filling
        """
        rcoord, gcoord, bcoord = red / 255.0, green / 255.0, blue / 255.0
        self.settings.draw_color = f"{rcoord:.3f} {gcoord:.3f} {bcoord:.3f} RG"

        if self.current_page > 0:
            self._out(self.settings.draw_color)

    def set_fill_color(self, red=0, green=0, blue=0):
        """
        Set color for all filling operations

        Note: The 'RG' vs 'rg' versions of the color setting string refer to
        the difference between stroking and non-stroking colors. See:
        https://stackoverflow.com/questions/27959391/what-is-pdf-stroking-non-stroking-and-filling
        """
        rcoord, gcoord, bcoord = red / 255.0, green / 255.0, blue / 255.0
        self.settings.fill_color = f"{rcoord:.3f} {gcoord:.3f} {bcoord:.3f} rg"

        self.settings.color_flag = self.settings.fill_color != self.settings.text_color

        if self.current_page > 0:
            self._out(self.settings.fill_color)

    def set_text_color(self, red=0, green=0, blue=0):
        """
        Set color for text

        Note: The 'RG' vs 'rg' versions of the color setting string refer to
        the difference between stroking and non-stroking colors. See:
        https://stackoverflow.com/questions/27959391/what-is-pdf-stroking-non-stroking-and-filling
        """
        rcoord, gcoord, bcoord = red / 255.0, green / 255.0, blue / 255.0
        self.settings.text_color = f"{rcoord:.3f} {gcoord:.3f} {bcoord:.3f} rg"

        self.settings.color_flag = self.settings.fill_color != self.settings.text_color

    def get_string_width(self, s, normalized=False):
        """Get width of a string in the current font"""
        # normalized is parameter for internal use
        s = s if normalized else self.normalize_text(s)
        cw = self.current_font['cw']
        w = 0
        l = len(s)
        if self.unifontsubset:
            for char in s:
                char = ord(char)
                if len(cw) > char:
                    w += cw[char]  # ord(cw[2*char])<<8 + ord(cw[2*char+1])
                # elif char>0 and char<128 and isset($cw[chr($char)]) { $w += $cw[chr($char)]; }
                elif self.current_font['desc']['MissingWidth']:
                    w += self.current_font['desc']['MissingWidth']
                # elif (isset($this->CurrentFont['MissingWidth'])) { $w += $this->CurrentFont['MissingWidth']; }
                else:
                    w += 500
        else:
            for i in range(0, l):
                w += cw.get(s[i], 0)
        if self.settings.font_stretching != 100:
            w = w * self.settings.font_stretching / 100.0
        return w * self.font_size / 1000.0

    def set_line_width(self, width):
        """Set line width"""
        self.settings.line_width = width
        if self.current_page > 0:
            self._out(f"{width * self.settings.scale:.2f} w")


    def add_font(self, font_family, font_style='', font_name='', uni=False):
        """Add a TrueType or Type1 font"""
        font_family = font_family.lower()
        if font_name == '':
            font_name = font_family.replace(' ', '') + font_style.lower() + '.pkl'
        if font_family == 'arial':
            font_family = 'helvetica'
        font_style = font_style.upper()
        if font_style == 'IB':
            font_style = 'BI'
        font_key = font_family + font_style
        if font_key in self.fonts:
            # Font already added!
            return

        if uni:
            ttffilename = get_font_ttf_filepath(font_name)
            unifilename = get_unifilename(ttffilename)

            font_dict = load_cache(unifilename)

            if font_dict is None:
                ttf = TTFontFile()
                ttf.getMetrics(ttffilename)

                desc = {
                    'Ascent': int(round(ttf.ascent, 0)),
                    'Descent': int(round(ttf.descent, 0)),
                    'CapHeight': int(round(ttf.capHeight, 0)),
                    'Flags': ttf.flags,
                    'FontBBox': "[%s %s %s %s]" % (
                        int(round(ttf.bbox[0], 0)),
                        int(round(ttf.bbox[1], 0)),
                        int(round(ttf.bbox[2], 0)),
                        int(round(ttf.bbox[3], 0))),
                    'ItalicAngle': int(ttf.italicAngle),
                    'StemV': int(round(ttf.stemV, 0)),
                    'MissingWidth': int(round(ttf.defaultWidth, 0)),
                }

                # Generate metrics .pkl file
                font_dict = {
                    'name': re.sub('[ ()]', '', ttf.fullName),
                    'type': 'TTF',
                    'desc': desc,
                    'up': round(ttf.underlinePosition),
                    'ut': round(ttf.underlineThickness),
                    'ttffile': ttffilename,
                    'fontkey': font_key,
                    'originalsize': os.stat(ttffilename).st_size,
                    'cw': ttf.charWidths,
                }
                if unifilename:
                    try:
                        with open(unifilename, "wb") as fh:
                            pickle.dump(font_dict, fh)
                    except Exception:
                        # Improve error catching with proper testing
                        raise Exception("Some unspecific error")

            if hasattr(self, 'str_alias_nb_pages'):
                sbarr = list(range(0, 57))  # include numbers in the subset!
            else:
                sbarr = list(range(0, 32))

            self.fonts[font_key] = {
                'i': len(self.fonts) + 1,
                'type': font_dict['type'],
                'name': font_dict['name'],
                'desc': font_dict['desc'],
                'up': font_dict['up'],
                'ut': font_dict['ut'],
                'cw': font_dict['cw'],
                'ttffile': font_dict['ttffile'],
                'fontkey': font_key,
                'subset': sbarr,
                'unifilename': unifilename,
            }

            self.font_files[font_key] = {
                'length1': font_dict['originalsize'],
                'type': "TTF",
                'ttffile': ttffilename
            }

            self.font_files[font_name] = {'type': "TTF"}

        else:
            with open(font_name, 'rb') as fontfile:
                font_dict = pickle.load(fontfile)
            self.fonts[font_key] = {'i': len(self.fonts) + 1}
            self.fonts[font_key].update(font_dict)
            diff = font_dict.get('diff')
            if diff:
                # Search existing encodings
                d = 0
                nb = len(self.diffs)
                for i in range(1, nb + 1):
                    if self.diffs[i] == diff:
                        d = i
                        break
                if d == 0:
                    d = nb + 1
                    self.diffs[d] = diff
                self.fonts[font_key]['diff'] = d
            filename = font_dict.get('filename')
            if filename:
                if font_dict['type'] == 'TrueType':
                    originalsize = font_dict['originalsize']
                    self.font_files[filename] = {'length1': originalsize}
                else:
                    self.font_files[filename] = {'length1': font_dict['size1'],
                                                 'length2': font_dict['size2']}

    def set_font(self, font_family, font_style='', font_size=0):
        """Select a font; size given in points"""

        font_family = font_family.lower()
        if font_family == '':
            font_family = self.settings.font_family
        if font_family == 'arial':
            font_family = 'helvetica'
        elif font_family == 'symbol' or font_family == 'zapfdingbats':
            font_style = ''

        font_style = font_style.upper()
        if 'U' in font_style:
            self.settings.underline = True
            font_style = font_style.replace('U', '')
        else:
            self.settings.underline = False
        if font_style == 'IB':
            font_style = 'BI'
        if font_size == 0:
            font_size = self.settings.font_size_pt

        # Test if font is already selected
        if self.settings.font_family == font_family and self.settings.font_style == font_style and self.settings.font_size_pt == font_size:
            return

        # Test if used for the first time
        fontkey = font_family + font_style
        if fontkey not in self.fonts:
            # Check if one of the standard fonts
            if fontkey in self.core_fonts:
                if fontkey not in fpdf_charwidths:
                    # Load metric file
                    name = os.path.join(FPDF_FONT_DIR, font_family)
                    if font_family == 'times' or font_family == 'helvetica':
                        name += font_style.lower()
                    with open(name + '.font') as file:
                        exec(compile(file.read(), name + '.font', 'exec'))
                    if fontkey not in fpdf_charwidths:
                        raise CatchAllError('Could not include font metric file for' + fontkey)
                i = len(self.fonts) + 1
                self.fonts[fontkey] = {'i': i, 'type': 'core', 'name': self.core_fonts[fontkey], 'up': -100, 'ut': 50, 'cw': fpdf_charwidths[fontkey]}
            else:
                raise CatchAllError('Undefined font: ' + font_family + ' ' + font_style)
        # Select it
        self.settings.font_family = font_family
        self.settings.font_style = font_style
        self.settings.font_size_pt = font_size
        self.font_size = font_size / self.settings.scale
        self.current_font = self.fonts[fontkey]
        self.unifontsubset = (self.fonts[fontkey]['type'] == 'TTF')
        if self.current_page > 0:
            self._out(f"BT /F{self.current_font['i']:d} {self.settings.font_size_pt:.2f} Tf ET")

    def set_font_size(self, size):
        """Set font size in points"""
        if (self.settings.font_size_pt == size):
            return
        self.settings.font_size_pt = size
        self.font_size = size / self.settings.scale
        if self.current_page > 0:
            self._out(f"BT /F{self.current_font['i']:d} {self.settings.font_size_pt:.2f} Tf ET")

    def set_stretching(self, factor):
        """Set from stretch factor percents (default: 100.0)"""
        if self.settings.font_stretching == factor:
            return
        self.settings.font_stretching = factor
        if self.current_page > 0:
            self._out(f"BT {self.settings.font_stretching:.2f} Tz ET")

    def add_link(self):
        """Create a new internal link"""
        n = len(self.links) + 1
        self.links[n] = (0, 0)
        return n

    def set_link(self, link, y=0, page=-1):
        """Set destination of internal link"""
        if y == -1:
            y = self.y
        if page == -1:
            page = self.current_page
        self.links[link] = [page, y]

    def link(self, x, y, w, h, link):
        """Put a link on the page"""
        if not self.current_page in self.page_links:
            self.page_links[self.current_page] = []
        self.page_links[self.current_page] += [(x * self.settings.scale, self.settings.height_points - y * self.settings.scale, w * self.settings.scale, h * self.settings.scale, link), ]

    @check_page
    def text(self, x, y, txt=''):
        """Output a string"""
        txt = self.normalize_text(txt)
        if self.unifontsubset:
            txt2 = self._escape(UTF8ToUTF16BE(txt, False))
            for uni in UTF8StringToArray(txt):
                self.current_font['subset'].append(uni)
        else:
            txt2 = self._escape(txt)
        s = f"BT {x * self.settings.scale:.2f} {(self.settings.height_unit - y) * self.settings.scale:.2f} Td ({txt2}) Tj ET"
        if self.settings.underline and txt != '':
            s += ' ' + self._dounderline(x, y, txt)
        if self.settings.color_flag:
            s = 'q ' + self.settings.text_color + ' ' + s + ' Q'
        self._out(s)

    @check_page
    def rotate(self, angle, x=None, y=None):
        if x is None:
            x = self.x
        if y is None:
            y = self.y
        if self.settings.angle != 0:
            self._out('Q')
        self.settings.angle = angle
        if angle != 0:
            angle *= math.pi / 180
            c = math.cos(angle)
            s = math.sin(angle)
            cx = x * self.settings.scale
            cy = (self.settings.height_unit - y) * self.settings.scale
            self._out(f"q {c:.5f} {s:.5f} {-s:.5f} {c:.5f} {cx:.2f} {cy:.2f} cm 1 0 0 1 {-cx:.2f} {-cy:.2f} cm")

    @check_page
    def cell(self, w, h=0, txt='', border=0, ln=0, align='', fill=0, link=''):
        """Output a cell"""
        txt = self.normalize_text(txt)
        k = self.settings.scale
        if self.y + h > self.settings.page_break_trigger and not self.in_footer and self.settings.auto_page_break:
            # Automatic page break
            x = self.x
            ws = self.settings.word_spacing
            if ws > 0:
                self.settings.word_spacing = 0
                self._out('0 Tw')
            self.add_page(same=True)
            self.x = x
            if ws > 0:
                self.settings.word_spacing = ws
                self._out(f'{ws * k:.3f} Tw')
        if w == 0:
            w = self.settings.width_unit - self.settings.right_page_margin - self.x
        s = ''
        if fill == 1 or border == 1:
            if fill == 1:
                if border == 1:
                    op = 'B'
                else:
                    op = 'f'
            else:
                op = 'S'
            s = f"{self.x * k:.2f} {(self.settings.height_unit - self.y) * k:.2f} {w * k:.2f} {-h * k:.2f} re {op} "
        if isinstance(border, basestring):
            x = self.x
            y = self.y
            if 'L' in border:
                s += f'{x * k:.2f} {(self.settings.height_unit - y) * k:.2f} m {x * k:.2f} {(self.settings.height_unit - (y + h)) * k:.2f} l S '
            if 'T' in border:
                s += f'{x * k:.2f} {(self.settings.height_unit - y) * k:.2f} m {(x + w) * k:.2f} {(self.settings.height_unit - y) * k:.2f} l S '
            if 'R' in border:
                s += f'{(x + w) * k:.2f} {(self.settings.height_unit - y) * k:.2f} m {(x + w) * k:.2f} {(self.settings.height_unit - (y + h)) * k:.2f} l S '
            if 'B' in border:
                s += f'{x * k:.2f} {(self.settings.height_unit - (y + h)) * k:.2f} m {(x + w) * k:.2f} {(self.settings.height_unit - (y + h)) * k:.2f} l S '
        if txt != '':
            if align == 'R':
                dx = w - self.settings.cell_margin - self.get_string_width(txt, True)
            elif align == 'C':
                dx = (w - self.get_string_width(txt, True)) / 2.0
            else:
                dx = self.settings.cell_margin
            if self.settings.color_flag:
                s += 'q ' + self.settings.text_color + ' '

            # If multibyte, Tw has no effect - do word spacing using an adjustment before each space
            if self.settings.word_spacing and self.unifontsubset:
                for uni in UTF8StringToArray(txt):
                    self.current_font['subset'].append(uni)
                space = self._escape(UTF8ToUTF16BE(' ', False))
                s += f'BT 0 Tw {(self.x + dx) * k:.2f} {(self.settings.height_unit - (self.y + 0.5 * h + 0.3 * self.font_size)) * k:.2f} Td ['
                t = txt.split(' ')
                numt = len(t)
                for i in range(numt):
                    tx = t[i]
                    tx = '(' + self._escape(UTF8ToUTF16BE(tx, False)) + ')'
                    s += f'{tx} '
                    if (i + 1) < numt:
                        adj = -(self.settings.word_spacing * self.settings.scale) * 1000 / self.settings.font_size_pt
                        s += f'{adj:d}({space}) '
                s += '] TJ'
                s += ' ET'
            else:
                if self.unifontsubset:
                    txt2 = self._escape(UTF8ToUTF16BE(txt, False))
                    for uni in UTF8StringToArray(txt):
                        self.current_font['subset'].append(uni)
                else:
                    txt2 = self._escape(txt)
                s += f'BT {(self.x + dx) * k:.2f} {(self.settings.height_unit - (self.y + .5 * h + .3 * self.font_size)) * k:.2f} Td ({txt2}) Tj ET'

            if self.settings.underline:
                s += ' ' + self._dounderline(self.x + dx, self.y + .5 * h + .3 * self.font_size, txt)
            if self.settings.color_flag:
                s += ' Q'
            if link:
                self.link(self.x + dx, self.y + .5 * h - .5 * self.font_size, self.get_string_width(txt, True), self.font_size, link)
        if s:
            self._out(s)
        self.lasth = h
        if ln > 0:
            # Go to next line
            self.y += h
            if ln == 1:
                self.x = self.settings.left_page_margin
        else:
            self.x += w

    @check_page
    def multi_cell(self, width, height, text='', border=0, align='J', fill=0, split_only=False):
        """Output text with automatic or explicit line breaks"""
        text = self.normalize_text(text)
        ret = []  # if split_only = True, returns splited text cells
        char_width = self.current_font['cw']
        if width == 0:
            width = self.settings.width_unit - self.settings.right_page_margin - self.x
        wmax = (width - 2 * self.settings.cell_margin) * 1000.0 / self.font_size
        s = text.replace("\r", '')
        nb = len(s)
        if nb > 0 and s[nb - 1] == "\n":
            nb -= 1
        b = 0
        if border:
            if border == 1:
                border = 'LTRB'
                b = 'LRT'
                b2 = 'LR'
            else:
                b2 = ''
                if 'L' in border:
                    b2 += 'L'
                if 'R' in border:
                    b2 += 'R'
                if 'T' in border:
                    b = b2 + 'T'
                else:
                    b = b2
        sep = -1
        i = 0
        j = 0
        l = 0
        ns = 0
        nl = 1
        while i < nb:
            # Get next character
            c = s[i]
            if c == "\n":
                # Explicit line break
                if self.settings.word_spacing > 0:
                    self.settings.word_spacing = 0
                    if not split_only:
                        self._out('0 Tw')
                if not split_only:
                    self.cell(width, height, substr(s, j, i - j), b, 2, align, fill)
                else:
                    ret.append(substr(s, j, i - j))
                i += 1
                sep = -1
                j = i
                l = 0
                ns = 0
                nl += 1
                if (border and nl == 2):
                    b = b2
                continue
            if c == ' ':
                sep = i
                ls = l
                ns += 1
            if self.unifontsubset:
                l += self.get_string_width(c, True) / self.font_size * 1000.0
            else:
                l += char_width.get(c, 0)
            if l > wmax:
                # Automatic line break
                if sep == -1:
                    if i == j:
                        i += 1
                    if self.settings.word_spacing > 0:
                        self.settings.word_spacing = 0
                        if not split_only:
                            self._out('0 Tw')
                    if not split_only:
                        self.cell(width, height, substr(s, j, i - j), b, 2, align, fill)
                    else:
                        ret.append(substr(s, j, i - j))
                else:
                    if align == 'J':
                        if ns > 1:
                            self.settings.word_spacing = (wmax - ls) / 1000.0 * self.font_size / (ns - 1)
                        else:
                            self.settings.word_spacing = 0
                        if not split_only:
                            self._out(f'{self.settings.word_spacing * self.settings.scale:.3f} Tw', )
                    if not split_only:
                        self.cell(width, height, substr(s, j, sep - j), b, 2, align, fill)
                    else:
                        ret.append(substr(s, j, sep - j))
                    i = sep + 1
                sep = -1
                j = i
                l = 0
                ns = 0
                nl += 1
                if border and nl == 2:
                    b = b2
            else:
                i += 1
        # Last chunk
        if self.settings.word_spacing > 0:
            self.settings.word_spacing = 0
            if not split_only:
                self._out('0 Tw')
        if border and 'B' in border:
            b += 'B'
        if not split_only:
            self.cell(width, height, substr(s, j, i - j), b, 2, align, fill)
            self.x = self.settings.left_page_margin
        else:
            ret.append(substr(s, j, i - j))
        return ret

    @check_page
    def write(self, h, txt='', link=''):
        """Output text in flowing mode"""
        txt = self.normalize_text(txt)
        cw = self.current_font['cw']
        w = self.settings.width_unit - self.settings.right_page_margin - self.x
        wmax = (w - 2 * self.settings.cell_margin) * 1000.0 / self.font_size
        s = txt.replace("\r", '')
        nb = len(s)
        sep = -1
        i = 0
        j = 0
        l = 0
        nl = 1
        while i < nb:
            # Get next character
            c = s[i]
            if c == "\n":
                # Explicit line break
                self.cell(w, h, substr(s, j, i - j), 0, 2, '', 0, link)
                i += 1
                sep = -1
                j = i
                l = 0
                if nl == 1:
                    self.x = self.settings.left_page_margin
                    w = self.settings.width_unit - self.settings.right_page_margin - self.x
                    wmax = (w - 2 * self.settings.cell_margin) * 1000.0 / self.font_size
                nl += 1
                continue
            if c == ' ':
                sep = i
            if self.unifontsubset:
                l += self.get_string_width(c, True) / self.font_size * 1000.0
            else:
                l += cw.get(c, 0)
            if l > wmax:
                # Automatic line break
                if sep == -1:
                    if self.x > self.settings.left_page_margin:
                        # Move to next line
                        self.x = self.settings.left_page_margin
                        self.y += h
                        w = self.settings.width_unit - self.settings.right_page_margin - self.x
                        wmax = (w - 2 * self.settings.cell_margin) * 1000.0 / self.font_size
                        i += 1
                        nl += 1
                        continue
                    if i == j:
                        i += 1
                    self.cell(w, h, substr(s, j, i - j), 0, 2, '', 0, link)
                else:
                    self.cell(w, h, substr(s, j, sep - j), 0, 2, '', 0, link)
                    i = sep + 1
                sep = -1
                j = i
                l = 0
                if nl == 1:
                    self.x = self.settings.left_page_margin
                    w = self.settings.width_unit - self.settings.right_page_margin - self.x
                    wmax = (w - 2 * self.settings.cell_margin) * 1000.0 / self.font_size
                nl += 1
            else:
                i += 1
        # Last chunk
        if i != j:
            self.cell(l / 1000.0 * self.font_size, h, substr(s, j), 0, 0, '', 0, link)

    @check_page
    def image(self, name, x=None, y=None, w=0, h=0, type='', link='', is_mask=False, mask_image=None):
        """Put an image on the page"""
        if name not in self.images:
            # First use of image, get info
            if type == '':
                pos = name.rfind('.')
                if not pos:
                    raise CatchAllError('image file has no extension and no type was specified: ' + name)
                type = substr(name, pos + 1)
            type = type.lower()
            if type == 'jpg' or type == 'jpeg':
                info = self._parsejpg(name)
            elif type == 'png':
                info = self._parsepng(name)
            else:
                # Allow for additional formats
                # maybe the image is not showing the correct extension,
                # but the header is OK,
                succeed_parsing = False
                # try all the parsing functions
                parsing_functions = [self._parsejpg, self._parsepng, self._parsegif]
                for pf in parsing_functions:
                    try:
                        info = pf(name)
                        succeed_parsing = True
                        break
                    except:
                        pass
                # last resource
                if not succeed_parsing:
                    mtd = '_parse' + type
                    if not hasattr(self, mtd):
                        raise CatchAllError('Unsupported image type: ' + type)
                    info = getattr(self, mtd)(name)
                mtd = '_parse' + type
                if not hasattr(self, mtd):
                    raise CatchAllError('Unsupported image type: ' + type)
                info = getattr(self, mtd)(name)

            info['i'] = len(self.images) + 1
            # is_mask and mask_image
            if is_mask and info['cs'] != 'DeviceGray':
                raise CatchAllError('Mask must be a gray scale image')
            if mask_image:
                info['masked'] = mask_image
            self.images[name] = info
        else:
            info = self.images[name]
        # Automatic width and height calculation if needed
        if w == 0 and h == 0:
            # Put image at 72 dpi
            w = info['w'] / self.settings.scale
            h = info['h'] / self.settings.scale
        elif w == 0:
            w = h * info['w'] / info['h']
        elif h == 0:
            h = w * info['h'] / info['w']
        # Flowing mode
        if y is None:
            if self.y + h > self.settings.page_break_trigger and not self.in_footer and self.settings.auto_page_break:
                # Automatic page break
                x = self.x
                self.add_page(same=True)
                self.x = x
            y = self.y
            self.y += h
        if x is None:
            x = self.x
        if not is_mask:
            self._out(f"q {w * self.settings.scale:.2f} 0 0 {h * self.settings.scale:.2f} {x * self.settings.scale:.2f} {(self.settings.height_unit - (y + h)) * self.settings.scale:.2f} cm /I{info['i']:d} Do Q")
        if link:
            self.link(x, y, w, h, link)

        return info

    @check_page
    def ln(self, h=''):
        """Line Feed; default value is last cell height"""
        self.x = self.settings.left_page_margin
        if isinstance(h, basestring):
            self.y += self.lasth
        else:
            self.y += h

    def get_x(self):
        """Get x position"""
        return self.x

    def set_x(self, x):
        """Set x position"""
        if x >= 0:
            self.x = x
        else:
            self.x = self.settings.width_unit + x

    def get_y(self):
        """Get y position"""
        return self.y

    def set_y(self, y):
        """Set y position and reset x"""
        self.x = self.settings.left_page_margin
        if y >= 0:
            self.y = y
        else:
            self.y = self.settings.height_unit + y

    def set_xy(self, x, y):
        """Set x and y positions"""
        self.set_y(y)
        self.set_x(x)

    def output(self, name='', dest=''):
        """Output PDF to some destination

        By default the PDF is written to sys.stdout. If a name is given, the
        PDF is written to a new file. If dest='S' is given, the PDF data is
        returned as a byte string."""

        # Finish document if necessary
        if self.state.value < DocumentState.TERMINATED.value:
            self.close()
        dest = dest.upper()
        if dest == '':
            if name == '':
                dest = 'I'
            else:
                dest = 'F'
        if PY3K:
            # manage binary data as latin1 until PEP461 or similar is implemented
            buffer = self.buffer.encode("latin1")
        else:
            buffer = self.buffer
        if dest in ('I', 'D'):
            # Python < 3 writes byte data transparently without "buffer"
            stdout = getattr(sys.stdout, 'buffer', sys.stdout)
            stdout.write(buffer)
        elif dest == 'F':
            # Save to local file
            with open(name, 'wb') as f:
                f.write(buffer)
        elif dest == 'S':
            # Return as a byte string
            return buffer
        else:
            raise CatchAllError('Incorrect output destination: ' + dest)

    def normalize_text(self, txt):
        # NOTE: The original method normalize_text above is replaced by the current
        # one. I intend to remove the complexity associated to supporing Python2

        """Check that text input is in the correct format/encoding"""
        # - for TTF unicode fonts: unicode object (utf8 encoding)
        # - for built-in fonts: string instances (encoding: latin-1, cp1252)

        if not self.unifontsubset and self.settings.core_fonts_encoding:
            return txt.encode(self.settings.core_fonts_encoding).decode("latin-1")

        return txt



##########################################################################################################################
##########################################################################################################################



    def _dochecks(self):
        # Check for locale-related bug
        #        if(1.1==1):
        #            raise CatchAllError("Don\'t alter the locale before including class file");
        # Check for decimal separator
        if f'{1.0:.1f}' != '1.0':
            import locale
            locale.setlocale(locale.LC_NUMERIC, 'C')

    def _getfontpath(self):
        return FPDF_FONT_DIR + '/'

    def _putpages(self):
        nb = self.current_page
        if hasattr(self, 'str_alias_nb_pages'):
            # Replace number of pages in fonts using subsets (unicode)
            alias = UTF8ToUTF16BE(self.str_alias_nb_pages, False)
            r = UTF8ToUTF16BE(str(nb), False)
            for n in range(1, nb + 1):
                self.pages[n]["content"] = self.pages[n]["content"].replace(alias, r)
            # Now repeat for no pages in non-subset fonts
            for n in range(1, nb + 1):
                self.pages[n]["content"] = self.pages[n]["content"].replace(self.str_alias_nb_pages, str(nb))
        if self.settings.def_orientation == 'P':
            dw_pt = self.settings.document_width_points
            dh_pt = self.settings.document_height_points
        else:
            dw_pt = self.settings.document_height_points
            dh_pt = self.settings.document_width_points
        if self.settings.compress:
            filter = '/Filter /FlateDecode '
        else:
            filter = ''
        for n in range(1, nb + 1):
            # Page
            with self._newobj():
                self._out('<</Type /Page')
                self._out('/Parent 1 0 R')
                w_pt = self.pages[n]["w_pt"]
                h_pt = self.pages[n]["h_pt"]
                if w_pt != dw_pt or h_pt != dh_pt:
                    self._out(f'/MediaBox [0 0 {w_pt:.2f} {h_pt:.2f}]')
                self._out('/Resources 2 0 R')
                if self.page_links and n in self.page_links:
                    # Links
                    annots = '/Annots ['
                    for pl in self.page_links[n]:
                        rect = f'{pl[0]:.2f} {pl[1]:.2f} {pl[0] + pl[2]:.2f} {pl[1] - pl[3]:.2f}'
                        annots += '<</Type /Annot /Subtype /Link /Rect [' + rect + '] /Border [0 0 0] '
                        if isinstance(pl[4], str):
                            annots += f"/A <</S /URI /URI {self._textstring(pl[4])}>>>>"
                        else:
                            l = self.links[pl[4]]
                            h = w_pt

                            # Note 20220206: This seems to be dead code... Links seem to appear properly both in
                            #  portrait as well as in landscape orientation regardless of this part here...
                            # if self.settings.def_orientation == "L":
                            #     h = w_pt
                            # else:
                            #     h = h_pt


                            annots += f'/Dest [{1 + 2 * l[0]:d} 0 R /XYZ 0 {h - l[1] * self.settings.scale:.2f} null]>>'
                    self._out(annots + ']')
                if self.pdf_version > '1.3':
                    self._out("/Group <</Type /Group /S /Transparency /CS /DeviceRGB>>")
                self._out('/Contents ' + str(self.n + 1) + ' 0 R>>')

            # Page content
            content = self.pages[n]["content"]
            if self.settings.compress:
                # manage binary data as latin1 until PEP461 or similar is implemented
                p = content.encode("latin1") if PY3K else content
                p = zlib.compress(p)
            else:
                p = content
            with self._newobj():
                self._out('<<' + filter + '/Length ' + str(len(p)) + '>>')
                self._putstream(p)

        # Pages root
        self.offsets[1] = len(self.buffer)
        self._out('1 0 obj')
        self._out('<</Type /Pages')
        kids = '/Kids ['
        for i in range(0, nb):
            kids += str(3 + 2 * i) + ' 0 R '
        self._out(kids + ']')
        self._out('/Count ' + str(nb))
        self._out(f'/MediaBox [0 0 {dw_pt:.2f} {dh_pt:.2f}]')
        self._out('>>')
        self._out('endobj')

    def _putfonts(self):
        nf = self.n
        for diff in self.diffs:
            # Encodings
            with self._newobj():
                self._out('<</Type /Encoding /BaseEncoding /WinAnsiEncoding /Differences [' + self.diffs[diff] + ']>>')

        for name, info in self.font_files.items():
            if 'type' in info and info['type'] != 'TTF':
                # Font file embedding
                with self._newobj():
                    self.font_files[name]['n'] = self.n
                    with open(self._getfontpath() + name, 'rb', 1) as f:
                        font = f.read()
                    compressed = (substr(name, -2) == '.z')
                    if not compressed and 'length2' in info:
                        header = (ord(font[0]) == 128)
                        if header:
                            # Strip first binary header
                            font = substr(font, 6)
                        if header and ord(font[info['length1']]) == 128:
                            # Strip second binary header
                            font = substr(font, 0, info['length1']) + substr(font, info['length1'] + 6)
                    self._out('<</Length ' + str(len(font)))
                    if compressed:
                        self._out('/Filter /FlateDecode')
                    self._out('/Length1 ' + str(info['length1']))
                    if 'length2' in info:
                        self._out('/Length2 ' + str(info['length2']) + ' /Length3 0')
                    self._out('>>')
                    self._putstream(font)

        flist = [(x[1]["i"], x[0], x[1]) for x in self.fonts.items()]
        flist.sort()
        for idx, k, font in flist:
            # Font objects
            self.fonts[k]['n'] = self.n + 1
            type = font['type']
            name = font['name']
            if type == 'core':
                # Standard font
                with self._newobj():
                    self._out('<</Type /Font')
                    self._out('/BaseFont /' + name)
                    self._out('/Subtype /Type1')
                    if name != 'Symbol' and name != 'ZapfDingbats':
                        self._out('/Encoding /WinAnsiEncoding')
                    self._out('>>')

            elif type == 'Type1' or type == 'TrueType':
                # Additional Type1 or TrueType font
                with self._newobj():
                    self._out('<</Type /Font')
                    self._out('/BaseFont /' + name)
                    self._out('/Subtype /' + type)
                    self._out('/FirstChar 32 /LastChar 255')
                    self._out('/Widths ' + str(self.n + 1) + ' 0 R')
                    self._out('/FontDescriptor ' + str(self.n + 2) + ' 0 R')
                    if font['enc']:
                        if 'diff' in font:
                            self._out('/Encoding ' + str(nf + font['diff']) + ' 0 R')
                        else:
                            self._out('/Encoding /WinAnsiEncoding')
                    self._out('>>')

                # Widths
                with self._newobj():
                    cw = font['cw']
                    s = '['
                    for i in range(32, 256):
                        # Get doesn't raise exception; returns 0 instead of None if not set
                        s += str(cw.get(chr(i)) or 0) + ' '
                    self._out(s + ']')

                # Descriptor
                with self._newobj():
                    s = '<</Type /FontDescriptor /FontName /' + name
                    for k in ('Ascent', 'Descent', 'CapHeight', 'Flags', 'FontBBox', 'ItalicAngle', 'StemV', 'MissingWidth'):
                        s += ' /%s %s' % (k, font['desc'][k])
                    filename = font['file']
                    if filename:
                        s += ' /FontFile'
                        if type != 'Type1':
                            s += '2'
                        s += ' ' + str(self.font_files[filename]['n']) + ' 0 R'
                    self._out(s + '>>')

            elif type == 'TTF':
                self.fonts[k]['n'] = self.n + 1
                ttf = TTFontFile()
                fontname = 'MPDFAA' + '+' + font['name']
                subset = font['subset']
                del subset[0]
                ttfontstream = ttf.makeSubset(font['ttffile'], subset)
                ttfontsize = len(ttfontstream)
                fontstream = zlib.compress(ttfontstream)
                codeToGlyph = ttf.codeToGlyph
                ##del codeToGlyph[0]
                # Type0 Font
                # A composite font - a font composed of other fonts, organized hierarchically
                with self._newobj():
                    self._out('<</Type /Font')
                    self._out('/Subtype /Type0')
                    self._out('/BaseFont /' + fontname + '')
                    self._out('/Encoding /Identity-H')
                    self._out('/DescendantFonts [' + str(self.n + 1) + ' 0 R]')
                    self._out('/ToUnicode ' + str(self.n + 2) + ' 0 R')
                    self._out('>>')

                # CIDFontType2
                # A CIDFont whose glyph descriptions are based on TrueType font technology
                with self._newobj():
                    self._out('<</Type /Font')
                    self._out('/Subtype /CIDFontType2')
                    self._out('/BaseFont /' + fontname + '')
                    self._out('/CIDSystemInfo ' + str(self.n + 2) + ' 0 R')
                    self._out('/FontDescriptor ' + str(self.n + 3) + ' 0 R')
                    if font['desc'].get('MissingWidth'):
                        self._out('/DW %d' % font['desc']['MissingWidth'])
                    self._putTTfontwidths(font, ttf.maxUni)
                    self._out('/CIDToGIDMap ' + str(self.n + 4) + ' 0 R')
                    self._out('>>')

                # ToUnicode
                with self._newobj():
                    toUni = "/CIDInit /ProcSet findresource begin\n" \
                            "12 dict begin\n" \
                            "begincmap\n" \
                            "/CIDSystemInfo\n" \
                            "<</Registry (Adobe)\n" \
                            "/Ordering (UCS)\n" \
                            "/Supplement 0\n" \
                            ">> def\n" \
                            "/CMapName /Adobe-Identity-UCS def\n" \
                            "/CMapType 2 def\n" \
                            "1 begincodespacerange\n" \
                            "<0000> <FFFF>\n" \
                            "endcodespacerange\n" \
                            "1 beginbfrange\n" \
                            "<0000> <FFFF> <0000>\n" \
                            "endbfrange\n" \
                            "endcmap\n" \
                            "CMapName currentdict /CMap defineresource pop\n" \
                            "end\n" \
                            "end"
                    self._out('<</Length ' + str(len(toUni)) + '>>')
                    self._putstream(toUni)

                # CIDSystemInfo dictionary
                with self._newobj():
                    self._out('<</Registry (Adobe)')
                    self._out('/Ordering (UCS)')
                    self._out('/Supplement 0')
                    self._out('>>')

                # Font descriptor
                with self._newobj():
                    self._out('<</Type /FontDescriptor')
                    self._out('/FontName /' + fontname)
                    for kd in ('Ascent', 'Descent', 'CapHeight', 'Flags', 'FontBBox', 'ItalicAngle', 'StemV', 'MissingWidth'):
                        v = font['desc'][kd]
                        if kd == 'Flags':
                            v = v | 4
                            v = v & ~32  # SYMBOLIC font flag
                        self._out(' /%s %s' % (kd, v))
                    self._out('/FontFile2 ' + str(self.n + 2) + ' 0 R')
                    self._out('>>')

                # Embed CIDToGIDMap
                # A specification of the mapping from CIDs to glyph indices
                cidtogidmap = ''
                cidtogidmap = ["\x00"] * 256 * 256 * 2
                for cc, glyph in codeToGlyph.items():
                    cidtogidmap[cc * 2] = chr(glyph >> 8)
                    cidtogidmap[cc * 2 + 1] = chr(glyph & 0xFF)
                cidtogidmap = ''.join(cidtogidmap)
                if PY3K:
                    # manage binary data as latin1 until PEP461-like function is implemented
                    cidtogidmap = cidtogidmap.encode("latin1")
                cidtogidmap = zlib.compress(cidtogidmap)

                with self._newobj():
                    self._out('<</Length ' + str(len(cidtogidmap)) + '')
                    self._out('/Filter /FlateDecode')
                    self._out('>>')
                    self._putstream(cidtogidmap)

                # Font file
                with self._newobj():
                    self._out('<</Length ' + str(len(fontstream)))
                    self._out('/Filter /FlateDecode')
                    self._out('/Length1 ' + str(ttfontsize))
                    self._out('>>')
                    self._putstream(fontstream)

            else:
                # Allow for additional types
                mtd = '_put' + type.lower()
                if not method_exists(self, mtd):
                    raise CatchAllError('Unsupported font type: ' + type)
                self.mtd(font)

    def _putTTfontwidths(self, font, maxUni):
        if font['unifilename']:
            cw127fname = os.path.splitext(font['unifilename'])[0] + '.cw127.pkl'
        else:
            cw127fname = None
        font_dict = load_cache(cw127fname)
        if font_dict is None:
            rangeid = 0
            range_ = {}
            range_interval = {}
            prevcid = -2
            prevwidth = -1
            interval = False
            startcid = 1
        else:
            rangeid = font_dict['rangeid']
            range_ = font_dict['range']
            prevcid = font_dict['prevcid']
            prevwidth = font_dict['prevwidth']
            interval = font_dict['interval']
            range_interval = font_dict['range_interval']
            startcid = 128
        cwlen = maxUni + 1

        # for each character
        subset = set(font['subset'])
        for cid in range(startcid, cwlen):
            if cid == 128 and cw127fname and not os.path.exists(cw127fname):
                try:
                    with open(cw127fname, "wb") as fh:
                        font_dict = {'rangeid': rangeid, 'prevcid': prevcid, 'prevwidth': prevwidth, 'interval': interval, 'range_interval': range_interval,
                                     'range': range_}
                        pickle.dump(font_dict, fh)
                except IOError:
                    if not exception().errno == errno.EACCES:
                        raise  # Not a permission error.
            if cid > 255 and (cid not in subset):  #
                continue
            width = font['cw'][cid]
            if width == 0:
                continue
            if width == 65535: width = 0
            if 'dw' not in font or (font['dw'] and width != font['dw']):
                if cid == (prevcid + 1):
                    if width == prevwidth:
                        if width == range_[rangeid][0]:
                            range_.setdefault(rangeid, []).append(width)
                        else:
                            range_[rangeid].pop()
                            # new range
                            rangeid = prevcid
                            range_[rangeid] = [prevwidth, width]
                        interval = True
                        range_interval[rangeid] = True
                    else:
                        if interval:
                            # new range
                            rangeid = cid
                            range_[rangeid] = [width]
                        else:
                            range_[rangeid].append(width)
                        interval = False
                else:
                    rangeid = cid
                    range_[rangeid] = [width]
                    interval = False
                prevcid = cid
                prevwidth = width
        prevk = -1
        nextk = -1
        prevint = False
        for k, ws in sorted(range_.items()):
            cws = len(ws)
            if k == nextk and not prevint and (not k in range_interval or cws < 3):
                if k in range_interval:
                    del range_interval[k]
                range_[prevk] = range_[prevk] + range_[k]
                del range_[k]
            else:
                prevk = k
            nextk = k + cws
            if k in range_interval:
                prevint = (cws > 3)
                del range_interval[k]
                nextk -= 1
            else:
                prevint = False
        w = []
        for k, ws in sorted(range_.items()):
            if len(set(ws)) == 1:
                w.append(' %s %s %s' % (k, k + len(ws) - 1, ws[0]))
            else:
                w.append(' %s [ %s ]\n' % (k, ' '.join([str(int(h)) for h in ws])))  ##
        self._out('/W [%s]' % ''.join(w))

    def _putimages(self):
        filter = ''
        if self.settings.compress:
            filter = '/Filter /FlateDecode '
        i = [(x[1]["i"], x[1]) for x in self.images.items()]
        i.sort()
        for idx, info in i:
            self._putimage(info)
            del info['data']
            if 'smask' in info:
                del info['smask']

    def _putimage(self, info):
        if 'data' in info:
            with self._newobj():
                info['n'] = self.n
                self._out('<</Type /XObject')
                self._out('/Subtype /Image')
                self._out('/Width ' + str(info['w']))
                self._out('/Height ' + str(info['h']))
                # set mask object for this image
                if 'masked' in info:
                    self._out('/SMask ' + str(info['masked']['n'] + 1) + ' 0 R')

                if info['cs'] == 'Indexed':
                    self._out('/ColorSpace [/Indexed /DeviceRGB ' + str(len(info['pal']) // 3 - 1) + ' ' + str(self.n + 1) + ' 0 R]')
                else:
                    self._out('/ColorSpace /' + info['cs'])
                    if info['cs'] == 'DeviceCMYK':
                        self._out('/Decode [1 0 1 0 1 0 1 0]')
                self._out('/BitsPerComponent ' + str(info['bpc']))
                if 'f' in info:
                    self._out('/Filter /' + info['f'])
                if 'dp' in info:
                    self._out('/DecodeParms <<' + info['dp'] + '>>')
                if 'trns' in info and isinstance(info['trns'], list):
                    trns = ''
                    for i in range(0, len(info['trns'])):
                        trns += str(info['trns'][i]) + ' ' + str(info['trns'][i]) + ' '
                    self._out('/Mask [' + trns + ']')
                if 'smask' in info:
                    self._out('/SMask ' + str(self.n + 1) + ' 0 R')
                self._out('/Length ' + str(len(info['data'])) + '>>')
                self._putstream(info['data'])

            # Soft mask
            if 'smask' in info:
                dp = '/Predictor 15 /Colors 1 /BitsPerComponent 8 /Columns ' + str(info['w'])
                smask = {'w': info['w'], 'h': info['h'], 'cs': 'DeviceGray', 'bpc': 8, 'f': info['f'], 'dp': dp, 'data': info['smask']}
                self._putimage(smask)
            # Palette
            if info['cs'] == 'Indexed':
                with self._newobj():
                    filter = self.settings.compress and '/Filter /FlateDecode ' or ''
                    if self.settings.compress:
                        pal = zlib.compress(info['pal'])
                    else:
                        pal = info['pal']
                    self._out('<<' + filter + '/Length ' + str(len(pal)) + '>>')
                    self._putstream(pal)

    def _putxobjectdict(self):
        i = [(x["i"], x["n"]) for x in self.images.values()]
        i.sort()
        for idx, n in i:
            self._out('/I' + str(idx) + ' ' + str(n) + ' 0 R')

    def _putresourcedict(self):
        self._out('/ProcSet [/PDF /Text /ImageB /ImageC /ImageI]')
        self._out('/Font <<')
        f = [(x["i"], x["n"]) for x in self.fonts.values()]
        f.sort()
        for idx, n in f:
            self._out('/F' + str(idx) + ' ' + str(n) + ' 0 R')
        self._out('>>')
        self._out('/XObject <<')
        self._putxobjectdict()
        self._out('>>')

    def _putresources(self):
        self._putfonts()
        self._putimages()
        # Resource dictionary
        self.offsets[2] = len(self.buffer)
        self._out('2 0 obj')
        self._out('<<')
        self._putresourcedict()
        self._out('>>')
        self._out('endobj')

    def _putinfo(self):
        self._out('/Producer ' + self._textstring('PyFPDF ' + FPDF_VERSION + ' http://pyfpdf.googlecode.com/'))
        if hasattr(self, 'title'):
            self._out('/Title ' + self._textstring(self.title))
        if hasattr(self, 'subject'):
            self._out('/Subject ' + self._textstring(self.subject))
        if hasattr(self, 'author'):
            self._out('/Author ' + self._textstring(self.author))
        if hasattr(self, 'keywords'):
            self._out('/Keywords ' + self._textstring(self.keywords))
        if hasattr(self, 'creator'):
            self._out('/Creator ' + self._textstring(self.creator))
        self._out('/CreationDate ' + self._textstring('D:' + datetime.now().strftime('%Y%m%d%H%M%S')))

    def _putcatalog(self):
        self._out('/Type /Catalog')
        self._out('/Pages 1 0 R')
        if self.settings.zoom_mode == 'fullpage':
            self._out('/OpenAction [3 0 R /Fit]')
        elif self.settings.zoom_mode == 'fullwidth':
            self._out('/OpenAction [3 0 R /FitH null]')
        elif self.settings.zoom_mode == 'real':
            self._out('/OpenAction [3 0 R /XYZ null null 1]')
        elif not isinstance(self.settings.zoom_mode, basestring):
            self._out(f'/OpenAction [3 0 R /XYZ null null {self.settings.zoom_mode / 100}]')

        if self.settings.layout_mode == 'single':
            self._out('/PageLayout /SinglePage')
        elif self.settings.layout_mode == 'continuous':
            self._out('/PageLayout /OneColumn')
        elif self.settings.layout_mode == 'two':
            self._out('/PageLayout /TwoColumnLeft')

    def _putheader(self):
        self._out('%PDF-' + self.pdf_version)

    def _puttrailer(self):
        self._out('/Size ' + str(self.n + 1))
        self._out('/Root ' + str(self.n) + ' 0 R')
        self._out('/Info ' + str(self.n - 1) + ' 0 R')

    def _enddoc(self):
        self._putheader()
        self._putpages()
        self._putresources()
        # Info
        with self._newobj():
            self._out('<<')
            self._putinfo()
            self._out('>>')

        # Catalog
        with self._newobj():
            self._out('<<')
            self._putcatalog()
            self._out('>>')

        # Cross-ref
        o = len(self.buffer)
        self._out('xref')
        self._out('0 ' + (str(self.n + 1)))
        self._out('0000000000 65535 f ')
        for i in range(1, self.n + 1):
            self._out(f'{self.offsets[i]:010d} 00000 n ', )
        # Trailer
        self._out('trailer')
        self._out('<<')
        self._puttrailer()
        self._out('>>')
        self._out('startxref')
        self._out(o)
        self._out('%%EOF')
        self.state = DocumentState.TERMINATED

    def set_page_format(self, page_format):
        if page_format:
            # Change page format
            self.settings.file_width_points, self.settings.file_height_points = get_page_dimensions(page_format, self.settings.scale)
        else:
            # Set to default format
            self.settings.file_width_points, self.settings.file_height_points = self.settings.document_width_points, self.settings.document_height_points

    def set_page_orientation(self, page_orientation):
        if not page_orientation:
            orientation = self.settings.def_orientation
        else:
            orientation = page_orientation[0].upper()

        if orientation == 'P':
            self.settings.width_points = self.settings.file_width_points
            self.settings.height_points = self.settings.file_height_points
        else:
            self.settings.width_points = self.settings.file_height_points
            self.settings.height_points = self.settings.file_width_points

    def _beginpage(self, page_orientation, page_format, same):

        self.current_page += 1
        self.pages[self.current_page] = {"content": ""}
        self.state = DocumentState.WRITING_PAGE
        self.x = self.settings.left_page_margin
        self.y = self.settings.top_page_margin
        self.settings.font_family = ''
        self.settings.font_stretching = 100

        if not same:
            self.set_page_format(page_format)
            self.set_page_orientation(page_orientation)
            self.settings.width_unit = self.settings.width_points / self.settings.scale
            self.settings.height_unit = self.settings.height_points / self.settings.scale
            self.settings.page_break_trigger = self.settings.height_unit - self.settings.bottom_page_margin

        self.pages[self.current_page]["w_pt"] = self.settings.width_points
        self.pages[self.current_page]["h_pt"] = self.settings.height_points

    def _endpage(self):
        # End of page contents
        self.state = DocumentState.OPEN_IDLE

    @contextmanager
    def _newobj(self):
        self.n += 1
        self.offsets[self.n] = len(self.buffer)
        self._out(str(self.n) + ' 0 obj')
        yield
        self._out('endobj')

    def _dounderline(self, x, y, txt):
        # Underline text
        up = self.current_font['up']
        ut = self.current_font['ut']
        w = self.get_string_width(txt, True) + self.settings.word_spacing * txt.count(' ')
        return f'{x * self.settings.scale:.2f} ' \
               f'{(self.settings.height_unit - (y - up / 1000.0 * self.font_size)) * self.settings.scale:.2f} ' \
               f'{w * self.settings.scale:.2f} ' \
               f'{-ut / 1000.0 * self.settings.font_size_pt:.2f} ' \
               f're f'

    def _parsejpg(self, filename):
        # Extract info from a JPEG file
        f = None
        try:
            f = load_resource("image", filename)
            while True:
                markerHigh, markerLow = struct.unpack('BB', f.read(2))
                if markerHigh != 0xFF or markerLow < 0xC0:
                    raise SyntaxError('No JPEG marker found')
                elif markerLow == 0xDA:  # SOS
                    raise SyntaxError('No JPEG SOF marker found')
                elif (markerLow == 0xC8 or  # JPG
                      (0xD0 <= markerLow <= 0xD9) or  # RSTx
                      (0xF0 <= markerLow <= 0xFD)):  # JPGx
                    pass
                else:
                    dataSize, = struct.unpack('>H', f.read(2))
                    data = f.read(dataSize - 2) if dataSize > 2 else ''
                    if ((0xC0 <= markerLow <= 0xC3) or  # SOF0 - SOF3
                            (0xC5 <= markerLow <= 0xC7) or  # SOF4 - SOF7
                            (0xC9 <= markerLow <= 0xCB) or  # SOF9 - SOF11
                            (0xCD <= markerLow <= 0xCF)):  # SOF13 - SOF15
                        bpc, height, width, layers = struct.unpack_from('>BHHB', data)
                        colspace = 'DeviceRGB' if layers == 3 else ('DeviceCMYK' if layers == 4 else 'DeviceGray')
                        break
        except Exception:
            if f:
                f.close()
            raise CatchAllError('Missing or incorrect image file: %s. error: %s' % (filename, str(exception())))

        with f:
            # Read whole file from the start
            f.seek(0)
            data = f.read()
        return {'w': width, 'h': height, 'cs': colspace, 'bpc': bpc, 'f': 'DCTDecode', 'data': data}

    def _parsegif(self, filename):
        # Extract info from a GIF file (via PNG conversion)
        if Image is None:
            raise CatchAllError('PIL is required for GIF support')
        try:
            im = Image.open(filename)
        except:
            raise CatchAllError('Missing or incorrect image file: %s. error: %s' % (filename, str(exception())))
        else:
            # Use temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as \
                    f:
                tmp = f.name
            if "transparency" in im.info:
                im.save(tmp, transparency=im.info['transparency'])
            else:
                im.save(tmp)
            info = self._parsepng(tmp)
            os.unlink(tmp)
        return info

    def _parsepng(self, filename):
        # Extract info from a PNG file
        f = load_resource("image", filename)
        # Check signature
        magic = f.read(8).decode("latin1")
        signature = '\x89' + 'PNG' + '\r' + '\n' + '\x1a' + '\n'
        if not PY3K: signature = signature.decode("latin1")
        if magic != signature:
            raise CatchAllError('Not a PNG file: ' + filename)
        # Read header chunk
        f.read(4)
        chunk = f.read(4).decode("latin1")
        if chunk != 'IHDR':
            raise CatchAllError('Incorrect PNG file: ' + filename)
        w = self._freadint(f)
        h = self._freadint(f)
        bpc = ord(f.read(1))
        if (bpc > 8):
            raise CatchAllError('16-bit depth not supported: ' + filename)
        ct = ord(f.read(1))
        if ct == 0 or ct == 4:
            colspace = 'DeviceGray'
        elif ct == 2 or ct == 6:
            colspace = 'DeviceRGB'
        elif ct == 3:
            colspace = 'Indexed'
        else:
            raise CatchAllError('Unknown color type: ' + filename)
        if ord(f.read(1)) != 0:
            raise CatchAllError('Unknown compression method: ' + filename)
        if ord(f.read(1)) != 0:
            raise CatchAllError('Unknown filter method: ' + filename)
        if ord(f.read(1)) != 0:
            raise CatchAllError('Interlacing not supported: ' + filename)
        f.read(4)
        dp = '/Predictor 15 /Colors '
        if colspace == 'DeviceRGB':
            dp += '3'
        else:
            dp += '1'
        dp += ' /BitsPerComponent ' + str(bpc) + ' /Columns ' + str(w) + ''
        # Scan chunks looking for palette, transparency and image data
        pal = ''
        trns = ''
        data = bytes() if PY3K else str()
        n = 1
        while n is not None:
            n = self._freadint(f)
            type = f.read(4).decode("latin1")
            if type == 'PLTE':
                # Read palette
                pal = f.read(n)
                f.read(4)
            elif type == 'tRNS':
                # Read transparency info
                t = f.read(n)
                if ct == 0:
                    trns = [ord(substr(t, 1, 1)), ]
                elif ct == 2:
                    trns = [ord(substr(t, 1, 1)), ord(substr(t, 3, 1)), ord(substr(t, 5, 1))]
                else:
                    pos = t.find('\x00'.encode("latin1"))
                    if pos != -1:
                        trns = [pos, ]
                f.read(4)
            elif type == 'IDAT':
                # Read image data block
                data += f.read(n)
                f.read(4)
            elif type == 'IEND':
                break
            else:
                f.read(n + 4)

        if colspace == 'Indexed' and not pal:
            raise CatchAllError('Missing palette in ' + filename)
        f.close()
        info = {'w': w, 'h': h, 'cs': colspace, 'bpc': bpc, 'f': 'FlateDecode', 'dp': dp, 'pal': pal, 'trns': trns, }
        if ct >= 4:
            # Extract alpha channel
            data = zlib.decompress(data)
            color = b('')
            alpha = b('')
            if ct == 4:
                # Gray image
                length = 2 * w
                for i in range(h):
                    pos = (1 + length) * i
                    color += b(data[pos])
                    alpha += b(data[pos])
                    line = substr(data, pos + 1, length)
                    re_c = re.compile('(.).'.encode("ascii"), flags=re.DOTALL)
                    re_a = re.compile('.(.)'.encode("ascii"), flags=re.DOTALL)
                    color += re_c.sub(lambda m: m.group(1), line)
                    alpha += re_a.sub(lambda m: m.group(1), line)
            else:
                # RGB image
                length = 4 * w
                for i in range(h):
                    pos = (1 + length) * i
                    color += b(data[pos])
                    alpha += b(data[pos])
                    line = substr(data, pos + 1, length)
                    re_c = re.compile('(...).'.encode("ascii"), flags=re.DOTALL)
                    re_a = re.compile('...(.)'.encode("ascii"), flags=re.DOTALL)
                    color += re_c.sub(lambda m: m.group(1), line)
                    alpha += re_a.sub(lambda m: m.group(1), line)
            del data
            data = zlib.compress(color)
            info['smask'] = zlib.compress(alpha)
            if self.pdf_version < '1.4':
                self.pdf_version = '1.4'
        info['data'] = data
        return info

    def _freadint(self, f):
        # Read a 4-byte integer from file
        try:
            return struct.unpack('>I', f.read(4))[0]
        except:
            return None

    def _textstring(self, s):
        # Format a text string
        return '(' + self._escape(s) + ')'

    def _escape(self, s):
        # Add \ before \, ( and )
        return s.replace('\\', '\\\\').replace(')', '\\)').replace('(', '\\(').replace('\r', '\\r')

    def _putstream(self, s):
        self._out('stream')
        self._out(s)
        self._out('endstream')

    def postprocess_image_dict(self, element):
        if element.name not in self.images:
            element.info['i'] = len(self.images) + 1
            self.images[element.name] = element.info
        else:
            element.info['i'] = self.images[element.name]['i']

    @check_page
    def insert(self, element):
        if hasattr(element, "to_string"):

            if isinstance(element, Figure):
                self.add_page_if_break_reached(element)

                if element.x is None:
                    element.x = self.x

                self.postprocess_image_dict(element)

                if element.link:
                    self.link(element.x, element.y, element.w, element.h, element.link)

            element_hex = element.to_string(self.settings)

            if isinstance(element_hex, str):
                self._out(element_hex)
            elif isinstance(element_hex, list):
                for item in element_hex:
                    self._out(item)
            else:
                raise TypeError("Invalid PDF element HEX type")

        elif isinstance(element, str):
            self._out(element)
        else:
            raise TypeError("Invalid PDF element type")

    def add_page_if_break_reached(self, figure):
        if figure.y is None:
            if self.y + figure.h > self.settings.page_break_trigger and not self.in_footer and self.settings.auto_page_break:
                # Automatic page break
                figure.x = self.x
                self.add_page(same=True)
                self.x = figure.x
            figure.y = self.y
            self.y += figure.h

    def _format_string(self, s):
        if isinstance(s, bytes):
            # manage binary data as latin1 until PEP461-like function is implemented
            s = s.decode("latin1")
        elif not isinstance(s, str):
            s = str(s)
        return s

    def _out(self, s):
        if self.state == DocumentState.WRITING_PAGE:
            self.pages[self.current_page]["content"] += f"{self._format_string(s)}\n"
        else:
            self.buffer += f"{self._format_string(s)}\n"

    @check_page
    def interleaved2of5(self, txt, x, y, w=1.0, h=10.0):
        """Barcode I2of5 (numeric), adds a 0 if odd lenght"""
        narrow = w / 3.0
        wide = w

        # wide/narrow codes for the digits
        bar_char = {'0': 'nnwwn', '1': 'wnnnw', '2': 'nwnnw', '3': 'wwnnn',
                    '4': 'nnwnw', '5': 'wnwnn', '6': 'nwwnn', '7': 'nnnww',
                    '8': 'wnnwn', '9': 'nwnwn', 'A': 'nn', 'Z': 'wn'}

        self.set_fill_color(0)
        code = txt
        # add leading zero if code-length is odd
        if len(code) % 2 != 0:
            code = '0' + code

        # add start and stop codes
        code = 'AA' + code.lower() + 'ZA'

        for i in range(0, len(code), 2):
            # choose next pair of digits
            char_bar = code[i]
            char_space = code[i + 1]
            # check whether it is a valid digit
            if char_bar not in bar_char.keys():
                raise RuntimeError('Char "%s" invalid for I25: ' % char_bar)
            if char_space not in bar_char.keys():
                raise RuntimeError('Char "%s" invalid for I25: ' % char_space)

            # create a wide/narrow-seq (first digit=bars, second digit=spaces)
            seq = ''
            for s in range(0, len(bar_char[char_bar])):
                seq += bar_char[char_bar][s] + bar_char[char_space][s]

            for bar in range(0, len(seq)):
                # set line_width depending on value
                if seq[bar] == 'n':
                    line_width = narrow
                else:
                    line_width = wide

                # draw every second value, the other is represented by space
                if bar % 2 == 0:
                    rectangle = Rectangle(x, y, line_width, h, "F")  # "F" stands for full
                    self.insert(rectangle)

                x += line_width

    @check_page
    def code39(self, txt, x, y, w=1.5, h=5.0):
        """Barcode 3of9"""
        dim = {'w': w, 'n': w / 3.}
        chars = {
            '0': 'nnnwwnwnn', '1': 'wnnwnnnnw', '2': 'nnwwnnnnw',
            '3': 'wnwwnnnnn', '4': 'nnnwwnnnw', '5': 'wnnwwnnnn',
            '6': 'nnwwwnnnn', '7': 'nnnwnnwnw', '8': 'wnnwnnwnn',
            '9': 'nnwwnnwnn', 'A': 'wnnnnwnnw', 'B': 'nnwnnwnnw',
            'C': 'wnwnnwnnn', 'D': 'nnnnwwnnw', 'E': 'wnnnwwnnn',
            'F': 'nnwnwwnnn', 'G': 'nnnnnwwnw', 'H': 'wnnnnwwnn',
            'I': 'nnwnnwwnn', 'J': 'nnnnwwwnn', 'K': 'wnnnnnnww',
            'L': 'nnwnnnnww', 'M': 'wnwnnnnwn', 'N': 'nnnnwnnww',
            'O': 'wnnnwnnwn', 'P': 'nnwnwnnwn', 'Q': 'nnnnnnwww',
            'R': 'wnnnnnwwn', 'S': 'nnwnnnwwn', 'T': 'nnnnwnwwn',
            'U': 'wwnnnnnnw', 'V': 'nwwnnnnnw', 'W': 'wwwnnnnnn',
            'X': 'nwnnwnnnw', 'Y': 'wwnnwnnnn', 'Z': 'nwwnwnnnn',
            '-': 'nwnnnnwnw', '.': 'wwnnnnwnn', ' ': 'nwwnnnwnn',
            '*': 'nwnnwnwnn', '$': 'nwnwnwnnn', '/': 'nwnwnnnwn',
            '+': 'nwnnnwnwn', '%': 'nnnwnwnwn',
        }
        self.set_fill_color(0)
        for c in txt.upper():
            if c not in chars:
                raise RuntimeError('Invalid char "%s" for Code39' % c)
            for i, d in enumerate(chars[c]):
                if i % 2 == 0:
                    rectangle = Rectangle(x, y, dim[d], h, "F")  # "F" stands for full
                    self.insert(rectangle)
                x += dim[d]
            x += dim['n']

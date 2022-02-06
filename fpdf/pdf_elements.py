import math
import abc
import os
import re
import zlib
import struct
import tempfile

from PIL import Image

from .helpers import get_op_from_draw_style, load_resource, substr, to_bytes
from .image_parsers import JPGParser, PNGParser, GIFParser


class PDFElement(abc.ABC):
    @abc.abstractmethod
    def __init__(self):
        pass

    @abc.abstractmethod
    def to_string(self, settings):
        pass


class Line(PDFElement):
    def __init__(self, x1, y1, x2, y2):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2

    def to_string(self, settings):
        return f"{self.x1 * settings.scale:.2f} " \
               f"{(settings.height_unit - self.y1) * settings.scale:.2f} m " \
               f"{self.x2 * settings.scale:.2f} " \
               f"{(settings.height_unit - self.y2) * settings.scale:.2f} l S"


class DashedLine(PDFElement):
    def __init__(self, x1, y1, x2, y2, dash_length=1, space_length=1):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.dash_length = dash_length
        self.space_length = space_length

    def to_string(self, settings):
        hex = []
        hex.append(self.set_dash(settings, self.dash_length, self.space_length))
        hex.append(Line(self.x1, self.y1, self.x2, self.y2).to_string(settings))
        hex.append(self.set_dash(settings))
        return hex

    def set_dash(self, settings, dash_length=1, space_length=1):
        if dash_length and space_length:
            return f"[{dash_length * settings.scale:.3f} {space_length * settings.scale:.3f}] 0 d"
        else:
            return "[] 0 d"


class Rectangle(PDFElement):
    def __init__(self, x_coord, y_coord, width, height, drawing_style=None):
        self.x_coord = x_coord
        self.y_coord = y_coord
        self.width = width
        self.height = height
        self.drawing_style = drawing_style

    def to_string(self, settings):
        return f"{self.x_coord * settings.scale:.2f} " \
               f"{(settings.height_unit - self.y_coord) * settings.scale:.2f} " \
               f"{self.width * settings.scale:.2f} {-self.height * settings.scale:.2f} re " \
               f"{get_op_from_draw_style(self.drawing_style)}"


class Ellipse(PDFElement):
    def __init__(self, x_top_left, y_top_left, width, height, drawing_style=''):
        self.drawing_style = drawing_style

        self.x_center = x_top_left + width / 2.0
        self.y_center = y_top_left + height / 2.0
        self.radius_along_x = width / 2.0
        self.radius_along_y = height / 2.0

        self.lenght_along_x = 4.0 / 3.0 * (math.sqrt(2) - 1) * self.radius_along_x
        self.lenght_along_y = 4.0 / 3.0 * (math.sqrt(2) - 1) * self.radius_along_y

    def to_string(self, settings):

        hex = []

        hex.append(f"{(self.x_center + self.radius_along_x) * settings.scale:.2f} "
                   f"{(settings.height_unit - self.y_center) * settings.scale:.2f} m "
                   f"{(self.x_center + self.radius_along_x) * settings.scale:.2f} "
                   f"{(settings.height_unit - (self.y_center - self.lenght_along_y)) * settings.scale:.2f} "
                   f"{(self.x_center + self.lenght_along_x) * settings.scale:.2f} "
                   f"{(settings.height_unit - (self.y_center - self.radius_along_y)) * settings.scale:.2f} "
                   f"{self.x_center * settings.scale:.2f} "
                   f"{(settings.height_unit - (self.y_center - self.radius_along_y)) * settings.scale:.2f} c")

        hex.append(f"{(self.x_center - self.lenght_along_x) * settings.scale:.2f} "
                   f"{(settings.height_unit - (self.y_center - self.radius_along_y)) * settings.scale:.2f} "
                   f"{(self.x_center - self.radius_along_x) * settings.scale:.2f} "
                   f"{(settings.height_unit - (self.y_center - self.lenght_along_y)) * settings.scale:.2f} "
                   f"{(self.x_center - self.radius_along_x) * settings.scale:.2f} "
                   f"{(settings.height_unit - self.y_center) * settings.scale:.2f} c")

        hex.append(f"{(self.x_center - self.radius_along_x) * settings.scale:.2f} "
                   f"{(settings.height_unit - (self.y_center + self.lenght_along_y)) * settings.scale:.2f} "
                   f"{(self.x_center - self.lenght_along_x) * settings.scale:.2f} "
                   f"{(settings.height_unit - (self.y_center + self.radius_along_y)) * settings.scale:.2f} "
                   f"{self.x_center * settings.scale:.2f} "
                   f"{(settings.height_unit - (self.y_center + self.radius_along_y)) * settings.scale:.2f} c")

        hex.append(f"{(self.x_center + self.lenght_along_x) * settings.scale:.2f} "
                   f"{(settings.height_unit - (self.y_center + self.radius_along_y)) * settings.scale:.2f} "
                   f"{(self.x_center + self.radius_along_x) * settings.scale:.2f} "
                   f"{(settings.height_unit - (self.y_center + self.lenght_along_y)) * settings.scale:.2f} "
                   f"{(self.x_center + self.radius_along_x) * settings.scale:.2f} "
                   f"{(settings.height_unit - self.y_center) * settings.scale:.2f} c"
                   f"{get_op_from_draw_style(self.drawing_style)}")

        return hex


# TODO: Get settings out of the __init__ signature
class Figure(PDFElement):

    parsers = [JPGParser, PNGParser, GIFParser]

    def __init__(self, name: str, x=None, y=None, w=0, h=0, is_mask=False, mask_image=None, settings=None, link=None):
        self.name = name
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.type = self._get_image_extension()
        self.settings = settings
        self.is_mask = is_mask
        self.link = link

        self.info = self.get_image_info()

        if is_mask:
            assert self.info['cs'] == 'DeviceGray', 'Mask must be a gray scale image'

        if mask_image:
            self.info['masked'] = mask_image

        # Automatic width and height calculation if needed
        if self.w == 0 and self.h == 0:
            # Put image at 72 dpi
            self.w = self.info['w'] / self.settings.scale
            self.h = self.info['h'] / self.settings.scale
        elif self.w == 0:
            self.w = self.h * self.info['w'] / self.info['h']

        elif self.h == 0:
            self.h = self.w * self.info['h'] / self.info['w']

    def _get_image_extension(self):
        image_name_members = self.name.split(".")
        if len(image_name_members) < 2:
            raise TypeError(f"image file has no extension and no type was specified: {self.name}")

        return image_name_members[-1].lower()

    def get_image_info(self):

        info = None

        if self.type in ['jpg', 'jpeg']:
            figure = JPGParser(self.name)
            info = figure.packaged_data

        elif self.type == 'png':
            figure = PNGParser(self.name)
            info = figure.packaged_data

        elif self.type == "gif":
            figure = GIFParser(self.name)
            info = figure.packaged_data

        else:
            # Maybe the image is not showing the correct extension, but the image file header is OK.

            for parser in self.parsers:
                try:
                    figure = parser(self.name)
                    info = figure.packaged_data
                    break
                except Exception:
                    continue

        assert info, f"Image file {self.name} cannot be parsed"

        return info


    def to_string(self, settings):
        if not self.is_mask:
            return f"q {self.w * settings.scale:.2f} 0 0 {self.h * settings.scale:.2f} {self.x * settings.scale:.2f} " \
                   f"{(settings.height_unit - (self.y + self.h)) * settings.scale:.2f} cm /I{self.info['i']:d} Do Q"

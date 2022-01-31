import math
import abc

from .helpers import get_op_from_draw_style


class PDFElement(abc.ABC):
    @abc.abstractmethod
    def __init__(self):
        pass

    @abc.abstractmethod
    def to_string(self):
        pass


class Line(PDFElement):
    def __init__(self, x1, y1, x2, y2, settings):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.settings = settings

    def to_string(self):
        return f"{self.x1 * self.settings.scale:.2f} " \
               f"{(self.settings.height_unit - self.y1) * self.settings.scale:.2f} m " \
               f"{self.x2 * self.settings.scale:.2f} " \
               f"{(self.settings.height_unit - self.y2) * self.settings.scale:.2f} l S"


class DashedLine(PDFElement):
    def __init__(self, x1, y1, x2, y2, settings, dash_length=1, space_length=1):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.settings = settings
        self.dash_length = dash_length
        self.space_length = space_length

    def to_string(self):
        hex = []
        hex.append(self.set_dash(self.dash_length, self.space_length))
        hex.append(Line(self.x1, self.y1, self.x2, self.y2, self.settings).to_string())
        hex.append(self.set_dash())
        return hex

    def set_dash(self, dash_length=1, space_length=1):
        if dash_length and space_length:
            return f"[{dash_length * self.settings.scale:.3f} {space_length * self.settings.scale:.3f}] 0 d"
        else:
            return "[] 0 d"


class Rectangle(PDFElement):
    def __init__(self, x_coord, y_coord, width, height, settings, drawing_style=None):
        self.x_coord = x_coord
        self.y_coord = y_coord
        self.width = width
        self.height = height
        self.settings = settings
        self.drawing_style = drawing_style

    def to_string(self):
        return f"{self.x_coord * self.settings.scale:.2f} " \
               f"{(self.settings.height_unit - self.y_coord) * self.settings.scale:.2f} " \
               f"{self.width * self.settings.scale:.2f} {-self.height * self.settings.scale:.2f} re " \
               f"{get_op_from_draw_style(self.drawing_style)}"


class Ellipse(PDFElement):
    def __init__(self, x_top_left, y_top_left, width, height, settings, drawing_style=''):

        self.settings = settings
        self.drawing_style = drawing_style

        self.x_center = x_top_left + width / 2.0
        self.y_center = y_top_left + height / 2.0
        self.radius_along_x = width / 2.0
        self.radius_along_y = height / 2.0

        self.lenght_along_x = 4.0 / 3.0 * (math.sqrt(2) - 1) * self.radius_along_x
        self.lenght_along_y = 4.0 / 3.0 * (math.sqrt(2) - 1) * self.radius_along_y

    def to_string(self):

        hex = []

        hex.append(f"{(self.x_center + self.radius_along_x) * self.settings.scale:.2f} "
                   f"{(self.settings.height_unit - self.y_center) * self.settings.scale:.2f} m "
                   f"{(self.x_center + self.radius_along_x) * self.settings.scale:.2f} "
                   f"{(self.settings.height_unit - (self.y_center - self.lenght_along_y)) * self.settings.scale:.2f} "
                   f"{(self.x_center + self.lenght_along_x) * self.settings.scale:.2f} "
                   f"{(self.settings.height_unit - (self.y_center - self.radius_along_y)) * self.settings.scale:.2f} "
                   f"{self.x_center * self.settings.scale:.2f} "
                   f"{(self.settings.height_unit - (self.y_center - self.radius_along_y)) * self.settings.scale:.2f} c")

        hex.append(f"{(self.x_center - self.lenght_along_x) * self.settings.scale:.2f} "
                   f"{(self.settings.height_unit - (self.y_center - self.radius_along_y)) * self.settings.scale:.2f} "
                   f"{(self.x_center - self.radius_along_x) * self.settings.scale:.2f} "
                   f"{(self.settings.height_unit - (self.y_center - self.lenght_along_y)) * self.settings.scale:.2f} "
                   f"{(self.x_center - self.radius_along_x) * self.settings.scale:.2f} "
                   f"{(self.settings.height_unit - self.y_center) * self.settings.scale:.2f} c")

        hex.append(f"{(self.x_center - self.radius_along_x) * self.settings.scale:.2f} "
                   f"{(self.settings.height_unit - (self.y_center + self.lenght_along_y)) * self.settings.scale:.2f} "
                   f"{(self.x_center - self.lenght_along_x) * self.settings.scale:.2f} "
                   f"{(self.settings.height_unit - (self.y_center + self.radius_along_y)) * self.settings.scale:.2f} "
                   f"{self.x_center * self.settings.scale:.2f} "
                   f"{(self.settings.height_unit - (self.y_center + self.radius_along_y)) * self.settings.scale:.2f} c")

        hex.append(f"{(self.x_center + self.lenght_along_x) * self.settings.scale:.2f} "
                   f"{(self.settings.height_unit - (self.y_center + self.radius_along_y)) * self.settings.scale:.2f} "
                   f"{(self.x_center + self.radius_along_x) * self.settings.scale:.2f} "
                   f"{(self.settings.height_unit - (self.y_center + self.lenght_along_y)) * self.settings.scale:.2f} "
                   f"{(self.x_center + self.radius_along_x) * self.settings.scale:.2f} "
                   f"{(self.settings.height_unit - self.y_center) * self.settings.scale:.2f} c"
                   f"{get_op_from_draw_style(self.drawing_style)}")

        return hex

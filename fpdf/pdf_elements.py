from .helpers import get_op_from_draw_style


class Line:
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


class Rectangle:
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

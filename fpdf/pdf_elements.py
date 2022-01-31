from .helpers import get_op_from_draw_style


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

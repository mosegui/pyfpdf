from .helpers import init_display_zoom_level, init_display_layout_mode, get_page_dimensions


class PDFSettings:

    core_fonts_encoding = "latin-1"

    def __init__(self, orientation='P', unit='mm', format='A4', title=None, subject=None, author=None, keywords=None, creator=None):

        self.title = title
        self.subject = subject
        self.author = author
        self.keywords = keywords
        self.creator = creator

        self.font_family = ''  # current font family
        self.font_style = ''  # current font style
        self.font_size_pt = 12  # current font size in points
        self.font_stretching = 100  # current font stretching
        self.underline = 0  # underlining flag
        self.draw_color = '0 G'
        self.fill_color = '0 g'
        self.text_color = '0 g'
        self.color_flag = 0  # indicates whether fill and text colors are different
        self.word_spacing = 0  # word spacing
        self.angle = 0

        self.scale = self.get_units_scale(unit)

        # Page format
        self.file_width_points, self.file_height_points = get_page_dimensions(format, self.scale)  # in points
        self.document_width_points = self.file_width_points
        self.document_height_points = self.file_height_points
        self.file_width_unit = self.file_width_points / self.scale
        self.file_height_unit = self.file_height_points / self.scale

        self.def_orientation, self.width_points, self.height_points = self.set_page_orientation(orientation)

        self.width_unit = self.width_points / self.scale
        self.height_unit = self.height_points / self.scale

        self.left_page_margin, self.top_page_margin, self.right_page_margin, self.bottom_page_margin = self.init_page_margins()
        self.cell_margin = self.init_cell_margin()
        self.line_width = self.init_line_width()

        self.auto_page_break = True
        self.page_break_trigger = self.height_unit - self.bottom_page_margin

        # Full width display mode
        self.zoom_mode = init_display_zoom_level()
        self.layout_mode = init_display_layout_mode()

        # Enable compression
        self.compress = True

    @staticmethod
    def get_units_scale(unit):
        """
        Returns the scaling factor points (pixels) per unit
        """
        if unit == "pt":
            return 1
        elif unit == "mm":
            return 72 / 25.4
        elif unit == "cm":
            return 72 / 2.54
        elif unit == 'in':
            return 72.
        else:
            raise ValueError(f"Unknown unit: {unit}")

    def set_page_orientation(self, orientation):
        # Page orientation
        orientation = orientation.lower()
        if orientation in ('p', 'portrait'):
            return "P", self.file_width_points, self.file_height_points
        elif orientation in ('l', 'landscape'):
            return "L", self.file_height_points, self.file_width_points
        else:
            raise ValueError(f"Invalid orientation option: {orientation}")

    def init_page_margins(self, left_margin=None, top_margin=None, right_margin=None):

        default_margin = 28.35 / self.scale

        if left_margin is None:
            left_margin = default_margin
        if top_margin is None:
            top_margin = default_margin
        if right_margin is None:
            right_margin = default_margin

        bottom_margin = 2 * top_margin

        return left_margin, top_margin, right_margin, bottom_margin

    def init_line_width(self):
        return .567 / self.scale

    def init_cell_margin(self):
        return 2.835 / self.scale
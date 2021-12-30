from .py3k import basestring

# TODO: get rid of the basetring and of the support for Python 2.X

def init_display_zoom_level(zoom="fullwidth"):
    named_zoom_levels = ['fullpage', 'fullwidth', 'real', 'default']
    if zoom.lower() in named_zoom_levels or isinstance(zoom, (float, int)):
        return zoom
    else:
        raise ValueError(f"Invalid zoom level: {zoom}. Valid types are {named_zoom_levels} or a number between 0 and 100")


def init_display_layout_mode(layout='continuous'):
    named_layout_modes = ["single", "continuous", "two", "default"]
    if layout in named_layout_modes:
        return layout
    else:
        raise ValueError(f"Invalid layout mode: {layout}. Valid modes are: {named_layout_modes}")


def get_page_dimensions(format: str, scale: float):
    """
    Returns the document dimensions (width and height) in points (pixels)
    """
    PAGE_FORMATS = {
        "a3": (841.89, 1190.55),
        "a4": (595.28, 841.89),
        "a5": (420.94, 595.28),
        "letter": (612, 792),
        "legal": (612, 1008)
    }

    if isinstance(format, basestring):
        format = format.lower()
        if format in PAGE_FORMATS:
            return PAGE_FORMATS[format]
        else:
            raise ValueError(f"Unknown page format: {format}. Allowed formats: {PAGE_FORMATS.keys()}")
    else:
        return format[0] * scale, format[1] * scale
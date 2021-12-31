from .py3k import basestring
import pickle
import functools

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


def load_cache(filename):
    """Return unpickled object, or None if cache unavailable"""
    if not filename:
        return None
    try:
        with open(filename, "rb") as fh:
            return pickle.load(fh)
    except (IOError, ValueError):  # File missing, unsupported pickle, etc
        return None


class CatchAllError(Exception):
    # Is here to replace a deprecated raise CatchAllError method. Adjust instances to best types of error
    pass


def check_page(fn):
    """
    Decorator to protect drawing methods
    """

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        if not self.current_page and not kwargs.get('split_only'):
            raise CatchAllError("No page open, you need to call add_page() first")
        else:
            return fn(self, *args, **kwargs)

    return wrapper

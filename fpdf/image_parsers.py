import enum
import os
import re
import zlib
import struct
import tempfile

from PIL import Image

from .helpers import load_resource, substr, to_bytes, read_int_from_file


class JPGParser:

    class JPEGMarkers(enum.Enum):
        NUL = 0x00
        TEM = 0x01  # Temporary private use for arithmetic coding

        ###### JPEG 1994 - defined in ITU T.81 | ISO IEC 10918-1 ######

        # Frame types
        SOF0 = 0xC0  # Start of Frame (Baseline)
        SOF1 = 0xC1  # Start of Frame (Extended sequential)
        SOF2 = 0xC2  # Start of Frame (Progressive)
        SOF3 = 0xC3  # Start of Frame (Lossless)
        DHT = 0xC4  # Define Human Tables
        SOF5 = 0XC5  # Start of Frame (Differential sequential)
        SOF6 = 0xC6  # Start of Frame (Differential progressive)
        SOF7 = 0xC7  # Start of Frame (Differential lossless)
        JPG = 0xC8  # Reserved for JPEG extension
        SOF9 = 0xC9  # Start of Frame (Extended sequential, arithmetic)
        SOF10 = 0xCA  # Start of Frame (Progressive, arithmetic)
        SOF11 = 0xCB  # Start of Frame (Lossless, arithmetic)
        DAC = 0xCC  # Define arithmetic-coding conditioning
        SOF13 = 0xCD  # Start of Frame (Differential sequential, arithmetic)
        SOF14 = 0xCE  # Start of Frame (Differential progressive, arithmetic)
        SOF15 = 0xCF  # Start of Frame (Differential lossless, arithmetic)

        # Restart markers
        RST0 = 0xD0
        RST1 = 0xD1
        RST2 = 0xD2
        RST3 = 0xD3
        RST4 = 0xD4
        RST5 = 0xD5
        RST6 = 0xD6
        RST7 = 0xD7

        # Delimiters
        SOI = 0xD8  # Start of Image
        EOI = 0xD9  # End of Image
        SOS = 0xDA  # Start of Scan
        DQT = 0xDB  # Define Quantization Tables
        DNL = 0xDC  # Define number of lines
        DRI = 0xDD  # Define Restart Interval
        DHP = 0xDE  # Define Hierarchical Progression
        EXP = 0xDF  # Expand reference components

        ###### JPEG 1997 extensions ITU T.84 | ISO IEC 10918-3 ######

        # Application data sections
        APP0 = 0xE0
        APP1 = 0xE1
        APP2 = 0xE2
        APP3 = 0xE3
        APP4 = 0xE4
        APP5 = 0xE5
        APP6 = 0xE6
        APP7 = 0xE7
        APP8 = 0xE8
        APP9 = 0xE9
        APP10 = 0xEA
        APP11 = 0xEB
        APP12 = 0xEC
        APP13 = 0xED
        APP14 = 0xEE
        APP15 = 0xEF

        # Extension data sections
        JPG0 = 0xF0
        JPG1 = 0xF1
        JPG2 = 0xF2
        JPG3 = 0xF3
        JPG4 = 0xF4
        JPG5 = 0xF5
        JPG6 = 0xF6
        SOF48 = 0xF7  # JPEG - LS
        LSE = 0xF8    # JPEG - LS extension parameters
        JPG9 = 0xF9
        JPG10 = 0xFA
        JPG11 = 0xFB
        JPG12 = 0xFC
        JPG13 = 0xFD
        JCOM = 0xFE  # Comment

        ###### JPEG 2000 - defined in IEC 15444 - 1 "JPEG 2000 Core (part 1)" ######

        #  Delimiters
        SOC = 0x4F  # Start of codestream
        SOT = 0x90  # Start of tile
        SOD = 0x93  # Start of data
        EOC = 0xD9  # End of codestream

        # Fixed information segment
        SIZ = 0x51  # Image and tile size

        # Functional segments
        COD = 0x52  # Coding style default
        COC = 0x53  # Coding style component
        RGN = 0x5E  # Region of interest
        QCD = 0x5C  # Quantization default
        QCC = 0x5D  # Quantization component
        POC = 0x5F  # Progression order change

        # Pointer segments
        TLM = 0x55  # Tile - part lengths
        PLM = 0x57  # Packet length(main header)
        PLT = 0x58  # Packet length(tile - part header)
        PPM = 0x60  # Packed packet headers(main header)
        PPT = 0x61  # Packet packet headers(tile - part header)

        # Bitstream internal markers and segments
        SOP = 0x91  # Start of packet
        EPH = 0x92  # End of packet header

        # Informational segments
        CRG = 0x63  # Component registration
        COM = 0x64  # Comment

        # Control
        CONTROL = 0xFF  # Marker control byte

    def __init__(self, filename):
        self.filename = filename

        self.file_bytes = None

        self.bpc, self.height, self.width, self.colspace = self.get_image_metadata()
        self.data = self.get_image_data()

    def get_image_metadata(self):
        try:
            self.file_bytes = load_resource("image", self.filename)

            while True:
                marker_high, marker_low = self.get_jpeg_marker(self.file_bytes)
                if marker_high != self.JPEGMarkers.CONTROL.value or marker_low < self.JPEGMarkers.SOF0.value:
                    raise SyntaxError('No JPEG marker found')

                elif marker_low == self.JPEGMarkers.SOS.value:
                    raise SyntaxError('No JPEG SOF marker found')

                elif (marker_low == self.JPEGMarkers.JPG.value or self.JPEGMarkers.RST0.value <= marker_low <= self.JPEGMarkers.EOI.value or self.JPEGMarkers.JPG0.value <= marker_low <= self.JPEGMarkers.JPG13.value):
                    pass

                else:
                    dataSize, = struct.unpack('>H', self.file_bytes.read(2))

                    if dataSize > 2:
                        data = self.file_bytes.read(dataSize - 2)
                    else:
                        data = ""

                    if self.JPEGMarkers.SOF0.value <= marker_low <= self.JPEGMarkers.SOF15.value and (marker_low not in [self.JPEGMarkers.DHT.value, self.JPEGMarkers.JPG.value, self.JPEGMarkers.DAC.value]):
                        bpc, height, width, layers = struct.unpack_from('>BHHB', data)
                        colspace = self._get_colspace(layers)
                        break

        except Exception as e:
            if self.file_bytes:
                self.file_bytes.close()
            raise TypeError(f"Missing or incorrect image file: {self.filename}. error: {e}")

        # finally:
        #     if self.file_bytes:
        #         self.file_bytes.close()

        return bpc, height, width, colspace

    def get_image_data(self):
        with self.file_bytes:
            self.file_bytes.seek(0)
            return self.file_bytes.read()

    @property
    def packaged_data(self):
        return {'w': self.width, 'h': self.height, 'cs': self.colspace, 'bpc': self.bpc, 'f': 'DCTDecode', 'data': self.data}

    @staticmethod
    def get_jpeg_marker(file_bytes):
        return struct.unpack('BB', file_bytes.read(2))

    @staticmethod
    def _get_colspace(layers):
        if layers == 3:
            return 'DeviceRGB'
        elif layers == 4:
            return 'DeviceCMYK'
        else:
            return 'DeviceGray'


class PNGParser:
    def __init__(self, filename):
        self.filename = filename

        self.file_bytes = load_resource("image", self.filename)

        self.check_file_is_PNG()
        self.check_header_chunk()

        self.width = read_int_from_file(self.file_bytes)
        self.height = read_int_from_file(self.file_bytes)

        self.bits_per_component = ord(self.file_bytes.read(1))
        assert self.bits_per_component <= 8, f"Image file: {self.filename}: 16-bit color depth not supported"

        self.color_type = ord(self.file_bytes.read(1))
        self.colspace = self.get_colspace()

        assert ord(self.file_bytes.read(1)) == 0, f"Unknown compression method: {self.filename}"
        assert ord(self.file_bytes.read(1)) == 0, f"Unknown filter method: {self.filename}"
        assert ord(self.file_bytes.read(1)) == 0, f"Interlacing not supported: {self.filename}"

        self.smask = None

        self.file_bytes.read(4)
        self.decoding_params = self.get_decoding_params()

        self.palette, self.transparency, self.data = self.get_image_data()

        if self.colspace == 'Indexed' and not self.palette:
            raise TypeError(f"Missing color palette in {self.filename}")

        self.file_bytes.close()

        if self.color_type >= 4:
            self.data, self.smask = self.extract_alpha_channel()

    def check_file_is_PNG(self):
        assert self.file_bytes.read(8).decode("latin1") == "\x89PNG\r\n\x1a\n", f"{self.filename} not a PNG file"

    def check_header_chunk(self):
        self.file_bytes.read(4)
        assert self.file_bytes.read(4).decode("latin1") == "IHDR", f"PNG file {self.filename} corrupted"

    def get_colspace(self):
        if self.color_type == 0 or self.color_type == 4:
            return 'DeviceGray'
        elif self.color_type == 2 or self.color_type == 6:
            return 'DeviceRGB'
        elif self.color_type == 3:
            return 'Indexed'
        else:
            raise TypeError(f"Unknown color type: {self.filename}")

    def get_decoding_params(self):
        # self.file_bytes.read(4)
        colors = 3 if self.colspace == 'DeviceRGB' else 1
        return f"/Predictor 15 /Colors {colors} /BitsPerComponent {self.bits_per_component} /Columns {self.width}"

    def get_image_data(self):
        """
        Scan chunks looking for palette, transparency and image data
        """
        palette = ''
        transparency = ''
        data = bytes()

        n = 1
        while n is not None:
            n = read_int_from_file(self.file_bytes)
            chunk_type = self.file_bytes.read(4).decode("latin1")

            if chunk_type == 'PLTE':  # palette
                palette = self.file_bytes.read(n)
                self.file_bytes.read(4)

            elif chunk_type == 'tRNS':  # transparency
                t = self.file_bytes.read(n)
                if self.color_type == 0:
                    transparency = [ord(substr(t, 1, 1)), ]
                elif self.color_type == 2:
                    transparency = [ord(substr(t, 1, 1)), ord(substr(t, 3, 1)), ord(substr(t, 5, 1))]
                else:
                    pos = t.find('\x00'.encode("latin1"))
                    if pos != -1:
                        transparency = [pos, ]
                self.file_bytes.read(4)

            elif chunk_type == 'IDAT':  # data block
                data += self.file_bytes.read(n)
                self.file_bytes.read(4)

            elif chunk_type == 'IEND':  # end of data
                break

            else:
                self.file_bytes.read(n + 4)

        return palette, transparency, data

    def extract_alpha_channel(self):
        data = zlib.decompress(self.data)
        color = to_bytes('')
        alpha = to_bytes('')

        if self.color_type == 4:
            # Gray image
            length = 2 * self.width
            re_c = re.compile('(.).'.encode("ascii"), flags=re.DOTALL)
            re_a = re.compile('.(.)'.encode("ascii"), flags=re.DOTALL)
        else:
            # RGB image
            length = 4 * self.width
            re_c = re.compile('(...).'.encode("ascii"), flags=re.DOTALL)
            re_a = re.compile('...(.)'.encode("ascii"), flags=re.DOTALL)

        for i in range(self.height):
            pos = (1 + length) * i
            color += to_bytes(data[pos])
            alpha += to_bytes(data[pos])
            line = substr(data, pos + 1, length)
            color += re_c.sub(lambda m: m.group(1), line)
            alpha += re_a.sub(lambda m: m.group(1), line)

        data = zlib.compress(color)
        smask = zlib.compress(alpha)

        return data, smask

    @property
    def packaged_data(self):
        result = {'w': self.width,
                'h': self.height,
                'cs': self.colspace,
                'bpc': self.bits_per_component,
                'f': 'FlateDecode',
                'dp': self.decoding_params,
                'pal': self.palette,
                'trns': self.transparency,
                "data": self.data}

        if self.smask:
            result["smask"] = self.smask

        return result


class GIFParser:
    def __init__(self, filename):
        self.filename = filename

        assert Image is not None, 'PIL is required for GIF support'

        try:
            im = Image.open(filename)
        except Exception as e:
            raise TypeError(f"Missing or incorrect image file: {filename}. error: {e}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
            tmp = f.name
        if "transparency" in im.info:
            im.save(tmp, transparency=im.info['transparency'])
        else:
            im.save(tmp)

        self.png_image = PNGParser(tmp)
        os.unlink(tmp)

    @property
    def packaged_data(self):
        return self.png_image.packaged_data

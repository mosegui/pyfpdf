# -*- coding: utf-8 -*-

"Tests new dashed line feature (issue 35)"

#PyFPDF-cover-test:format=PDF
#PyFPDF-cover-test:fn=issue_35.pdf
#PyFPDF-cover-test:hash=e8f92b3210aea65caa72f70d0f898c04

import common
from fpdf import FPDF

from fpdf.pdf_elements import DashedLine

@common.add_unittest
def dotest(outputname, nostamp):
    pdf = FPDF()
    if nostamp:
        pdf._putinfo = lambda: common.test_putinfo(pdf)

    pdf.add_page()

    pdf.insert(DashedLine(10, 10, 110, 10, pdf.settings))
    pdf.insert(DashedLine(10, 20, 110, 20, pdf.settings, 5, 5))
    pdf.insert(DashedLine(10, 30, 110, 30, pdf.settings, 1, 10))

    pdf.output(outputname, 'F')

if __name__ == "__main__":
    common.testmain(__file__, dotest)


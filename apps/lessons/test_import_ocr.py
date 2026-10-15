"""Real engine smoke tests, enabled in the Linux OCR image by CI."""
import io
import os
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch
from django.test import SimpleTestCase


def make_pdf(path, image=None):
    """Small valid PDF fixture, without a second PDF generation dependency."""
    stream = b'q 612 0 0 792 0 0 cm /Im1 Do Q' if image else b'BT /F1 24 Tf 50 700 Td (Digital lecture 42) Tj 0 -45 Td /F1 14 Tf (Exact source content for the course.) Tj ET'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> /XObject << /Im1 6 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    if image:
        raw = zlib.compress(image.convert('RGB').tobytes())
        objects.append(f'<< /Type /XObject /Subtype /Image /Width {image.width} /Height {image.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(raw)} >>\nstream\n'.encode() + raw + b'\nendstream')
    else:
        objects.append(b'<< >>')
    data = bytearray(b'%PDF-1.4\n'); offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data)); data.extend(f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(data)
    data.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    path.write_bytes(data)


@skipUnless(os.getenv('RUN_LECTURE_OCR_TESTS') == '1', 'Real OCR smoke runs in the Linux import-worker image')
class RealLectureOcrTests(SimpleTestCase):
    def image(self):
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new('RGB', (1600, 1600), 'white')
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 54)
        draw.text((100, 200), 'Optical lesson 42', font=font, fill='black')
        draw.text((100, 310), 'Source content stays editable.', font=font, fill='black')
        return image

    def extract(self, source, folder):
        from apps.lessons.importing.parser import Extractor
        return Extractor(folder, {'max_pages': 100, 'languages': 'rus+eng+kaz'}).extract(source)

    def test_digital_and_scanned_pdf_use_real_docling_and_tesseract(self):
        for scanned in (False, True):
            with self.subTest(scanned=scanned), TemporaryDirectory() as folder:
                source = Path(folder) / 'lecture.pdf'
                make_pdf(source, self.image() if scanned else None)
                result = self.extract(source, folder)
                text = ' '.join(element['text'] for element in result['elements'])
                self.assertIn('Optical lesson 42' if scanned else 'Digital lecture 42', text)
                self.assertTrue(any(asset['is_page'] for asset in result['assets']))
                self.assertTrue(any(element.get('page') == 1 for element in result['elements']))
                self.assertEqual('ocr_review' in result['warnings'], scanned)

    def test_digital_pdf_never_requires_tesseract(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'digital.pdf'
            make_pdf(source)
            with patch('apps.lessons.importing.parser.Extractor.require_ocr', side_effect=AssertionError('Digital PDFs must not start OCR')):
                result = self.extract(source, folder)
            self.assertIn('Digital lecture 42', ' '.join(item['text'] for item in result['elements']))

    def test_word_embedded_screenshot_uses_real_tesseract(self):
        from docx import Document
        with TemporaryDirectory() as folder:
            data = io.BytesIO(); self.image().save(data, 'PNG'); data.seek(0)
            document = Document(); document.add_picture(data)
            source = Path(folder) / 'lecture.docx'; document.save(source)
            result = self.extract(source, folder)
            self.assertIn('Optical lesson 42', ' '.join(item['text'] for item in result['elements']))
            self.assertTrue(any(item.get('ocr') for item in result['elements']))

from __future__ import annotations

import importlib.util
from io import BytesIO
import unittest

from alkalmazas.adatmodellek.dokumentumok import OfferRequestDocumentWrite
from alkalmazas.szolgaltatasok.dokumentumok import (
    DOCUMENT_FONT_BOLD,
    DOCUMENT_FONT_REGULAR,
    DOCUMENT_HEADER_IMAGE,
    build_offer_request_pdf,
    build_offer_request_word,
)


class WorkflowDocumentTests(unittest.TestCase):
    def test_offer_request_payload_accepts_manual_and_date_values(self):
        payload = OfferRequestDocumentWrite.model_validate({
            "title": "Árajánlatkérő - talajvédelem",
            "data": {
                "work_number": "43643_13",
                "request_text": "Kérjük az ajánlatot.",
                "response_deadline": "2026-08-01",
                "document_date": "2026-07-22",
            },
        })
        self.assertEqual(payload.data.work_number, "43643_13")
        self.assertEqual(payload.data.response_deadline.isoformat(), "2026-08-01")

    def test_offer_request_payload_normalizes_empty_text_from_older_clients(self):
        payload = OfferRequestDocumentWrite.model_validate({
            "title": None,
            "data": {
                "work_number": None,
                "history": None,
                "task_description": None,
                "response_deadline": None,
                "document_date": None,
            },
        })
        self.assertEqual(payload.title, "Árajánlatkérő")
        self.assertEqual(payload.data.work_number, "")
        self.assertEqual(payload.data.history, "")
        self.assertEqual(payload.data.task_description, "")
        self.assertIsNone(payload.data.response_deadline)

    def test_offer_request_pdf_is_a_real_pdf(self):
        if importlib.util.find_spec("reportlab") is None:
            self.skipTest("A reportlab nincs telepitve ebben a tesztkornyezetben.")
        content = build_offer_request_pdf({
            "title": "Árajánlatkérő",
            "project_name": "Minta projekt",
            "company_name": "Minta Kft.",
            "discipline": "Környezetvédelem",
            "request_text": "Kérjük az ajánlatot a feladat elvégzésére.",
        })
        self.assertTrue(content.startswith(b"%PDF"))
        self.assertGreater(len(content), 1000)
        self.assertTrue(DOCUMENT_HEADER_IMAGE.exists())
        self.assertTrue(DOCUMENT_FONT_REGULAR.exists())
        self.assertTrue(DOCUMENT_FONT_BOLD.exists())
        if importlib.util.find_spec("pypdf") is not None:
            from pypdf import PdfReader
            text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
            self.assertIn("AJÁNLATKÉRŐ", text)
            self.assertIn("Környezetvédelem", text)

    def test_offer_request_word_is_an_editable_docx(self):
        if importlib.util.find_spec("docx") is None:
            self.skipTest("A python-docx nincs telepítve ebben a tesztkörnyezetben.")
        content = build_offer_request_word({
            "title": "Árajánlatkérő",
            "project_name": "Minta projekt",
            "company_name": "Minta Kft.",
            "discipline": "Talajvédelem",
            "request_text": "Kérjük az ajánlatot a feladat elvégzésére.",
        })
        self.assertTrue(content.startswith(b"PK"))
        self.assertGreater(len(content), 1000)
        from docx import Document
        document = Document(BytesIO(content))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertIn("AJÁNLATKÉRŐ", text)
        self.assertIn("Minta projekt", text)
        self.assertGreaterEqual(len(document.inline_shapes), 1)


if __name__ == "__main__":
    unittest.main()

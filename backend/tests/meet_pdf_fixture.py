"""Tiny DiveRecorder-shaped PDFs for tests (made-up names, no real results)."""

HEADER = "N° HauteurCoef J1 J2 J3 J4 J5 J6 J7 Cumul Points Points Pen"
FOOTER = "Codes des pénalités :     1 = Plongeon manqué     2 = Faux départ, -2 points"

SAMPLE_LINES = [
    "Piscine Test", "dimanche 22 novembre 2026", "Meeting de test", "Résultats détaillés", "Montreuil", "7.0.7.6",
    HEADER,
    "Elite - Dames - 3m",
    "Anna TESTA (2001) -- Club Alpha 1",
    "201B 3 1,8 6,0 6,5 6,0 7,0 6,5   19,0 34,20 34,20  plongeon ordinaire arrière",
    "301B 3 1,9 6,0 6,0 6,5 7,5 6,5   19,0 36,10 70,30  plongeon renversé",
    "Berta EXEMPLE (2003) -- Club Beta 2",
    "103B 3 1,6 5,0 5,5 4,5 5,5 4,5   15,0 24,00 24,00  saut périlleux et demi avant",
    "304C 3 2,1 4,0 3,5 2,5 3,5 3,0   10,0 21,00 45,00 4double saut périlleux renversé",
    FOOTER,
    HEADER,
    "Elite - Messieurs - HV",
    "Carl MODELE (1990) -- Club Alpha 1",
    "612B 7,5 1,8 0,0 0,0 0,0 0,0 0,0   0,0 0,00 0,00 1équilibre et saut périlleux avant",
    "105B 10 2,4 7,5 7,5 5,5 5,5 7,0   20,0 48,00 48,00  double saut périlleux et demi avant",
]


def _escape(text: str) -> bytes:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("cp1252")


def make_pdf(lines=SAMPLE_LINES) -> bytes:
    """A one-page PDF whose text layer is `lines`, one per row (Helvetica, WinAnsi)."""
    ops = [b"BT /F1 8 Tf 20 820 Td 10 TL"]
    ops += [b"(" + _escape(line) + b") Tj T*" for line in lines]
    ops.append(b"ET")
    stream = b"\n".join(ops)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)

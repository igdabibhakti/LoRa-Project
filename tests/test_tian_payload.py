import tempfile
import unittest
from pathlib import Path
from PIL import Image
from tian_payload import prepare_text, prepare_image, decode_received

class TianPayloadTests(unittest.TestCase):
    def test_text_roundtrip(self):
        payload = prepare_text("hello Tian")
        decoded = decode_received(payload.encrypted, payload.content_type)
        self.assertEqual(decoded["text"], "hello Tian")

    def test_image_roundtrip(self):
        with tempfile.TemporaryDirectory() as tempdir:
            source = Path(tempdir) / "x.png"
            Image.new("RGB", (64, 32), (10, 20, 30)).save(source)
            payload = prepare_image(source)
            decoded = decode_received(
                payload.encrypted,
                payload.content_type,
                output_dir=Path(tempdir) / "out",
                output_stem="rx",
            )
            self.assertEqual(decoded["type"], "image")
            self.assertTrue(Path(decoded["path"]).is_file())
            self.assertEqual((decoded["width"], decoded["height"]), (64, 32))

if __name__ == "__main__":
    unittest.main()

"""Small photo previews, bounded in memory. Original uploads are never modified."""
from collections import OrderedDict
from contextlib import closing
import io
import threading
import warnings
from PIL import Image, ImageOps

class PreviewCache:
    def __init__(self, max_bytes=32 * 1024 * 1024, max_items=128):
        self.max_bytes, self.max_items = max_bytes, max_items
        self.items = OrderedDict()
        self.size = 0
        self.lock = threading.Lock()

    def get(self, path):
        stat = path.stat()
        key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
        with self.lock:
            if key in self.items:
                result = self.items.pop(key)
                self.items[key] = result
                return result
            try:
                result = self.render(path)
            except (OSError, ValueError, SyntaxError, Image.DecompressionBombError,
                    Image.DecompressionBombWarning):
                result = None  # Keep older/unsupported uploads available as originals.
            size = len(result[0]) if result else 0
            if size <= self.max_bytes:
                while self.items and (self.size + size > self.max_bytes or len(self.items) >= self.max_items):
                    _, old = self.items.popitem(last=False)
                    self.size -= len(old[0]) if old else 0
                self.items[key] = result
                self.size += size
            return result

    @staticmethod
    def render(path):
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as source:
                if source.width * source.height > 80_000_000:
                    raise ValueError('Image exceeds the preview processing limit')
                # Decode camera JPEGs at reduced resolution before resizing.
                source.draft(None, (512, 512))
                source.thumbnail((512, 512), Image.Resampling.LANCZOS)
                with closing(ImageOps.exif_transpose(source)) as upright:
                    transparent = upright.mode in ('RGBA', 'LA') or 'transparency' in upright.info
                    with closing(upright.convert('RGBA' if transparent else 'RGB')) as image:
                        output = io.BytesIO()
                        if transparent:
                            image.save(output, format='PNG')
                            return output.getvalue(), 'image/png'
                        image.save(output, format='JPEG', quality=82)
                        return output.getvalue(), 'image/jpeg'

PHOTO_PREVIEWS = PreviewCache()

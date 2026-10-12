"""Version the learning extension independently of the standalone campus map."""
import hashlib
from pathlib import Path
from django.templatetags.static import static


def map_asset_urls():
    folder = Path(__file__).resolve().parent / 'static' / 'learning'
    files = {'styles': 'learning.css', 'panel': 'learning.js', 'assets': 'classroom-assets.js',
             'map': 'classroom-map.js', 'controller': 'classroom.js'}
    return {key: f'{static("learning/" + name)}?v={hashlib.sha256((folder / name).read_bytes()).hexdigest()[:12]}'
            for key, name in files.items()}

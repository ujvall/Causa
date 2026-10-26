"""Create the cropped detail views used on the Studio slide from the captured screenshots.

    python3 presentation/make_crops.py      (needs Pillow)
"""
from pathlib import Path
from PIL import Image

A = Path(__file__).resolve().parent / "assets"
Image.open(A / "studio_whatif.png").crop((1035, 85, 2064, 500)).save(A / "crop_whatif.png")
g = Image.open(A / "studio_graph.png")
g.crop((0, 640, 745, 1110)).save(A / "crop_console.png")
g.crop((745, 85, 2064, 460)).save(A / "crop_graph.png")
print("crops written")

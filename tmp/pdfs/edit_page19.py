import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas


SOURCE = Path("/Users/ke/Library/Mobile Documents/com~apple~CloudDocs/Downloads/MOMO_省赛整合重排版_统一页面尺寸.pdf")
OUTPUT = Path("output/pdf/MOMO_省赛整合重排版_第19页已修改.pdf")
WORK = Path("tmp/pdfs")
FONT = "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/53fe5be564086fefc7523ccd0a31200acf92e0e5.asset/AssetData/STHEITI.ttf"

PAGE_W, PAGE_H = 1920, 1080
SCALE = 4000 / PAGE_W
BG = (51, 50, 64)
CARD = (66, 64, 84)
TRACK = (48, 46, 61)
PURPLE = (127, 123, 246)
WHITE = (245, 244, 247)


def box(x, y, w, h):
    return tuple(round(v * SCALE) for v in (x, y, x + w, y + h))


def font(size):
    return ImageFont.truetype(FONT, round(size * SCALE))


WORK.mkdir(parents=True, exist_ok=True)
render_prefix = WORK / "source19"
subprocess.run(
    ["pdftoppm", "-f", "19", "-l", "19", "-png", "-r", "150", str(SOURCE), str(render_prefix)],
    check=True,
    stdout=subprocess.DEVNULL,
)

image_path = WORK / "source19-19.png"
im = Image.open(image_path).convert("RGB")
d = ImageDraw.Draw(im)

# Page-level description.
d.rectangle(box(80, 215, 760, 55), fill=BG)
d.text((round(81 * SCALE), round(218 * SCALE)), "关键性能指标实测结果", font=font(33), fill=WHITE)

# Visual-processing panel description.
d.rectangle(box(120, 390, 760, 75), fill=CARD)
d.text((round(126 * SCALE), round(397 * SCALE)), "视觉处理性能实测结果", font=font(28), fill=WHITE)

# Replace the comparison with one centered measured-result row.
d.rectangle(box(120, 465, 780, 235), fill=CARD)
d.text((round(126 * SCALE), round(524 * SCALE)), "实测", font=font(34), fill=WHITE)
d.rounded_rectangle(box(266, 526, 598, 41), radius=round(6 * SCALE), fill=TRACK)
d.rounded_rectangle(box(266, 526, 598, 41), radius=round(6 * SCALE), fill=PURPLE)
label = "30 FPS"
label_font = font(34)
label_box = d.textbbox((0, 0), label, font=label_font)
d.text(
    (round(862 * SCALE) - (label_box[2] - label_box[0]), round(523 * SCALE)),
    label,
    font=label_font,
    fill=WHITE,
)

edited_png = WORK / "page19-edited.png"
im.save(edited_png, quality=95)

# Convert the edited page image back to a PDF page at the source dimensions.
single_page = WORK / "page19-edited.pdf"
c = canvas.Canvas(str(single_page), pagesize=(PAGE_W, PAGE_H))
c.drawImage(str(edited_png), 0, 0, width=PAGE_W, height=PAGE_H)
c.save()

reader = PdfReader(str(SOURCE))
replacement = PdfReader(str(single_page)).pages[0]
writer = PdfWriter()
for index, page in enumerate(reader.pages):
    writer.add_page(replacement if index == 18 else page)
if reader.metadata:
    writer.add_metadata(reader.metadata)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
with OUTPUT.open("wb") as stream:
    writer.write(stream)

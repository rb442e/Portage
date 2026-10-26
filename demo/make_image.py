import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 760, 190
img = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(img)
bold = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24, index=1)
reg = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
rows = [("user", "email"), ("Aisha Khan", "aisha.khan@example.com"), ("Tom Brennan", "tom.brennan@example.com")]
col_x = [0, 250, W]
for r in range(4):
    d.line((0, r * 46 + 2, W, r * 46 + 2), fill="#c8c8c8", width=2)
for x in col_x:
    d.line((x + 1, 0, x + 1, 140), fill="#c8c8c8", width=2)
d.rectangle([0, 2, W, 48], fill="#f1f3f4")
for i, (a, b) in enumerate(rows):
    f = bold if i == 0 else reg
    d.text((14, i * 46 + 12), a, font=f, fill="#202124")
    d.text((264, i * 46 + 12), b, font=f, fill="#202124")
img.save(sys.argv[1] if len(sys.argv) > 1 else "new_users.png")
print("ok")

"""Generate a 7x9-inner-corner 20mm checkerboard SVG for printing at actual size."""
from pathlib import Path
import sys
cols,rows,square=8,10,20
out=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).with_name("checkerboard_20mm.svg")
lines=['<svg xmlns="http://www.w3.org/2000/svg" width="186mm" height="240mm" viewBox="0 0 186 240">',
'<rect width="186" height="240" fill="white"/>']
for r in range(rows):
 for c in range(cols):
  if (r+c)%2==0:
   lines.append(f'<rect x="{13+20*c}" y="{14+20*r}" width="20" height="20" fill="black"/>')
lines += ['<text x="93" y="229" font-size="4" text-anchor="middle">PRINT AT 100%; MEASURE SQUARES: 20 mm</text>','</svg>']
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text("\n".join(lines),encoding="utf-8")
print(f"CREATED {out}")

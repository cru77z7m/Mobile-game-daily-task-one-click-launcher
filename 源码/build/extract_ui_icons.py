"""Extract the GPT Image 3x3 atlas; Pillow is a build-time dependency only."""
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[2]
atlas = Image.open(root / 'design' / 'fluent-icon-atlas.png').convert('RGBA')
names = ['dashboard', 'moon', 'tasks', 'update', 'info', 'sliders', 'play', 'apps', 'sparkle']
w, h = atlas.size
for i, name in enumerate(names):
    x, y = i % 3, i // 3
    tile = atlas.crop((round(x*w/3), round(y*h/3), round((x+1)*w/3), round((y+1)*h/3)))
    box = tile.getbbox()
    if box:
        tile = tile.crop(box)
    tile.thumbnail((112, 112), Image.Resampling.LANCZOS)
    icon = Image.new('RGBA', (128, 128))
    icon.alpha_composite(tile, ((128-tile.width)//2, (128-tile.height)//2))
    icon.save(root / '源码' / 'assets' / 'icons' / ('ui_'+name+'.ico'),
              sizes=[(16,16), (24,24), (32,32), (48,48), (64,64), (96,96), (128,128)])
print('Extracted 9 icons; generated alpha preserved.')

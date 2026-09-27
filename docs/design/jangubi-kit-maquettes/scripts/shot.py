import sys, re, asyncio, os
from playwright.async_api import async_playwright
async def main(files, out):
    os.makedirs(out, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for f in files:
            h = open(f).read()
            m = re.search(r'"\$preview":\{"width":(\d+),"height":(\d+)\}', h)
            w, ht = (int(m.group(1)), int(m.group(2))) if m else (390, 844)
            pg = await b.new_page(viewport={'width': w, 'height': ht})
            await pg.route('**/fonts.googleapis.com/**', lambda r: r.abort())
            await pg.goto('file://' + os.path.abspath(f))
            await pg.add_style_tag(content=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'fonts.css')).read())
            await pg.evaluate('document.fonts.ready')
            await pg.wait_for_timeout(300)
            await pg.screenshot(path=os.path.join(out, os.path.basename(f).replace('.dc.html', '.png')))
            await pg.close()
        await b.close()
asyncio.run(main(sys.argv[2:], sys.argv[1]))

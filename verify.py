import zipfile
from pathlib import Path
output = Path('data_pack_split')
zips = sorted(output.glob('*.zip'))
total=0
for p in zips:
    with zipfile.ZipFile(p) as zf:
        n=len(zf.namelist())
    sz=p.stat().st_size
    total+=sz
    status = 'PASS <=5GB' if sz<=5*1024**3 else 'FAIL'
    print(f'{p.name:45} | {n:5} files | {sz/1024**3:.3f} GiB | {sz/1e9:.3f} GB dec | {status}')
print('---')
total_files = sum(len(zipfile.ZipFile(p).namelist()) for p in zips)
print(f'TOTAL 5 zips | {total_files} files | {total/1024**3:.3f} GiB | {total/1e9:.3f} GB dec')
for p in zips:
    with zipfile.ZipFile(p) as zf:
        bad=[q for q in zf.namelist() if '.env' in q]
        res = 'PASS' if not bad else 'FAIL'
        print(f'{p.name} .env check: {res}')
    # sample
    with zipfile.ZipFile(p) as zf:
        print(f'  sample {p.name}: {zf.namelist()[:1]}')
# also check raw sources
print("\nSource vs zipped counts:")
import pathlib
sources = {
 "bhavcopy": len(list((Path('reality_engine/data/bhavcopy')).rglob('*'))),
}
print(sources)
# detailed
root=Path('reality_engine/data/pdfs')
concall=len([x for x in root.rglob('*') if x.is_file() and x.parent.name=='CONCALL_TRANSCRIPT'])
ppt=len([x for x in root.rglob('*') if x.is_file() and x.parent.name=='INVESTOR_PRESENTATION'])
print(f"concall src {concall} ppt src {ppt}")
print(f"concall zipped {4816+3157} match {4816+3157==concall}")
print(f"ppt zipped 1856 match {1856==ppt}")

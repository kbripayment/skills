#!/usr/bin/env python3
import os, shutil
from pathlib import Path

home = r'C:\Users\user'
target = r'C:\Users\user\AppData\Local\hermes\skills\research\paper-summary\scripts'

print('home dir contents:')
for f in sorted(os.listdir(home)):
    fp = os.path.join(home, f)
    sz = os.path.getsize(fp) if os.path.isfile(fp) else 0
    tag = '[DIR]' if os.path.isdir(fp) else ''
    print(f'  {f} ({sz} bytes) {tag}')

print('\nfiles to copy (py/bat/txt):')
for f in sorted(os.listdir(home)):
    fp = os.path.join(home, f)
    if not os.path.isfile(fp):
        continue
    ext = os.path.splitext(f)[1].lower()
    if ext in ('.py','.bat','.txt'):
        print(f'  {f} ({os.path.getsize(fp)} bytes)')

print(f'\ntarget dir: {target}')
Path(target).mkdir(parents=True, exist_ok=True)

copied = []
for f in sorted(os.listdir(home)):
    fp = os.path.join(home, f)
    if not os.path.isfile(fp):
        continue
    ext = os.path.splitext(f)[1].lower()
    if ext not in ('.py','.bat','.txt'):
        continue
    dst = os.path.join(target, f)
    if os.path.exists(dst):
        base, suf = os.path.splitext(f)
        c = 1
        while os.path.exists(os.path.join(target, f'{base}_{c}{suf}')):
            c += 1
        dst = os.path.join(target, f'{base}_{c}{suf}')
    shutil.copy2(fp, dst)
    copied.append((f, os.path.basename(dst)))
    print(f'copied: {f} -> {os.path.basename(dst)}')

print(f'\ndone: {len(copied)} files copied')
print('target contents:')
for f in sorted(os.listdir(target)):
    fp = os.path.join(target, f)
    if os.path.isfile(fp):
        print(f'  {f} ({os.path.getsize(fp)} bytes)')

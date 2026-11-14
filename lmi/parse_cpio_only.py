#!/usr/bin/env python3
# Robust newc cpio parser for already-decompressed ramdisks.
import os, sys

OUT = r"H:/workbuddy/2026-11-13-18-00-49/skyward-lmi-port/ramdisk_out"

def parse_cpio(data, tag):
    entries=[]; pos=0; n=len(data)
    guard=0; max_iter=n//110+16
    while pos+110<=n and guard<max_iter:
        guard+=1
        magic=data[pos:pos+6]
        if magic not in (b'070701', b'070702'):
            chunk=data[pos:pos+512]
            if chunk.count(0)==len(chunk):
                pos+=512; continue
            print(f"  [{tag}] stop at pos={pos}: non-cpio magic {magic!r}", flush=True); break
        def hx(o,l): return int(data[pos+o:pos+o+l],16)
        namesize=hx(94,8); filesize=hx(54,8)
        name=data[pos+110:pos+110+max(namesize-1,0)].decode('utf-8','replace')
        header=((110+namesize+3)//4)*4
        fdata_end=((header+filesize+3)//4)*4
        if name=='TRAILER!!!':
            print(f"  [{tag}] TRAILER at pos={pos} after {len(entries)} entries", flush=True)
            break
        entries.append((pos, name, filesize, header))
        newpos=pos+fdata_end
        if newpos<=pos:
            print(f"  [{tag}] WARN pos stuck at {pos}, forcing +4", flush=True); newpos=pos+4
        pos=newpos
        if len(entries)%20000==0:
            print(f"  [{tag}] ...{len(entries)} entries, pos={pos}", flush=True)
    return entries

def main():
    for tag in ['MINE','OTHER']:
        p=os.path.join(OUT,f"{tag}.cpio")
        with open(p,'rb') as f: data=f.read()
        print(f"[{tag}] file={len(data)} bytes", flush=True)
        entries=parse_cpio(data, tag)
        print(f"[{tag}] entries={len(entries)} total_data={sum(e[2] for e in entries)}", flush=True)
        with open(os.path.join(OUT,f"{tag}.list.txt"),'w') as f:
            for _,nm,sz,_ in entries:
                f.write(f"{sz:>10}  {nm}\n")
        d=os.path.join(OUT,tag); os.makedirs(d,exist_ok=True)
        for pos,nm,sz,header in entries:
            base=os.path.basename(nm)
            if base in ('skyward','skyward-system-init','recovery','init','adbd') or 'skyward' in nm or nm.endswith('device.toml'):
                with open(os.path.join(d,base),'wb') as f: f.write(data[pos+header:pos+header+sz])
                print(f"  extracted {nm} ({sz}B)", flush=True)
        tops=sorted({e[1].split('/')[1] for e in entries if e[1].startswith('/') and len(e[1].split('/'))>1})
        print(f"[{tag}] top dirs: {tops}", flush=True)

if __name__=='__main__':
    main()

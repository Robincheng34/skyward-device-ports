#!/usr/bin/env python3
# Extract and compare the recovery ramdisks of two Android boot images.
# MINE  : stock-LineageOS based Skyward image (LZ4-legacy ramdisk)
# OTHER : third-party skyward-lmi-0.1.2 image (gzip ramdisk, TWRP-flavored)
import os, gzip, struct, sys

OUT = r"H:/workbuddy/2026-11-13-18-00-49/skyward-lmi-port/ramdisk_out"
MINE  = r"H:/idmDownload/skyward-lmi.img"
OTHER = r"C:/Users/Robin/Desktop/skyward-lmi-0.1.2.img"

def parse_header(p):
    with open(p,'rb') as f: h=f.read(4096)
    u=lambda o,n: int.from_bytes(h[o:o+n],'little')
    kernel_size=u(8,4); ramdisk_size=u(16,4); page_size=u(36,4) or 2048
    return dict(kernel_size=kernel_size, ramdisk_size=ramdisk_size, page_size=page_size,
                ramdisk_off=page_size + ((kernel_size+page_size-1)//page_size)*page_size)

def copy_match(out, offset, mlen):
    # overlapping copy: always re-read from the growing tail
    while mlen>0:
        chunk=min(offset, mlen)
        tail=len(out)
        out += out[tail-offset:tail-offset+chunk]
        mlen-=chunk

def lz4_block_decompress(block):
    out=bytearray(); pos=0; n=len(block)
    while pos < n:
        token=block[pos]; pos+=1
        lit_len=token>>4
        if lit_len==15:
            while True:
                b=block[pos]; pos+=1; lit_len+=b
                if b!=0xFF: break
        out.extend(block[pos:pos+lit_len]); pos+=lit_len
        if pos>=n: break
        offset=block[pos]|(block[pos+1]<<8); pos+=2
        mlen=token&0x0F
        if mlen==15:
            while True:
                b=block[pos]; pos+=1; mlen+=b
                if b!=0xFF: break
        mlen+=4
        copy_match(out, offset, mlen)
    return bytes(out)

def lz4_legacy_decompress(data):
    assert data[:4]==b'\x02\x21\x4c\x18', "not lz4 legacy"
    out=bytearray(); pos=4
    while pos+4<=len(data):
        size=int.from_bytes(data[pos:pos+4],'little'); pos+=4
        if size==0: break
        out+=lz4_block_decompress(data[pos:pos+size]); pos+=size
    return bytes(out)

def decompress_ramdisk(p):
    hdr=parse_header(p)
    with open(p,'rb') as f:
        f.seek(hdr['ramdisk_off']); raw=f.read(hdr['ramdisk_size'])
    magic=raw[:4]
    if magic[:2]==b'\x1f\x8b':
        return gzip.decompress(raw), 'gzip'
    if magic==b'\x02\x21\x4c\x18':
        return lz4_legacy_decompress(raw), 'lz4-legacy'
    if magic[:4]==b'\x28\xb5\x2f\xfd' or magic[:4]==b'\x04\x22\x4d\x18':
        return None,'lz4-modern/zstd-unhandled'
    return None, 'unknown:'+magic.hex()

def parse_cpio(data):
    # newc 070701
    entries=[]; pos=0; n=len(data)
    while pos+110<=n:
        if data[pos:pos+6]!=b'070701' and data[pos:pos+6]!=b'070702':
            # skip a 512-byte pad if we hit zeros
            if data[pos:pos+6]==b'\x00\x00\x00\x00\x00\x00':
                pos+=512; continue
            break
        def hx(o,l): return int(data[pos+o:pos+o+l],16)
        namesize=hx(94,8); filesize=hx(102,8)
        name=data[pos+110:pos+110+namesize-1].decode('utf-8','replace')
        header=110+namesize
        header=((header+3)//4)*4  # 4-byte align
        fdata=data[header:header+filesize]
        fdata_end=header+filesize
        fdata_end=((fdata_end+3)//4)*4  # 4-byte align
        if name=='TRAILER!!!':
            break
        entries.append((name,filesize,fdata))
        pos=fdata_end
    return entries

def main():
    os.makedirs(OUT,exist_ok=True)
    for tag,p in [('MINE',MINE),('OTHER',OTHER)]:
        data,kind=decompress_ramdisk(p)
        print(f"[{tag}] decompress kind={kind} size={len(data) if data else 0}")
        if data is None:
            print(f"  !! cannot decompress {tag}"); continue
        cpio_path=os.path.join(OUT,f"{tag}.cpio")
        with open(cpio_path,'wb') as f: f.write(data)
        entries=parse_cpio(data)
        names=[e[0] for e in entries]
        print(f"[{tag}] cpio entries={len(names)}")
        # save listing + extract skyward binaries
        with open(os.path.join(OUT,f"{tag}.list.txt"),'w') as f:
            for nm,sz,_ in entries:
                f.write(f"{sz:>10}  {nm}\n")
        # extract interesting binaries
        for nm,sz,b in entries:
            base=os.path.basename(nm)
            if base in ('skyward','skyward-system-init','recovery','init','adbd','twrp') or 'skyward' in nm or 'device.toml' in nm:
                d=os.path.join(OUT,tag); os.makedirs(d,exist_ok=True)
                with open(os.path.join(d,base),'wb') as f: f.write(b)
                print(f"  extracted {nm} ({sz} bytes) -> {tag}/{base}")
        # print top-level dirs
        tops=sorted({e[0].split('/')[1] for e in entries if e[0].startswith('/') and '/' in e[0][1:]})
        print(f"[{tag}] top dirs: {tops}")

if __name__=='__main__':
    main()

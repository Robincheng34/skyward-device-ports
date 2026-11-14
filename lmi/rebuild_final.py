#!/usr/bin/env python3
# FINAL build: OTHER base -> my 0.2.0.
#  - trim customzip/Magisk (TWRP-only, useless to skyward) to free space
#  - swap /system/bin/recovery -> 0.2.0, add /skyward/system-init
#  - reassemble within AVB original_image_size, recompute hash-footer digest (algo NONE)
import gzip, hashlib, sys

PROJ=r"H:/workbuddy/2026-11-13-18-00-49/skyward-lmi-port"
OTH=r"C:/Users/Robin/Desktop/skyward-lmi-0.1.2.img"
OUT=PROJ+r"/skyward-lmi-0.2.0-fixed.img"
MY_REC=PROJ+r"/ramdisk_out/MINE/recovery_patched"
MY_SI =PROJ+r"/ramdisk_out/MINE/system-init"
PS=4096
def al(x): return ((x+PS-1)//PS)*PS
def hexf(v): return format(v,'08x')

def parse(data):
    ents=[]; pos=0; n=len(data)
    while pos+110<=n:
        if data[pos:pos+6] not in (b'070701',b'070702'): break
        f=[data[pos+6+8*i:pos+6+8*(i+1)].decode('ascii') for i in range(13)]
        ns=int(f[11],16); fs=int(f[6],16)
        name=data[pos+110:pos+110+ns-1]
        hdr=((110+ns+3)//4)*4
        body=data[pos+hdr:pos+hdr+fs]
        ents.append({'f':f,'name':name,'data':body,'trailer':name==b'TRAILER!!!'})
        if name==b'TRAILER!!!': break
        pos+=((hdr+fs+3)//4)*4
    return ents

def build(ents):
    out=bytearray()
    for e in ents:
        f=list(e['f']); name=e['name']; data=e['data']
        if e['trailer']:
            f[11]=hexf(len(b'TRAILER!!!')+1); f[6]='00000000'
            out+=b'070701'+b''.join(x.encode() for x in f)+b'TRAILER!!!\x00'
            out+=b'\x00'*((-len(out))%4); continue
        f[6]=hexf(len(data)); f[11]=hexf(len(name)+1)
        hdr=b'070701'+b''.join(x.encode() for x in f)+name+b'\x00'
        out+=hdr; out+=b'\x00'*((-len(hdr))%4)
        out+=data; out+=b'\x00'*((-len(data))%4)
    return bytes(out)

my_rec=open(MY_REC,'rb').read(); my_si=open(MY_SI,'rb').read()
orig=open(OTH,'rb').read(); IMG=len(orig)
hdr=bytearray(orig[:4096])
hu=lambda o,n:int.from_bytes(hdr[o:o+n],'little')
ks=hu(8,4); ors=hu(16,4); rdtbo_size=hu(1632,4); old_off=hu(1636,4); dtb_size=hu(1648,4)
kernel=orig[4096:4096+ks]
cpio=gzip.decompress(orig[46665728:46665728+ors])
ents=parse(cpio)
print(f"orig entries={len(ents)}")

# 1) drop customzip/Magisk* to free space
before=len(ents)
ents=[e for e in ents if not (e['name']==b'customzip/Magisk' or e['name'].startswith(b'customzip/Magisk/'))]
print(f"dropped {before-len(ents)} Magisk entries")

# 2) swap recovery
names=[e['name'] for e in ents]
ri=names.index(b'system/bin/recovery'); ents[ri]['data']=my_rec
# 2b) override device.toml with 0.2.0-schema lmi config (OTHER's minus [haptics])
TOML_OVR=PROJ+r"/ramdisk_out/device_lmi_020.toml"
di=names.index(b'skyward/device.toml')
ents[di]['data']=open(TOML_OVR,'rb').read()
print(f"device.toml -> {len(ents[di]['data'])}B (0.2.0 schema)")
# 3) add system-init after device.toml
di=names.index(b'skyward/device.toml')
tmpl=ents[di]; f=list(tmpl['f'])
maxino=max(int(e['f'][0],16) for e in ents if not e['trailer'])
f[0]=hexf(maxino+1); f[1]='000081ed'; f[2]='00000000'; f[3]='00000000'; f[4]='00000001'
f[6]=hexf(len(my_si)); f[11]=hexf(len(b'skyward/system-init')+1)
ents.insert(di+1,{'f':f,'name':b'skyward/system-init','data':my_si,'trailer':False})
print(f"new entries={len(ents)}  recovery={len(my_rec)} sysinit={len(my_si)}")

newcpio=build(ents)
gz=gzip.compress(newcpio,compresslevel=9,mtime=0)
print(f"new cpio={len(newcpio)} gz9={len(gz)} (orig gz {ors})")

# 4) layout within AVB original_image_size
ft=orig[IMG-64:]
orig_sz=int.from_bytes(ft[12:20],'big'); vb_off=int.from_bytes(ft[20:28],'big'); vb_sz=int.from_bytes(ft[28:36],'big')
assert vb_off==orig_sz
old_rdtbo=orig[old_off:old_off+rdtbo_size]
old_dtb_off=al(old_off+rdtbo_size); dtb=orig[old_dtb_off:old_dtb_off+dtb_size]
ram_off=al(4096+ks); ram_pad=al(len(gz)); nrd=ram_off+ram_pad; ndtb=al(nrd+rdtbo_size)
end=ndtb+dtb_size
print(f"ram_off={ram_off} nrd={nrd} ndtb={ndtb} content_end={end} limit={orig_sz} (slack {orig_sz-end})")
if end>orig_sz:
    print("DOES NOT FIT"); sys.exit(1)

# 5) assemble
hdr[16:20]=len(gz).to_bytes(4,'little'); hdr[1636:1640]=nrd.to_bytes(4,'little')
img=bytearray(IMG)
img[0:4096]=hdr; img[4096:4096+ks]=kernel
img[ram_off:ram_off+len(gz)]=gz
img[nrd:nrd+rdtbo_size]=old_rdtbo
img[ndtb:ndtb+dtb_size]=dtb
# 6) recompute AVB hash digest over [0:orig_sz] and patch vbmeta
newdig=hashlib.sha256(bytes(img[:orig_sz])).digest()
vb=bytearray(orig[vb_off:vb_off+vb_sz])
# find old digest location (sha256 of original content) to patch same slot
olddig=hashlib.sha256(orig[:orig_sz]).digest()
pos=bytes(vb).find(olddig)
print(f"old digest at vbmeta offset {pos}")
assert pos>=0
vb[pos:pos+32]=newdig
img[vb_off:vb_off+vb_sz]=vb
img[IMG-64:IMG]=ft
open(OUT,'wb').write(img)
print("wrote",OUT,len(img))
# verify
chk=hashlib.sha256(bytes(img[:orig_sz])).digest()
print("verify digest matches patched:", chk==newdig, "| differs from old:", newdig!=olddig)
c2=gzip.decompress(img[ram_off:ram_off+len(gz)]); e2=parse(c2)
nm2=[x['name'] for x in e2]
print(f"verify: entries={len(e2)} has_sysinit={b'skyward/system-init' in nm2} "
      f"recovery_sz={[x for x in e2 if x['name']==b'system/bin/recovery'][0]['data'].__len__()} "
      f"magisk_left={any(n.startswith(b'customzip/Magisk') for n in nm2)}")

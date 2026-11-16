import struct, gzip, io
SRC='/Users/tangshui/test/m463/debian/boot-stock-20261116.img'
DST='/Users/tangshui/test/m463/debian/boot-root.img'
d=bytearray(open(SRC,'rb').read())
page=struct.unpack_from('<I',d,36)[0]
ks=struct.unpack_from('<I',d,page+4)[0]
roff=(page+512+ks+page-1)//page*page
magic,rsize=struct.unpack_from('<II',d,roff)
assert magic==0x58881688
raw=gzip.decompress(bytes(d[roff+512:roff+512+rsize]))
print('原 cpio',len(raw))

# 解析 newc
entries=[]; p=0
while p<len(raw):
    if raw[p:p+6] not in (b'070701',b'070702'): break
    hdr=bytes(raw[p:p+110])
    f=[int(raw[p+6+8*i:p+6+8*(i+1)],16) for i in range(13)]
    ns=f[11]; fs=f[6]
    name=bytes(raw[p+110:p+110+ns-1])
    do=(p+110+ns+3)&~3
    data=bytes(raw[do:do+fs])
    entries.append([bytearray(hdr),name,data])
    if name==b'TRAILER!!!': break
    p=(do+fs+3)&~3
print('条目',len(entries))

hit=False
for e in entries:
    if e[1]==b'default.prop':
        t=e[2].decode()
        t=t.replace('ro.secure=1','ro.secure=0').replace('ro.debuggable=0','ro.debuggable=1').replace('ro.adb.secure=1','ro.adb.secure=0')
        if 'service.adb.tcp.port' not in t:
            t=t.rstrip('\n')+'\nservice.adb.tcp.port=5555\n'
        e[2]=t.encode(); hit=True
        print('default.prop 新长度',len(e[2]))
assert hit

out=bytearray()
for hdr,name,data in entries:
    hdr[54:62]=('%08X'%len(data)).encode()
    out+=hdr+name+b'\0'
    while len(out)%4: out+=b'\0'
    out+=data
    while len(out)%4: out+=b'\0'
newraw=bytes(out)

buf=io.BytesIO()
with gzip.GzipFile(fileobj=buf,mode='wb',compresslevel=9,mtime=0) as f: f.write(newraw)
newp=buf.getvalue()
print('ramdisk',rsize,'->',len(newp))
assert len(newp) <= len(d)-(roff+512)
d[roff+512:roff+512+len(newp)]=newp
struct.pack_into('<I',d,roff+4,len(newp))
struct.pack_into('<I',d,16,len(newp)+512)
open(DST,'wb').write(d)
print('OK ->',DST,len(d))

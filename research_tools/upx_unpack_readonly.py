import sys,struct,time,pefile
src_path,out_path=sys.argv[1],sys.argv[2]
pe=pefile.PE(src_path,fast_load=True)
s=[x for x in pe.sections if x.Name.startswith(b'UPX1')][0]
src=bytes(s.get_data())
raw=open(src_path,'rb').read()
i=raw.find(b'UPX!')
ver,fmt,meth,lvl=raw[i+4:i+8]
u_adler,c_adler,u_len,c_len=struct.unpack_from('<IIII',raw,i+8)
print('method',meth,'level',lvl,'u_len',u_len,'c_len',c_len)
assert meth==8, 'only NRV2E_LE32 implemented'
dst=bytearray(u_len+4096)
bb=0;bc=0;il=0;ol=0;last=1
n=len(src)
def u32(p): return src[p]|(src[p+1]<<8)|(src[p+2]<<16)|(src[p+3]<<24)
t0=time.time()
while True:
    # literals
    while True:
        if bc>0:
            bc-=1;b=(bb>>bc)&1
        else:
            bc=31;bb=u32(il);il+=4;b=(bb>>31)&1
        if not b: break
        dst[ol]=src[il];ol+=1;il+=1
    m_off=1
    while True:
        if bc>0: bc-=1;b=(bb>>bc)&1
        else: bc=31;bb=u32(il);il+=4;b=(bb>>31)&1
        m_off=m_off*2+b
        if bc>0: bc-=1;b=(bb>>bc)&1
        else: bc=31;bb=u32(il);il+=4;b=(bb>>31)&1
        if b: break
        if bc>0: bc-=1;b=(bb>>bc)&1
        else: bc=31;bb=u32(il);il+=4;b=(bb>>31)&1
        m_off=(m_off-1)*2+b
    def gb():
        global bb,bc,il
        if bc>0:
            bc-=1;return (bb>>bc)&1
        bc=31;bb=u32(il);il+=4;return (bb>>31)&1
    if m_off==2:
        m_off=last
        m_len=gb()
    else:
        m_off=(m_off-3)*256+src[il];il+=1
        if m_off==0xffffffff or m_off<0: break
        m_len=(m_off ^ 0xffffffff)&1
        m_off>>=1
        m_off+=1; last=m_off
    if m_len:
        m_len=1+gb()
    elif gb():
        m_len=3+gb()
    else:
        m_len+=1
        while True:
            m_len=m_len*2+gb()
            if gb(): break
        m_len+=3
    m_len+=(m_off>0x500)
    # copy m_len+1 bytes
    cnt=m_len+1
    p=ol-m_off
    if m_off>=cnt:
        dst[ol:ol+cnt]=dst[p:p+cnt]
    else:
        for k in range(cnt): dst[ol+k]=dst[p+k]
    ol+=cnt
    if ol>u_len+2000: print('overrun');break
print('done',ol,u_len,il,'of',n,round(time.time()-t0,1),'s')
open(out_path,'wb').write(dst[:ol])

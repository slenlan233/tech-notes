"""Generate offline browser-based fallback for downloading Mubu image bytes.

When direct Python requests fail, the user's browser may still access images from
Mubu's CDN. This page tries the same URLs using CORS and packages the result in
an uncompressed ZIP for import on the next local build. It does NOT claim that
browser download will always work; CDN/CORS rules can still block access.
"""
from __future__ import annotations
import json
from pathlib import Path


def create_rescue_page(root: Path, missing: list[dict]) -> Path:
    target = root / '恢复幕布图片.html'
    payload = json.dumps(missing, ensure_ascii=False).replace('<', '\\u003c')
    html = r'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>恢复幕布图片｜技术知识库</title>
<style>
body{font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;max-width:900px;margin:36px auto;padding:0 20px;color:#1f2937;line-height:1.65}
h1{font-size:26px}button{padding:11px 18px;background:#2563eb;color:white;border:0;border-radius:9px;cursor:pointer;font-size:15px}
button:disabled{opacity:.45;cursor:wait}a{color:#2563eb}li{margin:7px 0;word-break:break-all}
.note{background:#f1f5f9;padding:12px 16px;border-radius:8px}
.failed{color:#b91c1c}.ok{color:#047857}small{color:#64748b}
</style></head><body>
<h1>恢复幕布 HTML 中的图片</h1>
<p>构建程序无法直接下载下方的图片。它们只以远程链接存在于原始幕布 HTML 中，并没有随 HTML 导出。</p>
<p>本页会尝试通过你当前浏览器连接幕布图片服务器，打包成一个 <code>mubu-images.zip</code>。<strong>如果服务器禁止跨域下载，本页也无法绕过该限制</strong>，仍需通过原始图片链接手动另存。</p>
<p class="note">点击下载按钮后，把下载好的 <code>mubu-images.zip</code> 放到博客项目的 <code>cached_images</code> 文件夹中；重新双击 <code>build.bat</code>，程序会自动导入图片并把它们嵌入生成的网页。</p>
<p><button id="download">尝试批量下载并打包图片</button></p>
<p id="status" role="status"></p><ol id="report"></ol>
<script>
const items = __IMAGE_LIST__;
const button=document.getElementById('download');
const status=document.getElementById('status');
const report=document.getElementById('report');
const te=new TextEncoder();
const u16=(n)=>{let a=new Uint8Array(2);new DataView(a.buffer).setUint16(0,n,true);return a};
const u32=(n)=>{let a=new Uint8Array(4);new DataView(a.buffer).setUint32(0,n>>>0,true);return a};
const concat=(parts)=>{let out=new Uint8Array(parts.reduce((s,v)=>s+v.length,0)),i=0;for(const p of parts){out.set(p,i);i+=p.length}return out};
let crcTable=Array.from({length:256},(_,i)=>{let c=i;for(let j=0;j<8;j++)c=(c&1)?(0xedb88320^(c>>>1)):(c>>>1);return c>>>0});
function crc32(bytes){let c=0xffffffff;for(let v of bytes)c=crcTable[(c^v)&255]^(c>>>8);return (c^0xffffffff)>>>0}
function makeZip(entries){
  const files=[],central=[];let offset=0;
  for(const {name,data} of entries){
    const filename=te.encode(name),crc=crc32(data);
    const local=concat([u32(0x04034b50),u16(20),u16(0),u16(0),u16(0),u16(0),u32(crc),u32(data.length),u32(data.length),u16(filename.length),u16(0),filename]);
    files.push(local,data);
    central.push(concat([u32(0x02014b50),u16(20),u16(20),u16(0),u16(0),u16(0),u16(0),u32(crc),u32(data.length),u32(data.length),u16(filename.length),u16(0),u16(0),u16(0),u16(0),u32(0),u32(offset),filename]));
    offset+=local.length+data.length;
  }
  const dir=concat(central);
  return concat([...files,dir,u32(0x06054b50),u16(0),u16(0),u16(entries.length),u16(entries.length),u32(dir.length),u32(offset),u16(0)]);
}
function isImage(bytes){const x=bytes;return (x.length>8&&x[0]===137&&x[1]===80&&x[2]===78&&x[3]===71)||(x[0]===255&&x[1]===216)||(x[0]===71&&x[1]===73&&x[2]===70)||(x[0]===82&&x[1]===73&&x[2]===70&&x[8]===87&&x[9]===69&&x[10]===66&&x[11]===80)||new TextDecoder().decode(x.subarray(0,80)).includes('<svg')}
async function downloadOne(item){
  const urls=[item.url];
  try{const u=new URL(item.url);if(u.hostname==='api2.mubu.com'&&u.pathname.startsWith('/v3/'))urls.push('https://document-image.mubu.com/'+u.pathname.substring(4));}catch(e){}
  let reason='';
  for(const url of urls){
    try{
      const r=await fetch(url,{mode:'cors',credentials:'omit'});
      if(!r.ok)throw new Error('HTTP '+r.status);
      const bytes=new Uint8Array(await r.arrayBuffer());
      if(!isImage(bytes))throw new Error('服务器返回的不是图片');
      return bytes;
    }catch(e){reason=String(e.message||e)}
  }
  throw new Error(reason || '下载失败');
}
button.addEventListener('click',async()=>{
  button.disabled=true;report.replaceChildren();const files=[];
  for(let i=0;i<items.length;i++){
    const item=items[i];status.textContent=`正在下载 ${i+1}/${items.length}：${item.name}`;
    const li=document.createElement('li');report.appendChild(li);
    try{const data=await downloadOne(item);files.push({name:item.name,data});li.className='ok';li.textContent=`成功：${item.name}（${Math.round(data.length/1024)} KB）`}
    catch(e){li.className='failed';li.textContent=`失败：${item.name} — ${e.message||e}。`;
      const a=document.createElement('a');a.href=item.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=' 在浏览器打开原图';li.appendChild(a);
    }
  }
  if(files.length){
    const bytes=makeZip(files);const blob=new Blob([bytes],{type:'application/zip'}),url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download='mubu-images.zip';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),15000);
    status.textContent=`下载成功 ${files.length}/${items.length} 张；请将 mubu-images.zip 放入 cached_images 再运行 build.bat。`;
  }else status.textContent='0 张图片下载成功。可能是幕布服务器不允许当前浏览器跨域读取，请点击上方失败项的原图链接尝试保存。';
  button.disabled=false;
});
status.textContent=`发现 ${items.length} 张缺失的幕布图片。`;
</script></body></html>'''
    target.write_text(html.replace('__IMAGE_LIST__',payload),encoding='utf8')
    return target

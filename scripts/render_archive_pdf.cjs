// Offline artifact rendering only. Never connects to an authenticated browser.
const {chromium}=require('playwright');
const fs=require('node:fs');
(async()=>{
 const [input,output,runId]=process.argv.slice(2);
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROME_CHANNEL?{channel:process.env.PLAYWRIGHT_CHROME_CHANNEL}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1000,height:1100}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',r=>r.abort());
  await page.setContent(fs.readFileSync(input,'utf8'));
  await page.locator('#rename-research-network[data-rendered=true]').waitFor();
  const run=page.locator('[data-kg-run]');
  if(!await run.locator('option').evaluateAll((es,id)=>es.some(e=>e.value===id),runId))throw Error('Requested run is absent from the report');
  await page.locator('[data-kg-runs]').evaluate(e=>e.open=true);
  await run.selectOption(runId);
  await page.evaluate(id=>{
    const root=document.getElementById('rename-research-network');
    const caption=document.createElement('p');caption.textContent='Archived run: '+id;
    caption.style.cssText='font-size:11px;overflow-wrap:anywhere;margin:0 0 12px';
    root.querySelector('.kg-header').after(caption);
    root.querySelector('[data-kg-run-summary]').textContent='';
    const runCaption=document.createElement('p');
    runCaption.textContent=root.querySelector('[data-kg-run-source]').textContent;
    runCaption.style.cssText='font-size:11px;margin:0 0 8px';
    root.querySelector('[data-kg-run-metrics]').before(runCaption);
    root.querySelector('.kg-inspector').hidden=true;
    root.querySelector('.kg-foot').hidden=true;
    root.querySelector('[data-kg-stale]').hidden=true;
  },runId);
  await page.addStyleTag({content:'@media print{#rename-research-network .kg-svg{height:500px!important;max-height:500px!important}#rename-research-network .kg-run-panel{overflow:visible}#rename-research-network .kg-run-top{display:none!important}#rename-research-network .kg-header{margin-bottom:12px}#rename-research-network .kg-stat{padding:10px 12px}#rename-research-network .kg-stat-value{font-size:24px}}'});
  await page.emulateMedia({media:'print',colorScheme:'light'});
  await page.waitForTimeout(150);
  if(errors.length)throw Error(errors.join('; '));
  await page.pdf({path:output,format:'A4',printBackground:true,margin:{top:'12mm',right:'10mm',bottom:'12mm',left:'10mm'}});
  const bytes=fs.readFileSync(output);if(!bytes.subarray(0,5).equals(Buffer.from('%PDF-')))throw Error('PDF output not verified');
  console.log(JSON.stringify({rendered:true,bytes:bytes.length,run_id:runId,external_requests_allowed:false}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exit(1);});

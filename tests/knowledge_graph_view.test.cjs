// Generated local report QA only. No authenticated browser, remote requests or writes to the journal.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROME_CHANNEL?{channel:process.env.PLAYWRIGHT_CHROME_CHANNEL}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{requests.push(route.request().url());return route.abort();});
 await page.setContent(fs.readFileSync(process.argv[2],'utf8'));
 const scope=await page.locator('iframe').count()?page.frameLocator('iframe'):page;
 const root=scope.locator('#rename-research-network');
 await root.locator('[data-kg-diagram] [data-node-id]').first().waitFor();
 const data=JSON.parse(await root.locator('[data-kg-data]').textContent());
 const counts=data.metadata.research_relation_counts,nodeMap=new Map(data.research.nodes.map(n=>[n.id,n]));
 const cross=data.research.edges.filter(e=>e.properties.layer==='cross_topic'&&e.properties.active);
 const ids=new Set(cross.flatMap(e=>[e.source,e.target]));
 const paths=root.locator('[data-kg-diagram] [data-relation-id]');
 assert.equal(await paths.count(),cross.length);
 assert.equal(await root.locator('[data-node-id]').count(),ids.size);
 assert.deepEqual(new Set(await paths.evaluateAll(es=>es.map(e=>e.dataset.relationId))),new Set(cross.map(e=>e.id)));
 assert.deepEqual(new Set(await root.locator('[data-node-id]').evaluateAll(es=>es.map(e=>e.dataset.nodeId))),ids);
 assert.equal(await root.locator('[data-kg-stat-conversations]').textContent(),String(data.conversations.length));
 const strokes=await paths.evaluateAll(es=>es.map(e=>getComputedStyle(e).stroke));
 assert.ok(strokes.every(s=>s&&s!=='none'&&s!=='rgba(0, 0, 0, 0)'),JSON.stringify(strokes));
 const output=path.dirname(process.argv[3]);
 await page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});
 const h=cross.find(e=>e.properties.tier==='H');
 if(h){await root.locator('[data-kg-edge]').selectOption(h.id);assert.match(await root.locator('[data-kg-detail]').textContent(),/PENDING_VALIDATION/);await root.locator('[data-kg-detail] summary').first().click();assert.match(await root.locator('[data-kg-detail]').textContent(),/Observation:/);for(const s of h.properties.support)assert.ok((await root.locator('[data-kg-detail]').textContent()).includes(s.result_event_id));}
 await root.locator('[data-kg-layers] input[value="H"]').uncheck();
 assert.equal(await paths.count(),cross.filter(e=>e.properties.tier!=='H').length);
 for(const t of ['E0','E1'])await root.locator(`[data-kg-layers] input[value="${t}"]`).uncheck();
 assert.equal(await paths.count(),0);
 for(const t of ['E0','E1','H'])await root.locator(`[data-kg-layers] input[value="${t}"]`).check();
 await root.locator('[data-kg-source]').selectOption('live_ui');
 const live=cross.filter(e=>[e.source,e.target].every(id=>e.properties.support.some(s=>s.conversation_url===nodeMap.get(id).properties.url&&s.source_type==='live_ui'))).length;
 assert.equal(await paths.count(),live);
 await root.locator('[data-kg-source]').selectOption('all');
 await root.locator('[data-kg-search]').fill('Heat');
 const searchable=data.research.nodes.filter(n=>[n.label,n.coding?.short_label,...(n.properties.latest_observed_titles||[])].join(' ').toLowerCase().includes('heat')).map(n=>n.id);
 assert.equal(await paths.count(),cross.filter(e=>searchable.includes(e.source)||searchable.includes(e.target)).length);
 await root.locator('[data-kg-search]').fill('no-such-topic-xyz');assert.equal(await root.locator('[data-node-id]').count(),0);
 await root.locator('[data-kg-search]').fill('   ');assert.equal(await root.locator('[data-node-id]').count(),ids.size);
 await root.locator('[data-kg-search]').fill('');
 const selected=[...ids][0];await root.locator('[data-kg-node]').selectOption(selected);await root.locator('[data-kg-focus]').click();
 assert.equal(await paths.count(),cross.filter(e=>e.source===selected||e.target===selected).length);
 await root.locator('[data-kg-focus]').click();await root.locator('[data-kg-node]').selectOption('');
 await root.locator('[data-kg-mode]').selectOption('domains');const domainEdges=data.research.edges.filter(e=>e.properties.layer==='domain_coding'&&e.properties.active);assert.equal(await paths.count(),domainEdges.length);
 assert.equal(await root.locator('[data-kg-tier-count="E1"]').textContent(),String(domainEdges.length));
 if(domainEdges.length){await root.locator('[data-kg-edge]').selectOption(domainEdges[0].id);assert.match(await root.locator('[data-kg-detail]').textContent(),/ANALYST_METADATA_CODING/);}
 await root.locator('[data-kg-mode]').selectOption('history');assert.equal(await root.locator('[data-kg-diagram]').isVisible(),false);assert.equal(await root.locator('[data-kg-node] option').count(),data.conversations.length+1);assert.ok(await root.locator('[data-kg-history] tbody tr').count()>0);
 await root.locator('[data-kg-mode]').selectOption('network');await root.locator('[data-kg-isolates]').check();assert.equal(await root.locator('[data-node-id]').count(),data.conversations.length);await root.locator('[data-kg-isolates]').uncheck();
 const scene=root.locator('[data-kg-diagram] > g');await root.locator('[data-kg-zoom-in]').click();assert.match(await scene.getAttribute('transform'),/scale\(1.25\)/);await root.locator('[data-kg-fit]').click();assert.match(await scene.getAttribute('transform'),/scale\(1\)/);
 const node=root.locator('[data-node-id]').first(),before=await node.getAttribute('transform'),box=await node.boundingBox();
 await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2+20,box.y+box.height/2+20,{steps:5});await page.mouse.up();assert.notEqual(await node.getAttribute('transform'),before);
 const download=page.waitForEvent('download');await root.locator('[data-kg-export]').click();const d=await download;let csv='';for await(const chunk of await d.createReadStream())csv+=chunk.toString('utf8');assert.match(csv,/validation_status/);for(const e of cross)assert.ok(csv.includes(e.id));
 await root.locator('[data-kg-runs] > summary').click();
 const runs=data.report.runs;assert.equal(await root.locator('[data-kg-run] option').count(),runs.length);
 const runId=await root.locator('[data-kg-run]').inputValue(),run=runs.find(r=>r.run_id===runId);
 assert.equal(await root.locator('[data-kg-run-table] tbody tr').count(),run.targets.length);
 const pending=runs.find(r=>r.pending_count>0);if(pending){await root.locator('[data-kg-run]').selectOption(pending.run_id);assert.ok((await root.locator('[data-kg-run-note]').textContent()).includes(`${pending.pending_count} pending`));}
 await root.locator('[data-kg-run]').selectOption(runId);await root.locator('[data-kg-runs] > summary').click();
 const layouts=[];
 for(const width of [1440,1000,736,420,320]){
  await page.setViewportSize({width,height:1000});await page.waitForTimeout(100);
  const m=await root.evaluate(e=>{const boxes=[...e.querySelectorAll('[data-node-id]')].map(n=>n.getBoundingClientRect());let overlap=0;for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){const dx=Math.min(boxes[i].right,boxes[j].right)-Math.max(boxes[i].left,boxes[j].left),dy=Math.min(boxes[i].bottom,boxes[j].bottom)-Math.max(boxes[i].top,boxes[j].top);if(dx>1&&dy>1)overlap++;}return {width:e.clientWidth,scroll:e.scrollWidth,viewport:e.ownerDocument.documentElement.clientWidth,docScroll:e.ownerDocument.documentElement.scrollWidth,nodeOverlaps:overlap};});
  assert.ok(m.scroll<=m.width+1,JSON.stringify(m));assert.ok(m.docScroll<=m.viewport+1,JSON.stringify(m));assert.equal(m.nodeOverlaps,0,JSON.stringify(m));layouts.push({screen:width,...m});
  if(width===420)await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
 }
 await page.setViewportSize({width:1440,height:1000});await page.emulateMedia({colorScheme:'dark'});await page.waitForTimeout(100);await page.screenshot({path:path.join(output,'dark.png'),fullPage:true});
 const darkStrokes=await paths.evaluateAll(es=>es.map(e=>getComputedStyle(e).stroke));assert.ok(darkStrokes.every(s=>s&&s!=='none'));
 assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);
 fs.writeFileSync(process.argv[3],JSON.stringify({status:'PASS',relation_counts:counts,default_nodes:ids.size,source_filter_live_edges:live,layouts,latest_displayed_run:runId,checks:['offline standalone styles','evidence layers','source coverage at both endpoints','provenance drilldown','no invented edges','search','one-hop focus','domain coding','history','isolates','zoom','drag','CSV with provenance','run denominators','responsive no overlap','dark theme','no runtime errors','no network requests']},null,2)+'\n');
 console.log(JSON.stringify({status:'PASS',checks:18,layouts}));await browser.close();
})().catch(e=>{console.error(e.stack);process.exit(1)});

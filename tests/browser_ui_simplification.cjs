// Fresh headless Edge context, synthetic project only, independent test service.
const {chromium}=require('./browser_runtime.cjs');
const fs=require('fs');
const path=require('path');
const zlib=require('zlib');
const assert=require('assert');

function readCsv(file){
  const source=fs.readFileSync(file,'utf8').replace(/^\uFEFF/,'');
  const records=[]; let row=[],cell='',quoted=false;
  for(let i=0;i<source.length;i++){
    const ch=source[i];
    if(ch==='"'){
      if(quoted&&source[i+1]==='"'){cell+='"';i++;} else quoted=!quoted;
    }else if(ch===','&&!quoted){row.push(cell);cell='';}
    else if(ch==='\n'&&!quoted){row.push(cell.replace(/\r$/,''));records.push(row);row=[];cell='';}
    else cell+=ch;
  }
  if(cell||row.length){row.push(cell);records.push(row);}
  const columns=records.shift();
  assert.equal(new Set(columns).size,columns.length,'unique CSV columns');
  for(const row of records) assert.equal(row.length,columns.length,'CSV has no extra index or metadata rows');
  return {columns,rows:records,col:match=>{
    const index=columns.findIndex(c=>typeof match==='function'?match(c):c.includes(match));
    assert(index>=0,`CSV column not found: ${match}`);
    return records.map(row=>row[index]===''?NaN:Number(row[index]));
  }};
}
function projectManifest(file){
  const bytes=fs.readFileSync(file);
  let end=-1;
  for(let i=bytes.length-22;i>=Math.max(0,bytes.length-65557);i--){
    if(bytes.readUInt32LE(i)===0x06054b50){end=i;break;}
  }
  assert(end>=0,'project ZIP end record');
  let offset=bytes.readUInt32LE(end+16);
  const count=bytes.readUInt16LE(end+10);
  for(let i=0;i<count;i++){
    assert.equal(bytes.readUInt32LE(offset),0x02014b50);
    const compression=bytes.readUInt16LE(offset+10),size=bytes.readUInt32LE(offset+20);
    const nameLen=bytes.readUInt16LE(offset+28),extra=bytes.readUInt16LE(offset+30),comment=bytes.readUInt16LE(offset+32);
    const name=bytes.subarray(offset+46,offset+46+nameLen).toString('utf8');
    const local=bytes.readUInt32LE(offset+42);
    if(name==='project.json'){
      const start=local+30+bytes.readUInt16LE(local+26)+bytes.readUInt16LE(local+28);
      const data=bytes.subarray(start,start+size);
      return JSON.parse((compression===8?zlib.inflateRawSync(data):data).toString('utf8'));
    }
    offset+=46+nameLen+extra+comment;
  }
  throw Error('project.json missing');
}
function near(actual,expected,message,tolerance=1e-10){
  assert(Number.isFinite(actual)&&Math.abs(actual-expected)<=tolerance,`${message}: ${actual} != ${expected}`);
}

(async()=>{
  const root=path.resolve(__dirname,'..'),output=path.join(root,'verification');
  fs.mkdirSync(output,{recursive:true});
  const expected=JSON.parse(fs.readFileSync(path.join(output,'ui_simplification_expected.json'),'utf8'));
  const fixture=path.join(output,'ui_simplification_initial.orrproj');
  const browser=await chromium.launch({channel:'msedge',headless:true,
    args:['--proxy-server=direct://','--proxy-bypass-list=*']});
  const page=await browser.newPage({viewport:{width:1600,height:1200},acceptDownloads:true});
  const pageErrors=[],downloadEvents=[],consoleErrors=[];
  page.on('pageerror',error=>pageErrors.push(error.message));
  page.on('download',file=>downloadEvents.push(file.suggestedFilename()));
  page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text());});
  const report={passed:false,pageErrors};
  const settle=async()=>{
    await page.locator('[data-testid="stApp"][data-test-script-state="notRunning"]').waitFor({timeout:45000});
    await page.getByTestId('stStatusWidget').waitFor({state:'hidden',timeout:45000}).catch(()=>{});
  };
  const open=async label=>{
    const summary=page.locator('summary').filter({has:page.getByText(label,{exact:true})}).first();
    await summary.waitFor();
    if(!await summary.evaluate(e=>e.parentElement.open)) await summary.click();
    await settle();
  };
  const choose=async(label,value)=>{
    const combo=page.getByRole('combobox',{name:label,exact:true});
    await combo.click();await combo.press('ArrowDown');
    await page.getByRole('option',{name:value,exact:typeof value==='string'}).click();
    await settle();
  };
  const navigate=async(label,heading=label)=>{
    await page.getByRole('link',{name:new RegExp(label)}).click();
    await page.getByRole('heading',{name:heading,exact:true}).waitFor({timeout:45000});
    await settle();
  };
  const restore=async file=>{
    await navigate('导入与设置');
    await open('继续上次的分析项目');
    await page.getByTestId('stFileUploader').filter({hasText:'载入 .orrproj 项目'}).locator('input[type="file"]').setInputFiles(file);
    await page.getByRole('button',{name:'载入项目（替换当前工作区）',exact:true}).click();
    await page.getByText('已载入项目，原始数据和参数已恢复。',{exact:true}).waitFor({timeout:45000});
    await settle();
  };
  const download=async(label,name)=>{
    const previousCount=downloadEvents.length;
    const pending=page.waitForEvent('download',{timeout:15000}).then(file=>({file}),error=>({error}));
    await page.getByRole('button',{name:label,exact:typeof label==='string'}).click();
    const received=await pending;
    if(received.error)throw received.error;
    const file=received.file;
    assert.equal(await file.failure(),null,'download completed');
    const target=path.join(output,name);
    await file.saveAs(target);await settle();
    assert.equal(downloadEvents.length,previousCount+1,'one action emits exactly one download');
    return target;
  };
  const assertNoDownload=async action=>{
    const count=downloadEvents.length;
    const pending=page.waitForEvent('download',{timeout:1800}).then(()=>true,()=>false);
    await action();
    assert.equal(await pending,false,'failed action must not download an old file');
    assert.equal(downloadEvents.length,count);
    await settle();
  };
  try{
    await page.goto(process.env.ORR_TEST_URL||'http://127.0.0.1:8766/orr-workbench/');
    await page.getByRole('heading',{name:'导入与设置',exact:true}).waitFor({timeout:45000});
    assert.equal(await page.title(),'ORR Worker');
    await restore(fixture);
    await navigate('极化曲线');
    await choose('按组筛选','KL');
    await open('修改实验条件');
    // Fill without Enter or a preparatory Apply: clicking the native CSV button
    // must capture this last focused value, apply once and emit a real download.
    await page.getByRole('spinbutton',{name:'pH *',exact:true}).fill('13.2');
    const lastInputFile=await download(/(?:下载|应用并导出)绘图 CSV/,'ui_last_input_plot.csv');
    const lastInput=readCsv(lastInputFile);
    for(const sample of expected.samples){
      const x=lastInput.col(c=>c.startsWith(sample.label+'__')&&c.endsWith('__E_RHE_V'));
      near(x[0],expected.raw_first_E+expected.initial_offset+.2*expected.ph_shift_per_unit,'one-click last input');
      near(x[sample.count-1],expected.raw_last_E+expected.initial_offset+.2*expected.ph_shift_per_unit,'unaltered sample grid end');
    }
    report.nativeOneClickLastInputDownload=true;
    await page.getByRole('button',{name:'PNG',exact:true}).waitFor({timeout:45000});
    assert.equal(await page.getByRole('button',{name:'PNG',exact:true}).isDisabled(),false,'post-download redraw restores exports');
    report.exportsRemainAvailableAfterCombinedDownload=true;
    process.stdout.write('Native apply-and-download emitted current CSV after one click.\n');
    await navigate('导出与项目');
    const appliedProject=await download('保存分析项目','ui_applied.orrproj');
    let manifest=projectManifest(appliedProject);
    for(const sample of expected.samples){near(manifest.files.find(f=>f.id===sample.id).config.pH,13.2,'applied project pH');}
    report.projectReflectsAppliedSettings=true;
    // Start a new draft in the curve page, carry it across pages, then combine
    // its application with project generation in the export page.
    await navigate('极化曲线');await open('修改实验条件');
    await page.getByRole('spinbutton',{name:'pH *',exact:true}).fill('13.3');
    await page.getByRole('heading',{name:'极化曲线',exact:true}).click();
    await page.getByRole('button',{name:'应用并导出绘图 CSV',exact:true}).waitFor({timeout:45000});
    await navigate('导出与项目');
    const draftProject=await download('应用并保存项目','ui_cross_page.orrproj');
    manifest=projectManifest(draftProject);
    for(const sample of expected.samples){near(manifest.files.find(f=>f.id===sample.id).config.pH,13.3,'cross-page draft project');}
    await restore(draftProject);
    await navigate('极化曲线');
    const restored=readCsv(await download('下载绘图 CSV','ui_restored_plot.csv'));
    near(restored.col(c=>c.startsWith(expected.samples[0].label+'__')&&c.endsWith('__E_RHE_V'))[0],
      expected.raw_first_E+expected.initial_offset+.3*expected.ph_shift_per_unit,'restored project axis');
    report.crossPageDraftAndProjectRoundtrip=true;

    // Use the original conditions for quantitative/smoothing comparisons.
    await restore(fixture);await navigate('极化曲线');
    await choose('按组筛选','KL');
    await page.getByText('环电流',{exact:true}).first().click();await settle();
    await choose('按组筛选','KL');
    const ringU=readCsv(await download('下载绘图 CSV','ui_ring_uA.csv'));
    assert.equal(ringU.columns.length,6);assert.equal(ringU.rows.length,121);
    assert(ringU.columns.filter(c=>c.endsWith('__I_ring_uA')).length===3);
    for(const sample of expected.samples){
      const x=ringU.col(c=>c.startsWith(sample.label+'__')&&c.endsWith('__E_RHE_V'));
      assert.equal(x.filter(Number.isFinite).length,sample.count);
      if(sample.count<121)assert(x.slice(sample.count).every(Number.isNaN));
    }
    await choose('纵坐标','环电流 / mA');
    const ringM=readCsv(await download('下载绘图 CSV','ui_ring_mA.csv'));
    for(const sample of expected.samples){
      const micro=ringU.col(c=>c.startsWith(sample.label+'__')&&c.endsWith('__I_ring_uA'));
      const milli=ringM.col(c=>c.startsWith(sample.label+'__')&&c.endsWith('__I_ring_mA'));
      for(let i=0;i<sample.count;i++)near(milli[i],micro[i]/1000,'ring current unit mapping');
    }
    await page.getByRole('switch',{name:'启用曲线平滑',exact:true}).press('Space');
    await page.getByRole('combobox',{name:'平滑强度',exact:true}).waitFor();await settle();
    const smooth=readCsv(await download('下载绘图 CSV','ui_ring_smoothed.csv'));
    assert(smooth.columns.filter(c=>c.includes('__I_ring_smoothed_plot_only_mA')).length===3);
    // The acknowledged automatic redraw must restore this section directly;
    // do not navigate away or change a setting to make it appear.
    await open('更多导出');
    const complete=readCsv(await download('完整数据 CSV','ui_ring_complete.csv'));
    const fileIndex=complete.columns.indexOf('file_id');
    const plotIndex=complete.columns.indexOf('plotted_current_value');
    const smoothIndex=complete.columns.indexOf('I_ring_smoothed_plot_only_mA');
    for(const sample of expected.samples){
      const selected=complete.rows.filter(row=>row[fileIndex]===sample.id);
      const y=smooth.col(c=>c.startsWith(sample.label+'__')&&c.endsWith('__I_ring_smoothed_plot_only_mA'));
      assert.equal(selected.length,sample.count);
      selected.forEach((row,index)=>{
        near(y[index],Number(row[plotIndex]),'wide CSV matches plotted values');
        near(y[index],Number(row[smoothIndex]),'wide CSV matches independent smoothing column');
      });
    }
    report.independentXyUnitsAndDisplaySmoothing=true;
    await page.screenshot({path:path.join(output,'ui_ring_smoothing.png'),fullPage:true});

    await restore(fixture);await navigate('多转速 K–L','多转速 K–L 分析');
    await page.getByRole('button',{name:'计算 K–L',exact:true}).waitFor();
    assert.equal(await page.getByTestId('stImage').count(),0,'K–L does not calculate on opening');
    await page.getByRole('checkbox',{name:'已核对：各文件属于同一电极和相同实验条件，以上物性参数适用',exact:true}).press('Space');
    await page.getByRole('button',{name:'计算 K–L',exact:true}).click();await settle();
    await page.getByTestId('stImage').first().waitFor({timeout:45000});
    const kl=readCsv(await download('下载绘图 CSV','ui_kl_plot.csv'));
    assert.deepEqual(kl.columns,['E_RHE_V','n_KL','two_e_pct_model','four_e_pct_model']);
    for(const n of kl.col('n_KL'))near(n,expected.expected_n,'synthetic K–L known n',2e-8);
    report.explicitKlCalculationAndCsv=true;
    await page.getByRole('checkbox',{name:'已核对：各文件属于同一电极和相同实验条件，以上物性参数适用',exact:true}).press('Space');
    await settle();
    await assertNoDownload(async()=>{
      await page.getByRole('button',{name:'下载绘图 CSV',exact:true}).click();
      await page.getByTestId('stAlert').filter({hasText:'请先核对实验条件和物性参数。'}).waitFor();
    });
    assert.equal(await page.getByRole('button',{name:'PNG',exact:true}).count(),0,'failed K–L calculation removes old result downloads');
    report.failureDoesNotDownloadOldResult=true;

    await restore(fixture);await navigate('RRDE 选择性');
    await page.getByRole('button',{name:'计算 RRDE',exact:true}).waitFor();
    assert.equal(await page.getByTestId('stImage').count(),0,'RRDE does not calculate on opening');
    await page.getByRole('button',{name:'计算 RRDE',exact:true}).click();await settle();
    await page.getByTestId('stImage').first().waitFor({timeout:45000});
    const rrde=readCsv(await download('下载绘图 CSV','ui_rrde_plot.csv'));
    const gapN=rrde.col(c=>c.startsWith(expected.gap.label+'__')&&c.endsWith('__n_RRDE'));
    const gapP=rrde.col(c=>c.startsWith(expected.gap.label+'__')&&c.endsWith('__peroxide_pct'));
    assert(Number.isNaN(gapN[expected.gap.gap_row]));
    assert(Number.isNaN(gapP[expected.gap.gap_row]));
    near(gapN[expected.gap.gap_row-1],3.2,'valid before internal gap');
    near(gapN[expected.gap.gap_row+1],3.2,'valid after internal gap');
    near(gapP[expected.gap.gap_row+1],40.,'peroxide percentage');
    report.explicitRrdeAndInternalGapPreservation=true;
    await page.screenshot({path:path.join(output,'ui_rrde_results.png'),fullPage:true});
    assert.deepEqual(pageErrors,[],'no browser page errors');
    report.downloads=downloadEvents;report.passed=true;
  }catch(error){
    report.error=error.stack||String(error);
    report.consoleErrors=consoleErrors;
    report.visibleButtons=await page.getByRole('button').allTextContents().catch(()=>[]);
    report.pageTextTail=(await page.locator('body').innerText().catch(()=>'' )).slice(-10000);
    report.shadowText=await page.locator('*').evaluateAll(elements=>elements.filter(e=>e.shadowRoot)
      .map(e=>e.shadowRoot.textContent).filter(Boolean)).catch(()=>[]);
    await page.screenshot({path:path.join(output,'ui_simplification_failure.png'),fullPage:true}).catch(()=>{});
    throw error;
  }finally{
    fs.writeFileSync(path.join(output,'ui_simplification_browser_report.json'),JSON.stringify(report,null,2));
    process.stdout.write(JSON.stringify(report,null,2)+'\n');
    await browser.close();
  }
})().catch(error=>{process.stderr.write(String(error.stack||error)+'\n');process.exitCode=1;});

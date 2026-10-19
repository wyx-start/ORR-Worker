// Isolated synthetic-data workflow. Never attaches to the user's open browser.
const {chromium}=require('./browser_runtime.cjs');
const fs=require('fs');
const path=require('path');
const assert=require('assert');

(async()=>{
  const output=path.resolve(__dirname,'../verification');
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({channel:'msedge',headless:true,args:['--proxy-server=direct://','--proxy-bypass-list=*']});
  const page=await browser.newPage({viewport:{width:1600,height:1150}});
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const settle=async()=>{
    await page.waitForTimeout(250);
    await page.locator('[data-testid="stApp"][data-test-script-state="notRunning"]').waitFor();
  };
  const open=async label=>{
    const summary=page.locator('summary').filter({has:page.getByText(label,{exact:true})});
    if(!await summary.evaluate(e=>e.parentElement.open)) await summary.click();
    await settle();
  };
  const choose=async(label,value)=>{
    const combo=page.getByRole('combobox',{name:label,exact:true});
    await combo.click(); await combo.press('ArrowDown');
    await page.getByRole('option',{name:value,exact:typeof value==='string'}).click();
    await settle();
  };
  const navigate=async label=>{
    await page.getByRole('link',{name:new RegExp(label)}).click();
    await page.getByRole('heading',{name:label,exact:true}).waitFor();
    await settle();
  };
  const scanSection=async()=>{
    if(!await page.getByRole('combobox',{name:'要检查的文件',exact:true}).count()){
      await page.getByText('扫描与背景',{exact:true}).click();
      await settle();
    }
  };
  const restore=async file=>{
    await navigate('导入与设置');
    await open('继续上次的分析项目');
    await page.locator('input[type="file"]').nth(1).setInputFiles(file);
    await page.getByRole('button',{name:'载入项目（替换当前工作区）',exact:true}).click();
    await page.getByText('已载入项目，原始数据和参数已恢复。',{exact:true}).waitFor();
    await settle();
  };
  const download=async(label,name)=>{
    const pending=page.waitForEvent('download');
    await page.getByRole('button',{name:label,exact:true}).click();
    const target=path.join(output,name);
    const file=await pending;
    await file.saveAs(target);
    await settle();
    return target;
  };
  const csvA=file=>{
    const lines=fs.readFileSync(file,'utf8').replace(/^\uFEFF/,'').trim().split(/\r?\n/);
    const headers=lines[0].split(',');
    return lines.slice(1).map(line=>Object.fromEntries(line.split(',').map((v,i)=>[headers[i],v])))
      .find(row=>row.filename==='Sample-A_900rpm.txt');
  };
  try {
    await page.goto(process.env.ORR_TEST_URL || 'http://127.0.0.1:8766/orr-workbench/');
    await restore(path.join(output,'ring_initial.orrproj'));
    await scanSection();
    for(const sample of [/Sample-A_900rpm/,/Sample-B_1600rpm/]){
      await choose('要检查的文件',sample);
      await open('修改扫描、通道与背景');
      await choose('盘环配对背景文件',/Ar_RRDE_background/);
      await page.getByRole('button',{name:'应用扫描与背景设置',exact:true}).click();
      await settle();
    }
    await page.getByRole('button',{name:'确认并应用分组与背景',exact:true}).click(); await settle();
    await navigate('极化曲线');
    await choose('绘制通道','环电流');
    await choose('按组筛选','全部');
    await page.getByRole('button',{name:'PNG · 300 dpi',exact:true}).waitFor();
    const micro=csvA(await download('单独导出曲线 CSV','ring_microamp.csv'));
    assert(Math.abs(Number(micro.plotted_current_value)-1.8)<1e-10);
    assert.equal(micro.plotted_current_unit,'uA');
    await download('PNG · 300 dpi','ring_current.png');
    await download('SVG · 矢量图','ring_current.svg');
    assert(fs.readFileSync(path.join(output,'ring_current.svg'),'utf8').includes('<svg'));
    await page.getByRole('button',{name:'PNG · 300 dpi',exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,'ring_comparison.png'),animations:'disabled'});
    await choose('纵坐标','环电流 / mA');
    const milli=csvA(await download('单独导出曲线 CSV','ring_milliamp.csv'));
    assert(Math.abs(Number(milli.plotted_current_value)-.0018)<1e-12);
    await choose('环电流显示','未扣背景');
    const raw=csvA(await download('单独导出曲线 CSV','ring_raw.csv'));
    assert(Math.abs(Number(raw.plotted_current_value)-.002)<1e-12);
    assert.equal(raw.ring_background_status,'未参与');
    await page.getByText('启用曲线平滑',{exact:true}).click(); await settle();
    const smoothed=fs.readFileSync(await download('单独导出曲线 CSV','ring_smoothed.csv'),'utf8');
    assert(smoothed.includes('I_ring_smoothed_plot_only_A'));
    const parameters=JSON.parse(fs.readFileSync(await download('单独导出参数 JSON','ring_parameters.json'),'utf8'));
    assert.equal(parameters.settings.ring_plot.unit,'mA');
    assert.equal(parameters.settings.ring_plot.background_view,'未扣背景');
    assert.equal(parameters.settings.ring_plot.comparison_audit.allowed,true);
    const samples=parameters.files.filter(f=>f.filename.startsWith('Sample-'));
    for(const sample of samples){
      assert.equal(sample.config.background_disk,sample.config.background_ring);
      assert.equal(sample.config.background_mode,'paired');
    }
    await navigate('导出与项目');
    const saved=await download('保存分析项目 .orrproj','ring_saved.orrproj');
    await restore(saved);
    await navigate('极化曲线');
    await page.getByRole('button',{name:'PNG · 300 dpi',exact:true}).waitFor();
    const restored=JSON.parse(fs.readFileSync(await download('单独导出参数 JSON','ring_restored_parameters.json'),'utf8'));
    assert.deepEqual(restored.files.map(f=>f.config),parameters.files.map(f=>f.config));
    assert.equal(restored.settings.ring_plot.unit,'mA');
    assert.equal(restored.settings.ring_plot.background_view,'未扣背景');
    await navigate('导入与设置');
    await scanSection();
    await choose('要检查的文件',/Sample-A_900rpm/);
    await open('修改扫描、通道与背景');
    await choose('背景模式','分别指定背景');
    await choose('环背景（单列背景按其唯一电流列）','不扣除');
    await page.getByRole('button',{name:'应用扫描与背景设置',exact:true}).click(); await settle();
    await navigate('导出与项目');
    const independent=JSON.parse(fs.readFileSync(await download('导出全部参数与处理记录 JSON','ring_independent_parameters.json'),'utf8'));
    const independentA=independent.files.find(f=>f.filename==='Sample-A_900rpm.txt').config;
    assert.equal(independentA.background_mode,'independent');
    assert.equal(independentA.background_ring,null);
    assert(independentA.background_disk);
    await navigate('导入与设置');
    await scanSection();
    await choose('要检查的文件',/Sample-A_900rpm/);
    await open('修改扫描、通道与背景');
    await choose('背景模式','盘环配对背景');
    await choose('盘环配对背景文件','不扣除');
    await page.getByRole('button',{name:'应用扫描与背景设置',exact:true}).click(); await settle();
    await navigate('导出与项目');
    const cleared=JSON.parse(fs.readFileSync(await download('导出全部参数与处理记录 JSON','ring_cleared_parameters.json'),'utf8'));
    const clearedA=cleared.files.find(f=>f.filename==='Sample-A_900rpm.txt').config;
    assert.equal(clearedA.background_disk,null);
    assert.equal(clearedA.background_ring,null);
    await restore(path.join(output,'ring_conflict.orrproj'));
    await navigate('极化曲线');
    await choose('绘制通道','环电流'); await choose('按组筛选','全部');
    const conflict=page.getByTestId('stAlert').filter({hasText:'环电流比较存在已知条件冲突'});
    await conflict.waitFor();
    assert.equal(await page.getByRole('button',{name:'PNG · 300 dpi',exact:true}).count(),0);
    await conflict.scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,'ring_conflict.png'),animations:'disabled'});
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'ring_browser_report.json'),JSON.stringify({passed:true,
      pairedBothChannels:true,crossGroupComparison:true,missingRecordsAllowed:true,
      differingRingPotentialAllowed:true,microampMilliampConversion:true,rawView:true,
      pngSvgCsvParameters:true,ringSmoothing:true,projectRoundtrip:true,
      independentOverrideProtected:true,pairedClearBothChannels:true,knownConflictBlocked:true,pageErrors:errors},null,2));
    console.log('Ring comparison browser workflow passed');
  }catch(error){
    await page.screenshot({path:path.join(output,'ring_browser_failure.png'),fullPage:true});
    console.error(error); process.exitCode=1;
  }finally{await browser.close();}
})();

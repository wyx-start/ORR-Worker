const {chromium}=require('./browser_runtime.cjs');
const fs=require('fs');
const path=require('path');
const assert=require('assert');

(async()=>{
  const root=path.resolve(__dirname,'..');
  const output=path.join(root,'verification');
  fs.mkdirSync(output,{recursive:true});
  const state=JSON.parse(fs.readFileSync(path.join(root,'.runtime','server.json'),'utf8'));
  const executable=chromium.executablePath();
  const installed=fs.existsSync(executable)?{executablePath:executable}:{channel:'msedge'};
  const browser=await chromium.launch({...installed,headless:true,args:['--proxy-server=direct://','--proxy-bypass-list=*']});
  const page=await browser.newPage({viewport:{width:1500,height:1000}});
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const navigate=async name=>{
    await page.getByRole('link',{name:new RegExp(name)}).click();
    await page.getByRole('heading',{name,exact:true}).waitFor();
  };
  const parameters=async filename=>{
    await navigate('导出与项目');
    const pending=page.waitForEvent('download');
    await page.getByRole('button',{name:'导出全部参数与处理记录 JSON',exact:true}).click();
    const file=path.join(output,filename);
    await (await pending).saveAs(file);
    const result=JSON.parse(fs.readFileSync(file,'utf8'));
    return Object.fromEntries(result.files.map(f=>[f.filename,f.config]));
  };
  const restore=async file=>{
    await navigate('导入与设置');
    const button=page.getByRole('button',{name:'载入项目（替换当前工作区）',exact:true});
    if(!await button.isVisible()) await page.getByText('继续上次的分析项目',{exact:true}).click();
    await page.locator('input[type="file"]').nth(1).setInputFiles(file);
    await button.click();
    await page.getByText('已载入项目，原始数据和参数已恢复。',{exact:true}).waitFor();
  };
  try{
    await page.goto(process.env.ORR_TEST_URL || state.url,{waitUntil:'domcontentloaded'});
    await page.getByRole('heading',{name:'导入与设置',exact:true}).waitFor({timeout:30000});
    const buffer=fs.readFileSync(path.join(root,'examples','O-0.1MNa-5mv-900.txt'));
    const names=['CoPc_1600转.txt','CoPc_RPM900.txt','CoPc_900转_1600转.txt','CoPc_1600.5rpm.txt','CoPc_0转.txt'];
    await page.locator('input[type="file"]').first().setInputFiles(names.map(name=>({name,mimeType:'text/plain',buffer})));
    await page.getByRole('button',{name:'导入所选文件',exact:true}).click();
    await page.getByText(/新增 5 个文件/).waitFor();
    await page.getByRole('button',{name:'确认并应用分组与背景',exact:true}).click();
    await page.getByRole('heading',{name:'当前实验条件',exact:true}).waitFor();
    await page.locator('[data-testid="stDataFrame"]').first().screenshot({path:path.join(output,'rpm_import_table.png')});
    const initial=await parameters('rpm_initial_parameters.json');
    assert.equal(initial[names[0]].rpm,1600);
    assert.equal(initial[names[1]].rpm,900);
    assert.equal(initial[names[0]].rpm_source,'filename_explicit');
    assert.equal(initial[names[2]].rpm,null);
    assert.equal(initial[names[2]].rpm_status,'ambiguous');
    assert.equal(initial[names[3]].rpm_status,'invalid');
    assert.equal(initial[names[4]].rpm,0);
    assert.equal(initial[names[0]].group,'CoPc');
    assert.equal(initial[names[1]].group,'CoPc');

    await restore(path.join(output,'rpm_legacy_fixture.orrproj'));
    const legacy=await parameters('rpm_legacy_parameters.json');
    assert.equal(legacy['CoPc_1600转.txt'].rpm,null);
    assert.equal(legacy['CoPc_900转.txt'].rpm,1200);
    assert.equal(legacy['CoPc_900转.txt'].rpm_source,'saved_project');
    await navigate('极化曲线');
    await page.getByRole('button',{name:'PNG · 300 dpi',exact:true}).waitFor();
    await navigate('导出与项目');
    await page.getByRole('button',{name:'polarization.png',exact:true}).waitFor();
    await navigate('导入与设置');
    await page.getByRole('button',{name:'根据文件名补全空白转速',exact:true}).click();
    await page.getByText(/已补全 1 个空白转速/).waitFor();
    await page.screenshot({path:path.join(output,'rpm_filled.png'),fullPage:true});
    const filled=await parameters('rpm_filled_parameters.json');
    assert.equal(filled['CoPc_1600转.txt'].rpm,1600);
    assert.equal(filled['CoPc_1600转.txt'].group,'保留分组');
    assert.equal(filled['CoPc_900转.txt'].rpm,1200);
    assert.equal(filled['CoPc_900转.txt'].rpm_source,'saved_project');
    assert.equal(filled['CoPc_900转_1600转.txt'].rpm,null);
    assert.equal(filled['CoPc_900转_1600转.txt'].rpm_status,'ambiguous');
    assert.equal(await page.getByRole('button',{name:'polarization.png',exact:true}).count(),0);
    const pending=page.waitForEvent('download');
    await page.getByRole('button',{name:'保存分析项目 .orrproj',exact:true}).click();
    const saved=path.join(output,'rpm_saved_project.orrproj');
    await (await pending).saveAs(saved);
    await restore(saved);
    const restored=await parameters('rpm_restored_parameters.json');
    assert.deepEqual(restored,filled);
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'rpm_browser_report.json'),JSON.stringify({passed:true,
      explicitFilenameImport:true,conflictsRemainEmpty:true,legacyProjectPreserved:true,
      fillOnlyEmpty:true,groupsPreserved:true,priorExportsInvalidated:true,projectRestored:true,pageErrors:errors},null,2));
    console.log('RPM browser passed: upload recognition, conflict, legacy values, fill-only-empty, export invalidation and project restore.');
  }finally{
    await browser.close();
  }
})().catch(e=>{console.error(e);process.exitCode=1;});

// Isolated browser workflow; test currents come from the public synthetic bundle.
const {chromium}=require('./browser_runtime.cjs');
const fs=require('fs');
const path=require('path');
const assert=require('assert');

(async()=>{
  const root=path.resolve(__dirname,'..');
  const output=path.join(root,'verification');
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({channel:'msedge',headless:true,args:['--proxy-server=direct://','--proxy-bypass-list=*']});
  const page=await browser.newPage({viewport:{width:1600,height:1150}});
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const settle=async()=>{
    // Expansion is a server-backed control; wait for its round-trip before
    // typing into widgets that belonged to the preceding render.
    await page.waitForTimeout(250);
    await page.locator('[data-testid="stApp"][data-test-script-state="notRunning"]').waitFor();
  };
  const open=async label=>{
    const summary=page.locator('summary').filter({hasText:label}).filter({has:page.getByText(label,{exact:true})});
    if(!await summary.evaluate(e=>e.parentElement.open)) await summary.click();
    await settle();
  };
  const choose=async(label,value)=>{
    const combo=page.getByRole('combobox',{name:label,exact:true});
    await combo.click(); await combo.press('ArrowDown');
    await page.getByRole('option',{name:value,exact:true}).click();
    await settle();
  };
  const navigate=async(label,heading=label)=>{
    await page.getByRole('link',{name:new RegExp(label)}).click();
    await page.getByRole('heading',{name:heading,exact:true}).waitFor();
    await settle();
  };
  const parameters=async filename=>{
    await navigate('导出与项目');
    const pending=page.waitForEvent('download');
    await page.getByRole('button',{name:'导出全部参数与处理记录 JSON',exact:true}).click();
    const target=path.join(output,filename);
    await (await pending).saveAs(target);
    return JSON.parse(fs.readFileSync(target,'utf8'));
  };
  const restore=async filename=>{
    await navigate('导入与设置');
    await open('继续上次的分析项目');
    await page.locator('input[type="file"]').nth(1).setInputFiles(filename);
    await page.getByRole('button',{name:'载入项目（替换当前工作区）',exact:true}).click();
    await page.getByText('已载入项目，原始数据和参数已恢复。',{exact:true}).waitFor();
    await settle();
  };
  const background=data=>data.files.find(f=>f.config.role==='背景').config;
  try {
    await page.goto(process.env.ORR_TEST_URL || 'http://127.0.0.1:8766/orr-workbench/');
    await page.getByRole('heading',{name:'ORR Worker',exact:true}).waitFor();
    assert.equal(await page.title(),'ORR Worker');
    await page.getByRole('button',{name:'载入四份示例',exact:true}).click();
    await page.getByRole('heading',{name:'当前实验条件',exact:true}).waitFor();
    await page.getByRole('button',{name:'确认并应用分组与背景',exact:true}).click();
    await page.getByRole('heading',{name:'当前实验条件',exact:true}).waitFor();
    await open('修改实验条件');
    const ph=page.getByRole('spinbutton',{name:'pH *',exact:true});
    await ph.fill('13'); await ph.press('Tab');
    await page.getByText(/修改尚未应用：输入框是草稿/).waitFor();
    await page.getByRole('button',{name:'应用实验参数',exact:true}).click();
    await page.getByText('已应用实验条件到 2 个文件。',{exact:true}).waitFor();
    const inherited=await parameters('background_ph_inherited.json');
    assert.equal(background(inherited).pH,13);
    assert.equal(background(inherited).background_ph_mode,'follow');
    assert.equal(background(inherited).background_ph_sources.length,2);
    assert.equal(background(inherited).ref_V_SHE,null); // only pH is copied

    await restore(path.join(output,'background_ph_conflict_fixture.orrproj'));
    await open('修改实验条件');
    await open('背景 pH：Ar-5mv-beijing.txt');
    await page.getByTestId('stAlert').filter({hasText:'共享背景 pH 冲突：'}).first().waitFor();
    await page.screenshot({path:path.join(output,'background_ph_conflict.png'),animations:'disabled'});
    await choose('背景 pH 模式','独立填写背景 pH');
    const independent=page.getByRole('spinbutton',{name:'背景独立 pH（允许 0）',exact:true});
    await independent.fill('12'); await independent.press('Tab');
    await page.getByRole('button',{name:'应用背景 pH 设置',exact:true}).click();
    await page.getByText('已应用背景 pH 设置；关联状态已重新核对。',{exact:true}).waitFor();
    await page.getByRole('spinbutton',{name:'pH *',exact:true}).fill('14');
    await page.getByRole('spinbutton',{name:'pH *',exact:true}).press('Tab');
    await page.getByText(/修改尚未应用：输入框是草稿/).waitFor();
    await page.getByRole('button',{name:'应用实验参数',exact:true}).click();
    await page.getByText('已应用实验条件到 2 个文件。',{exact:true}).waitFor();
    const manual=await parameters('background_ph_manual.json');
    assert.equal(background(manual).pH,12);
    assert.equal(background(manual).background_ph_mode,'manual');

    await navigate('导入与设置'); await open('修改实验条件');
    await open('背景 pH：Ar-5mv-beijing.txt');
    await choose('背景 pH 模式','跟随关联样品（默认）');
    await page.getByRole('button',{name:'应用背景 pH 设置',exact:true}).click();
    await page.getByText('已应用背景 pH 设置；关联状态已重新核对。',{exact:true}).waitFor();
    const following=await parameters('background_ph_following.json');
    assert.equal(background(following).pH,14);
    assert.equal(background(following).background_ph_mode,'follow');
    assert.equal(background(following).background_ph_status,'following');
    const pending=page.waitForEvent('download');
    await page.getByRole('button',{name:'保存分析项目 .orrproj',exact:true}).click();
    const saved=path.join(output,'background_ph_saved.orrproj');
    const download=await pending;
    assert.equal(download.suggestedFilename(),'ORR_Worker_analysis.orrproj');
    await download.saveAs(saved);
    await restore(saved);
    const restored=await parameters('background_ph_restored.json');
    assert.deepEqual(restored.files.map(f=>f.config),following.files.map(f=>f.config));
    await navigate('极化曲线');
    await page.getByRole('button',{name:'PNG · 300 dpi',exact:true}).waitFor();
    await page.screenshot({path:path.join(output,'background_ph_following.png'),animations:'disabled'});
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'background_ph_browser_report.json'),JSON.stringify({passed:true,
      automaticPhWithoutBackgroundApply:true,referenceNotCopied:true,sharedConflictVisible:true,
      independentValueProtected:true,followingRestored:true,projectRoundtrip:true,
      projectName:'ORR Worker',projectFilename:'ORR_Worker_analysis.orrproj',pageErrors:errors},null,2));
    console.log('Background pH browser workflow passed');
  } catch(error) {
    await page.screenshot({path:path.join(output,'background_ph_browser_failure.png'),fullPage:true});
    console.error(error); process.exitCode=1;
  } finally { await browser.close(); }
})();

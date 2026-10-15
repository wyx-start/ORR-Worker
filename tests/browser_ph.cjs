// Isolated pH/background regression; no writes to the user's local profiles.
const {chromium}=require('./browser_runtime.cjs');
const fs=require('fs');
const path=require('path');
const assert=require('assert');

(async()=>{
  const root=path.resolve(__dirname,'..');
  const output=path.join(root,'verification');
  const browser=await chromium.launch({channel:'msedge',headless:true,args:['--proxy-server=direct://','--proxy-bypass-list=*']});
  const page=await browser.newPage({viewport:{width:1500,height:1100}});
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  try {
    await page.goto(process.env.ORR_TEST_URL || 'http://127.0.0.1:8766/orr-workbench/');
    await page.getByRole('button',{name:'载入四份示例',exact:true}).click();
    await page.getByRole('heading',{name:'当前实验条件',exact:true}).waitFor();
    await page.getByRole('button',{name:'确认并应用分组与背景',exact:true}).click();
    await page.getByRole('heading',{name:'当前实验条件',exact:true}).waitFor();
    await page.getByText('修改实验条件',{exact:true}).click();
    const ph=page.getByRole('spinbutton',{name:'pH *',exact:true});
    await ph.fill('13');
    await ph.press('Tab');
    await page.getByText(/修改尚未应用：输入框是草稿/).waitFor();
    await page.getByText('常用条件：保存与复用',{exact:true}).click();
    await page.getByRole('button',{name:'保存到当前项目',exact:true}).click();
    await page.getByText('修改尚未应用：请先点击“应用实验参数”，再保存常用条件。',{exact:true}).waitFor();
    const reference=page.getByRole('combobox',{name:'参比方案 *',exact:true});
    await reference.click();
    await reference.press('ArrowDown');
    await page.getByRole('option',{name:'Ag/AgCl · 饱和 KCl · 25 °C',exact:true}).click();
    await page.getByRole('button',{name:'应用实验参数',exact:true}).click();
    await page.getByText('已应用实验条件到 2 个文件。',{exact:true}).waitFor();
    await page.getByRole('link',{name:/多转速 K–L/}).click();
    await page.getByRole('heading',{name:'多转速 K–L 分析',exact:true}).waitFor();
    await page.getByText('修改实验条件',{exact:true}).click();
    await page.getByRole('button',{name:'将关联背景加入应用范围',exact:true}).waitFor();
    assert.equal(Number(await page.getByRole('spinbutton',{name:'pH *',exact:true}).inputValue()),13);
    await page.screenshot({path:path.join(output,'ph_background_diagnosis.png'),animations:'disabled'});
    await page.getByRole('button',{name:'将关联背景加入应用范围',exact:true}).click();
    await page.getByText('本次应用范围：3 个文件。跨组和背景文件请在上方明确选入。',{exact:true}).waitFor();
    await page.getByRole('button',{name:'应用实验参数',exact:true}).click();
    await page.getByText('已应用实验条件到 3 个文件。',{exact:true}).waitFor();
    await page.getByRole('combobox',{name:'电解液参数方案 *',exact:true}).waitFor();
    await page.getByRole('link',{name:/导出与项目/}).click();
    await page.getByRole('heading',{name:'导出与项目',exact:true}).waitFor();
    const pending=page.waitForEvent('download');
    await page.getByRole('button',{name:'导出全部参数与处理记录 JSON',exact:true}).click();
    const filename=path.join(output,'ph_fixed_parameters.json');
    await (await pending).saveAs(filename);
    const data=JSON.parse(fs.readFileSync(filename,'utf8'));
    for(const file of data.files.filter(f=>f.filename.startsWith('O-') || f.filename.startsWith('Ar-'))){
      assert.equal(file.config.pH,13);
      assert.equal(file.config.ref_V_SHE,.197);
    }
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'ph_browser_report.json'),JSON.stringify({passed:true,
      draftWarning:true,staleProjectProfileBlocked:true,samplePhPreserved:true,
      explicitBackgroundInclusion:true,klAvailableAfterBackgroundApplied:true,pageErrors:errors},null,2));
    console.log('pH/background regression passed');
  } catch(error) {
    await page.screenshot({path:path.join(output,'ph_browser_failure.png'),fullPage:true});
    console.error(error);
    process.exitCode=1;
  } finally {
    await browser.close();
  }
})();

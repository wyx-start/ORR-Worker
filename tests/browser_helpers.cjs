// Helpers for a self-owned isolated service. Never reads the user's runtime state.
const {chromium}=require('./browser_runtime.cjs');
const fs=require('fs');
const path=require('path');
const assert=require('assert');
async function setup(){
  const root=path.resolve(__dirname,'..'), output=path.join(root,'verification');
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({channel:'msedge',headless:true,
    args:['--proxy-server=direct://','--proxy-bypass-list=*']});
  const page=await browser.newPage({viewport:{width:1600,height:1150}});
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const settle=async()=>{
    await page.waitForTimeout(250);
    await page.locator('[data-testid="stApp"][data-test-script-state="notRunning"]').waitFor();
    assert.equal(await page.getByTestId('stException').count(),0);
  };
  const open=async label=>{
    const summary=page.locator('summary').filter({has:page.getByText(label,{exact:true})});
    if(!await summary.evaluate(e=>e.parentElement.open)) await summary.click();
    await settle();
  };
  const choose=async(label,value)=>{
    const combo=page.getByRole('combobox',{name:label,exact:true});
    await combo.click(); await combo.press('ArrowDown');
    await page.getByRole('option',{name:value,exact:true}).click(); await settle();
  };
  const navigate=async(label,heading=label)=>{
    await page.getByRole('link',{name:new RegExp(label)}).click();
    await page.getByRole('heading',{name:heading,exact:true}).waitFor(); await settle();
  };
  const apply=async()=>{
    const button=page.getByRole('button',{name:'应用设置',exact:true});
    if(await button.count()) {await button.click(); await settle();}
  };
  const download=async(button,filename)=>{
    const pending=page.waitForEvent('download'); await button.click();
    const target=path.join(output,filename); await (await pending).saveAs(target); await settle(); return target;
  };
  const parameters=async filename=>{
    await navigate('导出与项目');
    await download(page.getByRole('button',{name:/^(下载全部完整数据 CSV|应用并导出完整数据 CSV)$/}),filename+'.csv');
    await open('更多导出：图片、完整结果、参数与结果包');
    const target=await download(page.getByRole('button',{name:'parameters.json',exact:true}),filename);
    return JSON.parse(fs.readFileSync(target,'utf8'));
  };
  const restore=async filename=>{
    await navigate('导入与设置'); await open('继续上次的分析项目');
    await page.locator('input[type="file"]').nth(1).setInputFiles(filename);
    await page.getByRole('button',{name:'载入项目（替换当前工作区）',exact:true}).click(); await settle();
  };
  const save=async filename=>{
    await navigate('导出与项目');
    return download(page.getByRole('button',{name:/^(保存分析项目|应用并保存项目)$/}),filename);
  };
  try {
    await page.goto(process.env.ORR_TEST_URL||'http://127.0.0.1:8766/orr-workbench/');
    await page.getByRole('heading',{name:'导入与设置',exact:true}).waitFor(); await settle();
  } catch (error) {
    await browser.close();
    throw error;
  }
  return {browser,page,errors,root,output,settle,open,choose,navigate,apply,download,parameters,restore,save};
}
module.exports={setup,fs,path,assert};

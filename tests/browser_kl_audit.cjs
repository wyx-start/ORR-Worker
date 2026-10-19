// Uses an isolated server and synthetic demo data; never the user's browser session.
const {chromium}=require('./browser_runtime.cjs');
const fs=require('fs');
const path=require('path');
const assert=require('assert');

(async()=>{
  const output=path.resolve(__dirname,'../verification');
  fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({channel:'msedge',headless:true,
    args:['--proxy-server=direct://','--proxy-bypass-list=*']});
  const page=await browser.newPage({viewport:{width:1600,height:1150}});
  const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const settle=async()=>{
    await page.waitForTimeout(250);
    await page.locator('[data-testid="stApp"][data-test-script-state="notRunning"]').waitFor();
  };
  try {
    await page.goto(process.env.ORR_TEST_URL || 'http://127.0.0.1:8766/orr-workbench/');
    await page.getByRole('button',{name:'载入四份示例',exact:true}).click();
    await page.getByRole('button',{name:'先查看原始电位曲线',exact:true}).click();
    await settle();
    await page.getByRole('link',{name:/多转速 K–L/}).click();
    await page.getByRole('heading',{name:'多转速 K–L 分析',exact:true}).waitFor();
    await settle();
    assert.equal(await page.getByRole('spinbutton',{name:'分析起点 / V',exact:true}).isVisible(),true);
    await page.getByText('核对实际参与计算的文件参数',{exact:true}).waitFor();
    await page.getByRole('spinbutton',{name:'氧浓度 C / mol·cm⁻³ *',exact:true}).fill('0.0000012');
    await page.getByRole('spinbutton',{name:'扩散系数 D / cm²·s⁻¹ *',exact:true}).fill('0.000019');
    await page.getByRole('spinbutton',{name:'运动黏度 ν / cm²·s⁻¹ *',exact:true}).fill('0.01');
    const confirmation=page.getByRole('checkbox',{name:'已核对：各文件属于同一电极和相同实验条件，以上物性参数适用',exact:true});
    await page.getByText('已核对：各文件属于同一电极和相同实验条件，以上物性参数适用',{exact:true}).click();
    assert.equal(await confirmation.isChecked(),true);
    await page.getByRole('button',{name:'计算 K–L',exact:true}).click();
    const warning=page.getByTestId('stAlert').filter({hasText:'不满足两路径模型检查'});
    await warning.waitFor();
    await page.getByText(/本次结果使用：C=/).waitFor();
    await warning.scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,'kl_audit_result.png'),animations:'disabled'});
    const pending=page.waitForEvent('download');
    await page.getByRole('button',{name:'单独导出 K–L 参数',exact:true}).click();
    const target=path.join(output,'kl_audit_parameters.json');
    await (await pending).saveAs(target);
    const parameters=JSON.parse(fs.readFileSync(target,'utf8'));
    assert.equal(parameters.C,1.2e-6);
    assert.equal(parameters.D,1.9e-5);
    assert.equal(parameters.nu,.01);
    assert.equal(parameters.axis,'原始');
    assert.equal(parameters.units.C,'mol/cm³');
    await page.getByText('已核对：各文件属于同一电极和相同实验条件，以上物性参数适用',{exact:true}).click();
    assert.equal(await confirmation.isChecked(),false);
    await page.getByRole('button',{name:'计算 K–L',exact:true}).click();
    await page.getByTestId('stAlert').filter({hasText:'请先核对实验条件和物性参数。'}).waitFor();
    await settle();
    assert.equal(await page.getByRole('button',{name:'单独导出 K–L 结果 CSV',exact:true}).count(),0);
    await page.getByRole('link',{name:/导出与项目/}).click();
    await page.getByRole('heading',{name:'导出与项目',exact:true}).waitFor();
    await settle();
    assert.equal(await page.getByRole('button',{name:'kl_results.csv',exact:true}).count(),0);
    assert.equal(await page.getByRole('button',{name:'kl_electron_number.png',exact:true}).count(),0);
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'kl_audit_browser_report.json'),JSON.stringify({passed:true,
      parameterReview:true,rangeVisible:true,invalidModelWarning:true,exportedUnits:true,
      failedRecalculationClearsResults:true,pageErrors:errors},null,2));
    console.log('K-L parameter audit browser workflow passed');
  } catch(error) {
    await page.screenshot({path:path.join(output,'kl_audit_failure.png'),fullPage:true});
    console.error(error); process.exitCode=1;
  } finally {await browser.close();}
})();

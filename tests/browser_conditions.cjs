// Run against an isolated local server; never changes the user's open session.
const {chromium} = require('./browser_runtime.cjs');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

(async()=>{
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, 'verification');
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({channel:'msedge', headless:true,
    args:['--proxy-server=direct://', '--proxy-bypass-list=*']});
  const page = await browser.newPage({viewport:{width:1500, height:1100}});
  const errors = [];
  page.on('pageerror', e=>errors.push(e.message));
  const select = async(label, value)=>{
    const combo = page.getByRole('combobox', {name:label, exact:true});
    await combo.click();
    await combo.press('ArrowDown');
    await page.getByRole('option', {name:value, exact:true}).click();
  };
  const navigate = async(name)=>{
    await page.getByRole('link', {name:new RegExp(name.replace(' 分析', ''))}).click();
    await page.getByRole('heading', {name, exact:true}).waitFor();
  };
  const parameters = async(filename)=>{
    await navigate('导出与项目');
    const pending = page.waitForEvent('download');
    await page.getByRole('button', {name:'导出全部参数与处理记录 JSON', exact:true}).click();
    const target = path.join(output, filename);
    await (await pending).saveAs(target);
    return JSON.parse(fs.readFileSync(target, 'utf8'));
  };
  try {
    await page.goto(process.env.ORR_TEST_URL || 'http://127.0.0.1:8766/orr-workbench/', {waitUntil:'domcontentloaded'});
    await page.getByRole('button', {name:'载入四份示例', exact:true}).click();
    await page.getByRole('heading', {name:'当前实验条件', exact:true}).waitFor();
    await page.getByText('修改实验条件', {exact:true}).click();
    await page.getByRole('spinbutton', {name:'pH *', exact:true}).waitFor();
    await page.getByRole('spinbutton', {name:'盘直径 / mm *', exact:true}).waitFor({state:'detached'});
    assert.equal(await page.getByRole('spinbutton', {name:'RRDE 收集效率 N（0–1） *', exact:true}).count(), 0);
    await select('原始电位的换算方式 *', '实测 RHE 总偏移');
    await page.getByRole('spinbutton', {name:'实测 RHE 总偏移 / V *', exact:true}).waitFor();
    assert.equal(await page.getByRole('spinbutton', {name:'pH *', exact:true}).count(), 0);
    await page.getByRole('spinbutton', {name:'实测 RHE 总偏移 / V *', exact:true}).fill('0');
    await page.getByRole('button', {name:'应用实验参数', exact:true}).click();
    await page.getByText('已应用实验条件到 2 个文件。', {exact:true}).waitFor();
    await page.getByRole('button', {name:'先查看原始电位曲线', exact:true}).click();
    await page.getByText('已切换为原始电位，当前不执行 RHE 换算。', {exact:true}).waitFor();
    await navigate('极化曲线');
    await page.getByRole('button', {name:'PNG · 300 dpi', exact:true}).waitFor();
    await select('纵坐标', '电流密度 / mA·cm⁻²');
    await page.getByText('修改实验条件', {exact:true}).click();
    const diameter = page.getByRole('spinbutton', {name:'盘直径 / mm *', exact:true});
    await diameter.waitFor();
    assert.equal(await diameter.inputValue(), '5.000000');
    await page.getByText(/盘几何面积：0\.19634954 cm²/).waitFor();
    await diameter.scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output, 'conditions_default_area.png'), animations:'disabled'});
    await diameter.fill('4');
    await diameter.press('Tab');
    await page.getByText(/盘几何面积：0\.12566371 cm²/).waitFor();
    await page.getByRole('button', {name:'应用实验参数', exact:true}).click();
    await page.getByText('已应用实验条件到 2 个文件。', {exact:true}).waitFor();
    await page.getByRole('button', {name:'PNG · 300 dpi', exact:true}).waitFor();
    const data = await parameters('conditions_parameters.json');
    const disks = data.files.filter(f=>f.filename.startsWith('O-'));
    assert.equal(disks.length, 2);
    for (const f of disks) {
      assert.equal(f.config.disk_diameter_mm, 4);
      assert(Math.abs(f.config.area_cm2-Math.PI*.04)<1e-14);
      assert.equal(f.config.rhe_offset_V, 0);
      assert.equal(f.config.pH, null);
    }
    for (const f of data.files.filter(f=>!f.filename.startsWith('O-'))) {
      assert.equal(f.config.disk_diameter_mm, 5);
      assert(Math.abs(f.config.area_cm2-Math.PI/16)<1e-14);
    }
    const pending = page.waitForEvent('download');
    await page.getByRole('button', {name:'保存分析项目 .orrproj', exact:true}).click();
    const savedProject = path.join(output, 'conditions_saved_project.orrproj');
    await (await pending).saveAs(savedProject);
    await navigate('导入与设置');
    await page.getByText('继续上次的分析项目', {exact:true}).click();
    await page.locator('input[type="file"]').nth(1).setInputFiles(savedProject);
    await page.getByRole('button', {name:'载入项目（替换当前工作区）', exact:true}).click();
    await page.getByText('已载入项目，原始数据和参数已恢复。', {exact:true}).waitFor();
    const restored = await parameters('conditions_restored_parameters.json');
    assert.deepEqual(restored.files.map(f=>f.config), data.files.map(f=>f.config));
    await navigate('RRDE 选择性');
    await page.getByText('修改实验条件', {exact:true}).click();
    await page.getByRole('spinbutton', {name:'RRDE 收集效率 N（0–1） *', exact:true}).waitFor();
    await page.getByRole('spinbutton', {name:'盘直径 / mm *', exact:true}).waitFor({state:'detached'});
    await page.getByRole('spinbutton', {name:'RRDE 收集效率 N（0–1） *', exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output, 'conditions_rrde_required.png'), animations:'disabled'});
    await navigate('多转速 K–L 分析');
    await select('电解液参数方案 *', 'O₂ 饱和 0.1 M KOH · 25 °C（文献近似值）');
    await page.getByRole('spinbutton', {name:'氧浓度 C / mol·cm⁻³ *', exact:true}).waitFor({state:'detached'});
    await page.getByText(/仅适用于 O₂ 饱和 0\.1 M KOH、25 °C/).waitFor();
    await page.screenshot({path:path.join(output, 'conditions_kl_preset.png'), fullPage:true});
    assert.equal(await page.locator('[data-testid="stException"]').count(), 0);
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'conditions_browser_report.json'), JSON.stringify({passed:true,
      conditionalRheFields:true, calibratedZeroAccepted:true, default5mm:true, fullPrecisionArea:true,
      groupScopedEdits:true, rrdeDoesNotRequireArea:true, klPresetHidesConstants:true,
      projectRoundtrip:true, pageErrors:errors}, null, 2));
    console.log('Conditions browser validation passed');
  } catch (error) {
    await page.screenshot({path:path.join(output, 'conditions_browser_failure.png'), fullPage:true});
    console.error(error);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();

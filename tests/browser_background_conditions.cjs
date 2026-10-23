// Isolated browser workflow for background condition inheritance.
// Uses only the synthetic fixture built by tests/create_background_conditions_fixture.py
// (run it in this same tree first) against a self-owned service on 127.0.0.1:8766;
// never touches the user's session on 8765 nor any real experimental file.
const {chromium} = require('./browser_runtime.cjs');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

(async()=>{
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, 'verification');
  const fixture = path.join(output, 'background_conditions_fixture.orrproj');
  if (!fs.existsSync(fixture)) {
    console.error('Missing verification/background_conditions_fixture.orrproj; run tests/create_background_conditions_fixture.py first.');
    process.exitCode = 1;
    return;
  }
  const browser = await chromium.launch({channel:'msedge', headless:true,
    args:['--proxy-server=direct://', '--proxy-bypass-list=*']});
  const page = await browser.newPage({viewport:{width:1600, height:1150}});
  const errors = [];
  page.on('pageerror', e=>errors.push(e.message));
  const settle = async()=>{
    // Server-backed controls need one round-trip before dependent widgets exist.
    await page.waitForTimeout(250);
    await page.locator('[data-testid="stApp"][data-test-script-state="notRunning"]').waitFor();
  };
  const open = async label=>{
    const summary = page.locator('summary').filter({hasText:label}).filter({has:page.getByText(label, {exact:true})});
    if (!await summary.evaluate(e=>e.parentElement.open)) await summary.click();
    await settle();
  };
  const chooseSource = async name=>{
    const combo = page.getByRole('combobox', {name:'读取设置的文件', exact:true});
    await combo.click();
    await combo.press('ArrowDown');
    await page.getByRole('option', {name:new RegExp('^'+name.replace(/[.*]/g, '\\$&'))}).click();
    await settle();
  };
  const segment = async value=>{
    await page.getByRole('radio', {name:value, exact:true}).click();
    await settle();
  };
  const navigate = async label=>{
    await page.getByRole('link', {name:new RegExp(label)}).click();
    await page.getByRole('heading', {name:label, exact:true}).waitFor();
    await settle();
  };
  const applySettings = async()=>{
    await page.getByRole('button', {name:'应用设置', exact:true}).click();
    await page.getByText(/已应用 · 配置修订/).waitFor();
    await settle();
  };
  const parameters = async filename=>{
    await navigate('导出与项目');
    let pending = page.waitForEvent('download');
    await page.getByRole('button', {name:'下载全部完整数据 CSV', exact:true}).click();
    await (await pending).saveAs(path.join(output, 'background_conditions_curves.csv'));
    await settle(); // the validated-download component rebuilds the page after handoff
    await open('更多导出：图片、完整结果、参数与结果包');
    pending = page.waitForEvent('download');
    await page.getByRole('button', {name:'parameters.json', exact:true}).click();
    const target = path.join(output, filename);
    await (await pending).saveAs(target);
    return JSON.parse(fs.readFileSync(target, 'utf8'));
  };
  const restore = async filename=>{
    await navigate('导入与设置');
    await open('继续上次的分析项目');
    await page.locator('input[type="file"]').nth(1).setInputFiles(filename);
    await page.getByRole('button', {name:'载入项目（替换当前工作区）', exact:true}).click();
    await page.getByText('已载入项目，原始数据和参数已恢复。', {exact:true}).waitFor();
    await settle();
  };
  const background = data=>data.files.find(f=>f.config.role==='背景');
  const samples = data=>data.files.filter(f=>f.config.role==='样品')
    .map(f=>f.config.pH).sort((a,b)=>a-b);
  try {
    await page.goto(process.env.ORR_TEST_URL || 'http://127.0.0.1:8766/orr-workbench/');
    await page.getByRole('heading', {name:'导入与设置', exact:true}).waitFor();
    await restore(fixture);

    // 1. Restored conflict: follow fields stay read-only, adopt is gated off.
    await open('修改实验条件');
    await chooseSource('Ar-background.txt');
    await page.getByText(/状态：条件冲突/).first().waitFor();
    assert(await page.getByRole('spinbutton', {name:'pH *', exact:true}).isDisabled());
    assert(await page.getByRole('button', {name:'用当前有效条件建立独立记录', exact:true}).isDisabled());
    await page.screenshot({path:path.join(output, 'background_conditions_conflict.png'), fullPage:true});

    // 2. Explicit switch to independent, edit the retained cache, apply.
    await page.getByRole('button', {name:'切到独立设置', exact:true}).click();
    await settle();
    const ph = page.getByRole('spinbutton', {name:'pH *', exact:true});
    assert(!(await ph.isDisabled()));
    assert.equal(await ph.inputValue(), '11.000'); // retained independent cache, not an effective copy
    await ph.fill('10');
    await ph.press('Tab');
    await settle();
    await applySettings();
    const independent = await parameters('background_conditions_independent.json');
    const storedIndependent = background(independent).stored_config;
    assert.equal(storedIndependent.background_conditions_mode, 'independent');
    assert.equal(storedIndependent.pH, 10);
    assert.equal(storedIndependent.temperature_C, 20);
    assert.equal(storedIndependent.ref_V_SHE, .110);
    assert(!('background_conditions' in storedIndependent)); // canonical record, no projection
    assert.deepEqual(samples(independent), [12, 13]);

    // 3. Panel switch back to follow: the shared-background conflict returns.
    await navigate('导入与设置');
    await segment('扫描与背景');
    await open('背景实验条件 · Ar-background.txt');
    await page.getByRole('button', {name:'改为跟随关联样品', exact:true}).click();
    await settle();
    await applySettings();
    await open('背景实验条件 · Ar-background.txt');
    await page.getByText(/状态：条件冲突/).first().waitFor();
    await page.screenshot({path:path.join(output, 'background_conditions_follow_conflict.png'), fullPage:true});

    // 4. Mode-only switch back to independent: the stored cache survives unchanged.
    await segment('实验条件');
    await open('修改实验条件');
    await chooseSource('Ar-background.txt');
    await page.getByRole('button', {name:'切到独立设置', exact:true}).click();
    await settle();
    await applySettings();
    const restoredCache = await parameters('background_conditions_cache.json');
    assert.equal(background(restoredCache).stored_config.background_conditions_mode, 'independent');
    assert.equal(background(restoredCache).stored_config.pH, 10); // never overwritten by effective values

    // 5. Project roundtrip keeps canonical records identical in parameters.
    await navigate('导出与项目');
    const pendingProject = page.waitForEvent('download');
    await page.getByRole('button', {name:'保存分析项目', exact:true}).click();
    const projectDownload = await pendingProject;
    assert.equal(projectDownload.suggestedFilename(), 'ORR_Worker_analysis.orrproj');
    const saved = path.join(output, 'background_conditions_saved.orrproj');
    await projectDownload.saveAs(saved);
    await restore(saved);
    const roundtrip = await parameters('background_conditions_roundtrip.json');
    assert.deepEqual(roundtrip.files.map(f=>f.stored_config), restoredCache.files.map(f=>f.stored_config));
    assert.deepEqual(roundtrip.files.map(f=>f.config), restoredCache.files.map(f=>f.config));

    assert.equal(await page.locator('[data-testid="stException"]').count(), 0);
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'background_conditions_browser_report.json'), JSON.stringify({passed:true,
      conflictBlocksEditing:true, adoptGatedOffOnConflict:true, retainedCacheSeedsEditor:true,
      canonicalRecordHasNoProjection:true, followSwitchKeepsStoredCache:true,
      projectRoundtrip:true, pageErrors:errors}, null, 2));
    console.log('Background conditions browser workflow passed');
  } catch (error) {
    await page.screenshot({path:path.join(output, 'background_conditions_browser_failure.png'), fullPage:true});
    console.error(error);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();

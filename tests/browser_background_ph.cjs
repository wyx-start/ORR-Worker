const {setup,fs,path,assert}=require('./browser_helpers.cjs');
(async()=>{
  const h=await setup(), {page,output,open,choose,navigate,apply,settle,parameters,restore,save}=h;
  const background=data=>data.files.find(f=>f.stored_config.role==='背景');
  try {
    await restore(path.join(output,'background_ph_conflict_fixture.orrproj'));
    await page.getByRole('radio',{name:'扫描与背景',exact:true}).click(); await settle();
    await open('背景 pH · Ar-background.txt');
    assert((await page.getByText(/共享背景 pH 冲突/).count())>0);
    await choose('背景 pH 模式','独立填写');
    const ph=page.getByRole('spinbutton',{name:'背景独立 pH（允许 0）',exact:true});
    await ph.fill('10'); await ph.press('Tab'); await settle(); await apply();
    const independent=await parameters('background_ph_manual.json');
    assert.equal(background(independent).stored_config.pH,10);
    assert.equal(background(independent).stored_config.background_ph_mode,'manual');
    await navigate('导入与设置');
    await page.getByRole('radio',{name:'实验条件',exact:true}).click(); await settle();
    await open('修改实验条件'); await choose('分析与导出的电位坐标','RHE'); await settle();
    const samplePh=page.getByRole('spinbutton',{name:'pH *',exact:true});
    await samplePh.fill('14'); await samplePh.press('Tab'); await settle(); await apply();
    await page.getByRole('radio',{name:'扫描与背景',exact:true}).click(); await settle();
    await open('背景 pH · Ar-background.txt'); await choose('背景 pH 模式','跟随关联样品'); await apply();
    const following=await parameters('background_ph_following.json');
    const bg=background(following);
    assert.equal(bg.config.pH,14); assert.equal(bg.stored_config.pH,10);
    assert.equal(bg.stored_config.background_conditions_mode,'legacy_ph');
    assert.equal(bg.stored_config.background_ph_mode,'follow');
    assert.equal(bg.stored_config.ref_V_SHE,.197);
    const saved=await save('background_ph_saved.orrproj'); await restore(saved);
    const roundtrip=await parameters('background_ph_restored.json');
    assert.deepEqual(roundtrip.files.map(f=>f.stored_config),following.files.map(f=>f.stored_config));
    assert.deepEqual(h.errors,[]);
    await page.screenshot({path:path.join(output,'background_ph_following.png')});
    fs.writeFileSync(path.join(output,'background_ph_browser_report.json'),JSON.stringify({passed:true,legacyConflictVisible:true,independentValueProtected:true,followingRestored:true,legacyReferenceIndependent:true,projectRoundtrip:true,pageErrors:h.errors},null,2));
    console.log('Legacy background pH browser validation passed');
  }catch(error){await page.screenshot({path:path.join(output,'background_ph_browser_failure.png')});throw error;}
  finally{await h.browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
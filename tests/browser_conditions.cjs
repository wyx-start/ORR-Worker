const {setup,fs,path,assert}=require('./browser_helpers.cjs');
(async()=>{
  const h=await setup(), {page,output,open,choose,navigate,apply,settle,parameters,restore,save}=h;
  try {
    await page.getByRole('button',{name:'载入四份示例',exact:true}).click(); await settle();
    await open('修改实验条件');
    assert.equal(await page.getByRole('spinbutton',{name:'pH *',exact:true}).inputValue(),'13.000');
    assert.equal(await page.getByText('转速识别依据与需要核对的记录',{exact:true}).count(),0);
    const initial=await parameters('conditions_import_defaults.json');
    for(const f of initial.files){
      assert.equal(f.stored_config.pH,13);assert.equal(f.stored_config.reference,'SCE');
      assert.equal(f.stored_config.filling,'饱和 KCl');assert.equal(f.stored_config.ref_V_SHE,.241);
    }
    await navigate('导入与设置');await open('修改实验条件');
    assert.equal(await page.getByRole('spinbutton',{name:'RRDE 收集效率 N（0–1） *',exact:true}).count(),0);
    await choose('原始电位的换算方式 *','实测 RHE 总偏移');
    const offset=page.getByRole('spinbutton',{name:'实测 RHE 总偏移 / V *',exact:true});
    await offset.fill('0'); await offset.press('Tab'); await settle(); await apply();
    await choose('分析与导出的电位坐标','原始'); await apply();
    await navigate('极化曲线'); await choose('纵坐标','电流密度 / mA·cm⁻²');
    await open('修改实验条件');
    const diameter=page.getByRole('spinbutton',{name:'盘直径 / mm *',exact:true});
    assert.equal(await diameter.inputValue(),'5.000000');
    await diameter.fill('4'); await diameter.press('Tab'); await settle(); await apply();
    const data=await parameters('conditions_parameters.json');
    const disks=data.files.filter(f=>f.filename.startsWith('O-'));
    assert.equal(disks.length,2);
    for(const f of disks){assert.equal(f.stored_config.disk_diameter_mm,4);assert(Math.abs(f.stored_config.area_cm2-Math.PI*.04)<1e-14);assert.equal(f.stored_config.rhe_offset_V,0);}
    const saved=await save('conditions_saved_project.orrproj'); await restore(saved);
    const roundtrip=await parameters('conditions_restored_parameters.json');
    assert.deepEqual(roundtrip.files.map(f=>f.stored_config),data.files.map(f=>f.stored_config));
    await navigate('RRDE 选择性'); await open('修改实验条件');
    assert.equal(await page.getByRole('spinbutton',{name:'RRDE 收集效率 N（0–1） *',exact:true}).inputValue(),'0.36900');
    assert.equal(await page.getByRole('spinbutton',{name:'盘直径 / mm *',exact:true}).count(),0);
    await page.screenshot({path:path.join(output,'conditions_rrde_required.png')});
    await navigate('多转速 K–L','多转速 K–L 分析');
    await choose('电解液参数方案 *','O₂ 饱和 0.1 M KOH · 25 °C（文献近似值）');
    assert.equal(await page.getByRole('spinbutton',{name:'氧浓度 C / mol·cm⁻³ *',exact:true}).count(),0);
    assert.deepEqual(h.errors,[]);
    fs.writeFileSync(path.join(output,'conditions_browser_report.json'),JSON.stringify({passed:true,defaultSce:true,defaultPh13:true,rpmDetailsRemoved:true,conditionalRheFields:true,calibratedZeroAccepted:true,default5mm:true,fullPrecisionArea:true,groupScopedEdits:true,rrdeDefault369:true,klPresetHidesConstants:true,projectRoundtrip:true,pageErrors:h.errors},null,2));
    console.log('Conditions browser validation passed');
  }catch(error){await page.screenshot({path:path.join(output,'conditions_browser_failure.png')});throw error;}
  finally{await h.browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

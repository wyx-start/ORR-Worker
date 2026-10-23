const {setup,fs,path,assert}=require('./browser_helpers.cjs');
(async()=>{
  const h=await setup(), {page,output,open,choose,navigate,apply,settle,parameters,restore,save}=h;
  const editRpm=async(row,value)=>{
    const grid=page.getByTestId('stDataFrame').first().locator('canvas').first();
    await grid.scrollIntoViewIfNeeded();
    await page.getByTestId('stDataFrame').first().locator('.dvn-scroller').click({position:{x:30,y:52}});
    await grid.focus();
    await page.keyboard.press('Control+Home');
    for(let i=0;i<4;i++) await page.keyboard.press('ArrowRight');
    for(let i=0;i<row;i++) await page.keyboard.press('ArrowDown');
    await page.waitForTimeout(100);
    await page.keyboard.press('Enter');
    const input=page.locator('.gdg-input');
    await input.waitFor({state:'visible'});
    await input.fill(String(value)); await input.press('Enter'); await settle();
  };
  try {
    await restore(path.join(output,'blank_rpm_controls.orrproj'));
    await editRpm(0,1600);
    await page.screenshot({path:path.join(output,'blank_rpm_first_edit.png')});
    await editRpm(1,900);
    await page.screenshot({path:path.join(output,'blank_rpm_second_edit.png')});
    await apply();
    const blank=await parameters('blank_rpm_manual.json');
    assert.deepEqual(blank.files.map(f=>f.stored_config.rpm),[1600,900]);
    assert(blank.files.every(f=>f.stored_config.rpm_source==='manual'));
    await restore(path.join(output,'batch_controls.orrproj'));
    await editRpm(0,1600); await editRpm(1,900); await editRpm(2,1200); await apply();
    await page.getByRole('radio',{name:'扫描与背景',exact:true}).click(); await settle();
    await page.getByRole('radio',{name:'全部样品',exact:true}).click(); await settle();
    await choose('批量扫描方向','递减');
    await choose('批量自动选择规则','B · 最后完整单向支线');
    await choose('批量背景操作','盘环配对背景');
    const combo=page.getByRole('combobox',{name:'批量盘背景',exact:true});
    await combo.click(); await combo.press('ArrowDown');
    await page.getByRole('option',{name:/^Ar-background.txt/}).click(); await settle();
    await page.getByRole('button',{name:'加入本批草稿',exact:true}).click(); await settle();
    await page.getByText(/应用自动规则将清除 9 个文件/).waitFor();
    await page.screenshot({path:path.join(output,'batch_scan_background_preview.png')});
    await apply();
    const applied=await parameters('batch_controls_applied.json');
    const samples=applied.files.filter(f=>f.stored_config.role!=='背景');
    const background=applied.files.find(f=>f.stored_config.role==='背景');
    assert.equal(samples.length,9);
    for(const f of samples){
      const c=f.stored_config;
      assert.equal(c.mode,'B');assert.equal(c.direction,'递减');assert.equal(c.manual_segment,null);
      assert.equal(c.background_mode,'paired');assert.equal(c.background_disk,background.id);assert.equal(c.background_ring,background.id);
      assert.equal(f.selected_segment.segment,2);
    }
    assert.deepEqual(samples.slice(0,3).map(f=>f.stored_config.rpm),[1600,900,1200]);
    assert.equal(samples[2].stored_config.collection_efficiency,.4);
    assert.equal(background.stored_config.manual_segment,2);assert.equal(background.stored_config.pH,11);
    assert.equal(background.config.pH,13);
    assert.equal(applied.settings.rrde.floor_A,8e-9);
    await navigate('RRDE 选择性');
    assert.equal(await page.getByText('核对参与计算的盘环条件',{exact:true}).count(),0);
    assert.equal(await page.getByText('高级：低电流阈值',{exact:true}).count(),0);
    assert.equal(await page.getByText('补充实验记录（选填）',{exact:true}).count(),0);
    assert.equal(await page.getByText('常用条件：保存与复用',{exact:true}).count(),0);
    await page.getByRole('button',{name:'计算 RRDE',exact:true}).click(); await settle();
    await page.getByRole('button',{name:'下载绘图 CSV',exact:true}).waitFor();
    await page.screenshot({path:path.join(output,'rrde_simplified_results.png')});
    const saved=await save('batch_controls_saved.orrproj');await restore(saved);
    const restored=await parameters('batch_controls_restored.json');
    assert.deepEqual(restored.files.map(f=>f.stored_config),applied.files.map(f=>f.stored_config));
    assert.deepEqual(h.errors,[]);
    fs.writeFileSync(path.join(output,'batch_controls_browser_report.json'),JSON.stringify({passed:true,
      blankColumnManualEditing:true,conflictAndRecognizedManualEditing:true,tenFiles:true,
      atomicBatchScanAndPairing:true,ownLastCompleteSegment:true,backgroundCachePreserved:true,
      manualRpmAndNPreserved:true,rrdeCalculation:true,legacyThresholdPreserved:true,
      removedFourSections:true,projectRoundtrip:true,pageErrors:h.errors},null,2));
    console.log('Batch/blank rpm/RRDE browser workflow passed');
  }catch(error){await page.screenshot({path:path.join(output,'batch_controls_browser_failure.png')});throw error;}
  finally{await h.browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

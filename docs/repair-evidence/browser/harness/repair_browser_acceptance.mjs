import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
let input='';
for await (const chunk of process.stdin) input+=chunk;
const config=JSON.parse(input);
const secretValues=Object.values(config.users).map(user=>user.password);
const redact=value=>secretValues.reduce((text,secret)=>text.split(secret).join('[redacted synthetic credential]'),String(value));
let phase='setup';
input='';
const require=createRequire(path.join(config.work,'package.json'));
const { chromium, expect }=require('@playwright/test');
const output=path.join(config.runRoot,'browser');
await fs.mkdir(output,{recursive:true});
const result={checks:[],screenshots:[],network:[],pageErrors:[],consoleErrors:[],blockedRequests:[],viewports:[],loginLandings:[],pilotRowBasedControls:'NOT_VERIFIED: preserved existing ready flow requires forbidden row/Parquet resolution'};
const check=(name,pass,details={})=>result.checks.push({name,pass:Boolean(pass),...details});
const steps=['modellab','evaluation','refinement','calibration','simulation','champion','registry'];
const titleByStep={modellab:'Model Development Laboratory',evaluation:'Candidate Evaluation',refinement:'Model Refinement',calibration:'Calibration',simulation:'Simulation',champion:'Champion',registry:'Registry'};
const url=(project,step='modellab')=>`${config.origin}/workflows/mlb?projectId=${project}&stage=3&stage3Step=${step}`;
const browser=await chromium.launch({headless:true,args:['--disable-background-networking','--disable-component-update','--disable-domain-reliability','--disable-sync','--no-first-run']});
async function context(viewport){
  const ctx=await browser.newContext({viewport,serviceWorkers:'block',acceptDownloads:false});
  await ctx.route('**/*',async route=>{
    const request=route.request();
    const u=new URL(request.url());
    if(u.origin!==config.origin && !['data:','blob:'].includes(u.protocol)){
      result.blockedRequests.push({kind:'outside_origin',resourceType:request.resourceType()});
      return route.abort('blockedbyclient');
    }
    const metadataAutosave=request.method()==='PUT'&&['/api/projects/asp-mtlozhdx','/api/projects/asp-mtddc6pw','/api/projects/asp-mtlozhdx/workflow-state','/api/projects/asp-mtddc6pw/workflow-state'].includes(u.pathname);
    if(u.origin===config.origin && !['GET','HEAD','OPTIONS'].includes(request.method()) && !['/api/auth/login','/api/auth/logout'].includes(u.pathname) && !metadataAutosave){
      result.blockedRequests.push({kind:'application_mutation',method:request.method(),path:u.pathname});
      return route.abort('blockedbyclient');
    }
    return route.continue();
  });
  ctx.on('page',page=>{
    page.setDefaultTimeout(10000);
    page.setDefaultNavigationTimeout(30000);
    page.on('pageerror',error=>result.pageErrors.push({name:error.name,message:redact(error.message)}));
    page.on('console',message=>{if(message.type()==='error')result.consoleErrors.push({phase,message:redact(message.text()),location:message.location().url?.split('?')[0]});});
    page.on('response',response=>{
      const u=new URL(response.url());
      if(u.origin===config.origin && u.pathname.startsWith('/api/')) result.network.push({method:response.request().method(),path:u.pathname,status:response.status()});
    });
  });
  return ctx;
}
async function login(page,label,returnPath='/dashboard'){
  phase='authentication';
  await page.goto(`${config.origin}/login?returnTo=${encodeURIComponent(returnPath)}`,{waitUntil:'domcontentloaded'});
  await page.getByLabel('Email',{exact:true}).fill(config.users[label].email);
  await page.getByLabel('Password',{exact:true}).fill(config.users[label].password);
  const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/auth/login');
  await page.getByRole('button',{name:'Sign In',exact:true}).click();
  check(`real_cookie_login_${label}`,(await response).status()===200);
  await page.waitForURL(u=>!u.pathname.includes('/login'),{timeout:30000});
  await settle(page);
  const landing=new URL(page.url());
  const actual=landing.pathname+landing.search;
  result.loginLandings.push({user:label,requested:returnPath,actual});
  check(`real_cookie_login_${label}_preserves_deep_link`,actual===returnPath,{requested:returnPath,actual});
}
async function screenshot(page,name){
  const file=path.join(output,name+'.png');
  await page.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
  await page.waitForTimeout(120);
  await page.screenshot({path:file,fullPage:true});
  result.screenshots.push(file);
}
async function settle(page){
  await page.waitForLoadState('networkidle',{timeout:12000}).catch(()=>{});
  await page.waitForTimeout(400);
}
async function layout(page){
  return page.evaluate(()=>({viewportWidth:innerWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,focusMode:document.querySelector('[data-testid="stage3-focus-workspace"]')?.getAttribute('data-focus-mode'),headerHeight:document.querySelector('[data-testid="stage3-compact-header"]')?.getBoundingClientRect().height,canvasWidth:document.querySelector('[data-testid="stage3-analytical-canvas"]')?.getBoundingClientRect().width}));
}
try{
  for(const viewport of [{width:1920,height:1080},{width:1024,height:768},{width:390,height:844}]){
    const ctx=await context(viewport);
    const page=await ctx.newPage();
    const label=`${viewport.width}x${viewport.height}`;
    await login(page,'admin',`/workflows/mlb?projectId=asp-mtlozhdx&stage=3&stage3Step=modellab`);
    phase='entitled_navigation';
    for(const project of ['asp-mtlozhdx']){
      for(const step of steps){
        await page.goto(url(project,step),{waitUntil:'domcontentloaded'});
        await settle(page);
        const text=await page.locator('body').innerText();
        if(!(await page.getByTestId('project-workflow-blocked').count())){
          await screenshot(page,`${label}_${project}_${step}_blocked_gate_missing`);
          await fs.writeFile(path.join(output,`${label}_${project}_${step}_blocked_gate_missing.txt`),redact(text));
          throw new Error('Expected project prerequisite gate missing; sanitized page evidence retained.');
        }
        const state={project,step,viewport:label,layout:await layout(page)};
        check(`${label}_${project}_${step}_project_binding`,text.includes(project),state);
        check(`${label}_${project}_${step}_title`,text.includes(titleByStep[step]));
        check(`${label}_${project}_${step}_no_document_horizontal_overflow`,state.layout.documentWidth<=viewport.width+1);
        if(project==='asp-mtlozhdx'){
          check(`${label}_${step}_correct_project_name`,text.includes('MLB 2026 Current-Data Challenger v2')&&text.includes('Deliberate Development'));
          check(`${label}_${step}_draft_preserved`,text.includes('DRAFT'));
          check(`${label}_${step}_population`,text.includes('683,662')&&text.includes('14,067'));
          check(`${label}_${step}_prior_authenticated`,text.includes('Authenticated')&&text.includes('V1 priors: 11')&&text.includes('V2 priors: 10')&&text.includes('Retired features: 3')&&text.includes('Folds: 5'));
          check(`${label}_${step}_disabled_action_has_reason`,await page.getByRole('button',{name:'Queue model development for this project'}).isDisabled().catch(()=>false));
          const queue=page.getByRole('button',{name:'Queue model development for this project'});
          const queueBox=await queue.boundingBox().catch(()=>null);
          check(`${label}_${step}_primary_action_not_horizontally_clipped`,queueBox && queueBox.x>=0 && queueBox.x+queueBox.width<=viewport.width+1);
          const describedBy=await queue.getAttribute('aria-describedby').catch(()=>null);
          check(`${label}_${step}_disabled_reason_visible`,Boolean(describedBy)&&await page.locator(`[id="${describedBy}"]`).isVisible().catch(()=>false));
          const disclosure=page.getByText('Verified authority identifiers',{exact:true});
          if(await disclosure.count()){
            await disclosure.click();
            const expanded=await page.locator('body').innerText();
            check(`${label}_${step}_exact_bundle_visible`,expanded.includes('9d9cfaf34f87be67f7d3ab2b8b024d83a6fc5e8abe0dde8de7be0866f1b8366e'));
            check(`${label}_${step}_exact_final_development_visible`,expanded.includes('5ae0f9f560f83935e1f89440657ac4080afc33ac3318c3c2c8e50656a9eee526'));
          }
          check(`${label}_${step}_no_pilot_candidate_leak`,!text.includes('stage3-candidate-')&&!text.includes('asp-mtddc6pw'));
        }else{
          check(`${label}_${step}_historical_view`,/historical/i.test(text));
          check(`${label}_${step}_pilot_population`,text.includes('683,662')&&text.includes('14,067'));
          check(`${label}_${step}_no_challenger_authority_leak`,!text.includes('asp-mtlozhdx'));
        }
        await screenshot(page,`${label}_${project}_${step}`);
        if(config.explore){
          await fs.writeFile(path.join(output,`${label}_${project}_${step}.txt`),text);
          break;
        }
      }
      if(config.explore)break;
    }
    if(!config.explore){
      await page.goto(url('asp-mtlozhdx','modellab'),{waitUntil:'domcontentloaded'});
      await settle(page);
      for(const step of steps.slice(1)){
        const previousStep=steps[steps.indexOf(step)-1];
        const navigationMode=['calibration','simulation','champion'].includes(previousStep)?'workflow_drawer':'next_footer';
        if(navigationMode==='workflow_drawer'){
          await page.getByRole('button',{name:'Open workflow navigator',exact:true}).click();
          await page.getByRole('navigation',{name:'Stage 3 modeling steps',exact:true}).getByRole('button',{name:new RegExp('^[0-9]+ · '+titleByStep[step])}).click();
        }else{
          await page.getByTestId('stage3-analytical-canvas').getByRole('button',{name:new RegExp('^(?:'+titleByStep[step]+'.*|Next)$')}).click();
        }
        await settle(page);
        const current=new URL(page.url());
        const body=await page.locator('body').innerText();
        check(`${label}_navigation_click_${step}_preserves_project_and_step`,current.searchParams.get('projectId')==='asp-mtlozhdx'&&current.searchParams.get('stage3Step')===step&&body.includes(titleByStep[step])&&body.includes('DRAFT'),{navigationMode});
      }
      await page.getByTestId('stage3-analytical-canvas').getByRole('button',{name:/^(?:Champion.*|Previous)$/}).click();
      await settle(page);
      check(`${label}_previous_click_returns_to_champion`,new URL(page.url()).searchParams.get('stage3Step')==='champion'&&(await page.locator('body').innerText()).includes('asp-mtlozhdx'));
    }
    await page.goto(url('asp-mtlozhdx','evaluation'),{waitUntil:'domcontentloaded'});
    await settle(page);
    await page.reload({waitUntil:'domcontentloaded'});
    await settle(page);
    check(`${label}_refresh_preserves_project`,(await page.locator('body').innerText()).includes('asp-mtlozhdx'));
    await page.goto(url('asp-mtlozhdx','refinement'),{waitUntil:'domcontentloaded'});
    await page.goBack({waitUntil:'domcontentloaded'});
    await settle(page);
    check(`${label}_back_preserves_project`,(await page.locator('body').innerText()).includes('asp-mtlozhdx')&&new URL(page.url()).searchParams.get('stage3Step')==='evaluation');
    await page.goForward({waitUntil:'domcontentloaded'});
    await settle(page);
    check(`${label}_forward_preserves_project`,(await page.locator('body').innerText()).includes('asp-mtlozhdx')&&new URL(page.url()).searchParams.get('stage3Step')==='refinement');
    const workflowButton=page.getByRole('button',{name:'Open workflow navigator',exact:true});
    if(await workflowButton.count()){
      await workflowButton.first().click();
      await screenshot(page,`${label}_navigator`);
      await page.keyboard.press('Escape');
      check(`${label}_navigator_escape_restores_focus`,await expect(workflowButton.first()).toBeFocused({timeout:3000}).then(()=>true).catch(()=>false));
    }
    const authorityButton=page.getByRole('button',{name:/^(Authority.*Audit|Audit)$/});
    if(await authorityButton.count()){
      await authorityButton.first().click();
      await screenshot(page,`${label}_authority`);
      await page.keyboard.press('Escape');
      check(`${label}_authority_escape_restores_focus`,await expect(authorityButton.first()).toBeFocused({timeout:3000}).then(()=>true).catch(()=>false));
    }
    result.viewports.push({viewport,finalLayout:await layout(page)});
    await ctx.close();
    if(config.explore)break;
  }
  if(!config.explore){
    const ctx=await context({width:1024,height:768});
    const page=await ctx.newPage();
    await login(page,'alpha','/workflows/mlb?projectId=asp-mtlozhdx&stage=3&stage3Step=modellab');
    await settle(page);
    check('ordinary_alpha_entitled_challenger',(await page.locator('body').innerText()).includes('DRAFT'));
    phase='intentional_denial_checks';
    const simultaneous=await context({width:1024,height:768});
    const betaLogin=await simultaneous.request.post(`${config.origin}/api/auth/login`,{data:{email:config.users.beta.email,password:config.users.beta.password}});
    check('simultaneous_beta_real_login',betaLogin.status()===200);
    const [alphaResponse,betaResponse]=await Promise.all([
      ctx.request.get(`${config.origin}/api/projects/asp-mtlozhdx/sports/stage3-model-laboratory/summary`),
      simultaneous.request.get(`${config.origin}/api/projects/asp-mtlozhdx/sports/stage3-model-laboratory/summary`),
    ]);
    check('simultaneous_cookie_sessions_remain_separate',alphaResponse.status()===200&&[403,404].includes(betaResponse.status()));
    await simultaneous.close();
    const api=await ctx.request.get(`${config.origin}/api/projects/asp-mtddc6pw/sports/stage3-model-laboratory/summary`);
    check('ordinary_alpha_nonmember_pilot_denied',[403,404].includes(api.status()));
    await page.goto(url('asp-mtddc6pw'),{waitUntil:'domcontentloaded'});
    await settle(page);
    const denied=await page.locator('body').innerText();
    check('nonmember_pilot_browser_no_candidates',!denied.includes('stage3-candidate-')&&!denied.includes('Historical run'));
    await screenshot(page,'ordinary_alpha_denied_pilot');
    await ctx.request.post(`${config.origin}/api/auth/logout`);
    await login(page,'beta','/workflows/mlb?projectId=asp-mtlozhdx&stage=3&stage3Step=evaluation');
    await settle(page);
    const beta=await page.locator('body').innerText();
    check('same_browser_beta_cannot_see_alpha_challenger',!beta.includes('V1 priors:')&&!beta.includes('stage3-candidate-')&&!beta.includes('683,662'));
    const wrong=await ctx.request.get(`${config.origin}/api/projects/asp-mtlozhdx/sports/stage3-model-laboratory/summary`);
    check('ordinary_beta_challenger_denied',[403,404].includes(wrong.status()));
    await screenshot(page,'ordinary_beta_denied_challenger');
    await ctx.close();
  }
}catch(error){
  result.failure={name:error.name,message:redact(error.message).slice(0,700)};
}finally{
  await browser.close();
  for(const entry of Object.values(config.users)) entry.password='';
  check('no_eda_or_row_route_requested',!result.network.some(x=>/stage3-eda|preview|class-distribution/.test(x.path)));
  check('no_placeholder_project_request',!result.network.some(x=>x.path.includes('/projects/mlb-gen2/')));
  check('no_external_application_requests',!result.blockedRequests.some(x=>x.kind==='outside_origin'));
  check('no_page_script_errors',result.pageErrors.length===0);
  check('no_console_errors_during_entitled_navigation',!result.consoleErrors.some(item=>item.phase==='entitled_navigation'));
  result.summary={checks:result.checks.length,passed:result.checks.filter(x=>x.pass).length,failed:result.checks.filter(x=>!x.pass).length,exception:Boolean(result.failure),exploratory:config.explore};
  await fs.writeFile(path.join(output,'acceptance.json'),redact(JSON.stringify(result,null,2)));
  process.stdout.write(JSON.stringify(result.summary));
  if(result.failure || result.summary.failed)process.exitCode=1;
}

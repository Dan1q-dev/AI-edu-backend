'use strict';
// No operational .env files, databases or provider credentials enter the test copy.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto');
const {spawnSync}=require('node:child_process');
function argument(name,fallback){const i=process.argv.indexOf(name);return i<0?fallback:process.argv[i+1];}
const source=path.resolve(argument('--source',path.join(__dirname,'../services/ai-tutor')));
const dependencies=path.resolve(argument('--node-modules',path.join(source,'node_modules')));
const outputParent=path.resolve(argument('--out',path.join(os.tmpdir(),'aiedu-gateway-contract')));
const gatewayPort=Number(argument('--gateway-port','3401')),providerPort=Number(argument('--provider-port','9401'));
for(const p of [gatewayPort,providerPort])if(!Number.isInteger(p)||p<1024||p>65534)throw new Error('Ports must be integers between 1024 and 65534');
if(!fs.existsSync(path.join(dependencies,'next/dist/bin/next')))throw new Error('Install gateway dependencies with npm ci or provide --node-modules');
if(Number(process.versions.node.split('.')[0])<24)throw new Error('Node.js 24 or later is required for node:sqlite');
fs.mkdirSync(outputParent,{recursive:true});
const root=fs.mkdtempSync(path.join(outputParent,'run-')),copy=path.join(root,'gateway-source');
fs.mkdirSync(copy);fs.mkdirSync(path.join(root,'tmp'));
const files=[];
function copyFile(relative){const from=path.join(source,relative),to=path.join(copy,relative);fs.mkdirSync(path.dirname(to),{recursive:true});fs.copyFileSync(from,to);files.push({path:relative.split(path.sep).join('/'),sha256:crypto.createHash('sha256').update(fs.readFileSync(from)).digest('hex')});}
function walk(directory){if(!fs.existsSync(path.join(source,directory)))return;for(const e of fs.readdirSync(path.join(source,directory),{withFileTypes:true})){const rel=path.join(directory,e.name);if(e.isDirectory())walk(rel);else if(e.isFile()&&/\.(?:ts|tsx|js|css|prisma)$/.test(e.name))copyFile(rel);}}
for(const d of ['app','lib','prisma','types'])walk(d);
for(const f of ['package.json','package-lock.json','next.config.js','tsconfig.json','next-env.d.ts','middleware.ts','postcss.config.js','tailwind.config.js'])if(fs.existsSync(path.join(source,f)))copyFile(f);
fs.symlinkSync(dependencies,path.join(copy,'node_modules'),process.platform==='win32'?'junction':'dir');
fs.writeFileSync(path.join(root,'source-manifest.json'),JSON.stringify({source,copy,files,environment_files_copied:false,production_databases_copied:false,implementation_modified:false},null,2));
function run(script,gateway,provider){const r=spawnSync(process.execPath,[path.join(__dirname,script)],{env:{...process.env,GATEWAY_TEST_WORKDIR:root,GATEWAY_TEST_SOURCE:copy,LOCAL_GATEWAY_TEST_PORT:String(gateway),LOCAL_PROVIDER_TEST_PORT:String(provider)},stdio:'inherit',windowsHide:true});if(r.error)throw r.error;if(r.status!==0)throw new Error(script+' exited with '+r.status);}
run('gateway-fault-scenarios.cjs',gatewayPort,providerPort);
run('gateway-policy-scope.cjs',gatewayPort+1,providerPort+1);
const latest=JSON.parse(fs.readFileSync(path.join(root,'latest-run.json'),'utf8'));
const fault=JSON.parse(fs.readFileSync(path.join(latest.run_directory,'results.json'),'utf8'));
const policy=JSON.parse(fs.readFileSync(path.join(root,'contract-checks/results.json'),'utf8'));
const summary={date_utc:new Date().toISOString(),source,output_directory:root,scope:'Actual isolated Next chat HTTP, deterministic loopback provider, disposable SQLite. No live-provider quality or deployment claim. Missing history/telemetry endpoints are not added; history HTTP authorization is not applicable.',fault_criteria:{tests:fault.tests,passed:fault.passed,failed:fault.failed,not_applicable:fault.not_applicable||0},policy_scope_criteria:{tests:policy.tests,passed:policy.passed,failed:policy.failed},source_hashes_match:fault.implementation_files_hash_match_tested_revision,source_unchanged:fault.original_project_files_unchanged,passed:fault.passed+policy.passed,failed:fault.failed+policy.failed};
fs.writeFileSync(path.join(root,'gateway-contract-summary.json'),JSON.stringify(summary,null,2));
console.log(JSON.stringify(summary,null,2));
if(summary.failed||!summary.source_hashes_match||!summary.source_unchanged)process.exitCode=1;

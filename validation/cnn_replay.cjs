// Replays the frozen browser model; does not train or claim a PyTorch export.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto');
const {pathToFileURL}=require('node:url');
const assert=require('node:assert/strict');
const source=require('./load-source.cjs');
const JSZip=source.dependency('jszip');
const materials=path.resolve(process.argv[2]),output=path.resolve(process.argv[3]);
const s1=path.join(materials,'supplementary/S1 configuration and source');
const s3=path.join(materials,'supplementary/S3 browser CNN');
const json=name=>JSON.parse(fs.readFileSync(path.join(s3,name),'utf8'));
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
(async()=>{
  const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'aiedu-cnn-replay-'));
  try {
    const archive=path.join(s1,fs.readdirSync(s1).find(n=>n.startsWith('cnn source ')&&n.endsWith('.zip')));
    const zip=await JSZip.loadAsync(fs.readFileSync(archive));
    const hashes={};
    fs.writeFileSync(path.join(tmp,'package.json'),JSON.stringify({type:'module'}));
    for(const name of ['cnn.js','mlp.js']) {
      const data=await zip.file('src/engine/models/'+name).async('nodebuffer');
      fs.writeFileSync(path.join(tmp,name),data);hashes[name]=hash(data);
    }
    const cnn=await import(pathToFileURL(path.join(tmp,'cnn.js'))),{MLP}=await import(pathToFileURL(path.join(tmp,'mlp.js')));
    const checkpoint=json('dense checkpoint and normalization.json');
    const net=new MLP([200,32,10],{activation:'relu',outputActivation:'softmax',seed:3});
    net.weights=checkpoint.weights;net.biases=checkpoint.biases;
    const samples=json('test predictions.json');let maximumError=0,correct=0;
    const replay=[];
    for(const sample of samples) {
      const image={w:28,h:28,c:1,data:Float32Array.from(sample.pixels)};
      const r=cnn.extractFeatures(image);
      const x=Array.from(r.features,(v,i)=>(v-checkpoint.standardization_mean[i])/checkpoint.standardization_sd[i]);
      const probabilities=net.forward(x).at(-1);
      const predicted=probabilities.indexOf(Math.max(...probabilities));
      maximumError=Math.max(maximumError,...probabilities.map((p,i)=>Math.abs(p-sample.probabilities[i])));
      assert.equal(predicted,sample.predicted_class);if(predicted===sample.true_class) correct++;
      replay.push({sample_id:sample.sample_id,predicted_class:predicted,maximum_probability_error:Math.max(...probabilities.map((p,i)=>Math.abs(p-sample.probabilities[i])))});
    }
    assert.equal(correct,197);assert.ok(maximumError<=1e-12);
    const mnist=json('MNIST/MNIST predictions.json'),summary=json('MNIST/MNIST summary.json');
    const mnistCorrect=mnist.filter(r=>r.true_class===r.predicted_class).length;
    assert.equal(mnist.length,10000);assert.equal(mnistCorrect,5773);assert.equal(mnistCorrect/mnist.length,summary.accuracy);
    const confusion=Array.from({length:10},()=>Array(10).fill(0));
    for(const r of mnist) confusion[r.true_class][r.predicted_class]++;
    assert.deepEqual(confusion,summary.confusion);
    const f1=confusion.map((r,i)=>{const tp=r[i],p=confusion.reduce((s,row)=>s+row[i],0),n=r.reduce((a,b)=>a+b,0);return p+n?2*tp/(p+n):0;});
    assert.ok(Math.abs(f1.reduce((a,b)=>a+b,0)/10-summary.macro_f1)<1e-12);
    const report={date_utc:new Date().toISOString(),runtime:process.version,framework:'JavaScript frozen browser model; numerical replay under Node.js',
      pytorch_used:false,model_retrained:false,source_archive_sha256:hash(fs.readFileSync(archive)),source_hashes:hashes,
      checkpoint_sha256:hash(fs.readFileSync(path.join(s3,'dense checkpoint and normalization.json'))),
      synthetic_replay:{samples:samples.length,correct,accuracy:correct/samples.length,max_probability_error:maximumError,all_predictions_match:true},
      mnist_retained_result_audit:{samples:mnist.length,correct:mnistCorrect,confusion_matches:true,macro_f1_matches:true,inference_rerun:false},
      scope:'MNIST aggregates were recomputed from retained predictions, not new inference. No PyTorch checkpoint or export chain is claimed.',passed:true};
    fs.mkdirSync(output,{recursive:false});
    fs.writeFileSync(path.join(output,'replay results.json'),JSON.stringify(report,null,2));
    fs.writeFileSync(path.join(output,'synthetic replay predictions.json'),JSON.stringify(replay,null,2));
    console.log(JSON.stringify(report,null,2));
  } finally {
    // Only our own two modules/package file were created here; no archive tree is extracted.
    for(const name of ['cnn.js','mlp.js','package.json']) {const p=path.join(tmp,name);if(fs.existsSync(p)) fs.unlinkSync(p);}
    fs.rmdirSync(tmp);
  }
})().catch(error=>{console.error(error);process.exitCode=1;});

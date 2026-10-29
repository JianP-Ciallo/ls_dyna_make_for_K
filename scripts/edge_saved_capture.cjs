/* Bounded CDP reads and per-frame export. Contains no simulation entry point. */
const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),{once}=require('node:events'),{pipeline}=require('node:stream/promises'),{execFile}=require('node:child_process');
function checked(result){if(result.exceptionDetails)throw Error(JSON.stringify(result.exceptionDetails));return result.result;}
async function evaluateVoid(call,expression){checked(await call('Runtime.evaluate',{expression:`(async()=>{void(await (${expression}));})()`,awaitPromise:true,returnByValue:false}));}
async function evaluateText(call,expression,maxChars=16000000){
 const result=checked(await call('Runtime.evaluate',{expression:`(async()=>{const text=await (${expression});if(typeof text!=='string'||text.length>${maxChars})throw Error('bounded capture exceeded');return text;})()`,awaitPromise:true,returnByValue:true}));
 if(typeof result.value!=='string'||result.value.length>maxChars)throw Error('bounded capture exceeded');return result.value;
}
async function evaluateJson(call,expression){return JSON.parse(await evaluateText(call,`(async()=>JSON.stringify(await (${expression})))()`,262144));}
async function streamCase(destination,metadata,count,frameText,onFrame=()=>{}){
 if(!Number.isInteger(count)||count<1||count>10000||metadata.length>16000000)throw Error('Invalid frame export bounds');
 const meta=JSON.parse(metadata);if('frames'in meta)throw Error('Metadata must exclude frame data');
 if(fs.existsSync(destination)||fs.existsSync(destination+'.partial'))throw Error('Refusing to overwrite evidence');
 const gzip=zlib.createGzip(),sink=fs.createWriteStream(destination+'.partial',{flags:'wx'}),done=pipeline(gzip,sink);done.catch(()=>{});
 const write=async text=>{if(!gzip.write(text))await once(gzip,'drain');};
 try{await write(metadata.slice(0,-1)+',"frames":[');for(let i=0;i<count;i++){const text=await frameText(i);if(typeof text!=='string'||text.length>16000000)throw Error('bounded frame capture exceeded');if(i)await write(',');await write(text);await onFrame(i);}gzip.end(']}');await done;fs.renameSync(destination+'.partial',destination);}
 catch(error){gzip.destroy(error);sink.destroy(error);await done.catch(()=>{});throw error;}
}
function profileArgumentPattern(profile){const escaped=path.resolve(profile).replace(/[.*+?^${}()|[\]\\]/g,'\\$&');return `(?:^|\\s)(?:"--user-data-dir=${escaped}"|--user-data-dir=(?:"${escaped}"|${escaped}))(?=\\s|$)`;}
async function stopOwnedEdge(profile){
 profile=path.resolve(profile);if(path.basename(profile)!=='edge-profile')throw Error('Refusing an unscoped Edge profile');
 const quoted=value=>"'"+value.replaceAll("'","''")+"'",pattern=profileArgumentPattern(profile);
 const script=`$ErrorActionPreference='Stop';$pattern=${quoted(pattern)};$stopped=@();$deadline=[DateTime]::UtcNow.AddSeconds(8);do{$all=@(Get-CimInstance Win32_Process);$owned=@($all|Where-Object{$_.Name -eq 'msedge.exe' -and $_.CommandLine -and $_.CommandLine.Replace('/','\\') -match $pattern});$ids=@($owned|ForEach-Object{$_.ProcessId});do{$more=@($all|Where-Object{$ids -contains $_.ParentProcessId -and $ids -notcontains $_.ProcessId});$ids+=@($more|ForEach-Object{$_.ProcessId})}while($more.Count);foreach($idValue in $ids){Stop-Process -Id $idValue -Force -ErrorAction SilentlyContinue;$stopped+=$idValue};Start-Sleep -Milliseconds 120;$remaining=@(Get-CimInstance Win32_Process -Filter "Name = 'msedge.exe'"|Where-Object{$_.CommandLine -and $_.CommandLine.Replace('/','\\') -match $pattern})}while($remaining.Count -gt 0 -and [DateTime]::UtcNow -lt $deadline);if($remaining.Count){throw 'Owned Edge did not stop'};[pscustomobject]@{profile=${quoted(profile)};stopped=@($stopped|Select-Object -Unique);remaining=0}|ConvertTo-Json -Compress`;
 return new Promise((resolve,reject)=>execFile('powershell.exe',['-NoProfile','-EncodedCommand',Buffer.from(script,'utf16le').toString('base64')],{windowsHide:true,timeout:15000},(error,stdout,stderr)=>error?reject(Error(stderr||error.message)):resolve(JSON.parse(stdout))));
}
module.exports={evaluateVoid,evaluateText,evaluateJson,streamCase,profileArgumentPattern,stopOwnedEdge};

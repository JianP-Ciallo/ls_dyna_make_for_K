const fs=require('node:fs'),path=require('node:path');
function moduleUrl(file){let code=fs.readFileSync(file,'utf8');code=code.replace(/from ['"]\.\/([^'"]+\.js)['"]/g,(_m,name)=>'from '+JSON.stringify(moduleUrl(path.join(path.dirname(file),name))));return 'data:text/javascript;base64,'+Buffer.from(code).toString('base64');}
module.exports=file=>import(moduleUrl(file));

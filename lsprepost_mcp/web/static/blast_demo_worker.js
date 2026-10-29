import {buildBuilding,simulate,validateConfig} from './blast_demo_model.js';
self.onmessage=async ({data})=>{
 try {
  const config=validateConfig(data);
  const result=await simulate(buildBuilding(config),config,{progress:p=>self.postMessage({kind:'progress',...p})});
  const buffers=result.frames.flatMap(f=>[f.poses.buffer,f.damage.buffer,...(f.fracture?['ids','offsets','vertices','damage','detachedFlags','cracks','crackIds','divisions','thickness','compression','cohesive','anchorDamage','nodeDamage','powderedFlags','powderDose','powderTimes'].filter(k=>f.fracture[k]).map(k=>f.fracture[k].buffer):[]),...(f.rebar?(f.rebar.schema==='local-steel-frame@2'?['ids','offsets','positions','edgeOffsets','edges','plastic','restLengths','free']:['positions','strains','plastic','failed','exposed']).map(k=>f.rebar[k].buffer):[])]);
  self.postMessage({kind:'result',result},buffers);
 }catch(error){self.postMessage({kind:'error',message:error.message});}
};

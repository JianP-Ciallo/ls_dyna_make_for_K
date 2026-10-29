/* Bounded illustrative compression DOF; source material constants are unchanged. */
export function refinementDivisions(body,fine=false){const thin=body.size.indexOf(Math.min(...body.size)),axes=[0,1,2].filter(k=>k!==thin),[w,h]=axes.map(k=>body.size[k]);if(!fine){const n=w*h>6?3:2;return {nx:n,ny:n};}return {nx:Math.max(2,Math.min(6,Math.ceil(w/.34))),ny:Math.max(2,Math.min(6,Math.ceil(h/.34)))};}
export function compressionState(thickness){return {original:thickness,thickness,velocity:0,plastic:0,peak:0,damage:0};}
export function stepCompression(state,acceleration,dt){
 const reference=state.original*(1-state.plastic),k=9000,damping=85;
 state.velocity=(state.velocity-dt*(Math.max(0,acceleration)+k*(state.thickness-reference)))/(1+damping*dt+k*dt*dt);state.thickness=Math.max(state.original*.65,Math.min(state.original,state.thickness+dt*state.velocity));
 const strain=Math.max(0,(state.original-state.thickness)/state.original);state.peak=Math.max(state.peak,strain);state.plastic=Math.min(.28,state.plastic+dt*7*Math.max(0,strain-.018));state.damage=Math.max(state.damage,Math.min(1,Math.max(0,(state.peak-.018)/.16)));return state;
}
export function materialDamage(cohesive,compression){return 1-(1-Math.max(0,Math.min(1,cohesive)))*(1-Math.max(0,Math.min(1,compression)));}
export function damageRGB(value){const d=Math.max(0,Math.min(1,value)),a=d<.5?[.24,.58,.72]:[.95,.72,.32],b=d<.5?[.95,.72,.32]:[.76,.25,.21],t=d<.5?d*2:(d-.5)*2;return a.map((v,k)=>v+(b[k]-v)*t);}

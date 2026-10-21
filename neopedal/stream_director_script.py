#  NeoPedal is an open-source overlay application for racing simulation.
#  Copyright (C) 2022-2026 TinyPedal developers, see contributors.md file
#
#  This file is part of NeoPedal.
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Script of the broadcast graphics page (end of stream_director_page.DIRECTOR_HTML): state asked to /api/director
again and again (long poll) & live positions to /api/director/live, graphics drawn from the state (tower, cards,
banners, onboard, track map...), layout editor (edit=1)
"""

# End of the graphics page: its script (DIRECTOR_HTML = DIRECTOR_PAGE + DIRECTOR_SCRIPT)
DIRECTOR_SCRIPT = """<script>
"use strict";
const query=new URLSearchParams(location.search);
const token=query.get("token")||"";
const edit=query.get("edit")==="1";
const animate=query.get("animate")!=="0"&&!edit;
const once=query.get("once")==="1"||edit;
const scale=Math.max(parseFloat(query.get("scale")||"1")||1,0.3);
const only=(query.get("only")||"").split(",").map(text=>text.trim()).filter(Boolean);
const sourcePreset=query.has("preset")?query.get("preset"):null;
const IDS=["tower","card","battle","train","banners","pitradar","replay","clock","onboard","quali","map","grid","event","results",
"champ","message","countdown","logo","sponsors"];
if(!animate)document.documentElement.classList.add("still");
document.documentElement.style.setProperty("--u",scale+"vh");
const $=id=>document.getElementById(id);
const TONES={fastest:"var(--purple)",loss:"var(--loss)",warning:"var(--warn)",gain:"var(--gain)",accent:"var(--accent)",
yellow:"var(--gold)",dim:"#9aa3b2"};
const TYRES=@@tyres@@;  // letter: [fill, letter color], as compound badges of overlays
const ROW=3.3,HEAD=2.4;  // tower row & class title heights (u)
const picture=link=>link?link+(link.includes("?")?"&":"?")+"token="+encodeURIComponent(token):"";
let state={},layout={},preset="",version=0,lastCut=-1,cardTimer=0,towerPage=0,towerScroll=0,towerScrolls=1,towerTimer=0,shownBanners=new Set(),bannerQueue=[],bannerBusy=false;
let wasReplay=false,received=Date.now(),replayEnded=0,lastTrain=null,trainUntil=0,laps=new Map(),live={},liveVersion=0,trackKey=null,track=null;
const pages={grid:0,results:0,champ:0},pageTimers={},towerLines=new Map(),recentBanners=new Map();
let sponsorIndex=0,sponsorTimer=0,sponsorKey="";
function set(id,value){const el=typeof id==="string"?$(id):id;const text=value==null?"":String(value);if(el.textContent!==text)el.textContent=text}
function toggle(id,on){$(id).classList.toggle("show",!!on)}
function image(id,link){const el=$(id);const src=picture(link);if(src){if(el.getAttribute("src")!==src)el.src=src;el.style.display="block"}else el.style.display="none"}
function cell(className,value){const div=document.createElement("div");div.className=className;div.textContent=value==null?"":String(value);return div}
function labels(){return state.labels||{}}
// Places of the layout editor: left & top (fractions of the canvas), size factor (--u of the graphic)
function applyLayout(){
  for(const id of IDS){
    const el=$(id),place=layout[id];
    if(place){el.style.left=(place[0]*100)+"vw";el.style.top=(place[1]*100)+"vh";el.style.right="auto";el.style.bottom="auto";
      el.style.setProperty("--u",(scale*place[2])+"vh");if(id==="banners")el.style.transform="none"}
    else{for(const name of ["left","top","right","bottom","transform","--u"])el.style.removeProperty(name)}
  }
}
function tyreMark(letter){const mark=cell("tyre",letter),badge=TYRES[letter]||["#AAAAAA","#0E1116"];
  mark.style.background=badge[0];mark.style.color=badge[1];return mark}
// Tower: one element per car, kept from answer to answer (texts changed only when they change, moves animated)
function towerLine(key,header){
  let line=towerLines.get(key);
  if(!line){
    line=document.createElement("div");
    if(header){line.className="thead";line.innerHTML="<i></i><span></span>"}
    else{line.className="trow new";line.innerHTML='<div class="tpos"></div><div class="tbar"></div><div class="tnum"></div><div class="tname"><span></span><span class="tchange"></span></div><div class="tmarks"></div><div class="tgap"></div>'}
    line.style.transition="none";line.dataset.fresh="1";$("towerRows").append(line);towerLines.set(key,line);
  }
  return line;
}
function placeLine(line,y){
  line.style.transform="translateY(calc(var(--u)*"+y+"))";
  if(line.dataset.fresh){delete line.dataset.fresh;void line.offsetWidth;
    requestAnimationFrame(()=>{line.style.removeProperty("transition");line.classList.remove("new")})}
}
function towerEntries(group){
  if(!group.grouped)return group.rows.map(row=>({row}));
  // Overall by class: class title then its cars (best placed class first)
  const classes=[...new Set(group.rows.map(row=>row.cls))],entries=[];
  for(const cls of classes){const rows=group.rows.filter(row=>row.cls===cls);entries.push({header:cls,color:rows[0].color});for(const row of rows)entries.push({row})}
  return entries;
}
// Carousel: more cars than the tower height (cars shown): pages of whole rows in turn, sliding up, the last one
// ending on the last car; a page never ends on a class title
function towerPages(entries,height){
  const tops=[];let total=0;
  for(const entry of entries){tops.push(total);total+=entry.header?HEAD:ROW}
  tops.push(total);
  if(total<=height+.01)return {pages:[{offset:0,height:total}],total};
  let last=entries.length;while(last>0&&total-tops[last-1]<=height+.01)last--;
  const pages=[];
  for(let start=0;start<last;){
    let end=start;while(end<entries.length&&tops[end+1]-tops[start]<=height+.01)end++;
    if(end<entries.length&&end-1>start&&entries[end-1].header)end--;
    end=Math.max(end,start+1);pages.push({offset:tops[start],height:tops[end]-tops[start]});start=end;
  }
  pages.push({offset:tops[last],height:total-tops[last]});
  return {pages,total};
}
function tower(){
  const g=state.graphics||{},rows=state.tower||[];
  if(!g.tower||!rows.length){toggle("tower",false);return}
  let groups=[{title:labels().overall,rows,grouped:!!g.towerGroup}];
  if(g.towerMode==="class"){
    const names=[...new Set(rows.map(row=>row.cls))];
    groups=names.map(name=>({title:name,rows:rows.filter(row=>row.cls===name),byClass:true}));
  }else if(g.towerMode==="air"&&state.onAir){
    const cls=state.onAir.cls;groups=[{title:cls,rows:rows.filter(row=>row.cls===cls),byClass:true}];
  }
  const group=groups[towerPage%groups.length];
  set("towerTitle",group.title);set("towerSub",state.clock?state.clock.text:"");
  const entries=towerEntries(group),height=(g.towerRows||12)*ROW+(group.grouped?HEAD:0);
  const {pages,total}=towerPages(entries,height),page=pages[towerScroll%pages.length],offset=page.offset;towerScrolls=pages.length;
  const now=Date.now(),used=new Set(),leader=g.towerGap==="leader";let y=-offset;
  for(const entry of entries){
    if(entry.header){
      const key="h|"+entry.header,line=towerLine(key,true);used.add(key);
      line.firstChild.style.background=entry.color;set(line.lastChild,entry.header);
      placeLine(line,y);y+=HEAD;continue;
    }
    const row=entry.row,key="c|"+row.number+"|"+row.cls,line=towerLine(key,false);used.add(key);
    const [pos,bar,num,name,marks,gapBox]=line.children;
    line.classList.toggle("air",!!row.air);
    set(pos,group.byClass?row.classPos:row.pos);bar.style.background=row.color;set(num,"#"+row.number);
    set(name.firstChild,row.name);
    const change=name.lastChild;set(change,row.change?(row.change>0?"\\u25b2":"\\u25bc")+Math.abs(row.change):"");
    change.className="tchange "+(row.change>0?"up":row.change<0?"down":"");
    const sig=[g.towerPenalties&&row.pen,g.towerFastest&&row.fastest,g.towerStops&&row.stops,g.towerTyres&&(row.tyres||[]).join("")].join("|");
    if(marks.dataset.sig!==sig){marks.dataset.sig=sig;marks.innerHTML="";
      if(g.towerPenalties&&row.pen>0)marks.append(cell("tpen",labels().pen+(row.pen>1?" "+row.pen:"")));
      if(g.towerFastest&&row.fastest)marks.append(cell("tfl",labels().fastestTag));
      if(g.towerStops&&row.stops>0)marks.append(cell("tstops",row.stops+"\\u00d7"));
      if(g.towerTyres)for(const letter of row.tyres||[])marks.append(tyreMark(letter))}
    // Lap just completed: its time shown a few seconds in place of the gap (gold, purple for the fastest)
    const lapKey=row.number+"|"+row.cls,seen=laps.get(lapKey);
    if(row.lap&&(!seen||seen.id!==row.lapId)){
      const until=state.demo?Infinity:seen||state.version?now+5000:0;laps.set(lapKey,{id:row.lapId,until});
      if(until>now&&until<Infinity)setTimeout(tower,5100)}
    const flash=g.towerLaps&&row.lap&&laps.get(lapKey)&&laps.get(lapKey).until>now;
    const status=row.state||(row.pit?"pit":"");  // pit lane, garage, retired, disqualified: colored as in the app
    if(status){if(gapBox.dataset.mode!==status){gapBox.dataset.mode=status;gapBox.className="tgap";gapBox.innerHTML="";
      const tag=document.createElement("span");tag.className="tpit "+status;tag.textContent=labels()[status]||status;gapBox.append(tag)}}
    else{gapBox.dataset.mode="";gapBox.className="tgap"+(flash?" lap"+(row.lapTone==="fastest"?" fastest":""):row.close&&!leader?" close":"");
      set(gapBox,flash?row.lap:group.byClass?(leader?row.gapClassLeader:row.gapClass):(leader?row.gapLeader:row.gap))}
    placeLine(line,y);y+=ROW;
  }
  for(const [key,line] of towerLines)if(!used.has(key)){line.remove();towerLines.delete(key)}
  $("towerRows").style.height="calc(var(--u)*"+page.height+")";
  // Scroll mark: part of the cars shown (carousel only)
  const thumb=$("towerThumb");thumb.style.display=pages.length>1?"block":"none";
  if(pages.length>1){thumb.style.top="calc(var(--u)*"+(offset/total*page.height)+")";thumb.style.height="calc(var(--u)*"+(page.height/total*page.height)+")"}
  toggle("tower",true);
}
// Every few seconds: next page of the carousel, then next class (each class in turn)
function cycleTower(){clearTimeout(towerTimer);towerTimer=setTimeout(()=>{if(++towerScroll>=towerScrolls){towerScroll=0;towerPage++}tower();cycleTower()},(state.graphics&&state.graphics.towerCycle||10)*1000)}
function fillCard(car,story,storyTone){
  const g=state.graphics||{};
  set("cardPos","P"+car.classPos);set("cardClass",car.cls);$("cardPlace").style.background=car.color||"var(--accent)";
  set("cardNum","#"+car.number);set("cardName",car.name);set("cardTeam",car.team);
  image("cardLogo",car.logo);image("cardPicture",g.cardPicture?car.picture:"");
  const stats=$("cardStats");stats.innerHTML="";
  for(const [label,value] of car.stats||[]){if(!value)continue;const span=document.createElement("span");const tag=document.createElement("i");tag.textContent=label;span.append(tag,value);stats.append(span)}
  const box=$("cardStory");box.textContent=story||"";box.style.display=story?"block":"none";
  box.style.background=storyTone?TONES[storyTone]||"rgba(255,255,255,.1)":"rgba(255,255,255,.1)";box.style.color=storyTone?"#111":"";
}
function card(){
  const g=state.graphics||{},car=state.onAir,info=g.replayGraphics?state.replayInfo:null;
  // Instant replay of a flag or a stopped car: driver card of the car all along the replay
  if(info&&info.mode==="driver"&&info.car){fillCard(info.car,info.kind,info.tone);toggle("card",true);return}
  // Battle card on air tells both drivers: it takes the place of the driver card
  if(!g.card||!car||(g.battle&&(state.battle||state.train))||(info&&info.mode==="duel")||(g.quali&&state.quali)){toggle("card",false);if(car)lastCut=state.cut;return}
  fillCard(car,car.story,car.storyTone);
  if(state.cut!==lastCut){lastCut=state.cut;clearTimeout(cardTimer);toggle("card",true);
    if(g.cardSeconds>0)cardTimer=setTimeout(()=>toggle("card",false),g.cardSeconds*1000)}
  else if(g.cardSeconds<=0)toggle("card",true);
}
function battle(){
  const g=state.graphics||{},info=g.replayGraphics?state.replayInfo:null;
  let fight=state.battle;
  if(info&&info.mode==="duel")fight={title:info.kind,color:TONES[info.tone]||"var(--accent)",gap:info.center||"",trend:"",ahead:info.ahead,behind:info.behind};
  else if(!g.battle||(g.train&&trainShown()))fight=null;
  if(!fight){toggle("battle",false);return}
  fillBattle(fight);toggle("battle",true);
}
function fillBattle(fight){
  set("battleTitle",fight.title);
  set("bAheadNum","#"+fight.ahead.number);set("bAheadName",fight.ahead.name);set("bAheadTeam",fight.ahead.team);
  set("bBehindNum","#"+fight.behind.number);set("bBehindName",fight.behind.name);set("bBehindTeam",fight.behind.team);
  set("bGap",fight.gap);const trend=$("bTrend");trend.textContent=fight.trend||"";trend.className=fight.trendClass||"";
  $("battle").querySelector("header").style.background="linear-gradient(90deg,transparent,"+(fight.color||"var(--accent)")+",transparent)";
}
// Battle train kept 10 s after it broke up (no flicker on the gap threshold)
function trainShown(){const g=state.graphics||{};return !!(g.battle&&g.train&&(state.train||(lastTrain&&Date.now()<trainUntil)))&&!(state.replayInfo&&g.replayGraphics)}
function train(){
  if(state.train){lastTrain=state.train;trainUntil=Date.now()+10000}
  const fight=state.train||lastTrain;
  if(!trainShown()||!fight){toggle("train",false);return}
  set("trainTitle",fight.title);$("train").querySelector("header").style.background="linear-gradient(90deg,transparent,"+(fight.color||"var(--accent)")+",transparent)";
  const box=$("trainCars");box.innerHTML="";
  for(const car of fight.cars){
    const div=document.createElement("div");div.className="tcard"+(car.air?" air":"");div.style.borderTopColor=car.color;
    const top=document.createElement("b");top.textContent="P"+car.classPos;
    div.append(top,cell("bnum","#"+car.number),cell("bname",car.name),cell("tgap",car.gap));box.append(div);
  }
  toggle("train",true);
}
// Banners: most important first, the same news not told twice in 30 s, 4 waiting at most
function banners(){
  const g=state.graphics||{},now=Date.now();
  for(const event of state.events||[]){
    if(shownBanners.has(event.id))continue;shownBanners.add(event.id);
    if(!g.banners)continue;
    const same=(event.type||event.kind)+"|"+event.title;
    if(now-(recentBanners.get(same)||-1e9)<30000)continue;
    recentBanners.set(same,now);
    bannerQueue.push(event);
  }
  bannerQueue.sort((a,b)=>(b.priority||0)-(a.priority||0));
  if(bannerQueue.length>4)bannerQueue.length=4;
  if(!bannerBusy)nextBanner();
}
// Banners wait during a replay, then 5 s after it, so viewers see them live
function bannersHeld(){return !!(state.replay&&(state.graphics||{}).replayGraphics)||Date.now()<replayEnded+5000}
function nextBanner(){
  if(bannersHeld()&&bannerQueue.length){bannerBusy=true;setTimeout(nextBanner,500);return}
  const event=bannerQueue.shift();if(!event){bannerBusy=false;return}
  bannerBusy=true;
  const box=document.createElement("div");box.className="banner panel";
  const tag=cell("tag",event.kind);tag.style.background=TONES[event.tone]||"var(--accent)";
  const text=document.createElement("div");text.className="txt";
  const title=document.createElement("b");title.textContent=event.title;text.append(title);
  if(event.detail){const detail=document.createElement("span");detail.textContent=event.detail;text.append(detail)}
  box.append(tag,text);$("banners").append(box);
  requestAnimationFrame(()=>requestAnimationFrame(()=>box.classList.add("show")));
  const seconds=(state.graphics&&state.graphics.bannerSeconds)||6;
  setTimeout(()=>{box.classList.remove("show");setTimeout(()=>{box.remove();nextBanner()},animate?500:0)},seconds*1000);
}
function pitRadar(){
  const radar=state.pitRadar;
  if(!radar){toggle("pitradar",false);return}
  set("pitTitle",radar.title);set("pitCount",radar.count);
  const box=$("pitRows");box.innerHTML="";
  for(const row of radar.rows){
    const line=document.createElement("div");line.className="prow";
    const bar=cell("tbar","");bar.style.background=row.color;
    const distance=document.createElement("div");distance.className="pdist"+(row.alongside?" near":"");
    if(row.alongside)distance.textContent=labels().alongside;
    else{const arrow=document.createElement("i");arrow.textContent=row.ahead?"\\u25b2":"\\u25bc";distance.append(arrow,row.distance)}
    line.append(bar,cell("tnum","#"+row.number),cell("tname",row.name),distance);box.append(line);
  }
  toggle("pitradar",true);
}
function chrome(){
  const g=state.graphics||{};
  set("replayText",labels().replay||"");toggle("replay",g.replay&&state.replay);
  if(g.clock&&state.clock){set("clockTime",state.clock.text);set("clockLabel",state.clock.label);set("weather",(state.weather||[]).join("  \\u00b7  "));
    const flag=$("clockFlag");flag.textContent=state.flag||"";flag.style.display=state.flag?"block":"none";toggle("clock",true)}
  else toggle("clock",false);
}
function onboardStatic(){
  const g=state.graphics||{},car=state.onboard;
  const box=$("onboard");box.classList.remove("dash","cockpit","helmet");box.classList.add(g.onboardStyle||"dash");
  if(!g.onboard||!car){toggle("onboard",false);return}
  set("obNum","#"+car.number);set("obName",car.name);set("obAhead",car.ahead||"");$("obHead").style.borderLeftColor=car.color;
  set("obEnergyLabel",labels().energy);toggle("onboard",true);onboardLive();
}
// Onboard values eased each frame toward the last sample (10 a second): speed counts, pedals & lights move
// smoothly instead of jumping; a sample far from the shown value (car changed, replay jump) is taken at once
const ease={speed:null,rpm:0,throttle:0,brake:0,frame:0,last:0};
function onboardData(){return (live&&live.onboard)||(state.demo?{speed:247,gear:5,rpm:8420,rpmMax:9000,throttle:.92,brake:0,energy:.64,unit:"km/h"}:null)}
function onboardFrame(now){
  ease.frame=0;
  const data=onboardData();
  if(!data||!state.onboard||!(state.graphics||{}).onboard||document.hidden)return;
  const dt=Math.min(Math.max((now-(ease.last||now))/1000,0),0.25);ease.last=now;
  const k=animate?1-Math.exp(-dt/0.07):1;  // about 0.1 s to reach a new sample
  const speed=Number(data.speed)||0;
  ease.speed=ease.speed==null||Math.abs(speed-ease.speed)>60?speed:ease.speed+(speed-ease.speed)*k;
  ease.rpm+=((data.rpm||0)-ease.rpm)*k;ease.throttle+=((data.throttle||0)-ease.throttle)*k;ease.brake+=((data.brake||0)-ease.brake)*k;
  drawOnboard(data);
  const settled=Math.abs(speed-ease.speed)<.05&&Math.abs((data.rpm||0)-ease.rpm)<5&&Math.abs((data.throttle||0)-ease.throttle)<.005
    &&Math.abs((data.brake||0)-ease.brake)<.005;
  if(!settled)ease.frame=requestAnimationFrame(onboardFrame);else ease.last=0;
}
function onboardLive(){if(!ease.frame)ease.frame=requestAnimationFrame(onboardFrame)}
function drawOnboard(data){
  set("obSpeed",Math.round(ease.speed));set("obUnit",data.unit);
  set("obGear",data.gear==null?"-":data.gear<0?labels().reverse:data.gear===0?labels().neutral:data.gear);
  const max=data.rpmMax||state.onboard.rpmMax||1,ratio=Math.min(Math.max(ease.rpm/max,0),1);
  // Shift lights: from 70 % of the highest rpm, green, yellow then red, all blue (flashing) to shift up
  const leds=$("obLeds");if(leds.children.length!==10){leds.textContent="";for(let i=0;i<10;i++){const led=document.createElement("i");led.className=i<4?"led-g":i<7?"led-y":"led-r";leds.append(led)}}
  const lit=data.gear==null?0:Math.round(Math.min(Math.max((ratio-.7)/.27,0),1)*10);
  [...leds.children].forEach((led,i)=>led.classList.toggle("on",i<lit));leds.classList.toggle("flash",data.gear!=null&&ratio>=.97);
  $("obThrottle").style.height=(ease.throttle*100).toFixed(1)+"%";$("obBrake").style.height=(ease.brake*100).toFixed(1)+"%";
  $("obEnergyRow").style.display=data.energy>=0?"flex":"none";$("obEnergy").style.width=Math.max(data.energy,0)*100+"%";
  $("obEnergy").style.background=data.energy<=@@energyLow@@?"var(--loss)":data.energy<=@@energyMedium@@?"var(--warn)":"var(--gain)";  // as overlays
}
function lapClock(seconds){if(seconds<0)return "";const minutes=Math.floor(seconds/60),rest=seconds-minutes*60;
  return minutes+":"+(rest<10?"0":"")+rest.toFixed(1)}
function quali(){
  const g=state.graphics||{},lap=state.quali;
  if(!g.quali||!lap||(state.replayInfo&&g.replayGraphics)){toggle("quali",false);return}
  set("qPos",lap.position);set("qName","#"+lap.number+"  "+lap.name);$("qTop").style.borderLeftColor=lap.color;
  set("qStatus",lap.status);$("qStatus").style.display=lap.status?"block":"none";
  ["qS1","qS2","qS3"].forEach((id,index)=>{const sector=lap.sectors[index]||{text:"-",tone:""};set(id,sector.text);
    $(id).style.borderBottomColor=sector.tone?TONES[sector.tone]:"rgba(255,255,255,.12)"});
  set("qTargetLabel",lap.targetLabel+" "+lap.target);set("qDelta",lap.delta);$("qDelta").style.color=lap.deltaTone?TONES[lap.deltaTone]:"";
  qualiTime();toggle("quali",true);
}
function qualiTime(){
  const lap=state.quali;if(!lap)return;
  if(!lap.running){set("qTime",lap.best);return}
  set("qTime",lapClock(lap.now+(state.demo?0:(Date.now()-received)/1000)-lap.lapStart));
}
// Track map: world positions turned (map rotation) & scaled to the picture, sectors of the racing line
function turn(x,y){const angle=((state.graphics||{}).mapRotation||0)*Math.PI/180;if(!angle)return [x,y];
  const c=Math.cos(angle),s=Math.sin(angle);return [x*c-y*s,x*s+y*c]}
function fit(points){
  const turned=points.map(p=>turn(p[0],p[1])),xs=turned.map(p=>p[0]),ys=turned.map(p=>p[1]);
  const minX=Math.min(...xs),minY=Math.min(...ys),width=Math.max(Math.max(...xs)-minX,1),height=Math.max(Math.max(...ys)-minY,1);
  const f=Math.min(1000/width,1000/height)*.92;return {minX,minY,width,height,f,ox:(1000-width*f)/2,oy:(1000-height*f)/2}
}
function toMap(x,y){const [tx,ty]=turn(x,y);return [(tx-track.minX)*track.f+track.ox,(ty-track.minY)*track.f+track.oy]}
function polyline(points){return points.map((p,i)=>{const [x,y]=toMap(p[0],p[1]);return (i?"L":"M")+x.toFixed(1)+" "+y.toFixed(1)}).join(" ")}
function setupTrack(data){
  track={...data,rotation:(state.graphics||{}).mapRotation||0,...fit([...data.points,...data.pit])};
  const viewBox="0 "+Math.round(track.oy-20)+" 1000 "+Math.round(track.height*track.f+40);
  $("mapSvg").setAttribute("viewBox",viewBox);$("mapShade").setAttribute("viewBox",viewBox);
  // Length along the racing line of each point (sectors cut by fraction of the lap)
  const cum=[0];for(let i=1;i<data.points.length;i++){const a=data.points[i-1],b=data.points[i];cum.push(cum[i-1]+Math.hypot(b[0]-a[0],b[1]-a[1]))}
  track.cum=cum;track.total=cum[cum.length-1]||1;track.sectorKey="";
  $("mapPit").setAttribute("d",data.pit.length?polyline(data.pit):"");$("mapPit").style.strokeWidth=5;
  for(const id of ["mapS1","mapS2","mapS3"])$(id).style.strokeWidth=10;
  mapSectors(true);
}
function mapSectors(force){
  if(!track)return;
  const info=state.map||{},cuts=(info.sectors||[]).length===2?info.sectors:[],yellow=info.yellowSectors||[];
  const key=cuts.join(",")+"|"+yellow.join(",");if(!force&&key===track.sectorKey)return;track.sectorKey=key;
  const points=track.points,ends=[0,...cuts.map(cut=>cut*track.total),track.total+1];
  ["mapS1","mapS2","mapS3"].forEach((id,index)=>{
    const part=points.filter((p,i)=>track.cum[i]>=ends[index]-1&&track.cum[i]<=ends[index+1]+1);
    if(cuts.length&&index<2&&points.length){const next=points.find((p,i)=>track.cum[i]>ends[index+1]);if(next)part.push(next)}
    const whole=!cuts.length&&index===0;
    $(id).setAttribute("d",whole?polyline(points)+"Z":cuts.length&&part.length>1?polyline(part)+(index===2?" L"+toMap(points[0][0],points[0][1]).map(v=>v.toFixed(1)).join(" "):""):"");
    $(id).classList.toggle("yellow",!!yellow[index]);
  });
}
async function loadTrack(key){
  trackKey=key;
  try{const response=await fetch("/api/director/track?token="+encodeURIComponent(token),{cache:"no-store"});
    const data=await response.json();if(!data.key){track=null;return}
    setupTrack(data);mapCars();
  }catch(error){trackKey=null}
}
function mapCars(){
  const info=state.map;if(!info||!track)return;
  const g=state.graphics||{},size=(g.mapDots||100)/100;
  const box=$("mapCars"),positions=new Map(),flat=(live&&live.cars)||[];
  for(let i=0;i+2<flat.length;i+=3)positions.set(String(flat[i]),[flat[i+1],flat[i+2]]);
  const seen=new Set();
  for(const [slot,car] of Object.entries(info.cars||{})){
    const at=positions.get(slot)||[car[0],car[1]];seen.add(slot);
    let dot=box.querySelector('[data-slot="'+slot+'"]');
    if(!dot){dot=document.createElementNS("http://www.w3.org/2000/svg","g");dot.setAttribute("class","mcar");dot.dataset.slot=slot;
      dot.innerHTML='<circle r="14"></circle><text font-size="16"></text>';box.append(dot)}
    const air=car[4],yellow=String(info.yellow)===slot,circle=dot.firstChild,text=dot.lastChild;
    circle.setAttribute("r",(air?24:13)*size);circle.setAttribute("fill",yellow?"#facc15":car[2]);
    circle.setAttribute("stroke",air?"#fff":"rgba(0,0,0,.6)");circle.setAttribute("stroke-width",(air?5:3)*size);
    dot.classList.toggle("myellow",yellow);dot.classList.toggle("pit",!!car[5]&&!air);
    text.textContent=air?car[3]:"";text.setAttribute("font-size",22*size);
    const [x,y]=toMap(at[0],at[1]);
    dot.style.transform="translate("+x.toFixed(1)+"px,"+y.toFixed(1)+"px)";
    if(air&&box.lastChild!==dot)box.append(dot);
  }
  for(const dot of [...box.children])if(!seen.has(dot.dataset.slot))dot.remove();
}
// Layout editor: a sample circuit with a few cars
function demoTrack(){
  const points=[],cars={};
  for(let i=0;i<120;i++){const a=i/120*Math.PI*2;points.push([Math.cos(a)*(900+Math.sin(a*3)*120),Math.sin(a)*(420+Math.cos(a*2)*60)])}
  trackKey="demo";setupTrack({key:"demo",points,pit:[]});
  const colors=["#E5484D","#3E8EF7","#30A46C"];
  for(let i=0;i<10;i++){const p=points[(i*11+5)%points.length];cars[i]=[p[0],p[1],colors[i%3],String(7+i*3),i===2,i===8]}
  state.map={...state.map,track:"demo",yellow:6,cars};mapSectors(true);
}
function map(){
  const g=state.graphics||{};
  if(state.demo&&g.map&&(!track||track.key!=="demo"||track.rotation!==(g.mapRotation||0)))demoTrack();
  const info=state.map;
  if(!g.map||!info){toggle("map",false);return}
  if(!state.demo&&(info.track!==trackKey||(track&&track.rotation!==(g.mapRotation||0))))loadTrack(info.track);
  mapSectors(false);mapCars();toggle("map",!!track||state.demo);
}
function cyclePages(id,count,draw){
  const seconds=(id==="grid"?(state.graphics||{}).gridSeconds:(state.graphics||{}).pageSeconds)||10;
  if(pageTimers[id]||count<=1)return;
  const bar=$(id+"Bar");
  const tick=()=>{pages[id]=(pages[id]+1)%Math.max(count,1);draw();
    if(animate){bar.style.transition="none";bar.style.width="0";requestAnimationFrame(()=>requestAnimationFrame(()=>{bar.style.transition="width "+seconds+"s linear";bar.style.width="100%"}))}};
  pageTimers[id]=setInterval(tick,seconds*1000);
  if(animate){bar.style.transition="width "+seconds+"s linear";requestAnimationFrame(()=>bar.style.width="100%")}
}
function stopPages(id){clearInterval(pageTimers[id]);pageTimers[id]=0;pages[id]=0;$(id+"Bar").style.width="0"}
function pageOf(id,rows,per){const count=Math.max(Math.ceil(rows.length/per),1);const page=pages[id]%count;
  set(id+"Page",count>1?(page+1)+" / "+count:"");return {rows:rows.slice(page*per,page*per+per),count}}
function grid(){
  const info=state.grid;
  if(!info){toggle("grid",false);stopPages("grid");return}
  set("gridTitle",info.title);
  const page=pageOf("grid",info.cars,8),box=$("gridCars");box.innerHTML="";
  for(const car of page.rows){
    const div=document.createElement("div");div.className="gcar";div.style.borderLeftColor=car.color;
    const pos=document.createElement("b");pos.textContent=car.pos;
    const text=document.createElement("div");text.append(cell("bname","#"+car.number+"  "+car.name),cell("bteam",car.team),cell("gtime",car.time));
    div.append(pos,text);
    if(car.picture){const img=document.createElement("img");img.alt="";img.src=picture(car.picture);div.append(img)}
    box.append(div);
  }
  toggle("grid",true);cyclePages("grid",page.count,grid);
}
function eventCard(){
  const info=state.event;
  if(!info){toggle("event",false);return}
  set("eventTrack",info.track);set("eventSession",info.session);image("eventLogo",info.logo);
  set("eventCond",(info.conditions||[]).join("  \\u00b7  "));
  const cast=$("eventCast");cast.innerHTML="";
  for(const node of info.forecast||[]){const div=document.createElement("div");div.className="ev-node"+(node.wet?" wet":"");
    const label=document.createElement("span");label.textContent=node.label;const value=document.createElement("b");value.textContent=node.temperature;
    const sky=document.createElement("span");sky.textContent=[node.sky,node.rain].filter(Boolean).join(" \\u00b7 ");div.append(label,value,sky);cast.append(div)}
  const box=$("eventSchedule");box.innerHTML="";
  for(const [label,value] of info.schedule||[]){const row=document.createElement("div");row.className="ev-row";
    const name=document.createElement("span");name.textContent=label;const text=document.createElement("b");text.textContent=value;row.append(name,text);box.append(row)}
  toggle("event",true);
}
function results(){
  const info=state.results;
  if(!info){toggle("results",false);stopPages("results");return}
  set("resultsTitle",info.title);set("resultsSub",info.subtitle);
  const per=(state.graphics||{}).resultsRows||10,page=pageOf("results",info.rows,per),box=$("resultsRows");box.innerHTML="";
  const head=document.createElement("div");head.className="rrow head";const l=labels();
  head.append(cell("r","P"),cell("",""),cell("","#"),cell("",""),cell("",""),cell("r",l.laps),cell("r",l.gap),cell("r",l.best),cell("r",l.pits));box.append(head);
  for(const row of page.rows){
    const line=document.createElement("div");line.className="rrow";const bar=cell("tbar","");bar.style.background=row.color;
    line.append(cell("tpos",row.pos),bar,cell("tnum","#"+row.number),cell("tname",row.name),cell("bteam",row.team),cell("r",row.laps),
      cell("r"+(row.status?" out":""),row.status||row.gap),cell("r",row.best),cell("r",row.pits));box.append(line);
  }
  toggle("results",true);cyclePages("results",page.count,results);
}
function champ(){
  const info=state.champ;
  if(!info){toggle("champ",false);stopPages("champ");return}
  set("champTitle",info.title);set("champSub",info.subtitle);
  const per=(state.graphics||{}).resultsRows||10,page=pageOf("champ",info.rows,per),box=$("champRows");box.innerHTML="";
  for(const row of page.rows){
    const line=document.createElement("div");line.className="crow";
    const pos=document.createElement("div");if(row.medal){const medal=document.createElement("span");medal.className="medal m"+row.medal;medal.textContent=row.pos;pos.append(medal)}else{pos.className="tpos";pos.textContent=row.pos}
    const bar=cell("tbar","");bar.style.background=row.color||"transparent";
    line.append(pos,bar,cell("tname",row.name),cell("bteam",row.team),cell("cpts",row.points+" "+(labels().points||"").toLowerCase()));box.append(line);
  }
  toggle("champ",true);cyclePages("champ",page.count,champ);
}
function message(){
  const info=state.message;
  if(!info||!info.text){toggle("message",false);return}
  set("messageTitle",info.title||"");$("messageTitle").style.display=info.title?"flex":"none";set("messageText",info.text);toggle("message",true);
}
function clockText(seconds){seconds=Math.max(Math.ceil(seconds),0);const h=Math.floor(seconds/3600),m=Math.floor(seconds/60)%60,s=seconds%60;
  return (h?h+":"+(m<10?"0":""):"")+m+":"+(s<10?"0":"")+s}
function countdown(){
  const info=state.countdown;
  if(!info){toggle("countdown",false);return}
  set("countdownLabel",info.label);countdownTime();toggle("countdown",true);
}
function countdownTime(){const info=state.countdown;if(!info)return;
  set("countdownTime",clockText(info.endsAt>0?(info.endsAt-Date.now())/1000:info.seconds||0))}
// League logo & name, sponsors pictures in turn
function brand(){
  const g=state.graphics||{},info=state.brand||{};
  if(/^#[0-9a-fA-F]{6}$/.test(g.accent||"")){const root=document.documentElement.style,value=parseInt(g.accent.slice(1),16);
    root.setProperty("--accent",g.accent);root.setProperty("--ar",(value>>16)+","+(value>>8&255)+","+(value&255))}
  const logo=$("logoImage");if(info.logo){const src=picture(info.logo);if(logo.getAttribute("src")!==src)logo.src=src;logo.style.display="block"}else logo.style.display="none";
  set("logoName",info.name||"");toggle("logo",g.logo&&(info.logo||info.name));
  const items=(info.sponsors||[]).length?info.sponsors:(state.demo?info.names||[]:[]),box=$("sponsors"),key=items.join("|");
  if(key!==sponsorKey){sponsorKey=key;box.innerHTML="";sponsorIndex=0;
    for(const item of items){let el;if((info.sponsors||[]).length){el=document.createElement("img");el.alt="";el.src=picture(item)}else{el=document.createElement("span");el.textContent=item}box.append(el)}
    if(box.firstChild)box.firstChild.classList.add("on")}
  clearInterval(sponsorTimer);
  if(items.length>1&&!edit)sponsorTimer=setInterval(()=>{const children=box.children;if(!children.length)return;
    children[sponsorIndex%children.length].classList.remove("on");sponsorIndex++;children[sponsorIndex%children.length].classList.add("on")},(g.sponsorSeconds||8)*1000);
  toggle("sponsors",g.sponsors&&items.length);
}
function draw(){
  const g=state.graphics||{};
  document.documentElement.style.setProperty("--op",String(Math.min(Math.max((g.opacity||92)/100,.2),1)));
  document.body.classList.toggle("hidden-all",!edit&&(!!g.hidden||!state.live));
  if(!state.replay&&wasReplay)replayEnded=Date.now();wasReplay=!!state.replay;
  if(only.length&&!edit)for(const id of IDS)$(id).classList.toggle("off",!only.includes(id));
  applyLayout();brand();
  tower();train();card();battle();banners();pitRadar();chrome();onboardStatic();quali();map();grid();eventCard();results();champ();message();countdown();
  if(edit){if(state.onAir)fillCard(state.onAir,state.onAir.story,state.onAir.storyTone);if(state.battle)fillBattle(state.battle);editDraw()}
}
setInterval(()=>{if(state.quali&&state.quali.running)qualiTime();if(state.countdown)countdownTime();
  if(lastTrain&&trainUntil&&Date.now()>trainUntil&&!state.train){trainUntil=0;train();battle()}},100);
async function poll(){
  try{
    const asked=edit&&chosenPreset!==null?chosenPreset:sourcePreset;
    const response=await fetch("/api/director?v="+version+(edit?"&demo=1":"")+(asked!==null?"&preset="+encodeURIComponent(asked):"")
      +"&token="+encodeURIComponent(token),{cache:"no-store"});
    if(response.ok){const data=await response.json();
      if(data.v!==version||edit){const first=version===0;version=data.v;
        // Only the parts of the state that changed come, every part on the first answer
        if(data.full||first)state=data.state||{};else Object.assign(state,data.state||{});
        state.version=first?0:version;layout=data.layout||{};preset=data.preset||"";received=Date.now();
        if(first)for(const event of state.events||[])if(!event.fresh)shownBanners.add(event.id);
        draw();if(first)cycleTower()}}
  }catch(error){await new Promise(done=>setTimeout(done,1000))}
  if(!once)setTimeout(poll,0);
}
async function pollLive(){
  try{
    const response=await fetch("/api/director/live?v="+liveVersion+"&token="+encodeURIComponent(token),{cache:"no-store"});
    if(response.ok){const data=await response.json();if(data.v!==liveVersion){liveVersion=data.v;live=data.live||{};onboardLive();mapCars()}}
  }catch(error){await new Promise(done=>setTimeout(done,1000))}
  if(!once)setTimeout(pollLive,0);
}
// Layout editor: graphics dragged (snapped to the others & the middle), resized with the wheel, moved with the arrows,
// undone with Ctrl+Z, saved for a layout preset
let selected=null,drag=null,undo=[],chosenPreset=null,wheelUndo=0;
const EDIT_HIDDEN=new Set(["train","quali","event","results","champ","countdown"]);
function editPreset(){return chosenPreset!==null?chosenPreset:(sourcePreset!==null?sourcePreset:"")}
function remember(){undo.push(JSON.stringify(layout));if(undo.length>100)undo.shift()}
function editDraw(){
  const l=labels(),names=l.names||{};set("tbSave",l.save);set("tbReset",l.reset);set("tbResetAll",l.resetAll);set("tbUndo",l.undo);set("tbHint",l.editHint);
  const select=$("tbPreset");
  if(!select.options.length){for(const [value,text] of Object.entries(l.presets||{})){const option=document.createElement("option");option.value=value;option.textContent=(l.preset||"")+": "+text;select.append(option)}}
  if(chosenPreset===null)chosenPreset=preset;select.value=chosenPreset;
  const chips=$("chips");
  for(const id of IDS){const el=$(id);if(!el.querySelector(".glabel")){const tag=document.createElement("div");tag.className="glabel";tag.textContent=names[id]||id;el.append(tag)}
    el.classList.add("show");el.classList.toggle("off",EDIT_HIDDEN.has(id)||(only.length>0&&!only.includes(id)));
    let chip=chips.querySelector('[data-id="'+id+'"]');
    if(!chip){chip=document.createElement("button");chip.dataset.id=id;chip.textContent=names[id]||id;chips.append(chip);
      chip.onclick=()=>{if(EDIT_HIDDEN.has(id))EDIT_HIDDEN.delete(id);else EDIT_HIDDEN.add(id);editDraw()}}
    chip.classList.toggle("off",EDIT_HIDDEN.has(id))}
  if(!$("banners").querySelector(".banner")){const demo={kind:"FASTEST LAP",title:"K. Sato 1:34.902"};
    const box=document.createElement("div");box.className="banner panel";const tag=cell("tag",demo.kind);tag.style.background=TONES.fastest;
    const text=document.createElement("div");text.className="txt";const title=document.createElement("b");title.textContent=demo.title;text.append(title);box.append(tag,text);$("banners").prepend(box)}
  showPlace();
}
function placeOf(id){const el=$(id),rect=el.getBoundingClientRect();const current=layout[id];
  return [rect.left/innerWidth,rect.top/innerHeight,current?current[2]:1]}
function select(id){selected=id;for(const other of IDS)$(other).classList.toggle("sel",other===id);showPlace()}
function showPlace(){if(!selected){set("tbPlace","");return}const rect=$(selected).getBoundingClientRect(),place=layout[selected];
  set("tbPlace",((labels().names||{})[selected]||selected)+"  "+Math.round(rect.left/innerWidth*1920)+", "+Math.round(rect.top/innerHeight*1080)+"  "+Math.round((place?place[2]:1)*100)+"%")}
// Edges & middles of the other graphics shown, and of the screen: a dragged graphic snaps to them (6 px)
function snap(id,x,y){
  const el=$(id),rect=el.getBoundingClientRect(),w=rect.width,h=rect.height;let left=x*innerWidth,top=y*innerHeight,gx=null,gy=null;
  const xs=[innerWidth/2],ys=[innerHeight/2];
  for(const other of IDS){if(other===id)continue;const box=$(other);if(box.classList.contains("off"))continue;const r=box.getBoundingClientRect();if(!r.width)continue;
    xs.push(r.left,r.right,r.left+r.width/2);ys.push(r.top,r.bottom,r.top+r.height/2)}
  let best=7;for(const target of xs)for(const [offset,edge] of [[0,left],[w,left+w],[w/2,left+w/2]])if(Math.abs(edge-target)<best){best=Math.abs(edge-target);gx=target;left=target-offset}
  best=7;for(const target of ys)for(const [offset,edge] of [[0,top],[h,top+h],[h/2,top+h/2]])if(Math.abs(edge-target)<best){best=Math.abs(edge-target);gy=target;top=target-offset}
  $("guideX").style.display=gx===null?"none":"block";if(gx!==null)$("guideX").style.left=gx+"px";
  $("guideY").style.display=gy===null?"none":"block";if(gy!==null)$("guideY").style.top=gy+"px";
  return [left/innerWidth,top/innerHeight];
}
async function loadPreset(name){chosenPreset=name;version=0;undo=[];await poll()}
function setupEditor(){
  document.body.classList.add("edit");
  for(const id of IDS){const el=$(id);
    el.addEventListener("pointerdown",event=>{event.preventDefault();select(id);remember();const place=placeOf(id);
      drag={id,x:event.clientX,y:event.clientY,place};el.setPointerCapture(event.pointerId)});
    el.addEventListener("pointermove",event=>{if(!drag||drag.id!==id)return;
      let x=drag.place[0]+(event.clientX-drag.x)/innerWidth,y=drag.place[1]+(event.clientY-drag.y)/innerHeight;
      if(!event.shiftKey)[x,y]=snap(id,x,y);
      layout[id]=[x,y,drag.place[2]];applyLayout();showPlace()});
    el.addEventListener("pointerup",()=>{drag=null;$("guideX").style.display="none";$("guideY").style.display="none"});
    el.addEventListener("wheel",event=>{event.preventDefault();select(id);if(Date.now()-wheelUndo>800)remember();wheelUndo=Date.now();
      const place=placeOf(id);const size=Math.min(Math.max(place[2]*(event.deltaY<0?1.05:1/1.05),.3),3);
      layout[id]=[place[0],place[1],Math.round(size*1000)/1000];applyLayout();showPlace()},{passive:false});
    el.addEventListener("dblclick",()=>{remember();delete layout[id];applyLayout();showPlace()});
  }
  addEventListener("keydown",event=>{
    if(event.key==="h"||event.key==="H"){document.body.classList.toggle("bare");return}
    if((event.ctrlKey||event.metaKey)&&(event.key==="z"||event.key==="Z")){event.preventDefault();if(undo.length){layout=JSON.parse(undo.pop());applyLayout();showPlace()}return}
    const moves={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
    if(selected&&moves[event.key]){event.preventDefault();remember();const step=event.shiftKey?10:1,place=placeOf(selected);
      layout[selected]=[place[0]+moves[event.key][0]*step/innerWidth,place[1]+moves[event.key][1]*step/innerHeight,place[2]];applyLayout();showPlace()}
  });
  $("tbPreset").onchange=event=>loadPreset(event.target.value);
  $("tbUndo").onclick=()=>{if(undo.length){layout=JSON.parse(undo.pop());applyLayout();showPlace()}};
  $("tbReset").onclick=()=>{if(selected){remember();delete layout[selected];applyLayout();showPlace()}};
  $("tbResetAll").onclick=()=>{remember();layout={};applyLayout();showPlace()};
  $("tbSave").onclick=async()=>{
    try{const response=await fetch("/api/director/layout?preset="+encodeURIComponent(editPreset())+"&token="+encodeURIComponent(token),
      {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(layout)});
      set("tbHint",response.ok?labels().saved:labels().notSaved)}catch(error){set("tbHint",labels().notSaved)}};
}
if(edit)setupEditor();
poll();
if(!edit)pollLive();
</script></body></html>"""
